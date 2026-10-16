from typing import Iterable

from collector_app.models import Collector, CollectorTierLevel
from discord import app_commands

from ballsdex.core.utils.transformers import TTLModelTransformer


class CollectorTransformer(TTLModelTransformer[Collector]):
    name = "collector"
    model = Collector

    async def get_from_pk(self, value: int) -> Collector:
        return await self.get_queryset().aget(pk=value)


class CollectorEnabledTransformer(CollectorTransformer):
    async def load_items(self) -> Iterable[Collector]:
        # each collector shows up once, its tiers are picked afterwards
        queryset = Collector.objects.filter(tiers__enabled=True).distinct()
        return [collector async for collector in queryset if collector.active]


class CollectorTierLevelTransformer(TTLModelTransformer[CollectorTierLevel]):
    """
    The kind of recipe: Tier 1, Tier 2, Elemental, Craft... read from the table, so a new one needs no change
    here.
    """

    name = "tier"
    model = CollectorTierLevel

    async def get_from_pk(self, value: int) -> CollectorTierLevel:
        return await self.get_queryset().aget(pk=value)

    async def load_items(self) -> Iterable[CollectorTierLevel]:
        return [level async for level in CollectorTierLevel.objects.order_by("position", "pk")]


CollectorTransform = app_commands.Transform[Collector, CollectorTransformer]
CollectorEnabledTransform = app_commands.Transform[Collector, CollectorEnabledTransformer]
CollectorTierLevelTransform = app_commands.Transform[CollectorTierLevel, CollectorTierLevelTransformer]
