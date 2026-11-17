import random
import string
import zipfile
from collections.abc import AsyncIterable
from enum import StrEnum
from io import BytesIO
from typing import TYPE_CHECKING, NamedTuple, cast

import discord
from discord import ButtonStyle, SeparatorSpacing
from discord.ui import (
    ActionRow,
    Button,
    Container,
    Label,
    Section,
    Select,
    Separator,
    TextDisplay,
    TextInput,
    Thumbnail,
    button,
)
from discord.utils import format_dt

from ballsdex.core.discord import Modal, View
from ballsdex.core.utils.buttons import ConfirmChoiceView
from bd_models.models import (
    BerryPolicy,
    Block,
    DonationPolicy,
    FriendPolicy,
    Friendship,
    MentionPolicy,
    Player,
    PlayerDataDeletion,
    PrivacyPolicy,
    TradeCooldownPolicy,
)
from settings.models import settings

from .utils import get_items_csv, get_trades_csv

if TYPE_CHECKING:
    from crew_app.models import Crew
    from django.db.models import QuerySet

    from ballsdex.core.bot import BallsDexBot

type Interaction = discord.Interaction["BallsDexBot"]


class Row(NamedTuple):
    row: ActionRow
    setting: str
    buttons: dict[int, Button]


class ExportCategory(StrEnum):
    BALLS = "balls"
    TRADES = "trades"
    ALL = "all"


class ExportModal(Modal, title="Data export"):
    category = Label(
        text="Category",
        description="Choose the type of data you want to export.",
        component=Select(
            options=[
                discord.SelectOption(
                    label=settings.collectible_name.title(),
                    description=f"Export all of your {settings.plural_collectible_name}.",
                    value=ExportCategory.BALLS,
                ),
                discord.SelectOption(
                    label="Trades", description="Export your trade history.", value=ExportCategory.TRADES
                ),
                discord.SelectOption(label="All", description="Export everything.", value=ExportCategory.ALL),
            ]
        ),
    )
    footer = TextDisplay(
        f"-# Check the [privacy policy]({settings.privacy_policy}) for more informations about your data."
    )

    async def on_submit(self, interaction: Interaction):
        player = await Player.objects.aget_or_none(discord_id=interaction.user.id)
        if player is None:
            await interaction.response.send_message("You don't have any player data to export.", ephemeral=True)
            return
        await interaction.response.defer()
        files: list[tuple[str, BytesIO]] = []
        category = cast(Select, self.category.component).values[0]
        if category == ExportCategory.BALLS or category == ExportCategory.ALL:
            data = await get_items_csv(player)
            filename = f"{interaction.user.id}_{settings.collectible_name}.csv"
            files.append((filename, data))
        if category == ExportCategory.TRADES or category == ExportCategory.ALL:
            data = await get_trades_csv(player)
            filename = f"{interaction.user.id}_trades.csv"
            files.append((filename, data))
        zip_file = BytesIO()
        with zipfile.ZipFile(zip_file, "w") as z:
            for filename, file in files:
                z.writestr(filename, file.getvalue())
        zip_file.seek(0)
        if zip_file.tell() > 25_000_000:
            await interaction.followup.send(
                "Your data is too large to export. Please contact the bot support for more information.", ephemeral=True
            )
            return
        try:
            await interaction.user.send("Here is your player data:", file=discord.File(zip_file, "player_data.zip"))
            await interaction.followup.send("Your player data has been sent via DMs.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(
                "I couldn't send the player data to your DMs. "
                "Either you blocked me or you disabled DMs in this server.",
                ephemeral=True,
            )


CONFIRMATION_CODE_CHARS = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1IL")


class DeleteDataModal(Modal, title="Confirm data deletion"):
    confirmation = Label(
        text="Confirmation code", component=TextInput(style=discord.TextStyle.short, placeholder="Confirmation code")
    )

    def __init__(self, code: str):
        super().__init__()
        self.code = code
        self.confirmation.description = (
            f"This cannot be undone. Type {code} below to confirm."
        )

    async def on_submit(self, interaction: Interaction):
        value = cast(TextInput, self.confirmation.component).value.strip().upper()
        if value != self.code:
            await interaction.response.send_message(
                "The code you entered did not match. Your data was **not** deleted.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        player = await Player.objects.aget_or_none(discord_id=interaction.user.id)
        if player:
            await player.adelete()

        # Recorded after the player row is gone, so it survives the deletion. Deleting a player
        # also clears their reward cooldowns, which was being used to claim /daily and /weekly
        # over and over; the restriction below makes that pointless.
        deletion = await PlayerDataDeletion.objects.acreate(discord_id=interaction.user.id)
        interaction.client.data_deletion_restrictions[interaction.user.id] = deletion.restricted_until

        await interaction.followup.send(
            "Your player data has been permanently deleted.\n\n"
            f"Your account is now restricted until {format_dt(deletion.restricted_until, 'F')} "
            f"({format_dt(deletion.restricted_until, 'R')}).",
            ephemeral=True,
        )


class ConfirmDeleteDataView(View):
    """Second step of the deletion flow, so the warning above is seen before the code prompt."""

    def __init__(self):
        super().__init__(timeout=120)

    @button(label="I understand, delete my data", style=ButtonStyle.danger)
    async def confirm(self, interaction: Interaction, button: Button):
        code = "".join(random.choices(CONFIRMATION_CODE_CHARS, k=6))
        await interaction.response.send_modal(DeleteDataModal(code))


class DataActionRow(ActionRow):
    @button(label="Export")
    async def export(self, interaction: Interaction, button: Button):
        """
        Export your player data.
        """
        await interaction.response.send_modal(ExportModal())

    @button(label="Delete all data")
    async def delete(self, interaction: Interaction, button: Button):
        # The consequences are spelled out here rather than in the modal: a modal label only
        # holds a short line, and this is irreversible enough to deserve being read first.
        await interaction.response.send_message(
            "## Delete all of your data\n"
            "**This is irreversible.** Every "
            f"{settings.plural_collectible_name} in your inventory and all of your data will be "
            "permanently deleted. Nothing can be restored afterwards.\n\n"
            f"Your account will then be **restricted for {PlayerDataDeletion.RESTRICTION_DAYS} days**, "
            "during which you will not be able to use the bot.\n\n"
            "We reserve the right to keep your user ID and the time of the deletion — and nothing "
            "else — to enforce that restriction and prevent abuse.",
            view=ConfirmDeleteDataView(),
            ephemeral=True,
        )



class SettingsContainer(Container):
    title = Section(
        TextDisplay(content="# Player settings"),
        TextDisplay(content="Configure your personal settings here"),
        accessory=Thumbnail(media=""),
    )
    sep1 = Separator(visible=True, spacing=SeparatorSpacing.small)
    inv_text = TextDisplay(content="### Inventory privacy\n-# Who should be able to view your inventory")
    inv_actions = ActionRow()

    donation_text = TextDisplay(
        content=f"### Donation policy\n-# Who should be able to donate {settings.plural_collectible_name}"
    )
    donation_actions = ActionRow()

    berry_text = TextDisplay(
        content=f"### {settings.currency_plural.title()}\n"
        f"-# Who should be able to send you {settings.currency_plural} with the give command"
    )
    berry_actions = ActionRow()

    crew_text = TextDisplay(content="### Crew\n-# The crew you play for, in hunts and wars run between crews")
    crew_actions = ActionRow()

    fr_text = TextDisplay(content="### Friend requests\n-# You can open or close all friend requests")
    fr_actions = ActionRow()

    trade_text = TextDisplay(
        content="### Trade cooldown\n-# Skip all cooldowns in trades if the other player also has this off"
    )
    trade_actions = ActionRow()

    mention_text = TextDisplay(content="### Mention policy\n-# Choose if you want to be mentioned by the bot or not")
    mention_actions = ActionRow()

    sep2 = Separator(visible=True, spacing=SeparatorSpacing.small)

    data_text = TextDisplay(content="## Your data")
    data_actions = DataActionRow()

    player: Player

    async def interaction_check(self, interaction: Interaction) -> bool:
        if not await interaction.client.blacklist_check(interaction):
            return False
        if interaction.user.id == self.player.discord_id:
            return True
        await interaction.response.send_message("You are not allowed to interact with this!", ephemeral=True)
        return False

    def configure(
        self,
        interaction: Interaction,
        player: Player,
        crews: "list[Crew] | None" = None,
        current_crew: "Crew | None" = None,
    ):
        self.player = player
        self.title.accessory = discord.ui.Thumbnail(media=interaction.user.display_avatar.url)
        self._configure_crew(player, crews or [], current_crew)

        def fill_select(row: ActionRow, setting: str, choices: dict[int, str], placeholder: str):
            """
            A policy as a dropdown rather than one button per option.

            Four buttons cost four components, and this view sits close to Discord's limit of
            40 for the whole thing. A select costs one, and reads better for four options.
            """
            current = getattr(player, setting)
            select: Select = Select(
                placeholder=placeholder,
                options=[
                    discord.SelectOption(label=label, value=str(value), default=value == current)
                    for value, label in choices.items()
                ],
            )

            async def callback(interaction: Interaction):
                picked = int(select.values[0])
                setattr(player, setting, picked)
                await player.asave(update_fields=(setting,))
                for option in select.options:
                    option.default = int(option.value) == picked
                await interaction.response.edit_message(view=self.view)

            select.callback = callback
            row.clear_items()
            row.add_item(select)

        fill_select(
            self.inv_actions,
            "privacy_policy",
            {
                PrivacyPolicy.ALLOW: "Open to everyone",
                PrivacyPolicy.SAME_SERVER: "Same server only",
                PrivacyPolicy.FRIENDS: "Friends only",
                PrivacyPolicy.DENY: "Private",
            },
            "Who can see your inventory",
        )
        fill_select(
            self.donation_actions,
            "donation_policy",
            {
                DonationPolicy.ALWAYS_ACCEPT: "Always accept",
                DonationPolicy.REQUEST_APPROVAL: "Ask me first",
                DonationPolicy.FRIENDS_ONLY: "Friends only",
                DonationPolicy.ALWAYS_DENY: "Closed",
            },
            f"Who can donate {settings.plural_collectible_name} to you",
        )
        fill_select(
            self.berry_actions,
            "berry_policy",
            {
                BerryPolicy.ALWAYS_ACCEPT: "Always accept",
                BerryPolicy.REQUEST_APPROVAL: "Ask me first",
                BerryPolicy.FRIENDS_ONLY: "Friends only",
                BerryPolicy.ALWAYS_DENY: "Closed",
            },
            f"Who can send you {settings.currency_plural}",
        )

        def button_callback(buttons: dict[int, Button], setting: str, value: int):
            async def callback(interaction: Interaction):
                for v, item in buttons.items():
                    if v == value:
                        item.disabled = True
                        item.style = ButtonStyle.primary
                    else:
                        item.disabled = False
                        item.style = ButtonStyle.secondary
                setattr(player, setting, value)
                await player.asave(update_fields=(setting,))
                await interaction.response.edit_message(view=self.view)

            return callback

        settings_buttons = [
            Row(
                self.fr_actions,
                "friend_policy",
                {FriendPolicy.ALLOW: Button(label="Open"), FriendPolicy.DENY: Button(label="Closed")},
            ),
            Row(
                self.trade_actions,
                "trade_cooldown_policy",
                {
                    TradeCooldownPolicy.COOLDOWN: Button(label="Wait 10s"),
                    TradeCooldownPolicy.BYPASS: Button(label="Bypass"),
                },
            ),
            Row(
                self.mention_actions,
                "mention_policy",
                {MentionPolicy.ALLOW: Button(label="Mentions"), MentionPolicy.DENY: Button(label="No mentions")},
            ),
        ]
        for row, setting, buttons in settings_buttons:
            for value, item in buttons.items():
                item.callback = button_callback(buttons, setting, value)
                if getattr(player, setting) == value:
                    item.disabled = True
                    item.style = ButtonStyle.primary
                row.add_item(item)

    def _configure_crew(self, player: Player, crews: "list[Crew]", current: "Crew | None"):
        """
        The crew picker. With no crew set up in the panel the whole section disappears, so a dex
        that does not use crews never shows a menu with nothing in it.
        """
        if not crews:
            self.remove_item(self.crew_text)
            self.remove_item(self.crew_actions)
            return

        standing = f"-# You are flying **{current.label}**" if current else "-# You have not picked one yet"
        self.crew_text.content = (
            f"### Crew\n-# The crew you play for, in hunts and wars run between crews\n{standing}"
        )
        options = [
            discord.SelectOption(
                label=crew.name[:100],
                value=str(crew.pk),
                emoji=crew.emoji or None,
                description=(crew.description[:100] or None),
                default=current is not None and crew.pk == current.pk,
            )
            for crew in crews[:24]
        ]
        if current is not None:
            options.append(discord.SelectOption(label="Leave my crew", value="none", emoji="🚪"))
        select: Select = Select(placeholder="Pick your crew", options=options)

        async def callback(interaction: Interaction):
            from crew_app.models import CrewMembership

            if select.values[0] == "none":
                await CrewMembership.objects.filter(player=player).adelete()
                picked = None
            else:
                picked = next(crew for crew in crews if str(crew.pk) == select.values[0])
                await CrewMembership.objects.aupdate_or_create(player=player, defaults={"crew": picked})
            self._configure_crew(player, crews, picked)
            await interaction.response.edit_message(view=self.view)

        select.callback = callback
        self.crew_actions.clear_items()
        self.crew_actions.add_item(select)


class RelationContainer(Container):
    title = TextDisplay("")
    sep1 = Separator()

    async def paginate_relations[M: Friendship | Block](
        self, qs: "QuerySet[M]", player: Player
    ) -> AsyncIterable[Section]:
        assert self.view
        if TYPE_CHECKING:
            assert isinstance(self.view, discord.ui.LayoutView)

        def get_button(relationship: M):
            b = Button(label="Remove", style=discord.ButtonStyle.secondary)

            async def button_callback(interaction: Interaction):
                # should be handled by the view's interaction_check, but just in case
                assert interaction.user.id == player.discord_id

                await interaction.response.defer(ephemeral=True)
                view = ConfirmChoiceView(interaction)
                await interaction.followup.send(
                    "Are you sure you want to remove this "
                    f"{'friend' if isinstance(relationship, Friendship) else 'block'}?",
                    view=view,
                    ephemeral=True,
                )
                await view.wait()
                if view.value is not True:
                    return
                await relationship.adelete()
                b.disabled = True
                b.parent.children[0].content += "-# Removed"  # type: ignore
                await interaction.edit_original_response(view=self.view)

            b.callback = button_callback
            return b

        async for x in qs:
            other = x.player2 if x.player1 == player else x.player1
            yield Section(TextDisplay(f"<@{other.discord_id}>"), accessory=get_button(x))
