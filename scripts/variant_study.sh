#!/usr/bin/env bash
# Re-run the thesis variant study on the instances released with this paper.
#
# The thesis compared three formulations of the room-assignment model against
# three solvers, but reported the result only as a bar chart; the per-cell
# timings did not survive. The three formulations are recoverable from the
# published backend, where two of them sit alongside the third as commented
# code, and they differ in how they forbid a course group from occupying two
# rooms at once:
#
#   Salones       alldifferent_except_0 over each hour's row
#   SalonesCount  count(row, a) = 1 for each scheduled group   (the deployed one)
#   SalonesGC     global_cardinality with a 1/0 target per group
#
# The room model needs a timetable, so each run is two stages: solve the
# timetabling model, take its C matrix, and feed that to the room model
# together with an empty SAI (no pre-placed classes).
#
# Usage:
#   bash scripts/academiapp/variant_study.sh <instances-dir> <models-dir> <out.csv> <instance>...
# Environment:
#   LIMIT_MS  per-run time limit in milliseconds (default 300000)
#   SOLVERS   space-separated solver list (default "cbc chuffed gecode")

set -uo pipefail
export LC_ALL=C

INSTANCES=$(realpath "${1:?instances directory}")
MODELS=$(realpath "${2:?directory holding Horarios.mzn and the Salones variants}")
OUT="${3:?output csv}"
shift 3
LIMIT_MS="${LIMIT_MS:-300000}"
IMAGE="minizinc/minizinc:latest"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "instance,variant,solver,status,seconds,free_rooms" > "$OUT"

solve() {  # model dzn solver -> prints raw output
  timeout $(( LIMIT_MS / 1000 + 120 )) docker run --rm \
    -v "$INSTANCES:/inst:ro" -v "$MODELS:/model:ro" -v "$WORK:/work" \
    "$IMAGE" minizinc --solver "$3" --time-limit "$LIMIT_MS" \
    "/model/$1" "$2" 2>/dev/null
}

for instance in "$@"; do
  [[ -f "$INSTANCES/${instance}-horarios.dzn" ]] || continue

  # Stage 1: the timetable. Solved once per instance with COIN-BC, since the
  # variants under study belong to the room model.
  timetable=$(solve Horarios.mzn "/inst/${instance}-horarios.dzn" cbc)
  if ! grep -q "^C=\[|" <<<"$timetable"; then
    echo "  $instance: stage 1 produced no timetable, skipping"
    continue
  fi
  # Stage-2 data: the room instance, the timetable, and an empty input matrix.
  {
    cat "$INSTANCES/${instance}-salones.dzn"
    echo
    awk '/^C=\[\|/{f=1} f{print} /\];[[:space:]]*$/{if(f)exit}' <<<"$timetable"
    rooms=$(grep -oP 'salones=\K[0-9]+' "$INSTANCES/${instance}-salones.dzn")
    hours=$(grep -oP '^N=\K[0-9]+' "$INSTANCES/${instance}-salones.dzn")
    python3 -c "
rooms=$rooms; hours=$hours
print('SAI=[' + '\\n'.join('|' + ','.join(['0']*rooms) for _ in range(hours)) + '\\n|];')"
  } > "$WORK/${instance}-stage2.dzn"

  for variant in Salones SalonesCount SalonesGC; do
    for solver in ${SOLVERS:-cbc chuffed gecode}; do
      start=$(date +%s%3N)
      out=$(solve "$variant.mzn" "/work/${instance}-stage2.dzn" "$solver")
      end=$(date +%s%3N)
      elapsed=$(awk -v a="$start" -v b="$end" 'BEGIN{printf "%.1f",(b-a)/1000}')

      if grep -q "UNSATISFIABLE" <<<"$out"; then status=unsat
      elif grep -q "==========" <<<"$out"; then status=optimal
      elif grep -q "libres" <<<"$out"; then status=limit
      elif [[ -z "$out" ]]; then status=timeout
      else status=error; fi
      free=$(grep -oE "libres = [0-9]+" <<<"$out" | grep -oE "[0-9]+" | tail -1)

      echo "$instance,$variant,$solver,$status,$elapsed,${free:-}" >> "$OUT"
      echo "  $instance $variant $solver -> $status ${elapsed}s free=${free:-n/a}"
    done
  done
done

echo "written to $OUT"
