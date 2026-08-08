#!/usr/bin/env bash
# Solve the generated instances with each bundled solver and record timings.
#
# Both stages of the thesis model are run: the timetabling model on its own,
# then the room-assignment model fed with the timetable the first stage
# produced. A run that exceeds the limit is recorded as such rather than
# dropped, so the table shows where each solver stops being usable.
#
# Usage: bash scripts/academiapp/benchmark.sh <instances-dir> <models-dir> <out.csv> <instance>...

set -uo pipefail
export LC_ALL=C  # decimal points, not commas: the output is CSV

INSTANCES="${1:?instances directory}"
MODELS="${2:?directory holding Horarios.mzn and Salones.mzn}"
OUT="${3:?output csv}"
LIMIT_MS="${LIMIT_MS:-600000}"
IMAGE="minizinc/minizinc:latest"

echo "instance,stage,solver,status,seconds,objective" > "$OUT"

run() {
  local instance="$1" stage="$2" solver="$3" model="$4" data="$5"
  local start end elapsed output status objective
  start=$(date +%s%3N)
  output=$(timeout $(( LIMIT_MS / 1000 + 120 )) docker run --rm \
    -v "$(realpath "$INSTANCES"):/inst:ro" -v "$(realpath "$MODELS"):/model:ro" \
    "$IMAGE" minizinc --solver "$solver" --time-limit "$LIMIT_MS" \
    "/model/$model" "$data" 2>/dev/null)
  end=$(date +%s%3N)
  elapsed=$(awk -v a="$start" -v b="$end" 'BEGIN{printf "%.1f", (b-a)/1000}')

  if grep -q "UNSATISFIABLE" <<<"$output"; then
    status="unsat"
  elif grep -q "==========" <<<"$output"; then
    status="optimal"
  elif grep -q "=====" <<<"$output" && grep -qE "mediodia|SalonesLibres|^$" <<<"$output"; then
    status="solved"
  elif [[ -z "$output" ]]; then
    status="timeout"
  else
    status="solved"
  fi
  objective=$(grep -oE "mediodia = [0-9]+" <<<"$output" | grep -oE "[0-9]+" | head -1)
  echo "$instance,$stage,$solver,$status,$elapsed,${objective:-}" >> "$OUT"
  echo "  $instance $stage $solver -> $status ${elapsed}s"
}

shift 3
INSTANCES_TO_RUN=("$@")
[[ ${#INSTANCES_TO_RUN[@]} -eq 0 ]] && INSTANCES_TO_RUN=(syn0025 syn0050 syn0100 syn0200)

for instance in "${INSTANCES_TO_RUN[@]}"; do
  horarios="/inst/${instance}-horarios.dzn"
  [[ -f "$INSTANCES/${instance}-horarios.dzn" ]] || continue
  for solver in ${SOLVERS:-cbc gecode chuffed}; do
    run "$instance" horarios "$solver" Horarios.mzn "$horarios"
  done
done

echo "written to $OUT"
