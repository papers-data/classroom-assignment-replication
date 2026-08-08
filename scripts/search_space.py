"""Size the search space of the timetabling model, and emit pgfplots data.

The point of the figure this feeds is to separate two things that are easy to
conflate: the size of the space the model describes, which grows
exponentially, and the time the solver actually takes, which on these
instances grows polynomially. Both are computed from the model as written,
not estimated.

Three nested counts are reported per instance size A (course groups):

  raw          every assignment of the Boolean matrix C[h,a]: 2^(96A).
  intensity    each group takes exactly its weekly intensity from 96 hours,
               which is the first constraint the model imposes.
  structured   each group is confined to its shift and must occupy contiguous
               blocks with the per-intensity day rules, which is what the
               model actually searches.

The gap between the second and third is the leverage the formulation buys
before any search happens.

Usage:
    bash containers/run.sh paper-data python scripts/academiapp/search_space.py \\
        --data papers/timetabling-cp-velasquez/data \\
        --out papers/timetabling-cp-velasquez/data/search-space.csv
"""

import argparse
import csv
import math
from collections import Counter
from pathlib import Path

from make_instances import DAY_SHIFT_HOURS, HOURS_PER_DAY, hour_span, read_csv

TOTAL_HOURS = 6 * HOURS_PER_DAY
DAYS = 6
EVENING_HOURS_PER_DAY = HOURS_PER_DAY - DAY_SHIFT_HOURS


def log10_binomial(n, k):
    if k < 0 or k > n:
        return float("-inf")
    return (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)) / math.log(10)


def placements_per_group(intensity, shift):
    """How many hour sets the model allows for one group.

    A group is confined to its shift, and its hours form contiguous blocks
    whose lengths follow the model's per-intensity rule: up to three hours in
    a single block, four as one block or two plus two, and beyond that in
    blocks of two or three. Blocks sit on distinct days.
    """
    hours_per_day = DAY_SHIFT_HOURS if shift == 0 else EVENING_HOURS_PER_DAY

    def block_positions(length):
        return max(0, hours_per_day - length + 1)

    if intensity <= 3:
        return DAYS * block_positions(intensity)

    # Partition the intensity into blocks of 2, 3, or (for 4) a single block.
    partitions = []
    if intensity == 4:
        partitions = [[4], [2, 2]]
    else:
        remaining, parts = intensity, []
        while remaining > 3:
            parts.append(2 if remaining % 3 else 3)
            remaining -= parts[-1]
        if remaining:
            parts.append(remaining)
        partitions = [parts]

    total = 0
    for parts in partitions:
        if len(parts) > DAYS:
            continue
        # Choose distinct days for the blocks, then a position within each.
        ways = math.perm(DAYS, len(parts))
        for length in parts:
            ways *= block_positions(length)
        total += ways
    return max(total, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    data = Path(args.data)
    assignments = read_csv(data / "assignments.csv")

    # Empirical mixture of intensities and shifts, so the count reflects the
    # campus rather than a uniform assumption.
    groups = {}
    for row in assignments:
        key = (row["id_university_period"], row["id_university_subject"], row["group"])
        entry = groups.setdefault(key, {"hours": 0, "evening": False})
        entry["hours"] += len(hour_span(row["day"], row["entry_time"], row["departure_time"]))
        if int(row["entry_time"].split(":")[0]) >= 6 + DAY_SHIFT_HOURS:
            entry["evening"] = True

    profile = Counter(
        (min(max(g["hours"], 1), DAY_SHIFT_HOURS), 1 if g["evening"] else 0)
        for g in groups.values()
    )
    total = sum(profile.values())

    # Average log10 placements per group under the empirical mixture.
    log_structured_per_group = sum(
        count / total * math.log10(placements_per_group(intensity, shift))
        for (intensity, shift), count in profile.items()
    )
    log_intensity_per_group = sum(
        count / total * log10_binomial(TOTAL_HOURS, intensity)
        for (intensity, shift), count in profile.items()
    )

    real_sizes = sorted(
        Counter(k[0] for k in groups).values()
    )

    rows = []
    for size in list(range(25, 401, 25)) + real_sizes:
        rows.append(
            {
                "course_groups": size,
                "log10_raw": round(size * TOTAL_HOURS * math.log10(2), 1),
                "log10_intensity": round(size * log_intensity_per_group, 1),
                "log10_structured": round(size * log_structured_per_group, 1),
                "is_real_instance": int(size in real_sizes),
            }
        )
    rows.sort(key=lambda r: r["course_groups"])

    out = Path(args.out)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"placements per group, empirical mixture: "
          f"10^{log_structured_per_group:.2f} structured, "
          f"10^{log_intensity_per_group:.2f} intensity-only")
    print(f"{'groups':>7} {'log10 raw':>11} {'log10 intensity':>16} {'log10 structured':>17}")
    for row in rows:
        mark = " *" if row["is_real_instance"] else ""
        print(f"{row['course_groups']:7d} {row['log10_raw']:11.1f} "
              f"{row['log10_intensity']:16.1f} {row['log10_structured']:17.1f}{mark}")
    print(f"\n* real campus semester\nwritten to {out}")


if __name__ == "__main__":
    main()
