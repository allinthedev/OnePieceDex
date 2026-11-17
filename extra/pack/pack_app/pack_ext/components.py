from typing import TYPE_CHECKING

import discord
from currency_app.models import Item
from discord.ui import Button, button, select

from ballsdex.core.utils.menus.old import Pages, menus
from bd_models.models import Ball, Player
from settings.models import settings
from settings.utils import format_currency

from .opening import PackError, active_specials, open_packs_for, opening_embed, treasure_card, treasure_embed
from .rolls import Card, roll_special

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


class SelectBallPackSource(menus.ListPageSource):
    def __init__(self, entries: list[Ball]):
        super().__init__(entries, per_page=25)

    async def format_page(self, menu: "SelectBallPackView", balls: list[Ball]):
        menu.set_options(balls)
        return True  # signal to edit the page


class SelectBallPackView(Pages):
    """
    The picker for a pack whose treasure the player chooses.

    `remaining` is how many packs are still paid for but unopened. Each pick spends one, so a
    player opening five picks five times and may pick a different treasure every time. Walking
    away costs nothing: a pack is only charged for when its treasure is taken.
    """

    def __init__(
        self,
        pack: Item,
        interaction: discord.Interaction["BallsDexBot"],
        balls: list[Ball],
        remaining: int = 1,
    ):
        self.pack = pack
        self.bot = interaction.client
        self.remaining = max(int(remaining), 1)
        # when on, the next pick spends every remaining pack on that one treasure
        self.all_the_same = False
        source = SelectBallPackSource(balls)
        super().__init__(source=source, interaction=interaction)
        self.add_item(self.select_ball_menu)
        if self.remaining > 1:
            self.add_item(self.same_treasure)

    @property
    def prompt(self) -> str:
        """What to say above the menu, so the player knows how many picks are left."""
        collectible = settings.collectible_name
        if self.remaining > 1:
            if self.all_the_same:
                return (
                    f"Pick one {collectible} and the remaining **{self.remaining}** packs all give it."
                )
            return f"Select the {collectible} you want — **{self.remaining}** packs left to open."
        return f"Select the {collectible} that you want to purchase."

    @button(label="All the same one", style=discord.ButtonStyle.secondary)
    async def same_treasure(self, interaction: discord.Interaction["BallsDexBot"], button: Button):
        """Spend every remaining pack on whichever treasure is picked next."""
        self.all_the_same = not self.all_the_same
        button.style = discord.ButtonStyle.primary if self.all_the_same else discord.ButtonStyle.secondary
        button.label = "One at a time" if self.all_the_same else "All the same one"
        await interaction.response.edit_message(content=self.prompt, view=self)

    def set_options(self, balls: list[Ball]):
        options: list[discord.SelectOption] = []
        for ball in balls:
            emoji = self.bot.get_emoji(int(ball.emoji_id))
            options.append(discord.SelectOption(label=ball.country, emoji=emoji, value=f"{ball.pk}"))
        self.select_ball_menu.options = options

    @select()
    async def select_ball_menu(self, interaction: discord.Interaction["BallsDexBot"], item: discord.ui.Select):
        await interaction.response.defer(thinking=True, ephemeral=True)
        ball = await Ball.objects.aget(pk=int(interaction.data.get("values")[0]))  # type: ignore
        pack = self.pack
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)

        # the treasure is the player's pick, but the special riding on each copy still rolls
        # on the pack's own odds, so five of the same name are not five of the same card
        count = self.remaining if self.all_the_same else 1
        specials_in_play = [] if pack.special_id else active_specials()
        forced = [
            Card(ball.pk, ball.rarity, roll_special(specials_in_play, factor=pack.special_chance_factor))
            for _ in range(count)
        ]
        try:
            opening = await open_packs_for(
                self.bot,
                player,
                pack,
                count,
                server_id=interaction.guild_id,
                channel_id=interaction.channel_id,
                forced=forced,
            )
        except PackError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        if len(opening.instances) == 1:
            embed = await treasure_embed(opening, interaction.user)
            file = await treasure_card(self.bot, opening.instances[0])
            await interaction.followup.send(embed=embed, file=file)
        else:
            await interaction.followup.send(embed=opening_embed(self.bot, opening, interaction.user))

        self.remaining -= count
        if self.remaining > 0:
            # more packs are waiting: keep the menu open and say how many are left
            await self.original_interaction.edit_original_response(content=self.prompt, view=self)
            return
        self.stop()
        self.disable_button()
        await self.original_interaction.edit_original_response(view=self)

    def disable_button(self):
        self.stop()
        for item in self.children:
            item.disabled = True  # type: ignore


class ShopPages(Pages):
    def __init__(self, source, *, interaction, check_embeds=False, compact=False):
        super().__init__(source, interaction=interaction, check_embeds=check_embeds, compact=compact)
        self._current_item: Item | None = None
        self.add_item(self.buy_item)

    @button(style=discord.ButtonStyle.primary, label="Buy it!")
    async def buy_item(self, interaction: discord.Interaction["BallsDexBot"], button: Button):
        if not self._current_item:
            await interaction.response.send_message("There isn't any item to buy.", ephemeral=True)
            return
        pack = self._current_item
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)

        listed = [x.cached_ball async for x in pack.balls.all()]
        if listed and pack.cards == 1:
            # a one-treasure pack with a treasure list is the player's own pick, so it is only
            # charged for once they have picked: closing the menu now costs them nothing
            if pack.prize and player.money < pack.prize:
                emoji = self.bot.get_emoji(pack.emoji_id) if pack.emoji_id else ""
                await interaction.response.send_message(
                    f"You don't have enough {settings.currency_display_plural(self.bot)} to buy "
                    f"**{emoji} {pack.name}**\n"
                    f"Your actual balance: {format_currency(player.money, False, self.bot)}",
                    ephemeral=True,
                )
                return
            paginator = SelectBallPackView(pack, interaction, listed)
            await paginator.start(content=paginator.prompt, ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            opening = await open_packs_for(
                self.bot, player, pack, server_id=interaction.guild_id, channel_id=interaction.channel_id
            )
        except PackError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        if len(opening.instances) == 1:
            embed = await treasure_embed(opening, interaction.user)
            await interaction.followup.send(embed=embed, file=await treasure_card(self.bot, opening.instances[0]))
            return
        await interaction.followup.send(embed=opening_embed(self.bot, opening, interaction.user))


class ShopMenuSource(menus.ListPageSource):
    def __init__(self, entries: list[Item], bot: "BallsDexBot", luck: dict[int, float] | None = None):
        super().__init__(entries, per_page=1)
        self.bot = bot
        # per pack, the luck bonus the player browsing the shop carries right now
        self.luck = luck or {}

    def _pack_details(self, page: Item) -> str:
        """What this pack holds and how its odds are bent, for the packs that say anything."""
        lines = []
        if page.cards > 1:
            lines.append(f"Treasures: **{page.cards}** per pack")
        if page.packs_per_command > 1:
            lines.append(f"Open up to **{page.packs_per_command}** at a time with `/pack open`")
        if page.rare_rarity is not None:
            rare = f"Rare at rarity **{page.rare_rarity}** or below"
            if page.pity_every:
                rare += f", guaranteed within **{page.pity_every}** packs"
            lines.append(rare)
            bonus = self.luck.get(page.pk, 0.0)
            if bonus:
                lines.append(f"Your luck bonus right now: **+{round(bonus * 100)}%**")
        return "".join(f"{line}\n" for line in lines)

    async def format_page(self, menu: ShopPages, page: Item) -> discord.Embed:
        menu._current_item = self.entries[menu.current_page]
        embed = discord.Embed(title=page.name, color=settings.embed_colour)
        embed.set_footer(text=f"Item {menu.current_page + 1}/{menu.source.get_max_pages()}")
        emoji = str(self.bot.get_emoji(page.emoji_id)) if page.emoji_id else ""

        description = f"{page.description}\n\n" if page.description else ""
        description += (
            f"Price: **{format_currency(page.prize or 0, False, self.bot)}**\n"
            f"Special: **{page.special.name if page.special else 'Any'}**\n"
        )
        description += self._pack_details(page)

        countryballs = [x async for x in page.balls.all()]
        if countryballs:
            description += f"# Possible {settings.plural_collectible_name.title()}\n"
            for countryball in countryballs:
                emoji = self.bot.get_emoji(countryball.cached_ball.emoji_id)
                if emoji:
                    description += f"- {emoji} {countryball.cached_ball.country}\n"
                else:
                    description += f"- {countryball.cached_ball.country}\n"
        else:
            description += f"Minimum Rarity: **{page.minimum_rarity}**\nMaximum Rarity: **{page.maximum_rarity}**\n"

        embed.description = description
        return embed
