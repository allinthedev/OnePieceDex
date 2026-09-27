-- Awakened Fruit (collector tier level 5): rewrite what is already loaded so it matches
-- eventexample/awakened_fruit_craft.json. Run it after changing an amount or a setting in the dump, or to
-- correct an earlier load. It updates what is there, adds what is missing, and never deletes a recipe.
-- Safe to run twice, and it writes nothing at all if it stops on an error.
BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM collectortierlevel WHERE id = 5) THEN
    RAISE EXCEPTION 'collector tier level 5 does not exist on this database';
  END IF;
END $$;

CREATE TEMP TABLE awakened_recipe (collector_name text PRIMARY KEY, amount integer NOT NULL) ON COMMIT DROP;

INSERT INTO awakened_recipe (collector_name, amount) VALUES
  ('Akuma no Mi (Devil''s Fruit)', 15),
  ('Yami Yami (Dark Dark)', 14),
  ('Gomu Gomu (Gum Gum)', 14),
  ('Nidhogg', 13),
  ('Gura Gura (Quake Quake)', 13),
  ('Ope Ope no Mi', 12),
  ('Seiryu (Azure Dragon)', 12),
  ('Magu Magu (Magma Magma)', 12),
  ('Hie Hie no Mi (Chilly Chilly)', 11),
  ('Pika Pika no Mi (Light Light)', 11),
  ('Jiki Jiki no Mi (Magnet Magnet)', 10),
  ('Ratatoskr', 10),
  ('Tori Tori:Phoenix', 10),
  ('Nikyu Nikyu no Mi (Paw Paw)', 10),
  ('Goro Goro no Mi (Thunder Thunder)', 10),
  ('Soru Soru no Mi (Soul Soul)', 10),
  ('Mera Mera no Mi (Fire Fire)', 10),
  ('Hito Hito: Buddha', 10),
  ('Suna no Mi (Sand Sand)', 10),
  ('Mori Mori no Mi (Forest Forest)', 10),
  ('Zushi Zushi no Mi (Press Press)', 10),
  ('Fengxi', 10),
  ('Bakotsu', 10),
  ('Itsumade', 10),
  ('Gyuki', 10),
  ('Sandworm', 10),
  ('Okuchi no Makami', 10),
  ('Mochi Mochi no Mi', 10),
  ('Doku Doku no Mi (Venom Venom)', 15),
  ('Ito Ito no Mi (String String)', 15),
  ('Neko:Leopard', 15),
  ('Brachiosaurus', 15),
  ('Pteranodon', 15),
  ('Fuwa Fuwa no Mi (Float Float)', 15),
  ('Toshi Toshi no Mi (Age Age)', 15),
  ('Aro Aro no Mi (Arrow Arrow)', 15),
  ('Gasu Gasu no Mi (Gas Gas)', 15),
  ('Susu Susu no Mi (Soot Soot)', 15),
  ('Moku Moku no Mi (Smoke Smoke)', 15),
  ('Mero Mero no Mi (Love Love)', 15),
  ('Iba Iba no Mi (Thorn Thorn)', 15),
  ('Kirin', 15),
  ('Kyubi no Kitsune (Nine Tailed Fox)', 16),
  ('Yuki Yuki no Mi (Snow Snow)', 16),
  ('Bara Bara no Mi (Chop Chop)', 16),
  ('Doru Doru no Mi (Wax Wax)', 18),
  ('Kage Kage no Mi (Shadow Shadow)', 18),
  ('Mammoth', 18),
  ('Pachycephalosaurus (Ulti)', 18),
  ('Triceratops', 18),
  ('Allosaurus', 18),
  ('Saber Tiger', 18),
  ('Spinosaurus', 18),
  ('Ushi Ushi no Mi (Giraffe)', 20),
  ('Kira Kira no Mi (Diamond Diamond)', 20),
  ('Wapu Wapu no Mi (Warp Warp)', 20),
  ('Horo Horo no Mi', 22),
  ('Batto Batto no Mi (Bat Bat)', 22),
  ('Hobi Hobi no Mi', 22),
  ('Horu Horu no Mi (Hormone Hormone)', 22),
  ('Shibo Shibo no Mi (Squeeze Squeeze)', 22),
  ('Cerberus', 23),
  ('Hito Hito no Mi (Human Human)', 23),
  ('Hapi Hapi no Mi (Harpy)', 23),
  ('Bari Bari no Mi (Barrier Barrier)', 23),
  ('Uta Uta no Mi (Sing Sing)', 25),
  ('Yamata Orochi', 25),
  ('Falcon', 25),
  ('Shima Shima no Mi (Island Island)', 26),
  ('Ishi Ishi no Mi (Stone Stone)', 26),
  ('Hana Hana no Mi (Flower Flower)', 26),
  ('Wara Wara no Mi (Straw Straw)', 27),
  ('Pero Pero no Mi (Lick Lick)', 27),
  ('Bisu Bisu no Mi (Biscuit Biscuit)', 27),
  ('Netsu Netsu no Mi (Heat Heat)', 28),
  ('Gunyo Gunyo no Mi (Clay Clay)', 28),
  ('Numa Numa no Mi (Swamp Swamp)', 28),
  ('Oto Oto no Mi (Tone Tone)', 29),
  ('Riki Riki no Mi (Strong Strong)', 29),
  ('Kyo Kyo no Mi (Buff Buff)', 29),
  ('Shiro Shiro no Mi (Castle Castle)', 29),
  ('King Cobra', 30),
  ('Hebi:Anaconda', 30),
  ('Inu:Wolf', 30),
  ('Suke Suke no Mi (Clear Clear)', 30),
  ('Inu:Dalmatian', 32),
  ('Inu:Hound', 32),
  ('Dachshund', 32),
  ('Toki Toki no Mi (Time Time)', 34),
  ('Nomi Nomi no Mi (Brain Brain)', 34),
  ('Noro Noro no Mi (Slow Slow)', 34),
  ('Sui Sui no Mi (Swim Swim)', 34),
  ('Ton Ton no Mi (Ton Ton)', 34),
  ('Baku Baku no Mi (Munch Munch)', 36),
  ('Woshu Woshu no Mi (Wash Wash)', 36),
  ('Mane Mane no Mi (Clone Clone)', 38),
  ('Bane Bane no Mi (Spring Spring)', 39),
  ('Fude Fude no Mi (Brush Brush)', 40),
  ('Ato Ato no Mi (Art Art)', 40),
  ('Yomi Yomi no Mi (Revive Revive)', 40),
  ('Juku Juku no Mi (Ripe Ripe)', 40),
  ('Onyudo', 41),
  ('Tori:Albatross', 42),
  ('Nui Nui no Mi (Stitch Stitch)', 42),
  ('Toge Toge no Mi (Spike Spike)', 42),
  ('Buku Buku no Mi (Book Book)', 43),
  ('Bomu Bomu no Mi (Bomb Bomb)', 43),
  ('Pamu Pamu no Mi (Pop Pop)', 43),
  ('Beri Beri no Mi', 45),
  ('Ancient Spider (Rosamygale Grauvogeli)', 45),
  ('Buki Buki no Mi (Arms Arms)', 45),
  ('Kobu Kobu no Mi (Pump Pump)', 45),
  ('Supa Supa no Mi (Dice Dice)', 45),
  ('Mira Mira no Mi (Mirror Mirror)', 45);

-- every name must point at a collector that has a treasure, or nothing is written
DO $$
DECLARE unknown text;
BEGIN
  SELECT string_agg(r.collector_name, ', ') INTO unknown
  FROM awakened_recipe r
  LEFT JOIN collector c ON c.name = r.collector_name
  WHERE c.id IS NULL OR c.ball_id IS NULL;
  IF unknown IS NOT NULL THEN
    RAISE EXCEPTION 'unknown collectors, or collectors without a treasure: %', unknown;
  END IF;
END $$;

-- a collector with several recipes on this tier would be rewritten into something wrong: stop instead
DO $$
DECLARE crowded text;
BEGIN
  SELECT string_agg(c.name, ', ') INTO crowded
  FROM awakened_recipe r
  JOIN collector c ON c.name = r.collector_name
  WHERE (SELECT count(*) FROM collectorrequirement q WHERE q.collector_id = c.id AND q.level_id = 5) > 1;
  IF crowded IS NOT NULL THEN
    RAISE EXCEPTION 'these collectors have more than one recipe on tier 5, fix them by hand first: %', crowded;
  END IF;
END $$;

SELECT 'before' AS step,
  (SELECT count(*) FROM collectortier WHERE level_id = 5) AS tiers,
  (SELECT count(*) FROM collectortier WHERE level_id = 5 AND tradeable) AS tradeable_tiers,
  (SELECT count(*) FROM collectorrequirement WHERE level_id = 5) AS recipes,
  (SELECT count(*) FROM collectorrequirement WHERE level_id = 5 AND delete_balls) AS consuming_recipes,
  (SELECT count(*) FROM collectorinstance WHERE level_id = 5 AND revoked_at IS NULL) AS cards_claimed;

-- 1. the tier of every listed collector
UPDATE collectortier t
SET tradeable = false, no_special = false, enabled = true, price = NULL
FROM awakened_recipe r
JOIN collector c ON c.name = r.collector_name
WHERE t.collector_id = c.id AND t.level_id = 5;

INSERT INTO collectortier (collector_id, level_id, special_id, no_special, tradeable, frame_key, enabled, price)
SELECT c.id, 5, NULL, false, false, '', true, NULL
FROM awakened_recipe r
JOIN collector c ON c.name = r.collector_name
WHERE NOT EXISTS (SELECT 1 FROM collectortier t WHERE t.collector_id = c.id AND t.level_id = 5);

-- 2. its recipe: the listed amount of the collector's own treasure, kept, never used up
UPDATE collectorrequirement q
SET amount = r.amount, delete_balls = false, ball_id = c.ball_id, special_id = NULL
FROM awakened_recipe r
JOIN collector c ON c.name = r.collector_name
WHERE q.collector_id = c.id AND q.level_id = 5;

INSERT INTO collectorrequirement (collector_id, level_id, ball_id, special_id, amount, delete_balls)
SELECT c.id, 5, c.ball_id, NULL, r.amount, false
FROM awakened_recipe r
JOIN collector c ON c.name = r.collector_name
WHERE NOT EXISTS (SELECT 1 FROM collectorrequirement q WHERE q.collector_id = c.id AND q.level_id = 5);

-- 3. a card already claimed keeps the flag it was given at the time: line it up with the tier
UPDATE ballinstance b
SET tradeable = false
FROM collectorinstance i
WHERE i.ball_instance_id = b.id AND i.level_id = 5 AND i.revoked_at IS NULL
  AND b.tradeable <> false;

SELECT 'after' AS step,
  (SELECT count(*) FROM collectortier WHERE level_id = 5) AS tiers,
  (SELECT count(*) FROM collectortier WHERE level_id = 5 AND tradeable) AS tradeable_tiers,
  (SELECT count(*) FROM collectorrequirement WHERE level_id = 5) AS recipes,
  (SELECT count(*) FROM collectorrequirement WHERE level_id = 5 AND delete_balls) AS consuming_recipes,
  (SELECT count(*) FROM collectorinstance WHERE level_id = 5 AND revoked_at IS NULL) AS cards_claimed;

COMMIT;
