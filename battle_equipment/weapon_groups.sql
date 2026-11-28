-- Battle mode equipment: sorts the weapons into precise groups (katanas, polearms, ...) that the affinity and
-- resistance tables use as item categories, and gives a role group to the four treasures that had none.
-- Everything goes by name. Safe to run twice: groups and memberships that already exist are skipped.
-- Run it by hand with psql, before the battle migrations. The token "venustoken" is left alone on purpose.
BEGIN;

-- the precise weapon groups this script creates
CREATE TEMP TABLE battle_new_group (group_name text PRIMARY KEY) ON COMMIT DROP;

INSERT INTO battle_new_group (group_name) VALUES
  ('Katanas'),
  ('Western Swords'),
  ('Cane Swords'),
  ('Polearms'),
  ('Blunt Weapons'),
  ('Staves'),
  ('Ranged Weapons');

-- which treasure goes into which group
CREATE TEMP TABLE battle_group_member (
  ball_name text NOT NULL,
  group_name text NOT NULL,
  PRIMARY KEY (ball_name, group_name)
) ON COMMIT DROP;

INSERT INTO battle_group_member (ball_name, group_name) VALUES
  -- Katanas: Japanese blades: katana, and the longer nodachi
  ('Shodai Kitetsu', 'Katanas'),
  ('Nidai Kitetsu', 'Katanas'),
  ('Sandai Kitetsu', 'Katanas'),
  ('Wado Ichimonji', 'Katanas'),
  ('Shusui', 'Katanas'),
  ('Enma', 'Katanas'),
  ('Ame No Habakiri', 'Katanas'),
  ('Yubashiri', 'Katanas'),
  ('Shigure', 'Katanas'),
  ('Kikoku', 'Katanas'),
  ('Raiu', 'Katanas'),
  ('Shirauo', 'Katanas'),
  ('Oto and Kogarashi', 'Katanas'),
  -- Western Swords: sabers, cutlasses, rapiers and longswords
  ('Yoru', 'Western Swords'),
  ('Ace', 'Western Swords'),
  ('Eclipse', 'Western Swords'),
  ('Gryphon', 'Western Swords'),
  ('Cerberus (Sword)', 'Western Swords'),
  ('Durandal', 'Western Swords'),
  ('Kaken', 'Western Swords'),
  ('Napoleon', 'Western Swords'),
  ('Pretzel', 'Western Swords'),
  ('Warabide', 'Western Swords'),
  -- Cane Swords: shikomizue, a blade hidden in a cane
  ('Yakuza Kasen', 'Cane Swords'),
  ('Soul Solid', 'Cane Swords'),
  -- Polearms: naginata, bisento, spears, tridents
  ('Murakumogiri', 'Polearms'),
  -- Blunt Weapons: kanabo, maces, hammers, clubs
  ('Ragnir', 'Blunt Weapons'),
  ('Hassaikai', 'Blunt Weapons'),
  -- Staves: bo staves and rods
  ('Sorcery Clima Tact', 'Staves'),
  ('God Staff', 'Staves'),
  -- Ranged Weapons: slingshots, and firearms or bows when the dex gets some
  ('Kabuto', 'Ranged Weapons'),
  -- the two weapons that had no group at all also join the umbrella group
  ('Hassaikai', 'Weapons'),
  ('God Staff', 'Weapons'),
  -- the two characters that had no group at all
  ('Shimotsuki Ryuma', 'Characters'),
  ('Shachi & Penguin', 'Characters');

-- every treasure name must exist, or nothing is written
DO $$
DECLARE unknown text;
BEGIN
  SELECT string_agg(DISTINCT m.ball_name, ', ') INTO unknown
  FROM battle_group_member m
  LEFT JOIN ball b ON b.country = m.ball_name
  WHERE b.id IS NULL;
  IF unknown IS NOT NULL THEN
    RAISE EXCEPTION 'unknown treasures: %', unknown;
  END IF;
END $$;

-- every group that this script does not create must already exist, or nothing is written
DO $$
DECLARE unknown text;
BEGIN
  SELECT string_agg(DISTINCT m.group_name, ', ') INTO unknown
  FROM battle_group_member m
  LEFT JOIN battle_new_group n ON n.group_name = m.group_name
  LEFT JOIN ballgroup g ON g.name = m.group_name
  WHERE n.group_name IS NULL AND g.id IS NULL;
  IF unknown IS NOT NULL THEN
    RAISE EXCEPTION 'unknown groups: %', unknown;
  END IF;
END $$;

-- a weapon goes into one precise group only, or nothing is written
DO $$
DECLARE doubled text;
BEGIN
  SELECT string_agg(d.ball_name, ', ') INTO doubled
  FROM (
    SELECT m.ball_name
    FROM battle_group_member m
    JOIN battle_new_group n ON n.group_name = m.group_name
    GROUP BY m.ball_name
    HAVING count(*) > 1
  ) d;
  IF doubled IS NOT NULL THEN
    RAISE EXCEPTION 'weapons listed in more than one precise group: %', doubled;
  END IF;
END $$;

-- the groups themselves
INSERT INTO ballgroup (name)
SELECT n.group_name
FROM battle_new_group n
WHERE NOT EXISTS (SELECT 1 FROM ballgroup g WHERE g.name = n.group_name);

-- the memberships
INSERT INTO ballgroup_countryballs (ballgroup_id, ball_id)
SELECT g.id, b.id
FROM battle_group_member m
JOIN ball b ON b.country = m.ball_name
JOIN ballgroup g ON g.name = m.group_name
WHERE NOT EXISTS (
  SELECT 1 FROM ballgroup_countryballs l WHERE l.ballgroup_id = g.id AND l.ball_id = b.id
);

-- what each precise group holds now
SELECT g.name AS weapon_group, count(l.id) AS members_now
FROM battle_new_group n
JOIN ballgroup g ON g.name = n.group_name
LEFT JOIN ballgroup_countryballs l ON l.ballgroup_id = g.id
GROUP BY g.name
ORDER BY g.name;

-- must come back empty: enabled weapons that are not in exactly one precise group
SELECT b.country AS weapon_to_sort, count(n.group_name) AS precise_groups
FROM ball b
JOIN ballgroup_countryballs wl ON wl.ball_id = b.id
JOIN ballgroup wg ON wg.id = wl.ballgroup_id AND wg.name = 'Weapons'
LEFT JOIN ballgroup_countryballs l ON l.ball_id = b.id
LEFT JOIN ballgroup g ON g.id = l.ballgroup_id
LEFT JOIN battle_new_group n ON n.group_name = g.name
WHERE b.enabled
GROUP BY b.country
HAVING count(n.group_name) <> 1
ORDER BY b.country;

COMMIT;
