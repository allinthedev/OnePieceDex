#!/bin/bash
# Replays every test of the battle mode and prints one summary.
#
#   bash battle_tests/run_all.sh            everything
#   bash battle_tests/run_all.sh t04 t07    only the files whose name starts with one of these
#
# The two pure suites run on the host (no Django). Everything else runs in the throwaway container of run.sh,
# against the scratch database "battle_test" and nothing else. The full output of each file is kept in
# battle_tests/out/<file>.txt.
#
# A test tied to a known bug fails with its tag, like [B06]: such a failure is expected until the bug is
# fixed. The exit code is 0 when every failure is a tagged one, 1 when a test fails without a tag or a file
# does not reach its end.
cd "$(dirname "$0")/.." || exit 2
OUT=battle_tests/out
mkdir -p "$OUT"
PYTHON="$(command -v python3 || command -v python)"

wanted() {
  [ $# -eq 0 ] && return 0
  local name="$1"
  shift
  for prefix in "${FILTERS[@]}"; do
    case "$name" in "$prefix"*) return 0 ;; esac
  done
  return 1
}
FILTERS=("$@")
selected() {
  [ ${#FILTERS[@]} -eq 0 ] && return 0
  wanted "$1" x
}

total=0
passed=0
failed=0
unexplained=0
broken=0
bugs=""
rows=""

add_row() { # name total passed failed bugs
  rows="$rows$(printf '%-22s %6s %6s %6s   %s' "$1" "$2" "$3" "$4" "$5")"$'\n'
  total=$((total + $2))
  passed=$((passed + $3))
  failed=$((failed + $4))
}

# -- pure rules, on the host -------------------------------------------------------------------------------
for name in test_loadout test_capacity; do
  selected "$name" || continue
  # -B: these two import engine.py and loadout.py straight from extra/, and must leave no .pyc there
  "$PYTHON" -I -B "battle_tests/$name.py" . >"$OUT/$name.txt" 2>&1
  code=$?
  p=$(grep -c '^  PASS' "$OUT/$name.txt")
  f=$(grep -c '^  FAIL' "$OUT/$name.txt")
  add_row "$name" $((p + f)) "$p" "$f" "-"
  unexplained=$((unexplained + f))
  if [ $code -ne 0 ] && [ "$f" -eq 0 ]; then
    broken=$((broken + 1))
    rows="$rows  ^ $name stopped with exit code $code, see $OUT/$name.txt"$'\n'
  fi
done

# -- Django's own checks, in the container ------------------------------------------------------------------
if selected "t00_django"; then
  name=t00_django
  : >"$OUT/$name.txt"
  p=0
  f=0
  if bash battle_tests/run.sh python3 -m django check >>"$OUT/$name.txt" 2>&1; then
    p=$((p + 1))
    echo "  PASS  manage.py check" >>"$OUT/$name.txt"
  else
    f=$((f + 1))
    echo "  FAIL  manage.py check" >>"$OUT/$name.txt"
  fi
  if bash battle_tests/run.sh python3 -m django makemigrations --check --dry-run battle_app >>"$OUT/$name.txt" 2>&1; then
    p=$((p + 1))
    echo "  PASS  the models of battle_app match its migrations" >>"$OUT/$name.txt"
  else
    f=$((f + 1))
    echo "  FAIL  the models of battle_app match its migrations" >>"$OUT/$name.txt"
  fi
  if bash battle_tests/run.sh python3 -m django load_battle_equipment /work/battle_equipment --dry-run >>"$OUT/$name.txt" 2>&1; then
    p=$((p + 1))
    echo "  PASS  the equipment files load (dry run, nothing saved)" >>"$OUT/$name.txt"
  else
    f=$((f + 1))
    echo "  FAIL  the equipment files load (dry run, nothing saved)" >>"$OUT/$name.txt"
  fi
  add_row "$name" $((p + f)) "$p" "$f" "-"
  unexplained=$((unexplained + f))
fi

# -- the real cog, in the container -------------------------------------------------------------------------
for path in battle_tests/t[0-9][0-9]_*.py; do
  name="$(basename "$path" .py)"
  selected "$name" || continue
  bash battle_tests/run.sh python3 "/work/battle_tests/$name.py" >"$OUT/$name.txt" 2>&1
  summary="$(grep '^SUMMARY ' "$OUT/$name.txt" | tail -1)"
  if [ -z "$summary" ]; then
    broken=$((broken + 1))
    rows="$rows$(printf '%-22s %s' "$name" "DID NOT FINISH, see $OUT/$name.txt")"$'\n'
    continue
  fi
  t=$(echo "$summary" | sed -E 's/.* total=([0-9]+).*/\1/')
  p=$(echo "$summary" | sed -E 's/.* passed=([0-9]+).*/\1/')
  f=$(echo "$summary" | sed -E 's/.* failed=([0-9]+).*/\1/')
  u=$(echo "$summary" | sed -E 's/.* unexplained=([0-9]+).*/\1/')
  b=$(echo "$summary" | sed -E 's/.* bugs=([^ ]+).*/\1/')
  add_row "$name" "$t" "$p" "$f" "$b"
  unexplained=$((unexplained + u))
  [ "$b" != "-" ] && bugs="$bugs,$b"
done

echo
printf '%-22s %6s %6s %6s   %s\n' "file" "tests" "pass" "fail" "bugs behind the failures"
printf '%s' "$rows"
printf '%-22s %6s %6s %6s\n' "TOTAL" "$total" "$passed" "$failed"
echo
known=$(echo "$bugs" | tr ',' '\n' | grep -v '^$' | sort -u | tr '\n' ' ')
echo "Known bugs still failing a test: ${known:-none}"
echo "Failures with no bug behind them: $unexplained"
echo "Files that did not finish: $broken"
echo "Full output of each file: $OUT/"
[ "$unexplained" -eq 0 ] && [ "$broken" -eq 0 ]
