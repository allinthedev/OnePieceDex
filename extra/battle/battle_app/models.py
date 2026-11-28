from asgiref.sync import sync_to_async
from django.db import models
from django.db.models import F, Q
from django.forms import ValidationError

from bd_models.models import Ball, BallGroup, BallInstance, Player, Special, balls, groups, specials


class BattleCapacityEffect(models.TextChoices):
    """
    What a treasure's Capacity does when it is used in a battle.

    The values are the ones `battle_ext.engine` branches on, so they are not free text.
    """

    DEFAULT = "", "Plain special attack (uses the default multiplier in the settings)"
    HEAL_PERCENT = "heal_percent", "Heals the user by a % of its own max health"
    FLAT_DAMAGE = "flat_damage", "Deals a fixed amount of damage, whatever the attack stat"
    DAMAGE_MULTIPLIER = "damage_multiplier", "Attacks with its damage multiplied"


class Buff(models.Model):
    """
    What a treasure (or every treasure of a special) is worth in a battle beyond its own stats: flat
    bonuses, and what its Capacity actually does.

    The Capacity lives here rather than in `Ball.capacity_logic`, which reads like the obvious place and
    is not: that column belongs to the frames package, which stores each treasure's alternate artwork in
    it. The name of the capacity still comes from `Ball.capacity_name`, which nothing else claims, so a
    treasure keeps its own wording and only needs a row here to be given an effect.
    """

    ball = models.OneToOneField(
        Ball, on_delete=models.CASCADE, null=True, blank=True, help_text="Ball that will receive an increase"
    )
    ball_id: int | None
    special = models.OneToOneField(
        Special, on_delete=models.CASCADE, null=True, blank=True, help_text="Specials that will receive an increase"
    )
    special_id: int | None
    health = models.IntegerField(default=0, help_text="Amount of health to add")
    attack = models.IntegerField(default=0, help_text="Amount of attack to add")
    capacity_effect = models.CharField(
        max_length=24,
        choices=BattleCapacityEffect.choices,
        blank=True,
        default=BattleCapacityEffect.DEFAULT,
        help_text="What the Capacity action does for this treasure. Left on the plain special attack, it hits "
        "for the default multiplier set in the battle settings.",
    )
    capacity_value = models.FloatField(
        default=0,
        help_text="The number the effect needs: a percentage healed, an amount of damage, or a multiplier. "
        "Ignored by the plain special attack. An amount of damage is dealt as written: size it against health "
        "as the health multiplier of the battle settings leaves it, not as the cards show it.",
    )

    @classmethod
    def get_buff(cls, instance: "BallInstance"):
        buff = cls.objects.filter(ball=instance.countryball).first()
        if not buff:
            special = instance.specialcard
            if special:
                buff = cls.objects.filter(special=special).first()
        return buff

    @classmethod
    async def aget_buff(cls, instance: "BallInstance"):
        return await sync_to_async(cls.get_buff)(instance)

    def clean(self):
        super().clean()
        has_ball = self.ball_id is not None
        has_special = self.special_id is not None
        if not has_ball and not has_special:
            raise ValidationError("You must provide either a ball or a special.")

        if has_ball and has_special:
            raise ValidationError("You cannot set both a ball and a special.")

        if self.capacity_effect and self.capacity_value <= 0:
            raise ValidationError("A capacity effect needs a value above zero to do anything.")

    def save(self, **kwargs) -> None:
        # The rules above live in clean() so the panel shows them next to the form instead of failing
        # the request; they are run again here for the rows that never go through a form.
        # Keywords only: Django stopped taking save()'s arguments by position, and passing them on that
        # way is what made every single save of a buff raise, so no buff could ever be created.
        self.clean()
        return super().save(**kwargs)

    @property
    def cached_ball(self):
        return balls.get(self.ball_id) or self.ball if self.ball_id else None

    @property
    def cached_special(self):
        return specials.get(self.special_id) or self.special if self.special_id else None

    class Meta:
        managed = True
        db_table = "buff"

    @property
    def capacity_summary(self) -> str:
        """What this row's Capacity does, in words, for the admin list."""
        if not self.capacity_effect:
            return "plain special attack"
        value = f"{self.capacity_value:g}"
        if self.capacity_effect == BattleCapacityEffect.HEAL_PERCENT:
            return f"heals {value}% of max health"
        if self.capacity_effect == BattleCapacityEffect.FLAT_DAMAGE:
            return f"{value} fixed damage"
        return f"attacks at x{value}"

    def display(self):
        if self.cached_ball:
            text = f"{self.cached_ball.country} "
        elif self.cached_special:
            text = f"{self.cached_special.name} "
        else:
            text = ""
        return f"{text} buff"

    def __str__(self):
        return self.display()


# the shortest turn the panel accepts: time to read the board and press a button
MIN_TURN_SECONDS = 10


def default_tier_bounds() -> list[int]:
    """Where one rarity tier ends and the next begins. A function, so each row gets a list of its own."""
    return [15, 35, 85, 140, 180]


class BattleSettings(models.Model):
    # Combat
    attack_variance_min = models.FloatField(default=0.6, help_text="Lowest multiplier applied to a hit's base damage.")
    attack_variance_max = models.FloatField(
        default=1.0, help_text="Highest multiplier applied to a hit's base damage."
    )
    crit_chance = models.FloatField(default=0.5, help_text="Chance (0-1) that a Crit Gamble action lands.")
    crit_multiplier = models.FloatField(default=2.0, help_text="Damage multiplier on a successful Crit Gamble.")
    crit_fail_multiplier = models.FloatField(default=0.5, help_text="Damage multiplier on a missed Crit Gamble.")
    dodge_chance = models.FloatField(default=0.15, help_text="Chance (0-1) that any damaging action is dodged.")
    heal_percent_min = models.FloatField(default=25.0, help_text="Minimum %% of max health restored by Heal.")
    heal_percent_max = models.FloatField(default=45.0, help_text="Maximum %% of max health restored by Heal.")
    heal_uses_per_battle = models.PositiveIntegerField(
        default=2, help_text="How many times a single card can use Heal in one battle."
    )
    capacity_uses_per_battle = models.PositiveIntegerField(
        default=1, help_text="How many times a single card can use its Capacity ability in one battle."
    )
    default_capacity_multiplier = models.FloatField(
        default=1.5,
        help_text=(
            "Damage multiplier used by the Capacity action when the treasure's Buff sets no capacity "
            "effect, which is the case for every treasure until one is given one."
        ),
    )
    health_multiplier = models.FloatField(
        default=3.0,
        help_text="What every fighter's health is multiplied by in a battle, what it holds included. Attack "
        "and health are about the same number on every treasure, so at 1 a hit takes most of an equal "
        "opponent's health and a character lasts one or two hits. At 2 it lasts two to four, at 3 three to "
        "five, and battles get longer by as much. Between 0.5 and 10. Only characters added to a deck after a "
        "change are affected.",
    )
    turn_timeout_seconds = models.PositiveIntegerField(
        default=60, help_text="If the active player doesn't act in time, the turn auto-resolves as an Attack."
    )
    max_deck_size = models.PositiveIntegerField(default=4, help_text="Default deck size for /battle start.")

    # Tier-based damage scaling. A tier is a BAND of rarities, cut by `tier_bounds`; since a LOWER rarity
    # number means a RARER card in this game, "enemy is a tier higher" means the enemy is rarer (harder
    # matchup, less damage dealt) and "enemy is a tier lower" means the enemy is more common (easier
    # matchup, more damage dealt). Applies to every damaging action (Attack, Crit Gamble, Capacity),
    # stacking multiplicatively with the lore Matchup multiplier.
    #
    # The five multipliers run from 0.9 to 1.0 on purpose: whatever the gap in rarity, it never costs more
    # than 10% of the damage. A rare card already hits harder through its own stats, and by a wide margin;
    # this only adds a touch on top.
    tier_bounds = models.JSONField(
        default=default_tier_bounds,
        help_text="Where each rarity tier ends, rarest first, as a list of rarities: [15, 35, 85, 140, 180] "
        "makes six tiers, T1 to T15, T16 to T35, and so on, the last one holding everything past 180. Cards of "
        "the same tier fight as equals however their rarities differ inside it.",
    )
    tier_same_multiplier = models.FloatField(default=0.95, help_text="Damage multiplier vs. an equal-tier enemy.")
    tier_enemy_1_higher_multiplier = models.FloatField(
        default=0.925, help_text="Damage multiplier vs. an enemy 1 tier higher (rarer)."
    )
    tier_enemy_2plus_higher_multiplier = models.FloatField(
        default=0.9, help_text="Damage multiplier vs. an enemy 2+ tiers higher (rarer)."
    )
    tier_enemy_1_lower_multiplier = models.FloatField(
        default=0.975, help_text="Damage multiplier vs. an enemy 1 tier lower (more common)."
    )
    tier_enemy_2plus_lower_multiplier = models.FloatField(
        default=1.0, help_text="Damage multiplier vs. an enemy 2+ tiers lower (more common)."
    )
    tier_enemy_2plus_lower_bonus_crit_chance = models.FloatField(
        default=0.0,
        help_text="Extra critical-strike chance (0-1) added to ANY damaging action vs. an enemy 2+ tiers lower. "
        "Left at 0 so that a gap in rarity is worth exactly what the multipliers above say and nothing more.",
    )

    # Special-card flat stat bonuses in battle, matching the existing /boss fight boosts exactly.
    haki_special_bonus = models.PositiveIntegerField(
        default=500, help_text="Flat ATK and HP bonus for Haki Infused (⚡) special cards, same as /boss."
    )
    shiny_special_bonus = models.PositiveIntegerField(
        default=1000, help_text="Flat ATK and HP bonus for Shiny (✨) special cards, same as /boss."
    )
    mythical_special_bonus = models.PositiveIntegerField(
        default=1500, help_text="Flat ATK and HP bonus for Mythical (🔮) special cards, same as /boss."
    )

    # Equipment. Only characters fight: a weapon and a devil fruit are attached to one, and add a share of
    # their own stats to it. Which treasure plays which part is read from the groups it belongs to.
    character_group = models.ForeignKey(
        BallGroup,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text='The group of the treasures allowed to fight. Left empty, the group named "Characters".',
    )
    weapon_group = models.ForeignKey(
        BallGroup,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text='The group of the treasures equipped as a weapon. Left empty, the group named "Weapons".',
    )
    fruit_group = models.ForeignKey(
        BallGroup,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text='The group of the treasures equipped as a devil fruit. Left empty, the group named '
        '"Devil fruits".',
    )
    default_equip_percent = models.PositiveIntegerField(
        default=50,
        help_text="Share of an item's stats, in percent, a character gets when no affinity rule says anything "
        "about the pair: neither for this character, nor for this item, nor for its kind.",
    )
    full_set_bonus_percent = models.PositiveIntegerField(
        default=10,
        help_text="Extra percent of attack and health for a character holding both a weapon and a devil fruit, "
        "applied on its total. 0 turns the bonus off.",
    )
    resistance_floor = models.FloatField(
        default=0.25,
        help_text="The least damage equipment can leave of one hit, as a multiplier. An attacker wears two items "
        "and the resistances to each multiply, so two reasonable rules could otherwise add up to an immunity.",
    )
    resistance_ceiling = models.FloatField(
        default=2.0,
        help_text="The most equipment can multiply one hit by, when weaknesses to the attacker's weapon and "
        "fruit line up.",
    )

    # Anti-abuse earnings
    guaranteed_daily_wins = models.PositiveIntegerField(
        default=3, help_text="How many wins per rolling 24h pay the flat guaranteed_win_reward."
    )
    guaranteed_win_reward = models.PositiveIntegerField(
        default=50, help_text="Flat berries paid for each of the first guaranteed_daily_wins wins per day."
    )
    performance_base_reward = models.PositiveIntegerField(
        default=30, help_text="Base berries for wins past the guaranteed daily count, before scaling."
    )
    performance_scale_min = models.FloatField(
        default=0.5, help_text="Minimum scale applied to performance_base_reward (beating a much weaker opponent)."
    )
    performance_scale_max = models.FloatField(
        default=2.0, help_text="Maximum scale applied to performance_base_reward (beating a much stronger opponent)."
    )
    max_rewarded_wins_per_opponent_per_day = models.PositiveIntegerField(
        default=1,
        help_text="Wins past this many against the SAME opponent in a day are still recorded but pay 0 berries "
        "(blunts the simplest two-account farming loop).",
    )

    def clean(self):
        super().clean()
        bounds = self.tier_bounds
        numbers = isinstance(bounds, list) and all(
            isinstance(bound, (int, float)) and not isinstance(bound, bool) for bound in bounds
        )
        if not numbers or not bounds:
            raise ValidationError({"tier_bounds": "A list of rarities is needed, such as [15, 35, 85, 140, 180]."})
        if bounds != sorted(set(bounds)):
            raise ValidationError({"tier_bounds": "The bounds go up, with no rarity twice: rarest tier first."})
        if not 0.5 <= self.health_multiplier <= 10:
            raise ValidationError({"health_multiplier": "Between 0.5 and 10."})
        if self.turn_timeout_seconds < MIN_TURN_SECONDS:
            # there is no battle without a clock: 0 does not switch it off, it plays every turn at once
            raise ValidationError(
                {"turn_timeout_seconds": f"A turn lasts at least {MIN_TURN_SECONDS} seconds."}
            )

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @classmethod
    async def aload(cls):
        return await sync_to_async(cls.load)()

    class Meta:
        managed = True
        db_table = "battlesettings"
        constraints = [
            models.CheckConstraint(
                condition=Q(attack_variance_min__lte=F("attack_variance_max")),
                name="battlesettings_variance_min_lte_max",
            ),
            models.CheckConstraint(
                condition=Q(heal_percent_min__lte=F("heal_percent_max")), name="battlesettings_heal_min_lte_max"
            ),
            models.CheckConstraint(
                condition=Q(performance_scale_min__lte=F("performance_scale_max")),
                name="battlesettings_perf_scale_min_lte_max",
            ),
            models.CheckConstraint(
                condition=Q(crit_chance__gte=0) & Q(crit_chance__lte=1), name="battlesettings_crit_chance_bounds"
            ),
            models.CheckConstraint(
                condition=Q(resistance_floor__gt=0) & Q(resistance_floor__lte=F("resistance_ceiling")),
                name="battlesettings_resistance_floor_lte_ceiling",
            ),
            models.CheckConstraint(
                condition=Q(dodge_chance__gte=0) & Q(dodge_chance__lte=1), name="battlesettings_dodge_chance_bounds"
            ),
            models.CheckConstraint(
                condition=Q(tier_enemy_2plus_lower_bonus_crit_chance__gte=0)
                & Q(tier_enemy_2plus_lower_bonus_crit_chance__lte=1),
                name="battlesettings_tier_bonus_crit_bounds",
            ),
            models.CheckConstraint(
                condition=Q(health_multiplier__gte=0.5) & Q(health_multiplier__lte=10),
                name="battlesettings_health_multiplier_bounds",
            ),
        ]

    def __str__(self) -> str:
        return "Battle Settings"


class Matchup(models.Model):
    """
    A lore-based rivalry: when `attacker` fights `defender`, damage dealt is scaled by
    `damage_multiplier` (e.g. Akainu vs Ace = 1.3 for a 30%% edge). Neutral (no row) means ×1.0.
    Not symmetric — add the reverse row too if the rivalry should cut both ways.
    """

    attacker = models.ForeignKey(Ball, on_delete=models.CASCADE, related_name="matchups_as_attacker")
    attacker_id: int
    defender = models.ForeignKey(Ball, on_delete=models.CASCADE, related_name="matchups_as_defender")
    defender_id: int
    damage_multiplier = models.FloatField(
        default=1.25,
        help_text="Damage multiplier applied when attacker hits defender. 1.0 = no effect, above 1 hits harder, "
        "below 1 holds back. Between 0.1 and 5.",
    )
    note = models.CharField(max_length=200, blank=True, default="", help_text="Why, for whoever reads this next.")

    class Meta:
        managed = True
        db_table = "battlematchup"
        unique_together = (("attacker", "defender"),)
        constraints = [
            models.CheckConstraint(condition=~Q(attacker=F("defender")), name="battlematchup_attacker_neq_defender"),
            models.CheckConstraint(
                condition=Q(damage_multiplier__gte=0.1) & Q(damage_multiplier__lte=5),
                name="battlematchup_multiplier_bounds",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.attacker.country} > {self.defender.country} (x{self.damage_multiplier})"


class GroupMatchup(models.Model):
    """
    A bond between the members of a group: when BOTH fighters belong to it, damage between them is scaled.
    "The Whitebeard Pirates are brothers: they hold back against each other", at 0.5.

    A `Matchup` naming the exact pair always wins over this; between two groups both fighters share, the
    narrower one does.
    """

    group = models.OneToOneField(
        BallGroup,
        on_delete=models.CASCADE,
        related_name="battle_bond",
        help_text="The group both fighters have to belong to.",
    )
    group_id: int
    damage_multiplier = models.FloatField(
        default=0.75,
        help_text="Applied to the damage between two members of the group. Below 1 they hold back, above 1 "
        "they go at each other harder. Between 0.1 and 5.",
    )
    note = models.CharField(max_length=200, blank=True, default="", help_text="Why, for whoever reads this next.")

    class Meta:
        managed = True
        db_table = "battlegroupmatchup"
        verbose_name = "group bond"
        constraints = [
            models.CheckConstraint(
                condition=Q(damage_multiplier__gte=0.1) & Q(damage_multiplier__lte=5),
                name="battlegroupmatchup_multiplier_bounds",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.group} among themselves (x{self.damage_multiplier:g})"


# the groups a treasure's part in a battle is read from when the settings name none
ROLE_GROUP_NAMES = {"character": "Characters", "weapon": "Weapons", "fruit": "Devil fruits"}


def role_group_ids(battle_settings: BattleSettings) -> dict[str, int | None]:
    """
    The group standing for each part a treasure can play, by id, from the settings or from the usual names.

    Read from the group cache, so it costs no query; a part whose group cannot be found maps to None, and no
    treasure can then play it.
    """
    chosen = {
        "character": battle_settings.character_group_id,
        "weapon": battle_settings.weapon_group_id,
        "fruit": battle_settings.fruit_group_id,
    }
    by_name = {group.name: pk for pk, group in groups.items()}
    return {role: pk or by_name.get(ROLE_GROUP_NAMES[role]) for role, pk in chosen.items()}


def role_of(ball_id: int, battle_settings: BattleSettings) -> str | None:
    """
    The part a treasure plays in a battle: "character", "weapon", "fruit", or None for the ones that sit
    battles out (ships, crew cards, anything in no role group).
    """
    for role, group_id in role_group_ids(battle_settings).items():
        group = groups.get(group_id) if group_id else None
        if group is not None and ball_id in group._ball_ids:
            return role
    return None


def group_ids_of(ball_id: int) -> list[int]:
    """Every group a treasure belongs to, from the cache."""
    return [pk for pk, group in groups.items() if ball_id in group._ball_ids]


def group_sizes() -> dict[int, int]:
    """How many treasures each group holds, which is how the narrower of two matching groups is told."""
    return {pk: len(group._ball_ids) for pk, group in groups.items()}


class EquipAffinity(models.Model):
    """
    What share of an item's stats a character gets when it is equipped on them.

    Three kinds of lines live here, and the most precise one wins outright (see `battle_ext.loadout`):
    a character with an exact item (Zoro with Wado Ichimonji, 200), a character with a kind of item (Zoro
    with any katana, 150), and a kind of item for anybody (any katana, 50), which is the default of a
    category. A kind of item is a group, the same groups the rest of the dex uses.
    """

    character = models.ForeignKey(
        Ball,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="equip_affinities",
        help_text="The character holding the item. Leave empty for a rule about everybody.",
    )
    character_id: int | None
    item = models.ForeignKey(
        Ball,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="+",
        help_text="One exact weapon or devil fruit. Set this or a group, never both.",
    )
    item_id: int | None
    item_group = models.ForeignKey(
        BallGroup,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="+",
        help_text="A kind of item: every weapon or fruit of this group. Set this or an exact item, never both.",
    )
    item_group_id: int | None
    percent = models.PositiveIntegerField(
        default=100,
        help_text="Share of the item's own attack and health added to the character, in percent. 200 for an "
        "item that is canonically theirs, 110 to 150 for a kind they master, 50 for one they have no business "
        "holding, less for one they cannot use at all.",
    )
    note = models.CharField(max_length=200, blank=True, default="", help_text="Why, for whoever reads this next.")

    def clean(self):
        super().clean()
        if bool(self.item_id) == bool(self.item_group_id):
            raise ValidationError("Set either an exact item or a group of items, and only one of the two.")

    def __str__(self) -> str:
        who = self.character.country if self.character_id and self.character else "Anybody"
        what = self.item.country if self.item_id and self.item else f"any {self.item_group}"
        return f"{who} + {what}: {self.percent}%"

    class Meta:
        managed = True
        db_table = "battleequipaffinity"
        verbose_name = "equip affinity"
        verbose_name_plural = "equip affinities"
        constraints = [
            models.CheckConstraint(
                condition=Q(item__isnull=False, item_group__isnull=True)
                | Q(item__isnull=True, item_group__isnull=False),
                name="battleequipaffinity_item_xor_group",
            ),
            # one line per pair. Written as four partial indexes because a plain unique constraint lets any
            # number of rows through as soon as one of its columns is empty
            models.UniqueConstraint(
                fields=["character", "item"],
                condition=Q(character__isnull=False, item__isnull=False),
                name="battleequipaffinity_character_item",
            ),
            models.UniqueConstraint(
                fields=["character", "item_group"],
                condition=Q(character__isnull=False, item_group__isnull=False),
                name="battleequipaffinity_character_group",
            ),
            models.UniqueConstraint(
                fields=["item"],
                condition=Q(character__isnull=True, item__isnull=False),
                name="battleequipaffinity_anybody_item",
            ),
            models.UniqueConstraint(
                fields=["item_group"],
                condition=Q(character__isnull=True, item_group__isnull=False),
                name="battleequipaffinity_anybody_group",
            ),
        ]


class EquipResistance(models.Model):
    """
    What a defender's equipment does to the damage coming in: a multiplier, tied to what the defender wears
    and to what the attacker wears.

    "Luffy, wearing the Gomu Gomu, takes half damage from blunt weapons." "Anybody wearing the Mera Mera
    takes half as much again from the Magu Magu." Who beats whom whatever they wear stays in `Matchup`.
    """

    character = models.ForeignKey(
        Ball,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="equip_resistances",
        help_text="The defender. Leave empty for a rule about anybody wearing the item below.",
    )
    character_id: int | None
    equipped_item = models.ForeignKey(
        Ball,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="+",
        help_text="What the defender has to be wearing for the rule to apply. Leave empty for a rule that "
        "holds whatever they wear.",
    )
    equipped_item_id: int | None
    against_item = models.ForeignKey(
        Ball,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="+",
        help_text="The exact item the attacker wears. Set this or a group, never both.",
    )
    against_item_id: int | None
    against_group = models.ForeignKey(
        BallGroup,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="+",
        help_text="The kind of item the attacker wears. Set this or an exact item, never both.",
    )
    against_group_id: int | None
    multiplier = models.FloatField(
        default=1.0,
        help_text="Applied to the damage the defender takes. 0.5 halves it (a resistance), 1.5 adds half again "
        "(a weakness). Between 0.05 and 5.",
    )
    note = models.CharField(max_length=200, blank=True, default="", help_text="Why, for whoever reads this next.")

    def clean(self):
        super().clean()
        if bool(self.against_item_id) == bool(self.against_group_id):
            raise ValidationError("Set either the exact item the attacker wears or a group, and only one.")

    def __str__(self) -> str:
        who = self.character.country if self.character_id and self.character else "Anybody"
        worn = f" wearing {self.equipped_item.country}" if self.equipped_item_id and self.equipped_item else ""
        against = (
            self.against_item.country if self.against_item_id and self.against_item else f"any {self.against_group}"
        )
        return f"{who}{worn} vs {against}: x{self.multiplier:g}"

    class Meta:
        managed = True
        db_table = "battleequipresistance"
        verbose_name = "equip resistance"
        verbose_name_plural = "equip resistances"
        constraints = [
            models.CheckConstraint(
                condition=Q(against_item__isnull=False, against_group__isnull=True)
                | Q(against_item__isnull=True, against_group__isnull=False),
                name="battleequipresistance_item_xor_group",
            ),
            models.CheckConstraint(
                condition=Q(multiplier__gte=0.05) & Q(multiplier__lte=5),
                name="battleequipresistance_multiplier_bounds",
            ),
        ]


class BattleRecord(models.Model):
    """
    One row per finished battle. Used as the source of truth for the 1v1 leaderboard and for the
    anti-abuse earnings cap (queried by rolling 24h window) instead of a resettable aggregate
    counter, so admins can see exactly who fought who, for how much, and why a payout was capped.
    """

    player1 = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="battles_as_player1")
    player2 = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="battles_as_player2")
    winner = models.ForeignKey(
        Player, on_delete=models.SET_NULL, null=True, blank=True, related_name="battles_won"
    )
    wager_amount = models.PositiveBigIntegerField(default=0, help_text="Berries each side staked, if any.")
    winner_earnings = models.PositiveBigIntegerField(
        default=0, help_text="Anti-abuse win reward actually paid out (0 if capped that day)."
    )
    turns = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        managed = True
        db_table = "battlerecord"
        indexes = [
            models.Index(fields=["player1"]),
            models.Index(fields=["player2"]),
            models.Index(fields=["winner"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"Battle #{self.pk}: {self.player1_id} vs {self.player2_id}"


class BattleItemEffect(models.TextChoices):
    EXTRA_HEAL = "extra_heal", "Bonus %% healed on this turn's Heal action"
    ATTACK_BOOST = "attack_boost", "Damage multiplier on this turn's Attack/Crit Gamble"
    GUARANTEED_CRIT = "guaranteed_crit", "This turn's Crit Gamble always lands"


class BattleItem(models.Model):
    name = models.CharField(max_length=64, unique=True)
    description = models.CharField(max_length=256, blank=True, null=True)
    price = models.PositiveIntegerField(help_text="Cost in berries.")
    effect_type = models.CharField(max_length=32, choices=BattleItemEffect.choices)
    effect_value = models.FloatField(help_text="Meaning depends on effect_type (a multiplier, a %%, ...).")
    emoji_id = models.BigIntegerField(null=True, blank=True, help_text="Optional custom emoji ID for this item.")
    enabled = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "battleitem"

    def __str__(self) -> str:
        return self.name


class PlayerBattleItem(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="battle_items")
    item = models.ForeignKey(BattleItem, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=0)

    class Meta:
        managed = True
        db_table = "playerbattleitem"
        unique_together = (("player", "item"),)

    def __str__(self) -> str:
        return f"{self.player_id} x{self.quantity} {self.item_id}"


class BattleSessionStatus(models.TextChoices):
    PROPOSED = "proposed", "Proposed"
    ACTIVE = "active", "Active"
    FINISHED = "finished", "Finished"
    CANCELLED = "cancelled", "Cancelled"


class BattleSession(models.Model):
    """
    Persisted battle state. Battles used to live purely in-memory, which was fine when nothing
    was at stake — now that a battle can escrow a berry wager, a bot restart mid-battle must be
    able to find and refund it instead of silently losing track of the money.
    """

    channel_id = models.BigIntegerField()
    player1 = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="battle_sessions_as_player1")
    player2 = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="battle_sessions_as_player2")
    wager_amount = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=16, choices=BattleSessionStatus.choices, default=BattleSessionStatus.PROPOSED)
    state = models.JSONField(default=dict, blank=True, help_text="Decks, HP, whose turn, use counters.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "battlesession"
        indexes = [models.Index(fields=["channel_id"]), models.Index(fields=["status"])]

    def __str__(self) -> str:
        return f"BattleSession #{self.pk} ({self.status})"
