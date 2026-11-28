"""
Reading the two CSV files the equip tables are loaded from, with nothing of Django in it, so the format can
be checked anywhere a file can be opened.

`affinities.csv` — the share of an item's stats a character gets:

    character,item,item_group,percent,note
    ,,Katanas,50,default for anybody
    Roronoa Zoro,Wado Ichimonji,,200,his own sword
    Roronoa Zoro,,Katanas,150,three-sword style

`resistances.csv` — what a defender's equipment does to the damage coming in:

    character,equipped_item,against_item,against_group,multiplier,note
    Monkey D. Luffy,Gomu Gomu no Mi (Gum Gum),,Blunt weapons,0.5,rubber body

`relations.csv` — what who the two fighters are does to a hit, whatever they wear:

    attacker,defender,group,multiplier,note
    Sakazuki (Akainu),Portgas D. Ace,,1.3,killed him at Marineford
    ,,Whitebeard Pirates,0.5,brothers hold back against each other

A line names either one attacker against one defender, or a group: the second kind applies when both
fighters belong to it.

Everything is a name: a treasure by the name it has in the dex, a kind of item by the name of its group.
An empty `character` means anybody, an empty `equipped_item` means whatever they wear. Every problem in a
file is reported at once, with its line, rather than one per run.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

AFFINITY_HEADER = ("character", "item", "item_group", "percent", "note")
RESISTANCE_HEADER = ("character", "equipped_item", "against_item", "against_group", "multiplier", "note")
RELATION_HEADER = ("attacker", "defender", "group", "multiplier", "note")
MIN_RELATION, MAX_RELATION = 0.1, 5.0
NOTE_MAX_LENGTH = 200
MAX_PERCENT = 1000
MIN_MULTIPLIER, MAX_MULTIPLIER = 0.05, 5.0


@dataclass(frozen=True)
class AffinityLine:
    line: int
    character: str
    item: str
    item_group: str
    percent: int
    note: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.character, self.item, self.item_group)


@dataclass(frozen=True)
class ResistanceLine:
    line: int
    character: str
    equipped_item: str
    against_item: str
    against_group: str
    multiplier: float
    note: str

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.character, self.equipped_item, self.against_item, self.against_group)


@dataclass(frozen=True)
class RelationLine:
    line: int
    attacker: str
    defender: str
    group: str
    multiplier: float
    note: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.attacker, self.defender, self.group)


def _rows(text: str, header: tuple[str, ...], name: str, errors: list[str]) -> list[tuple[int, dict[str, str]]]:
    """The data rows of a file with their line numbers, once its header is known to be the expected one."""
    # a file saved by Excel or Notepad starts with a byte order mark, which would otherwise end up glued to
    # the name of the first column
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿"), newline=""))
    found = tuple(reader.fieldnames or ())
    if found != header:
        errors.append(f"{name}: the header must be exactly {','.join(header)} (found {','.join(found) or 'nothing'}).")
        return []
    rows = []
    for row in reader:
        if None in row:
            errors.append(f"{name} line {reader.line_num}: too many columns, is a comma missing its quotes?")
            continue
        values = {column: (row[column] or "").strip() for column in header}
        if not any(values.values()):
            continue
        rows.append((reader.line_num, values))
    return rows


def _note(value: str, where: str, errors: list[str]) -> str:
    if len(value) > NOTE_MAX_LENGTH:
        errors.append(f"{where}: the note is {len(value)} characters long, {NOTE_MAX_LENGTH} at most.")
    return value[:NOTE_MAX_LENGTH]


def read_affinities(text: str, name: str = "affinities.csv") -> tuple[list[AffinityLine], list[str]]:
    """
    Parse the affinity file. Returns the lines that could be read and every problem found, the second list
    being empty when the file is fit to load.
    """
    errors: list[str] = []
    lines: list[AffinityLine] = []
    seen: dict[tuple[str, str, str], int] = {}
    for number, row in _rows(text, AFFINITY_HEADER, name, errors):
        where = f"{name} line {number}"
        if bool(row["item"]) == bool(row["item_group"]):
            errors.append(f"{where}: set either item or item_group, and only one of the two.")
            continue
        try:
            percent = int(row["percent"])
        except ValueError:
            errors.append(f"{where}: percent must be a whole number, not {row['percent']!r}.")
            continue
        if not 0 <= percent <= MAX_PERCENT:
            errors.append(f"{where}: percent must be between 0 and {MAX_PERCENT}, not {percent}.")
            continue
        line = AffinityLine(
            number, row["character"], row["item"], row["item_group"], percent, _note(row["note"], where, errors)
        )
        if line.key in seen:
            errors.append(f"{where}: the same pair is already on line {seen[line.key]}.")
            continue
        seen[line.key] = number
        lines.append(line)
    return lines, errors


def read_resistances(text: str, name: str = "resistances.csv") -> tuple[list[ResistanceLine], list[str]]:
    """Parse the resistance file, like `read_affinities`."""
    errors: list[str] = []
    lines: list[ResistanceLine] = []
    seen: dict[tuple[str, str, str, str], int] = {}
    for number, row in _rows(text, RESISTANCE_HEADER, name, errors):
        where = f"{name} line {number}"
        if bool(row["against_item"]) == bool(row["against_group"]):
            errors.append(f"{where}: set either against_item or against_group, and only one of the two.")
            continue
        try:
            multiplier = float(row["multiplier"])
        except ValueError:
            errors.append(f"{where}: multiplier must be a number, not {row['multiplier']!r}.")
            continue
        if not MIN_MULTIPLIER <= multiplier <= MAX_MULTIPLIER:
            errors.append(
                f"{where}: multiplier must be between {MIN_MULTIPLIER:g} and {MAX_MULTIPLIER:g}, not {multiplier:g}."
            )
            continue
        line = ResistanceLine(
            number,
            row["character"],
            row["equipped_item"],
            row["against_item"],
            row["against_group"],
            multiplier,
            _note(row["note"], where, errors),
        )
        if line.key in seen:
            errors.append(f"{where}: the same rule is already on line {seen[line.key]}.")
            continue
        seen[line.key] = number
        lines.append(line)
    return lines, errors


def read_relations(text: str, name: str = "relations.csv") -> tuple[list[RelationLine], list[str]]:
    """
    Parse the relations file, like `read_affinities`. A line is either a pair, attacker against defender,
    or a group whose members share a bond; never a mix of the two.
    """
    errors: list[str] = []
    lines: list[RelationLine] = []
    seen: dict[tuple[str, str, str], int] = {}
    for number, row in _rows(text, RELATION_HEADER, name, errors):
        where = f"{name} line {number}"
        pair = bool(row["attacker"]) and bool(row["defender"])
        if row["group"]:
            if row["attacker"] or row["defender"]:
                errors.append(f"{where}: a line names either a group or an attacker and a defender, not both.")
                continue
        elif not pair:
            errors.append(f"{where}: set both an attacker and a defender, or a group.")
            continue
        elif row["attacker"] == row["defender"]:
            errors.append(f"{where}: {row['attacker']} cannot be set against itself.")
            continue
        try:
            multiplier = float(row["multiplier"])
        except ValueError:
            errors.append(f"{where}: multiplier must be a number, not {row['multiplier']!r}.")
            continue
        if not MIN_RELATION <= multiplier <= MAX_RELATION:
            errors.append(
                f"{where}: multiplier must be between {MIN_RELATION:g} and {MAX_RELATION:g}, not {multiplier:g}."
            )
            continue
        line = RelationLine(
            number, row["attacker"], row["defender"], row["group"], multiplier, _note(row["note"], where, errors)
        )
        if line.key in seen:
            errors.append(f"{where}: the same relation is already on line {seen[line.key]}.")
            continue
        seen[line.key] = number
        lines.append(line)
    return lines, errors
