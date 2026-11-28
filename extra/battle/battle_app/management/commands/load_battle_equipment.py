from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from battle_app.equipment_files import read_affinities, read_relations, read_resistances
from battle_app.models import ROLE_GROUP_NAMES, BattleSettings, EquipAffinity, EquipResistance, GroupMatchup, Matchup
from bd_models.models import Ball, BallGroup


class Command(BaseCommand):
    help = (
        "Load the tables of the battle mode from affinities.csv, resistances.csv and relations.csv: who gets "
        "what share of an item's stats, what a defender's equipment does to the damage coming in, and what who "
        "the two fighters are does to it"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "directory",
            type=str,
            help="Folder holding affinities.csv, resistances.csv and relations.csv (any of them may be missing)",
        )
        parser.add_argument("--dry-run", action="store_true", help="Check the files without saving anything")
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Empty the tables of the files that are there first, so they end up holding exactly what those "
            "files say. A table whose file is missing is never touched. Without this, the lines of the files "
            "are added or updated and every other line is left alone.",
        )

    def handle(self, *args, **options):
        directory = Path(options["directory"])
        if not directory.is_dir():
            raise CommandError(f"Not a folder: {directory}")
        errors: list[str] = []
        affinities = self._read(directory / "affinities.csv", read_affinities, errors)
        resistances = self._read(directory / "resistances.csv", read_resistances, errors)
        relations = self._read(directory / "relations.csv", read_relations, errors)
        if affinities is None and resistances is None and relations is None:
            raise CommandError(f"No affinities.csv, resistances.csv or relations.csv in {directory}.")

        lookup = Lookup(errors)
        report: list[str] = []
        # one transaction for every file: a single mistake and nothing at all is saved
        with transaction.atomic():
            if affinities is not None:
                if options["clear"]:
                    report.append(f"Cleared {EquipAffinity.objects.all().delete()[0]} affinities.")
                report.append(self._load_affinities(affinities, lookup))
            if resistances is not None:
                if options["clear"]:
                    report.append(f"Cleared {EquipResistance.objects.all().delete()[0]} resistances.")
                report.append(self._load_resistances(resistances, lookup))
            if relations is not None:
                if options["clear"]:
                    cleared = Matchup.objects.all().delete()[0] + GroupMatchup.objects.all().delete()[0]
                    report.append(f"Cleared {cleared} relations.")
                report.append(self._load_relations(relations, lookup))
            if errors or options["dry_run"]:
                transaction.set_rollback(True)

        if errors:
            raise CommandError("Nothing was saved:\n" + "\n".join(f"- {error}" for error in errors))
        for line in report:
            self.stdout.write(line)
        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("The files are valid. Dry run: nothing was saved."))
        else:
            self.stdout.write(self.style.SUCCESS("Loaded. Restart the bot or reload its cache to be safe."))

    @staticmethod
    def _read(path: Path, reader, errors: list[str]):
        if not path.exists():
            return None
        try:
            # utf-8-sig: a file saved by Notepad or Excel starts with a byte order mark
            text = path.read_bytes().decode("utf-8-sig")
        except UnicodeDecodeError as error:
            errors.append(f"{path.name}: not a UTF-8 file ({error}).")
            return []
        lines, problems = reader(text, path.name)
        errors.extend(problems)
        return lines

    @staticmethod
    def _load_affinities(lines, lookup: "Lookup") -> str:
        created = updated = 0
        for line in lines:
            where = f"affinities.csv line {line.line}"
            character = lookup.character(line.character, where) if line.character else None
            item = lookup.item(line.item, where) if line.item else None
            group = lookup.group(line.item_group, where) if line.item_group else None
            if (line.character and character is None) or (line.item and item is None):
                continue
            if line.item_group and group is None:
                continue
            _, was_created = EquipAffinity.objects.update_or_create(
                character=character, item=item, item_group=group, defaults={"percent": line.percent, "note": line.note}
            )
            created += was_created
            updated += not was_created
        return f"Affinities: {created} added, {updated} updated."

    @staticmethod
    def _load_resistances(lines, lookup: "Lookup") -> str:
        created = updated = 0
        for line in lines:
            where = f"resistances.csv line {line.line}"
            character = lookup.character(line.character, where) if line.character else None
            equipped = lookup.item(line.equipped_item, where) if line.equipped_item else None
            against_item = lookup.item(line.against_item, where) if line.against_item else None
            against_group = lookup.group(line.against_group, where) if line.against_group else None
            if (line.character and character is None) or (line.equipped_item and equipped is None):
                continue
            if (line.against_item and against_item is None) or (line.against_group and against_group is None):
                continue
            _, was_created = EquipResistance.objects.update_or_create(
                character=character,
                equipped_item=equipped,
                against_item=against_item,
                against_group=against_group,
                defaults={"multiplier": line.multiplier, "note": line.note},
            )
            created += was_created
            updated += not was_created
        return f"Resistances: {created} added, {updated} updated."

    @staticmethod
    def _load_relations(lines, lookup: "Lookup") -> str:
        created = updated = 0
        for line in lines:
            where = f"relations.csv line {line.line}"
            defaults = {"damage_multiplier": line.multiplier, "note": line.note}
            if line.group:
                group = lookup.group(line.group, where)
                if group is None:
                    continue
                _, was_created = GroupMatchup.objects.update_or_create(group=group, defaults=defaults)
            else:
                attacker = lookup.character(line.attacker, where)
                defender = lookup.character(line.defender, where)
                if attacker is None or defender is None:
                    continue
                _, was_created = Matchup.objects.update_or_create(
                    attacker=attacker, defender=defender, defaults=defaults
                )
            created += was_created
            updated += not was_created
        return f"Relations: {created} added, {updated} updated."


class Lookup:
    """
    Finds treasures and groups by name, and says so when a name is wrong, retired, or plays the wrong part.

    A character has to be a treasure of the characters' group and an item one of the weapons' or the devil
    fruits': a line naming a ship as a character would otherwise load without a word and never apply, since
    a ship cannot be added to a deck. The same goes for a treasure retired from the dex, which battles turn
    away whatever groups it still belongs to.
    """

    def __init__(self, errors: list[str]):
        self.errors = errors
        self._balls = {ball.country: ball for ball in Ball.objects.all()}
        self._groups = {group.name: group for group in BallGroup.objects.all()}
        battle_settings = BattleSettings.load()
        self._members = {
            role: self._member_ids(getattr(battle_settings, f"{role}_group"), name)
            for role, name in ROLE_GROUP_NAMES.items()
        }

    def _member_ids(self, chosen: BallGroup | None, fallback: str) -> set[int]:
        group = chosen or self._groups.get(fallback)
        if group is None:
            self.errors.append(f'No group named "{fallback}", and none is picked in the battle settings.')
            return set()
        return set(group.countryballs.values_list("pk", flat=True))

    def _ball(self, name: str, where: str) -> Ball | None:
        ball = self._balls.get(name)
        if ball is None:
            self.errors.append(f'{where}: no treasure named "{name}".')
            return None
        if not ball.enabled:
            self.errors.append(f'{where}: "{name}" is retired from the dex, so it can never be in a battle.')
            return None
        return ball

    def character(self, name: str, where: str) -> Ball | None:
        ball = self._ball(name, where)
        if ball is not None and ball.pk not in self._members["character"]:
            self.errors.append(f'{where}: "{name}" is not in the characters\' group, so it can never fight.')
            return None
        return ball

    def item(self, name: str, where: str) -> Ball | None:
        ball = self._ball(name, where)
        if ball is not None and ball.pk not in self._members["weapon"] | self._members["fruit"]:
            self.errors.append(f'{where}: "{name}" is neither a weapon nor a devil fruit, so it cannot be equipped.')
            return None
        return ball

    def group(self, name: str, where: str) -> BallGroup | None:
        group = self._groups.get(name)
        if group is None:
            self.errors.append(f'{where}: no group named "{name}".')
        return group
