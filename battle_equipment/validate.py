#!/usr/bin/env python3
"""Consistency check for the battle equipment data.

    python battle_equipment/validate.py [path/to/data-dump.sql]

Reads the PostgreSQL dump as a stream (only the ball and group tables), then checks weapon_groups.sql,
affinities.csv, resistances.csv, relations.csv and REVIEW.md against it. Exit code 0 when everything holds,
1 otherwise.
Needs nothing but the standard library, and never touches a database.
"""

from __future__ import annotations

import csv
import io
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DUMP = HERE.parent / "data-dump-20261118-010638.sql"

AFFINITY_HEADER = ["character", "item", "item_group", "percent", "note"]
RESISTANCE_HEADER = ["character", "equipped_item", "against_item", "against_group", "multiplier", "note"]
CHARACTERS, WEAPONS, FRUITS = "Characters", "Weapons", "Devil fruits"
FRUIT_TYPES = ("Logia", "Zoan", "Paramecia")
UNTOUCHED = ("venustoken",)
MULTIPLIER_MIN, MULTIPLIER_MAX = 0.25, 2.0
RELATION_HEADER = ["attacker", "defender", "group", "multiplier", "note"]
RELATION_MIN, RELATION_MAX = 0.1, 5.0        # the range load_battle_equipment accepts for a relation

errors: list[str] = []
warnings: list[str] = []


def error(message: str) -> None:
    errors.append(message)


def warn(message: str) -> None:
    warnings.append(message)


# --------------------------------------------------------------------------- the dump
COPY_HEADER = re.compile(r"^COPY public\.(\w+) \((.*)\) FROM stdin;$")
COPY_ESCAPE = re.compile(r"\\(.)")
COPY_ESCAPES = {"t": "\t", "n": "\n", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "\\": "\\"}


def copy_value(raw: str) -> str | None:
    if raw == "\\N":
        return None
    return COPY_ESCAPE.sub(lambda m: COPY_ESCAPES.get(m.group(1), m.group(1)), raw)


def read_dump(path: Path, wanted: set[str]) -> dict[str, list[dict[str, str | None]]]:
    """Streams the dump and returns the rows of the wanted tables, never holding the file in memory."""
    tables: dict[str, list[dict[str, str | None]]] = {}
    columns: list[str] = []
    current: list[dict[str, str | None]] | None = None
    with path.open(encoding="utf-8", newline="\n") as dump:
        for line in dump:
            line = line.rstrip("\n")
            if current is None:
                if line.startswith("COPY public."):
                    match = COPY_HEADER.match(line)
                    if match and match.group(1) in wanted:
                        columns = [column.strip() for column in match.group(2).split(",")]
                        current = tables.setdefault(match.group(1), [])
            elif line == "\\.":
                current = None
                if len(tables) == len(wanted):
                    break
            else:
                current.append(dict(zip(columns, map(copy_value, line.split("\t")))))
    for table in wanted - tables.keys():
        error(f"dump: table {table} not found in {path.name}")
    return tables


# --------------------------------------------------------------------------- weapon_groups.sql
SQL_STRING = r"'((?:[^']|'')*)'"
SQL_ONE = re.compile(rf"^\s*\({SQL_STRING}\)[,;]\s*$")
SQL_TWO = re.compile(rf"^\s*\({SQL_STRING},\s*{SQL_STRING}\)[,;]\s*$")


def read_sql(path: Path) -> tuple[list[str], list[tuple[str, str]]]:
    """Returns (groups the script creates, [(treasure, group)] memberships it writes)."""
    new_groups: list[str] = []
    members: list[tuple[str, str]] = []
    target = None
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.startswith("INSERT INTO battle_new_group"):
            target = "groups"
        elif line.startswith("INSERT INTO battle_group_member"):
            target = "members"
        elif target and not line.strip():
            target = None
        elif target == "groups" and (match := SQL_ONE.match(line)):
            new_groups.append(match.group(1).replace("''", "'"))
        elif target == "members" and (match := SQL_TWO.match(line)):
            members.append((match.group(1).replace("''", "'"), match.group(2).replace("''", "'")))
        elif target and not line.lstrip().startswith("--"):
            error(f"weapon_groups.sql: cannot read this line of the value list: {line!r}")
    return new_groups, members


# --------------------------------------------------------------------------- CSV and Markdown
def read_text(path: Path) -> str | None:
    if not path.is_file():
        error(f"{path.name}: file is missing")
        return None
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        error(f"{path.name}: starts with a UTF-8 BOM")
    if b"\r" in raw:
        error(f"{path.name}: has CR characters, line endings must be LF")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        error(f"{path.name}: not valid UTF-8 ({exc})")
        return None


def read_csv(path: Path, header: list[str]) -> list[tuple[int, dict[str, str]]]:
    text = read_text(path)
    if text is None:
        return []
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if not rows or rows[0] != header:
        error(f"{path.name}: header must be exactly {','.join(header)}")
        return []
    out = []
    for number, row in enumerate(rows[1:], start=2):
        if len(row) != len(header):
            error(f"{path.name}:{number}: {len(row)} fields instead of {len(header)}")
            continue
        out.append((number, dict(zip(header, row))))
    return out


def between(text: str, name: str, file: str) -> list[str]:
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    if start not in text or end not in text:
        error(f"{file}: markers {start} / {end} not found")
        return []
    return text.split(start, 1)[1].split(end, 1)[0].strip("\n").split("\n")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dump_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DUMP
    if not dump_path.is_file():
        print(f"dump not found: {dump_path}")
        return 1

    # ----------------------------------------------------------------------- what the dump says
    tables = read_dump(dump_path, {"ball", "ballgroup", "ballgroup_countryballs"})
    if errors:
        print("\n".join(errors))
        return 1
    enabled = {ball["id"]: ball["country"] for ball in tables["ball"] if ball["enabled"] == "t"}
    every_ball = {ball["country"] for ball in tables["ball"]}
    active = set(enabled.values())
    group_name = {group["id"]: group["name"] for group in tables["ballgroup"]}
    dump_groups = set(group_name.values())
    in_group: dict[str, set[str]] = defaultdict(set)      # group -> active treasures
    for link in tables["ballgroup_countryballs"]:
        if link["ball_id"] in enabled:
            in_group[group_name[link["ballgroup_id"]]].add(enabled[link["ball_id"]])

    # ----------------------------------------------------------------------- weapon_groups.sql
    sql_path = HERE / "weapon_groups.sql"
    sql_text = read_text(sql_path)
    new_groups, members = read_sql(sql_path) if sql_text is not None else ([], [])
    if sql_text is not None:
        if not new_groups or not members:
            error("weapon_groups.sql: no group or no membership could be read")
        if re.search(r"_id\s*(=|IN)\s*\(?\s*\d", sql_text) or re.search(r"\(\s*\d+\s*,", sql_text):
            error("weapon_groups.sql: looks like a hard-coded id, everything must go by name")
        for name, count in Counter(new_groups).items():
            if count > 1:
                error(f"weapon_groups.sql: group {name!r} is created twice")
        for name in new_groups:
            if name in dump_groups:
                warn(f"weapon_groups.sql: group {name!r} already exists in the dump")
        for pair, count in Counter(members).items():
            if count > 1:
                error(f"weapon_groups.sql: membership {pair} is listed twice")
        for ball, group in members:
            if ball not in every_ball:
                error(f"weapon_groups.sql: treasure {ball!r} does not exist")
            elif ball not in active:
                error(f"weapon_groups.sql: treasure {ball!r} is disabled")
            if group not in dump_groups and group not in new_groups:
                error(f"weapon_groups.sql: group {group!r} neither exists nor is created by the script")
            if ball in UNTOUCHED:
                error(f"weapon_groups.sql: {ball!r} must not be touched")
    for ball, group in members:                             # the groups as they will be after the script
        if ball in active:
            in_group[group].add(ball)
    groups = dump_groups | set(new_groups)

    characters = in_group[CHARACTERS]
    weapons = in_group[WEAPONS]
    fruits = in_group[FRUITS]
    equipable = weapons | fruits
    if characters & equipable:
        error(f"treasures that are both a character and an item: {sorted(characters & equipable)}")

    precise_of: dict[str, list[str]] = defaultdict(list)
    for group in new_groups:
        for ball in in_group[group]:
            precise_of[ball].append(group)
            if ball not in weapons:
                error(f"weapon_groups.sql: {ball!r} is in {group!r} but is not in {WEAPONS!r}")
    for weapon in sorted(weapons):
        if len(precise_of[weapon]) != 1:
            error(f"weapon {weapon!r} is in {len(precise_of[weapon])} precise weapon groups instead of 1: {precise_of[weapon]}")
    for group in new_groups:
        if not in_group[group]:
            error(f"weapon_groups.sql: group {group!r} has no member")

    # ----------------------------------------------------------------------- affinities.csv
    affinities = read_csv(HERE / "affinities.csv", AFFINITY_HEADER)
    seen: dict[tuple[str, str, str], int] = {}
    layers = Counter()
    owned: set[str] = set()                                 # items that have a layer 2 line
    canon: dict[str, set[str]] = defaultdict(set)           # character -> items of its layer 2 lines
    defaults: set[str] = set()
    for number, row in affinities:
        where = f"affinities.csv:{number}"
        character, item, group = row["character"], row["item"], row["item_group"]
        if any(value != value.strip() for value in row.values()):
            error(f"{where}: a value has leading or trailing spaces")
        if character and character not in active:
            error(f"{where}: character {character!r} does not exist or is disabled")
        elif character and character not in characters:
            error(f"{where}: {character!r} is not in the {CHARACTERS!r} group")
        if bool(item) == bool(group):
            error(f"{where}: exactly one of item / item_group must be filled")
        if item and item not in active:
            error(f"{where}: item {item!r} does not exist or is disabled")
        elif item and item not in equipable:
            error(f"{where}: item {item!r} is neither a weapon nor a devil fruit")
        if group and group not in groups:
            error(f"{where}: group {group!r} neither exists in the dump nor is created by weapon_groups.sql")
        if not re.fullmatch(r"[1-9]\d*", row["percent"]):
            error(f"{where}: percent {row['percent']!r} is not a positive integer")
        elif int(row["percent"]) > 200:
            error(f"{where}: percent {row['percent']} is above 200")
        if not row["note"]:
            error(f"{where}: note is empty")
        key = (character, item, group)
        if key in seen:
            error(f"{where}: same character + item + item_group as line {seen[key]}")
        seen[key] = number
        if not character and group:
            layers[1] += 1
            defaults.add(group)
        elif character and item:
            layers[2] += 1
            owned.add(item)
            canon[character].add(item)
        elif character and group:
            layers[3] += 1
        elif not character and item:
            error(f"{where}: an item line needs a character (the three layers have no 'anyone + item' case)")
    for group in list(FRUIT_TYPES) + new_groups:
        if affinities and group not in defaults:
            error(f"affinities.csv: no default line (empty character) for the group {group!r}")
    for item in sorted(equipable):
        if affinities and not any(item in in_group[group] for group in defaults):
            error(f"affinities.csv: {item!r} is covered by no default line")

    # ----------------------------------------------------------------------- resistances.csv
    resistances = read_csv(HERE / "resistances.csv", RESISTANCE_HEADER)
    seen_rule: dict[tuple[str, str, str, str], int] = {}
    by_defender: dict[tuple[str, str], list[tuple[str, str, int]]] = defaultdict(list)
    for number, row in resistances:
        where = f"resistances.csv:{number}"
        character, worn = row["character"], row["equipped_item"]
        against_item, against_group = row["against_item"], row["against_group"]
        if any(value != value.strip() for value in row.values()):
            error(f"{where}: a value has leading or trailing spaces")
        if character and character not in active:
            error(f"{where}: character {character!r} does not exist or is disabled")
        elif character and character not in characters:
            error(f"{where}: {character!r} is not in the {CHARACTERS!r} group")
        for label, item in (("equipped_item", worn), ("against_item", against_item)):
            if item and item not in active:
                error(f"{where}: {label} {item!r} does not exist or is disabled")
            elif item and item not in equipable:
                error(f"{where}: {label} {item!r} is neither a weapon nor a devil fruit")
        if bool(against_item) == bool(against_group):
            error(f"{where}: exactly one of against_item / against_group must be filled")
        if against_group and against_group not in groups:
            error(f"{where}: group {against_group!r} neither exists in the dump nor is created by weapon_groups.sql")
        if not re.fullmatch(r"\d+(\.\d+)?", row["multiplier"]):
            error(f"{where}: multiplier {row['multiplier']!r} is not a decimal number")
        else:
            multiplier = float(row["multiplier"])
            if not MULTIPLIER_MIN <= multiplier <= MULTIPLIER_MAX:
                error(f"{where}: multiplier {row['multiplier']} is outside {MULTIPLIER_MIN}..{MULTIPLIER_MAX}")
            if multiplier == 1:
                warn(f"{where}: multiplier 1 does nothing")
        if not row["note"]:
            error(f"{where}: note is empty")
        if worn and worn == against_item:
            warn(f"{where}: the worn item and the attacking item are the same")
        if not character and not worn:
            warn(f"{where}: no character and no equipped item, the rule applies to everyone all the time")
        key = (character, worn, against_item, against_group)
        if key in seen_rule:
            error(f"{where}: same character + equipped_item + against_item + against_group as line {seen_rule[key]}")
        seen_rule[key] = number
        by_defender[(character, worn)].append((against_item, against_group, number))
    for (character, worn), rules in by_defender.items():      # an item rule and a group rule that both fire
        for against_item, _, number in rules:
            for _, against_group, other in rules:
                if against_item and against_group and against_item in in_group[against_group]:
                    warn(f"resistances.csv:{number} and :{other}: {against_item!r} is also in {against_group!r}, both rules fire together")

    # ----------------------------------------------------------------------- relations.csv
    relations = read_csv(HERE / "relations.csv", RELATION_HEADER)
    seen_relation: dict[tuple[str, str, str], int] = {}
    crews: list[str] = []
    for number, row in relations:
        where = f"relations.csv:{number}"
        attacker, defender, group = row["attacker"], row["defender"], row["group"]
        if any(value != value.strip() for value in row.values()):
            error(f"{where}: a value has leading or trailing spaces")
        if group:
            if attacker or defender:
                error(f"{where}: a group line must leave attacker and defender empty")
            if group not in groups:
                error(f"{where}: group {group!r} neither exists in the dump nor is created by weapon_groups.sql")
            else:
                crews.append(group)
                if len(in_group[group] & characters) < 2:
                    error(f"{where}: group {group!r} has fewer than two active characters")
                if in_group[group] - characters:
                    warn(f"{where}: group {group!r} also holds treasures that are not characters")
        else:
            if not attacker or not defender:
                error(f"{where}: fill attacker and defender, or group alone")
            for label, name in (("attacker", attacker), ("defender", defender)):
                if name and name not in active:
                    error(f"{where}: {label} {name!r} does not exist or is disabled")
                elif name and name not in characters:
                    error(f"{where}: {label} {name!r} is not in the {CHARACTERS!r} group")
            if attacker and attacker == defender:
                error(f"{where}: attacker and defender are the same character")
        if not re.fullmatch(r"\d+(\.\d+)?", row["multiplier"]):
            error(f"{where}: multiplier {row['multiplier']!r} is not a decimal number")
        else:
            multiplier = float(row["multiplier"])
            if not RELATION_MIN <= multiplier <= RELATION_MAX:
                error(f"{where}: multiplier {row['multiplier']} is outside {RELATION_MIN}..{RELATION_MAX}")
            if multiplier == 1:
                warn(f"{where}: multiplier 1 does nothing")
        if not row["note"]:
            error(f"{where}: note is empty")
        key = (attacker, defender, group)
        if key in seen_relation:
            error(f"{where}: same attacker + defender + group as line {seen_relation[key]}")
        seen_relation[key] = number
    for first, second in combinations(sorted(set(crews)), 2):   # two group lines for the same pair of fighters
        shared = in_group[first] & in_group[second] & characters
        if len(shared) > 1:
            warn(f"relations.csv: groups {first!r} and {second!r} share {sorted(shared)}; between them the engine keeps the line of the smaller group")

    # ----------------------------------------------------------------------- REVIEW.md
    review = read_text(HERE / "REVIEW.md")
    ownerless: list[str] = []
    doubts = 0
    if review is not None:
        for line in between(review, "ownerless", "REVIEW.md"):
            if match := re.match(r"^- `([^`]+)`", line):
                ownerless.append(match.group(1))
        for item, count in Counter(ownerless).items():
            if count > 1:
                error(f"REVIEW.md: {item!r} is listed twice among the ownerless items")
            if item not in equipable:
                error(f"REVIEW.md: ownerless item {item!r} is not an active weapon or devil fruit")
        for item in sorted(equipable):
            if item not in owned and item not in ownerless:
                error(f"{item!r} has no layer 2 line and is not in the ownerless list of REVIEW.md")
            if item in owned and item in ownerless:
                error(f"{item!r} has a layer 2 line and is also in the ownerless list of REVIEW.md")

        listed = []
        for line in between(review, "characters", "REVIEW.md")[2:]:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) != 6:
                error(f"REVIEW.md: character line with {len(cells)} cells instead of 6: {line[:80]!r}")
                continue
            listed.append(cells[1])
            shown = {re.sub(r" \(\d+ %\)$", "", item) for cell in cells[2:4] for item in cell.split("<br>") if item != "—"}
            if shown != canon[cells[1]]:
                warn(f"REVIEW.md: the items shown for {cells[1]!r} differ from affinities.csv (document out of date?)")
        for name, count in Counter(listed).items():
            if count > 1:
                error(f"REVIEW.md: character {name!r} appears {count} times")
            if name not in characters:
                error(f"REVIEW.md: {name!r} is not an active character")
        for name in sorted(characters - set(listed)):
            error(f"REVIEW.md: character {name!r} is missing from the table")
        if "## Doutes" in review:
            doubts = len(re.findall(r"^\d+\. ", review.split("## Doutes", 1)[1].split("\n## ", 1)[0], flags=re.M))
        else:
            error("REVIEW.md: no '## Doutes' section")

    # ----------------------------------------------------------------------- report
    print(f"dump: {dump_path.name} - {len(active)} active treasures: {len(characters)} characters, "
          f"{len(fruits)} devil fruits, {len(weapons)} weapons")
    print(f"weapon groups: {len(new_groups)} - " + ", ".join(f"{group} ({len(in_group[group])})" for group in new_groups))
    print(f"affinities: {len(affinities)} lines - layer 1: {layers[1]}, layer 2: {layers[2]}, layer 3: {layers[3]}")
    print(f"resistances: {len(resistances)} rules")
    print(f"relations: {len(relations)} rules - {len(crews)} on a group, {len(relations) - len(crews)} between two characters")
    print(f"items: {len(owned)} with a layer 2 line, {len(ownerless)} ownerless")
    print(f"REVIEW.md: {doubts} doubts")
    for message in warnings:
        print("WARNING " + message)
    for message in errors:
        print("ERROR   " + message)
    print(f"{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
