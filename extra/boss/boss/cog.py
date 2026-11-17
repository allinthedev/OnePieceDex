import asyncio
import io
import logging
import random
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks
from django.db import models
from django.utils import timezone

from ballsdex.core.game_events import Event, bus
from ballsdex.core.utils.transformers import BallEnabledTransform, BallInstanceTransform, SpecialEnabledTransform
from ballsdex.settings import settings
from bd_models.models import BallInstance, Player, specials
from boss.models import BossSchedule

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.boss")

# Configuration constants
SPECIAL_BUFFS = {
    "⚡": (500, 500),  # Haki Buff
    "✨": (1000, 1000),  # Shiny Buffs
    "🔮": (1500, 1500),  # Mythical Buffs
}  # Special buffs
# Emoji: (ATK, HP)
MAXSTATS = [12000, 12000]  # Max stats a card is limited to (before buffs)
# ATK, HP
ROUND_SECONDS_MIN = 180  # a round never closes sooner than this, however it was started
ROUND_SECONDS_DEFAULT = 180
WARNING_SECONDS = 60  # how long before a round closes the stragglers get pinged

DAMAGERNG = [0, 2000]  # Damage a boss can deal IF attack_amount has NOT been inputted in /boss admin attack.
# Min Damage, Max Damage


def ball_description(countryball, bot, *, include_emoji: bool = True) -> str:
    if not hasattr(countryball, "description"):
        return ""
    return countryball.description(short=True, include_emoji=include_emoji, bot=bot)


def get_special_buffs(countryball, bot) -> tuple[int, int]:
    if not getattr(countryball, "special_id", None):
        return 0, 0

    description = ball_description(countryball, bot)
    return next((buffs for emoji, buffs in SPECIAL_BUFFS.items() if emoji in description), (0, 0))


class JoinButton(discord.ui.View):
    """Join button for boss battles"""

    def __init__(self, boss_cog):
        super().__init__(timeout=900)  # 15 minutes timeout
        self.boss_cog = boss_cog
        self.join_button = discord.ui.Button(
            label="Join Boss Fight!", style=discord.ButtonStyle.primary, custom_id="join_boss"
        )
        self.join_button.callback = self.button_callback
        self.add_item(self.join_button)

    async def button_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not self.boss_cog.boss_enabled:
            return await interaction.followup.send("Boss is disabled", ephemeral=True)

        if interaction.user.id in self.boss_cog.disqualified:
            return await interaction.followup.send("You have been disqualified", ephemeral=True)

        if interaction.user.id in self.boss_cog.users:
            return await interaction.followup.send("You have already joined the boss", ephemeral=True)

        if self.boss_cog.round > 0 or self.boss_cog.picking:
            return await interaction.followup.send("The boss battle has already started", ephemeral=True)

        self.boss_cog.users.append(interaction.user.id)
        await interaction.followup.send("You have joined the Boss Battle!", ephemeral=True)
        await self.boss_cog._log_action(f"{interaction.user} has joined the {self.boss_cog.bossball} Boss Battle.")


# Django Models (integrated directly in cog)
class BossBattle(models.Model):
    """Active boss battle configuration"""

    ball_instance = models.OneToOneField(
        "bd_models.BallInstance",
        related_name="+",
        help_text="The ball instance acting as the boss",
        on_delete=models.DO_NOTHING,
        db_constraint=False,
    )
    max_hp = models.IntegerField(default=1000, help_text="Maximum HP of boss")
    current_hp = models.IntegerField(default=1000, help_text="Current HP of boss")
    attack_power = models.IntegerField(default=500, help_text="Attack power of the boss")
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True, help_text="Whether the boss battle is active")

    def __str__(self):
        return f"Boss Battle: {self.ball_instance.ball.country} ({self.current_hp}/{self.max_hp} HP)"


class BossBattleParticipant(models.Model):
    """Players participating in boss battles"""

    boss_battle = models.ForeignKey(
        BossBattle,
        related_name="participants",
        help_text="The boss battle this participant is in",
        on_delete=models.CASCADE,
    )
    player = models.ForeignKey(
        "bd_models.Player",
        related_name="+",
        help_text="The player participating",
        on_delete=models.DO_NOTHING,
        db_constraint=False,
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    total_damage_dealt = models.IntegerField(default=0, help_text="Total damage dealt by this participant")

    class Meta:
        unique_together = ["boss_battle", "player"]

    def __str__(self):
        return f"Player {self.player.discord_id} in {self.boss_battle}"


class BossBattleRound(models.Model):
    """Individual rounds in boss battles"""

    boss_battle = models.ForeignKey(
        BossBattle, related_name="rounds", help_text="The boss battle this round belongs to", on_delete=models.CASCADE
    )
    round = models.IntegerField(help_text="Round number")
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    is_attack_phase = models.BooleanField(default=True, help_text="Whether this is attack phase")
    boss_damage_taken = models.IntegerField(default=0, help_text="Total damage taken this round")

    class Meta:
        unique_together = ["boss_battle", "round"]
        ordering = ["round"]

    def __str__(self):
        phase = "Attack" if self.is_attack_phase else "Defend"
        return f"Round {self.round} ({phase}) - {self.boss_battle}"


class BossRoundAction(models.Model):
    """Player actions in boss battle rounds"""

    round = models.ForeignKey(
        BossBattleRound, related_name="actions", help_text="The round this action belongs to", on_delete=models.CASCADE
    )
    participant = models.ForeignKey(
        BossBattleParticipant,
        related_name="actions",
        help_text="The participant who performed this action",
        on_delete=models.CASCADE,
    )
    ball_used = models.ForeignKey(
        "bd_models.BallInstance",
        related_name="+",
        help_text="The ball instance used in this action",
        on_delete=models.DO_NOTHING,
        db_constraint=False,
    )
    damage_dealt = models.IntegerField(help_text="Damage dealt by this action")
    action_type = models.CharField(
        max_length=20,
        choices=[("attack", "Attack"), ("defend", "Defend"), ("special", "Special")],
        default="attack",
        help_text="Type of action performed",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Player {self.participant.player.discord_id} - {self.action_type} ({self.damage_dealt} dmg)"


class BossBattleReward(models.Model):
    """Rewards given for boss battles"""

    boss_battle = models.ForeignKey(
        BossBattle, related_name="rewards", help_text="The boss battle this reward is for", on_delete=models.CASCADE
    )
    winner = models.ForeignKey(
        "bd_models.Player",
        related_name="+",
        help_text="The player who won the boss battle",
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        null=True,
        blank=True,
    )
    reward_ball = models.ForeignKey(
        "bd_models.BallInstance",
        related_name="+",
        help_text="The ball instance given as reward",
        on_delete=models.DO_NOTHING,
        db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reward for {self.boss_battle} - Winner: {self.winner}"


class Boss(commands.GroupCog, name="boss"):
    """Boss battle system — fight powerful bosses with your collection!"""

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

        # Boss battle state
        self.boss_enabled = False
        self.bossball = None
        self.bossHP = 0
        self.bossmaxhp = 0
        self.bossattack_image: discord.Attachment | None = None
        self.bossdefend_image: discord.Attachment | None = None
        self.users = []
        self.usersdamage = []  # Track damage per user
        self.usersinround = []
        self.balls = []  # Track selected balls to prevent duplicates
        self.round = 0  # Will be set to 1 when battle starts
        self.picking = False
        self.attack = True
        self.bossattack = 0
        self.disqualified = []  # Track disqualified users
        self.lasthitter = 0  # Track last person to hit boss
        self.currentvalue = ""  # Track round actions
        self.pending_selections: dict[int, BallInstance] = {}
        # the task playing the fight out on its own, when the admin asked for auto mode
        self.auto_task: asyncio.Task | None = None

    async def cog_load(self):
        self.start_planned_fights.start()

    def cog_unload(self):
        self.start_planned_fights.cancel()
        if self.auto_task is not None:
            self.auto_task.cancel()

    admin = app_commands.Group(name="admin", description="Boss administration commands")

    def admin_permissions_check():
        """Custom permission check for admin commands that works with interactions"""

        async def check(interaction: discord.Interaction["BallsDexBot"]) -> bool:
            from users.utils import get_user_model

            try:
                user_model = get_user_model()
                dj_user = await user_model.objects.filter(discord_id=interaction.user.id).aget()
                if not dj_user.is_active:
                    return False
                return await dj_user.ahas_perms(["bd_models.add_ballinstance"])
            except user_model.DoesNotExist:
                return False

        return app_commands.check(check)

    @admin.command()
    @admin_permissions_check()
    async def start(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        countryball: BallEnabledTransform,
        hp_amount: int,
        start_image: discord.Attachment | None = None,
        defend_image: discord.Attachment | None = None,
        attack_image: discord.Attachment | None = None,
    ):
        """
        Start a boss battle with the specified countryball

        Parameters
        ----------
        countryball: Ball
            The countryball to use as boss
        hp_amount: int
            HP amount for the boss
        start_image: discord.Attachment | None
            Optional image to use for the boss announcement
        defend_image: discord.Attachment | None
            Optional image to use when the boss defends
        attack_image: discord.Attachment | None
            Optional image to use when the boss attacks
        """
        await interaction.response.defer(ephemeral=True, thinking=True)

        if self.boss_enabled:
            await interaction.followup.send("A boss battle is already active!", ephemeral=True)
            return

        try:
            await interaction.followup.send(f"Boss battle started with {countryball.country}!", ephemeral=True)
            await self._open_fight(
                interaction.channel, countryball, hp_amount, start_image, attack_image, defend_image
            )
        except Exception as e:
            log.error(f"Error starting boss battle: {e}")
            await interaction.followup.send(f"Error starting boss battle: {e}", ephemeral=True)

    @app_commands.command()
    async def select(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        countryball: BallInstanceTransform,
        special: SpecialEnabledTransform | None = None,
    ):
        """
        Select countryball to use against the boss

        Parameters
        ----------
        countryball: BallInstance
            The countryball you want to select
        special: Special
            Filter the results of autocompletion to a special event. Ignored afterwards.
        """
        await interaction.response.defer(ephemeral=True, thinking=True)

        if [interaction.user.id, self.round] in self.usersinround:
            return await interaction.followup.send(
                f"You have already selected a {settings.collectible_name}", ephemeral=True
            )

        if not self.boss_enabled:
            return await interaction.followup.send("Boss is disabled", ephemeral=True)

        if not self.picking:
            return await interaction.followup.send(
                f"It is not yet time to select a {settings.collectible_name}", ephemeral=True
            )

        if interaction.user.id not in self.users:
            return await interaction.followup.send("You did not join, or you're dead/disqualified.", ephemeral=True)

        if not countryball.tradeable:
            await interaction.followup.send(f"You cannot use this {settings.collectible_name}.", ephemeral=True)
            return

        if countryball in self.balls:
            return await interaction.followup.send(
                f"You cannot select the same {settings.collectible_name} twice", ephemeral=True
            )

        # Store the selection for processing in end_round
        self.pending_selections[interaction.user.id] = countryball

        # Add to selected balls and track round participation
        self.balls.append(countryball)
        self.usersinround.append([interaction.user.id, self.round])

        # Calculate stats with capping
        ball_attack = min(max(countryball.attack, 0), MAXSTATS[0])
        ball_health = min(max(countryball.health, 0), MAXSTATS[1])

        special_attack_buff, special_health_buff = get_special_buffs(countryball, self.bot)
        total_attack = ball_attack + special_attack_buff
        total_health = ball_health + special_health_buff
        ball_display = ball_description(countryball, self.bot)
        messageforuser = (
            f"{ball_display} has been selected for this round, with {total_attack} ATK and {total_health} HP"
        )

        await interaction.followup.send(messageforuser, ephemeral=True)
        await self._log_action(f"-# Round {self.round}\n{interaction.user}'s {messageforuser}\n-# -------")

    @app_commands.command()
    async def ongoing(self, interaction: discord.Interaction["BallsDexBot"]):
        """
        Show your damage to the boss in the current fight
        """
        await interaction.response.defer(ephemeral=True, thinking=True)

        user_damage = 0
        damage_details = ""

        for damage_record in self.usersdamage:
            if damage_record[0] == interaction.user.id:
                user_damage += damage_record[1]
                damage_details += f"{damage_record[2]}: {damage_record[1]} damage\n\n"

        if user_damage == 0:
            if interaction.user.id in self.users:
                await interaction.followup.send("You have not dealt any damage.", ephemeral=True)
            elif interaction.user.id in self.disqualified:
                await interaction.followup.send("You have been disqualified.", ephemeral=True)
            else:
                await interaction.followup.send("You have not joined the battle, or you have died.", ephemeral=True)
        else:
            if interaction.user.id in self.users:
                await interaction.followup.send(
                    f"You have dealt {user_damage} total damage.\n\n{damage_details}", ephemeral=True
                )
            elif interaction.user.id in self.disqualified:
                await interaction.followup.send(
                    f"You have dealt {user_damage} damage and have been disqualified.\n\n{damage_details}",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"You have dealt {user_damage} damage and you are now dead.\n\n{damage_details}", ephemeral=True
                )

    @admin.command()
    @admin_permissions_check()
    @app_commands.choices(
        winner=[
            app_commands.Choice(name="Random", value="RNG"),
            app_commands.Choice(name="Most Damage", value="DMG"),
            app_commands.Choice(name="Last Hitter", value="LAST"),
            app_commands.Choice(name="No Winner", value="None"),
        ]
    )
    async def conclude(self, interaction: discord.Interaction["BallsDexBot"], winner: str):
        """
        Finish the boss, conclude the Winner

        Parameters
        ----------
        winner: app_commands.Choice[str]
            Winner selection method (RNG/DMG/LAST/None)
        """
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not self.boss_enabled:
            return await interaction.followup.send("Boss is disabled.", ephemeral=True)

        if self.lasthitter not in self.users and winner == "LAST":
            return await interaction.followup.send("The last hitter is dead or disqualified.", ephemeral=True)

        self.picking = False
        self.boss_enabled = False

        # Calculate total damage per player
        test = self.usersdamage
        test2 = []
        total = ""
        total2 = ""
        totalnum = []

        for i in range(len(test)):
            if test[i][0] not in test2:
                temp = 0
                tempvalue = test[i][0]
                test2.append(tempvalue)
                for j in range(len(test)):
                    if test[j][0] == tempvalue:
                        temp += test[j][1]
                if test[i][0] in self.users:
                    user = await self.bot.fetch_user(int(tempvalue))
                    total += f"{user} has dealt a total of {temp} damage!\n"
                    totalnum.append([tempvalue, temp])
                else:
                    user = await self.bot.fetch_user(int(tempvalue))
                    total2 += f"[Dead/Disqualified] {user} has dealt a total of {temp} damage!\n"

        # Determine winner based on selection
        bosswinner = 0
        highest = 0
        if winner == "DMG":
            for k in range(len(totalnum)):
                if totalnum[k][1] > highest:
                    highest = totalnum[k][1]
                    bosswinner = totalnum[k][0]
        elif winner == "LAST":
            bosswinner = self.lasthitter
        elif winner == "RNG":
            if len(totalnum) != 0:
                bosswinner = totalnum[random.randint(0, len(totalnum) - 1)][0]

        # Create totalstats.txt file
        stats_content = f"{total}{total2}"
        stats_file = discord.File(fp=io.StringIO(stats_content), filename="totalstats.txt")

        await self._announce_participation(bosswinner, interaction.channel_id)

        if bosswinner == 0 or winner == "None":
            await interaction.followup.send("Boss successfully concluded", ephemeral=True)
            await interaction.channel.send(
                f"# Boss has concluded {self.bot.get_emoji(self.bossball.emoji_id) if self.bossball else ''}"
                f"\nThe boss has won the Boss Battle!"
            )
            await interaction.channel.send(file=stats_file)

            # Reset all battle state
            self._reset_battle_state()
            return

        # Reward the winner
        await self._reward_winner(bosswinner, channel=interaction.channel)
        await interaction.followup.send("Boss successfully concluded", ephemeral=True)
        await interaction.channel.send(file=stats_file)

        # Reset battle state
        self._reset_battle_state()

    async def _announce_participation(self, bosswinner: int, channel_id: int | None):
        """
        Tell the game event bus who fought this boss, and who won it.

        Everyone who picked at least once counts as having taken part, whether they survived or
        not — a war scored on showing up should not quietly drop the players the boss killed.
        """
        fought = {entry[0] for entry in self.usersdamage} | set(self.users) | set(self.disqualified)
        for user_id in fought:
            player = await Player.objects.filter(discord_id=user_id).afirst()
            if player is None:
                continue
            await bus.dispatch(player, Event.BOSS_PLAYED, channel_id=channel_id)
            if bosswinner and user_id == bosswinner:
                await bus.dispatch(player, Event.BOSS_WIN, channel_id=channel_id)

    async def _resolve_round(self, channel):
        """
        Close the open round: apply what everyone picked, then say what happened.

        Shared by `/boss admin end_round` and the auto driver.
        """
        self.picking = False

        for user_id, ball in list(self.pending_selections.items()):
            if not await BallInstance.objects.filter(pk=ball.pk, deleted=False).aexists():
                # the card was deleted mid-round: drop it as if it had never been picked
                if ball in self.balls:
                    self.balls.remove(ball)
                if [user_id, self.round] in self.usersinround:
                    self.usersinround.remove([user_id, self.round])
                del self.pending_selections[user_id]
                continue

            ball_attack = min(max(ball.attack, 0), MAXSTATS[0])
            ball_health = min(max(ball.health, 0), MAXSTATS[1])
            ball_desc = ball_description(ball, self.bot)
            special_attack_buff, special_health_buff = get_special_buffs(ball, self.bot)
            ball_health += special_health_buff
            ball_attack += special_attack_buff
            plain = ball_description(ball, self.bot, include_emoji=False)

            if not self.attack:  # the boss is defending, players attack
                self.bossHP -= ball_attack
                self.usersdamage.append([user_id, ball_attack, ball_desc])
                user_obj = await self.bot.fetch_user(user_id)
                self.currentvalue += f"{user_obj}'s {plain} has dealt {ball_attack} damage!\n"
                self.lasthitter = user_id
            else:  # the boss is attacking, players defend
                user_obj = await self.bot.fetch_user(user_id)
                if self.bossattack >= ball_health:
                    if user_id in self.users:
                        self.users.remove(user_id)
                    self.currentvalue += f"{user_obj}'s {plain} had {ball_health} HP and died!\n"
                else:
                    self.currentvalue += f"{user_obj}'s {plain} had {ball_health} HP and survived!\n"

        self.pending_selections = {}

        # anyone who did not pick in time is out, in either phase
        for user_id in self.users.copy():
            if [user_id, self.round] not in self.usersinround:
                user = await self.bot.fetch_user(int(user_id))
                if str(user) not in self.currentvalue:
                    self.currentvalue += str(user) + " has not selected on time and died!\n"
                    self.users.remove(user_id)

        emoji = self.bot.get_emoji(self.bossball.emoji_id) if self.bossball else ""
        if not self.attack:
            remaining = (
                "There is 0 HP remaining on the boss, the boss has been defeated!"
                if int(self.bossHP) <= 0
                else f"There is {self.bossHP} HP remaining on the boss"
            )
            await channel.send(f"# Round {self.round} has ended {emoji}\n{remaining}")
        else:
            outcome = f"The boss has dealt {self.bossattack} damage!"
            if len(self.users) == 0:
                outcome += "\nThe boss has won!"
            await channel.send(f"# Round {self.round} has ended {emoji}\n{outcome}")

        if self.currentvalue:
            await channel.send(file=discord.File(fp=io.StringIO(self.currentvalue), filename="roundstats.txt"))
        self.currentvalue = ""

    @admin.command()
    @admin_permissions_check()
    async def end_round(self, interaction: discord.Interaction["BallsDexBot"]):
        """End the current round"""
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not self.boss_enabled:
            return await interaction.followup.send("Boss is disabled", ephemeral=True)
        if self.auto_task is not None:
            return await interaction.followup.send(
                "This fight is running on auto, let it play or stop it with `/boss admin autostop`.", ephemeral=True
            )
        if not self.picking:
            return await interaction.followup.send(
                "There are no ongoing rounds, use `/boss admin attack` or `/boss admin defend` to start one",
                ephemeral=True,
            )

        await self._resolve_round(interaction.channel)
        await interaction.followup.send("Round successfully ended", ephemeral=True)

    async def _begin_attack(self, channel, attack_amount: int | None = None):
        """
        Open a round where the boss attacks.

        Shared by `/boss admin attack` and the auto driver, so a hand-run fight and an automatic
        one go through exactly the same steps.
        """
        self.round += 1
        file = await self._boss_file(self.bossattack_image, self.bossball.wild_card)

        await channel.send(
            f"Round {self.round}\n# {self.bossball.country} is preparing to attack! "
            f"{self.bot.get_emoji(self.bossball.emoji_id)}",
            file=file,
        )
        await channel.send(
            f"> Use `/boss select` to select your defending {settings.collectible_name}.\n"
            f"> Your selected {settings.collectible_name}'s HP will be used to defend."
        )

        self.picking = True
        self.attack = True
        self.bossattack = attack_amount if attack_amount is not None else random.randint(DAMAGERNG[0], DAMAGERNG[1])

    @admin.command()
    @admin_permissions_check()
    async def attack(self, interaction: discord.Interaction["BallsDexBot"], attack_amount: int | None = None):
        """
        Start a round where the Boss Attacks

        Parameters
        ----------
        attack_amount: int
            Custom attack amount
        """
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not self.boss_enabled:
            return await interaction.followup.send("Boss is disabled", ephemeral=True)
        if self.auto_task is not None:
            return await interaction.followup.send(
                "This fight is running on auto, let it play or stop it with `/boss admin autostop`.", ephemeral=True
            )
        if self.picking:
            return await interaction.followup.send("There is already an ongoing round", ephemeral=True)
        if len(self.users) == 0:
            return await interaction.followup.send("There are not enough users to start the round", ephemeral=True)
        if self.bossHP <= 0:
            return await interaction.followup.send("The Boss is dead", ephemeral=True)

        await interaction.followup.send("Round successfully started", ephemeral=True)
        await self._begin_attack(interaction.channel, attack_amount)

    async def _begin_defend(self, channel):
        """Open a round where the boss defends. Shared by the command and the auto driver."""
        self.round += 1
        file = await self._boss_file(self.bossdefend_image, self.bossball.wild_card)

        await channel.send(
            f"Round {self.round}\n# {self.bossball.country} is preparing to defend! "
            f"{self.bot.get_emoji(self.bossball.emoji_id)}",
            file=file,
        )
        await channel.send(
            f"> Use `/boss select` to select your attacking {settings.collectible_name}.\n"
            f"> Your selected {settings.collectible_name}'s ATK will be used to attack."
        )

        self.picking = True
        self.attack = False

    @admin.command()
    @admin_permissions_check()
    async def defend(self, interaction: discord.Interaction["BallsDexBot"]):
        """Start a round where the Boss Defends"""
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not self.boss_enabled:
            return await interaction.followup.send("Boss is disabled", ephemeral=True)
        if self.auto_task is not None:
            return await interaction.followup.send(
                "This fight is running on auto, let it play or stop it with `/boss admin autostop`.", ephemeral=True
            )
        if self.picking:
            return await interaction.followup.send("There is already an ongoing round", ephemeral=True)
        if len(self.users) == 0:
            return await interaction.followup.send("There are not enough users to start the round", ephemeral=True)
        if self.bossHP <= 0:
            return await interaction.followup.send("The Boss is dead", ephemeral=True)

        await interaction.followup.send("Round successfully started", ephemeral=True)
        await self._begin_defend(interaction.channel)

    def _auto_damage(self, swing: int, swings: int, low: int, high: int) -> int:
        """
        What the boss hits for on its `swing`-th attack out of `swings`.

        Damage climbs in a straight line from `low` on the first to `high` on the last, so the
        fight gets heavier as it goes instead of swinging at random. A single-attack fight hits
        for the high end.
        """
        if swings <= 1:
            return high
        return round(low + (high - low) * (swing - 1) / (swings - 1))

    def _auto_phases(self, swings: int, pattern: str) -> list[bool]:
        """
        The order of the rounds, as True for an attack and False for a defend.

        "alternate" opens with an attack and takes turns. "random" shuffles, but never lets the
        boss attack more than twice in a row: an unlucky streak of attacks wipes everybody out
        before they have had a chance to hit back.
        """
        if pattern == "alternate":
            phases = []
            for _ in range(swings):
                phases += [True, False]
            return phases

        phases: list[bool] = []
        attacks_left, defends_left, streak = swings, swings, 0
        while attacks_left or defends_left:
            # a third attack in a row is never allowed, and a defend is only allowed while the
            # attacks that remain can still be spaced out by the defends that remain. Without
            # that second rule the defends run out early and the tail is one long beating.
            can_attack = attacks_left > 0 and streak < 2
            can_defend = defends_left > 0 and attacks_left <= 2 * defends_left
            if can_attack and can_defend:
                attacking = random.random() < 0.5
            elif can_attack:
                attacking = True
            elif can_defend:
                attacking = False
            else:
                attacking = attacks_left > 0
            if attacking:
                phases.append(True)
                attacks_left -= 1
                streak += 1
            else:
                phases.append(False)
                defends_left -= 1
                streak = 0
        return phases

    async def _boss_file(self, override, fallback) -> discord.File:
        """
        A picture of the boss: the attachment an admin dragged into the command, the upload
        sitting on a planned fight, or the treasure's own card when there is neither.
        """
        source = override if override else fallback
        if isinstance(source, discord.Attachment):
            return await source.to_file()
        extension = source.name.split(".")[-1]
        return discord.File(str(source.path), filename=f"boss.{extension}")

    async def _open_fight(self, channel, ball, hp: int, start_image=None, attack_image=None, defend_image=None):
        """
        Open a fight in a channel and post the join button.

        Shared by `/boss admin start` and the planned fights, so neither can drift away from
        the other.
        """
        self.bossball = ball
        self.bossHP = hp
        self.bossmaxhp = hp
        self.bossattack_image = attack_image
        self.bossdefend_image = defend_image
        self.boss_enabled = True
        self.users = []
        self.usersinround = []
        self.balls = []
        self.round = 0
        self.picking = False
        self.attack = True
        self.pending_selections = {}

        file = await self._boss_file(start_image, ball.collection_card)
        view = JoinButton(self)
        message = await channel.send(
            f"# The boss battle has begun! {self.bot.get_emoji(ball.emoji_id)}\n-# HP: {self.bossHP}",
            file=file,
            view=view,
        )
        view.message = message
        return message

    async def _wait_for_picks(self, channel, seconds: int):
        """
        Hold the round open, and warn whoever has not picked a minute before it closes.

        Only the stragglers are pinged. Pinging everyone every round, the players who already
        acted included, is the surest way to have the ping ignored by the time it matters.
        """
        warn_at = seconds - WARNING_SECONDS
        if warn_at <= 0:
            await channel.send(f"-# Picking closes in {seconds}s.")
            await asyncio.sleep(seconds)
            return

        await channel.send(f"-# Picking closes in {seconds // 60} min.")
        await asyncio.sleep(warn_at)
        if not self.picking:
            return

        waiting = [user_id for user_id in self.users if [user_id, self.round] not in self.usersinround]
        if waiting:
            mentions = " ".join(f"<@{user_id}>" for user_id in waiting)
            await channel.send(
                f"⏰ **One minute left** to pick, or you are out of this round.\n{mentions}"
            )
        await asyncio.sleep(WARNING_SECONDS)

    async def _run_auto(self, channel, swings: int, low: int, high: int, pattern: str, seconds: int):
        """
        Play the fight out without an admin driving each round.

        It stops early the moment the boss dies or everybody is out, and it never concludes the
        fight itself: handing out the rewards stays a deliberate `/boss admin conclude`.
        """
        try:
            swing = 0
            for attacking in self._auto_phases(swings, pattern):
                if not self.boss_enabled or self.bossHP <= 0 or not self.users:
                    break
                if attacking:
                    swing += 1
                    await self._begin_attack(channel, self._auto_damage(swing, swings, low, high))
                else:
                    await self._begin_defend(channel)
                await self._wait_for_picks(channel, seconds)
                if not self.boss_enabled:
                    break
                await self._resolve_round(channel)

            if not self.boss_enabled:
                return
            if self.bossHP <= 0:
                await channel.send("# The boss is down! Use `/boss admin conclude` to hand out the rewards.")
            elif not self.users:
                await channel.send("# Everyone is out. Use `/boss admin conclude` to close the fight.")
            else:
                await channel.send(
                    f"# The automatic rounds are over, the boss is still standing with {self.bossHP} HP.\n"
                    "-# Keep going by hand, or conclude the fight."
                )
        except asyncio.CancelledError:
            await channel.send("-# The automatic fight was stopped. The round in progress was left open.")
            raise
        except Exception:
            log.exception("Boss auto mode failed")
            await channel.send("-# The automatic fight hit an error and stopped. Carry on by hand.")
        finally:
            self.auto_task = None

    @admin.command()
    @admin_permissions_check()
    @app_commands.choices(
        pattern=[
            app_commands.Choice(name="Attack, defend, attack, defend...", value="alternate"),
            app_commands.Choice(name="Random order", value="random"),
        ]
    )
    async def auto(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        min_damage: int,
        max_damage: int,
        swings: app_commands.Range[int, 1, 20] = 8,
        pattern: str = "alternate",
        seconds_per_round: app_commands.Range[int, ROUND_SECONDS_MIN, 1800] = ROUND_SECONDS_DEFAULT,
    ):
        """
        Play the whole fight out automatically, with damage climbing round after round.

        Parameters
        ----------
        min_damage: int
            What the boss hits for on its first attack.
        max_damage: int
            And on its last. The rounds in between climb evenly from one to the other.
        swings: int
            How many attacking rounds. Each one is paired with a defending round.
        pattern: str
            Whether the boss takes turns attacking and defending, or mixes them up.
        seconds_per_round: int
            How long players get to pick before the round is closed. Three minutes at least,
            and the players who have not picked are pinged a minute before it shuts.
        """
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not self.boss_enabled:
            return await interaction.followup.send("Boss is disabled", ephemeral=True)
        if self.auto_task is not None:
            return await interaction.followup.send("This fight is already running on auto.", ephemeral=True)
        if self.picking:
            return await interaction.followup.send(
                "Close the round in progress first with `/boss admin end_round`.", ephemeral=True
            )
        if not self.users:
            return await interaction.followup.send("Nobody has joined the fight yet.", ephemeral=True)
        if self.bossHP <= 0:
            return await interaction.followup.send("The Boss is dead", ephemeral=True)
        if min_damage < 0 or max_damage < min_damage:
            return await interaction.followup.send(
                "The damage range is the wrong way round: min_damage must be 0 or more, and max_damage at "
                "least as high.",
                ephemeral=True,
            )

        ladder = ", ".join(str(self._auto_damage(i, swings, min_damage, max_damage)) for i in range(1, swings + 1))
        self.auto_task = asyncio.create_task(
            self._run_auto(interaction.channel, swings, min_damage, max_damage, pattern, seconds_per_round)
        )
        await interaction.followup.send(
            f"Auto fight started: {swings} attacking rounds, {pattern}, {seconds_per_round}s to pick.\n"
            f"Damage per attack: {ladder}\n"
            "Stop it with `/boss admin autostop`.",
            ephemeral=True,
        )

    @admin.command()
    @admin_permissions_check()
    async def autostop(self, interaction: discord.Interaction["BallsDexBot"]):
        """Stop an automatic fight and go back to driving the rounds by hand."""
        await interaction.response.defer(ephemeral=True, thinking=True)
        if self.auto_task is None:
            return await interaction.followup.send("This fight is not running on auto.", ephemeral=True)
        self.auto_task.cancel()
        self.auto_task = None
        await interaction.followup.send(
            "Stopped. If a round was open, close it with `/boss admin end_round`.", ephemeral=True
        )

    @tasks.loop(minutes=1)
    async def start_planned_fights(self):
        """
        Open the boss fights that were set up in the panel and have come due.

        Only one fight runs at a time: a plan that comes due while another is going waits and
        is picked up on a later pass rather than trampling it. The start is written down before
        the fight opens, and only while the plan is still unstarted, so two passes cannot both
        open the same one.
        """
        now = timezone.now()
        due = BossSchedule.objects.filter(
            enabled=True, started_at__isnull=True, starts_at__lte=now
        ).select_related("ball")
        async for plan in due:
            if self.boss_enabled:
                return  # a fight is already running; try again next minute
            channel = self.bot.get_channel(plan.channel_id)
            if not isinstance(channel, discord.abc.Messageable):
                log.warning("boss: planned fight %r has no reachable channel %s", plan.name, plan.channel_id)
                continue
            if not await BossSchedule.objects.filter(pk=plan.pk, started_at__isnull=True).aupdate(started_at=now):
                continue
            try:
                await self._run_planned(plan, channel)
            except Exception:
                log.exception("boss: planned fight %r failed", plan.name)
            return  # one fight per pass, whatever happened to it

    async def _run_planned(self, plan: BossSchedule, channel):
        """Open a planned fight, hold the joining window, then play it out if it was told to."""
        await self._open_fight(
            channel,
            plan.ball,
            plan.hp,
            plan.start_image or None,
            plan.attack_image or None,
            plan.defend_image or None,
        )
        log.info(f"boss: planned fight {plan.name!r} opened in {plan.channel_id}", extra={"webhook": True})
        await channel.send(
            f"-# Joining closes in {plan.join_minutes} min. Press the button above to take part."
        )
        await asyncio.sleep(plan.join_minutes * 60)

        if not self.boss_enabled:
            return
        if not self.users:
            await channel.send("Nobody joined, the boss wanders off.")
            self._reset_battle_state()
            return
        if not plan.auto:
            await channel.send(
                f"-# {len(self.users)} fighters are in. An admin drives the rounds from here."
            )
            return

        await channel.send(f"-# {len(self.users)} fighters are in. The fight begins.")
        self.auto_task = asyncio.create_task(
            self._run_auto(channel, plan.swings, plan.min_damage, plan.max_damage, plan.pattern,
                           plan.seconds_per_round)
        )

    @start_planned_fights.before_loop
    async def before_start_planned_fights(self):
        await self.bot.wait_until_ready()

    @admin.command()
    @admin_permissions_check()
    async def disqualify(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        user: discord.User | None = None,
        user_id: str | None = None,
        undisqualify: bool | None = False,
    ):
        """
        Disqualify or undisqualify a user from the boss battle

        Parameters
        ----------
        user: discord.User
            User to disqualify
        user_id: str
            User ID to disqualify
        undisqualify: bool
            Set to True to remove disqualification
        """
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not user:
            try:
                user = await self.bot.fetch_user(int(user_id))
            except ValueError:
                await interaction.followup.send("The user ID you gave is not valid.", ephemeral=True)
                return
            except discord.NotFound:
                await interaction.followup.send("The given user ID could not be found.", ephemeral=True)
                return
        else:
            user_id = str(user.id)

        if int(user_id) in self.disqualified:
            if undisqualify:
                self.disqualified.remove(int(user_id))
                await interaction.followup.send(f"{user} has been removed from disqualification.", ephemeral=True)
            else:
                await interaction.followup.send(f"{user} has already been disqualified.", ephemeral=True)
        elif undisqualify:
            await interaction.followup.send(f"{user} has **not** been disqualified yet.", ephemeral=True)
        elif not self.boss_enabled:
            self.disqualified.append(int(user_id))
            await interaction.followup.send(f"{user} will be disqualified from the next fight.", ephemeral=True)
        elif int(user_id) not in self.users:
            self.disqualified.append(int(user_id))
            await interaction.followup.send(f"{user} has been disqualified successfully.", ephemeral=True)
        else:
            self.users.remove(int(user_id))
            self.disqualified.append(int(user_id))
            await interaction.followup.send(f"{user} has been disqualified successfully.", ephemeral=True)

    @admin.command()
    @admin_permissions_check()
    async def hackjoin(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        user: discord.User | None = None,
        user_id: str | None = None,
    ):
        """
        Force join a user to the boss battle

        Parameters
        ----------
        user: discord.User
            User to force join
        user_id: str
            User ID to force join
        """
        await interaction.response.defer(ephemeral=True, thinking=True)

        if (user and user_id) or (not user and not user_id):
            await interaction.followup.send("You must provide either `user` or `user_id`.", ephemeral=True)
            return

        if not user:
            try:
                user = await self.bot.fetch_user(int(user_id))
            except ValueError:
                await interaction.followup.send("The user ID you gave is not valid.", ephemeral=True)
                return
            except discord.NotFound:
                await interaction.followup.send("The given user ID could not be found.", ephemeral=True)
                return
        else:
            user_id = str(user.id)

        if not self.boss_enabled:
            return await interaction.followup.send("Boss is disabled", ephemeral=True)
        if int(user_id) in self.users:
            return await interaction.followup.send("This user is already in the boss battle.", ephemeral=True)

        self.users.append(int(user_id))
        if int(user_id) in self.disqualified:
            self.disqualified.remove(int(user_id))

        await interaction.followup.send(f"{user} has been force-joined into the Boss Battle.", ephemeral=True)
        await self._log_action(
            f"{user} has joined the `{self.bossball}` Boss Battle."
            f" [hackjoin by {await self.bot.fetch_user(int(interaction.user.id))}]"
        )

    @admin.command()
    @admin_permissions_check()
    async def ping(self, interaction: discord.Interaction["BallsDexBot"], unselected: bool | None = False):
        """
        Ping all the alive players

        Parameters
        ----------
        unselected: bool
            Only ping users who haven't selected yet
        """
        await interaction.response.defer(ephemeral=True, thinking=True)

        if len(self.users) == 0:
            return await interaction.followup.send("There are no users joined/remaining", ephemeral=True)

        pingsmsg = ""
        if unselected:
            for userid in self.users:
                if [userid, self.round] not in self.usersinround:
                    pingsmsg += f"<@{userid}> "
        else:
            for userid in self.users:
                pingsmsg += f"<@{userid}> "

        if pingsmsg == "":
            await interaction.followup.send("All users have selected", ephemeral=True)
        elif len(pingsmsg) < 2000:
            await interaction.followup.send("Ping Successful", ephemeral=True)
            await interaction.channel.send(pingsmsg)
        else:
            await interaction.followup.send("Message too long, exceeds 2000 character limit", ephemeral=True)

    @admin.command()
    @admin_permissions_check()
    async def stats(self, interaction: discord.Interaction["BallsDexBot"]):
        """See current stats of the boss"""
        await interaction.response.defer(ephemeral=True, thinking=True)

        stats_text = f"""Boss: {self.bossball.country if self.bossball else "None"}
HP: {self.bossHP}/{self.bossmaxhp}
Round: {self.round}
Users: {len(self.users)}
Disqualified: {len(self.disqualified)}
Attack Phase: {self.attack}
Picking Active: {self.picking}
Users in Round: {len(self.usersinround)}
Damage Records: {len(self.usersdamage)}"""

        await interaction.followup.send(f"```\n{stats_text}\n```", ephemeral=True)

    async def _defeat_boss(self, channel):
        """
        Handle boss defeat.

        Nothing calls this yet. It used to reach for an `interaction` it never had, which would
        have raised the moment anything did, so it now takes the channel it needs.
        """
        self.boss_enabled = False
        self.picking = False

        # Find winner (player with most participation)
        winner_id = None
        if self.users:
            winner_id = self.users[0]  # Simple: first participant wins

        if winner_id:
            await self._reward_winner(winner_id, channel=channel)

    async def _reward_winner(self, bosswinner: int, channel=None):
        """Reward the winner with a Boss special"""
        try:
            boss_special = None

            for special in specials.values():
                if special.name.lower() == "boss":
                    boss_special = special
                    break

            if boss_special:
                player = await Player.objects.aget(discord_id=bosswinner)
                # Create a special ball instance for the winner
                await BallInstance.objects.acreate(
                    ball=self.bossball,  # Use the actual boss ball
                    player=player,
                    special_id=boss_special.id,
                    attack_bonus=0,
                    health_bonus=0,
                    tradeable=True,
                )
                bosswinner_user = await self.bot.fetch_user(int(bosswinner))
                await self._log_action(
                    f"`BOSS REWARDS` gave {settings.collectible_name} {self.bossball} to {bosswinner_user}. "
                    f"Special=Boss "
                    f"ATK=0 HP=0"
                )

                if channel:
                    await channel.send(
                        f"# Boss has concluded {self.bot.get_emoji(self.bossball.emoji_id)}"
                        f"\n<@{bosswinner}> has won the Boss Battle!\n\n"
                        f"`Boss` `{self.bossball}` {settings.collectible_name} was successfully given.\n"
                    )
            else:
                if channel:
                    await channel.send(
                        "⚠️ Boss special not found! Please ensure there's a special named 'Boss' in the database."
                    )
        except Exception as e:
            log.error(f"Error rewarding winner: {e}")
            if channel:
                await channel.send(f"❌ Error rewarding winner: {e}")

    def _reset_battle_state(self):
        if self.auto_task is not None:
            self.auto_task.cancel()
            self.auto_task = None
        """Reset all boss battle state variables"""
        self.round = 0
        self.balls = []
        self.users = []
        self.currentvalue = ""
        self.usersdamage = []
        self.usersinround = []
        self.bossHP = 0
        self.attack = False
        self.bossattack = 0
        self.bossball = None
        self.bossattack_image = None
        self.bossdefend_image = None
        self.disqualified = []
        self.lasthitter = 0
        self.pending_selections = {}

    async def _log_action(self, message: str):
        """Log boss actions to console and webhook."""
        log.info(f"Boss: {message}", extra={"webhook": True})
