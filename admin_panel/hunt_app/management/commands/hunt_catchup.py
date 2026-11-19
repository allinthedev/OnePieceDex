"""
Repay a hunt that was finished before its reward was shared out.

Under the old rule a crew hunt paid the member who handed in the last stone and nobody else.
This hands the rest of the crew what the hunt's current settings say they were owed, without
paying the finisher their full share twice.

    django-admin hunt_catchup                     # the hunts that could be caught up
    django-admin hunt_catchup --hunt "Road"       # what it would pay, writing nothing
    django-admin hunt_catchup --hunt "Road" --apply
"""

from crew_app.models import CrewMembership
from currency_app.ledger import adjust_money
from currency_app.models import BerryTransaction
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bd_models.models import BallInstance, Player
from hunt_app.models import Hunt, HuntCompletion, PoneglyphClaim
from hunt_app.rewards import split_reward


def description_for(hunt: Hunt) -> str:
    """What the ledger records, and what tells a second run this crew was already repaid."""
    return f"Hunt reward catch-up: {hunt.name}"[: BerryTransaction.DESCRIPTION_MAX_LENGTH]


class Command(BaseCommand):
    help = (
        "Pay the members of a crew that finished a hunt before the reward was shared out. "
        "Prints what it would hand over and writes nothing, unless --apply is given."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--hunt",
            help="Name of the hunt, or enough of it to pick one out. Left out, the hunts that could be "
            "caught up are listed instead.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Hand the rewards over. Without it nothing is written and nothing is sent.",
        )

    def handle(self, *args, **options):
        if not options["hunt"]:
            self.list_hunts()
            return

        hunt = self.find(options["hunt"])
        completions = list(
            HuntCompletion.objects.filter(hunt=hunt, crew__isnull=False).select_related("crew", "player")
        )
        if not completions:
            self.stdout.write(f"No crew has finished {hunt.name} yet, so there is nothing to catch up.")
            return

        self.stdout.write(f"{hunt.name}: {hunt.reward_money:,} berries, {hunt.crew_share}% to the crew")
        if hunt.cached_reward_ball:
            who = "every member" if hunt.crew_reward_ball else "every member who claimed a stone"
            self.stdout.write(f"  treasure: {hunt.cached_reward_ball.country}, to {who}")
        if not hunt.reward_money:
            self.stdout.write(
                self.style.WARNING(
                    "  this hunt pays no berries, so a second run cannot tell it has already been caught up: "
                    "run it once."
                )
            )

        owed = [self.owed_by(hunt, completion) for completion in completions]
        total_money = sum(sum(money.values()) for _, money, _ in owed)
        total_cards = sum(len(cards) for _, _, cards in owed)
        for completion, money, cards in owed:
            self.report(completion, money, cards)
        self.stdout.write("")
        players = sum(len(money) for _, money, _ in owed)
        self.stdout.write(f"In all: {total_money:,} berries over {players} player(s), {total_cards} treasure(s).")

        if not options["apply"]:
            self.stdout.write(self.style.WARNING("Nothing was written. Pass --apply to hand it over."))
            return
        if not total_money and not total_cards:
            self.stdout.write("Nothing to hand over.")
            return
        for completion, money, cards in owed:
            self.pay(hunt, completion, money, cards)
        self.stdout.write(self.style.SUCCESS("Handed over."))

    # -- working out what is owed ---------------------------------------------------------------

    def find(self, name: str) -> Hunt:
        hunts = list(Hunt.objects.filter(name__icontains=name))
        if not hunts:
            raise CommandError(f"No hunt matches {name!r}.")
        if len(hunts) > 1:
            raise CommandError("Several hunts match: " + ", ".join(h.name for h in hunts))
        hunt = hunts[0]
        if not hunt.is_crew_hunt:
            raise CommandError(
                f"{hunt.name} runs per player, where the one who finished it was the only one owed anything."
            )
        return hunt

    def owed_by(self, hunt: Hunt, completion: HuntCompletion) -> tuple[HuntCompletion, dict[int, int], set[int]]:
        """What this crew is still owed: berries by player, and who is still due the treasure."""
        claimers = set(
            PoneglyphClaim.objects.filter(poneglyph__hunt=hunt, crew=completion.crew)
            .exclude(player__isnull=True)
            .values_list("player_id", flat=True)
        )
        if completion.player_id:
            claimers.add(completion.player_id)
        members = set(CrewMembership.objects.filter(crew=completion.crew).values_list("player_id", flat=True))
        money, cards = split_reward(hunt, claimers, members)

        # the finisher was paid in full on the day, and keeps that: only the crew's share is new
        if completion.player_id in money:
            money[completion.player_id] -= hunt.reward_money
            if money[completion.player_id] <= 0:
                del money[completion.player_id]
        if completion.reward_instance_id:
            cards.discard(completion.player_id)

        # and a crew caught up once is not caught up twice
        already = set(
            BerryTransaction.objects.filter(
                player_id__in=claimers | members, description=description_for(hunt)
            ).values_list("player_id", flat=True)
        )
        money = {paid: amount for paid, amount in money.items() if paid not in already}
        return completion, money, cards - already

    # -- saying it, then doing it ---------------------------------------------------------------

    def report(self, completion: HuntCompletion, money: dict[int, int], cards: set[int]) -> None:
        crew = completion.crew.name if completion.crew else "?"
        self.stdout.write("")
        if not money and not cards:
            self.stdout.write(f"{crew}: nothing left to hand over.")
            return
        self.stdout.write(f"{crew}: {sum(money.values()):,} berries and {len(cards)} treasure(s)")
        everyone = set(money) | cards
        names = dict(Player.objects.filter(pk__in=everyone).values_list("pk", "discord_id"))
        for paid in sorted(everyone):
            parts = []
            if amount := money.get(paid):
                parts.append(f"{amount:,} berries")
            if paid in cards:
                parts.append("the treasure")
            mark = " (finished it)" if paid == completion.player_id else ""
            self.stdout.write(f"  {names.get(paid, paid)}{mark}: {' and '.join(parts)}")

    def pay(self, hunt: Hunt, completion: HuntCompletion, money: dict[int, int], cards: set[int]) -> None:
        if not money and not cards:
            return
        ball = hunt.cached_reward_ball
        with transaction.atomic():
            for paid, amount in sorted(money.items()):
                adjust_money(
                    paid,
                    amount,
                    reason=BerryTransaction.Reason.ACHIEVEMENT,
                    description=description_for(hunt),
                )
            if ball is not None:
                # one at a time rather than in bulk: a treasure carries signals, and a reward
                # that skipped them would not look like one the bot handed over
                for paid in sorted(cards):
                    BallInstance.objects.create(
                        player_id=paid,
                        ball_id=ball.pk,
                        special_id=hunt.reward_special_id,
                        attack_bonus=0,
                        health_bonus=0,
                    )
        crew = completion.crew.name if completion.crew else "?"
        self.stdout.write(f"  {crew}: done.")

    # -- the listing ----------------------------------------------------------------------------

    def list_hunts(self) -> None:
        rows = Hunt.objects.filter(mode=Hunt.Mode.CREW)
        found = False
        for hunt in rows:
            crews = HuntCompletion.objects.filter(hunt=hunt, crew__isnull=False).count()
            if not crews:
                continue
            found = True
            self.stdout.write(f"{hunt.name}: finished by {crews} crew(s), {hunt.reward_money:,} berries")
        if not found:
            self.stdout.write("No crew hunt has been finished yet.")
            return
        self.stdout.write("")
        self.stdout.write('Pass --hunt "<name>" to see what one of them is owed.')
