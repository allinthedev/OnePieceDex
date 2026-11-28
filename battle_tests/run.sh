#!/bin/bash
# Run a command in a throwaway container: the dependencies of the "ballsdex" image, the code of THIS working
# tree (not the copy baked into the image), the battle package switched on, and the scratch database
# "battle_test". Nothing here touches the real local database or the real config.
#
#   bash battle_tests/run.sh python3 -m django check
#   bash battle_tests/run.sh python3 /work/battle_tests/some_test.py
#
# The repository is mounted read-only under /work, so a test can read everything and write nothing.
export MSYS_NO_PATHCONV=1
ROOT="$(cd "$(dirname "$0")/.." && (pwd -W 2>/dev/null || pwd))"
EXTRAS=""
for d in balls_extension battle collectible collector merchant pack boss vote_topgg auction_house frames augment; do
  EXTRAS="$EXTRAS:/work/extra/$d"
done
docker run --rm --network onepiecedex_internal --env-file "$ROOT/.env" \
  -v "$ROOT/admin_panel:/work/admin_panel:ro" \
  -v "$ROOT/ballsdex:/work/src/ballsdex:ro" \
  -v "$ROOT/extra:/work/extra:ro" \
  -v "$ROOT/battle_equipment:/work/battle_equipment:ro" \
  -v "$ROOT/eventexample:/work/eventexample:ro" \
  -v "$ROOT/battle_tests:/work/battle_tests:ro" \
  -e BALLSDEXBOT_EXTRA_TOML=/work/battle_tests/test-extra.toml \
  -e DJANGO_SETTINGS_MODULE=admin_panel.settings \
  -e PYTHONPATH="/work/admin_panel:/work/src$EXTRAS" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -w /work/admin_panel \
  ballsdex sh /work/battle_tests/in_container.sh "$@"
