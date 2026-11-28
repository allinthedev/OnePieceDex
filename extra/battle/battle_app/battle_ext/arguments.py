"""
The treasure arguments of the battle commands, each narrowed to what its command can take.

Left as they were, every one of them listed the whole collection of the player: `/battle equip` offered
ships to equip and characters that were not in the deck, and the right card had to be found by typing its
name. Only the list offered while typing changes here. What is picked, or typed by hand, is read and
checked by the commands exactly as before, so a card that has no business there still gets the command's
own explanation rather than a "not found".
"""

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from django.db.models import Q
from django.db.models.expressions import RawSQL

from ballsdex.core.utils.transformers import BallInstanceTransformer
from bd_models.models import BallInstance, groups

from ..models import BattleSession, BattleSessionStatus, BattleSettings, role_group_ids

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

# Discord takes 25 choices at most, each of 100 characters at most
MAX_CHOICES = 25
MAX_LABEL = 100


class RoleTransformer(BallInstanceTransformer):
    """
    Lists the treasures of the player that play one of `roles` in a battle, the rarest first, and leaves
    out the ones retired from the dex, which battles turn away.
    """

    roles: tuple[str, ...] = ()

    async def get_options(
        self, interaction: discord.Interaction["BallsDexBot"], value: str
    ) -> list[app_commands.Choice[int]]:
        cog = interaction.client.get_cog("Battle")
        # the cog's own copy is enough to know which group plays which part, and costs no query
        battle_settings = await cog.get_settings(refresh=False) if cog else await BattleSettings.aload()  # type: ignore
        wanted: set[int] = set()
        for role, group_id in role_group_ids(battle_settings).items():
            group = groups.get(group_id) if group_id else None
            if role in self.roles and group is not None:
                wanted |= group._ball_ids

        queryset = (
            self.get_queryset()
            .filter(player__discord_id=interaction.user.id, ball_id__in=wanted, ball__enabled=True)
            .select_related("ball")
        )
        if value.startswith("="):
            queryset = queryset.filter(ball__country__iexact=value[1:])
        else:
            # the same search as everywhere else in the bot: the card's id, its name and its other names.
            # With one difference: the dots go from both sides. Elsewhere they are dropped from what is
            # typed only, so "Monkey D. Luffy" typed in full finds nobody
            queryset = queryset.annotate(
                searchable=RawSQL(
                    "REPLACE(to_hex(ballinstance.id) || ' ' || ball.country || ' ' || "
                    "COALESCE(ball.catch_names, '') || ' ' || "
                    "COALESCE(ball.translations, ''), '.', '')",
                    (),
                )
            ).filter(searchable__icontains=value.replace(".", ""))
        queryset = queryset.order_by("ball__rarity", "-attack_bonus", "pk")[:MAX_CHOICES]
        return [
            app_commands.Choice(name=card.description(bot=interaction.client), value=f"{card.pk:X}")
            async for card in queryset
        ]


class CharacterTransformer(RoleTransformer):
    roles = ("character",)


class ItemTransformer(RoleTransformer):
    roles = ("weapon", "fruit")


class DeckTransformer(BallInstanceTransformer):
    """
    Lists what the deck the player is putting together holds: its characters, or with `worn` what those
    characters have been handed. Read from the battle itself, so the list is the deck and nothing else.
    """

    worn: bool = False

    async def get_options(
        self, interaction: discord.Interaction["BallsDexBot"], value: str
    ) -> list[app_commands.Choice[int]]:
        user_id = interaction.user.id
        session = (
            await BattleSession.objects.select_related("player1", "player2")
            .filter(
                Q(player1__discord_id=user_id) | Q(player2__discord_id=user_id), status=BattleSessionStatus.PROPOSED
            )
            .afirst()
        )
        if session is None:
            return []
        side = "p1" if session.player1.discord_id == user_id else "p2"
        needle = value.casefold().strip()
        choices: list[app_commands.Choice] = []
        for ball in session.state.get(f"{side}_balls", []):
            equipment = ball.get("equipment") or []
            if self.worn:
                listed = [
                    (entry["instance_id"], f"{entry['name']} — held by {ball['name']} ({entry['percent']}%)")
                    for entry in equipment
                ]
            else:
                label = f"{ball['name']} — {ball['attack']} ATK / {ball['max_health']} HP"
                if equipment:
                    label += " — holds " + ", ".join(entry["name"] for entry in equipment)
                listed = [(ball["instance_id"], label)]
            for instance_id, label in listed:
                if needle in label.casefold() or needle == f"{instance_id:x}":
                    choices.append(app_commands.Choice(name=label[:MAX_LABEL], value=f"{instance_id:X}"))
        return choices[:MAX_CHOICES]


class DeckCharacterTransformer(DeckTransformer):
    worn = False


class DeckItemTransformer(DeckTransformer):
    worn = True


CharacterTransform = app_commands.Transform[BallInstance, CharacterTransformer]
ItemTransform = app_commands.Transform[BallInstance, ItemTransformer]
DeckCharacterTransform = app_commands.Transform[BallInstance, DeckCharacterTransformer]
DeckItemTransform = app_commands.Transform[BallInstance, DeckItemTransformer]
