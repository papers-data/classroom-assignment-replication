"""Score the schedules the campus ran on the model's own criteria.

The thesis model minimises two counts, classes in the 06:00--07:00 opening
hour and classes in the 12:00--14:00 lunch band, and maximises the number of
rooms left free all week. Those are the campus's own stated preferences, so
they can be measured on the schedules the campus produced by hand. Together
with the constraint violations audited by make_instances.py, this is the
evidence for the discussion of where model and practice diverge.

Usage:
    bash containers/run.sh paper-data python \\
        scripts/academiapp/compare_model_practice.py \\
        --data papers/timetabling-llm-individual/data \\
        --out papers/timetabling-llm-individual/data/model-vs-practice.csv
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

from make_instances import FIRST_HOUR, HOURS_PER_DAY, hour_span, read_csv

# The model counts an hour index h as the opening hour when h mod 16 == 1 and
# as lunch when h mod 16 is 7 or 8, which on the 06:00 grid is 06:00--07:00
# and 12:00--14:00.
OPENING_OFFSET = 0
LUNCH_OFFSETS = (6, 7)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    data = Path(args.data)
    assignments = read_csv(data / "assignments.csv")
    spaces = [
        s
        for s in read_csv(data / "spaces.csv")
        if s["sw_virtual"] in ("0", "False", "false")
    ]
    periods = {
        p["id_university_period"]: p["name"] for p in read_csv(data / "periods.csv")
    }

    rows = []
    for pid in sorted({r["id_university_period"] for r in assignments}, key=int):
        subset = [r for r in assignments if r["id_university_period"] == pid]
        opening = lunch = 0
        used_rooms = set()
        occupancy = defaultdict(set)
        for row in subset:
            hours = hour_span(row["day"], row["entry_time"], row["departure_time"])
            for hour in hours:
                offset = (hour - 1) % HOURS_PER_DAY
                if offset == OPENING_OFFSET:
                    opening += 1
                if offset in LUNCH_OFFSETS:
                    lunch += 1
                occupancy[row["id_space"]].add(hour)
            used_rooms.add(row["id_space"])

        total_hours = sum(
            len(hour_span(r["day"], r["entry_time"], r["departure_time"]))
            for r in subset
        )
        room_hours = len(spaces) * 6 * HOURS_PER_DAY
        rows.append(
            {
                "id_university_period": pid,
                "name": periods.get(pid, ""),
                "class_hours": total_hours,
                "opening_hour_classes": opening,
                "lunch_band_classes": lunch,
                "objective_sum": opening + lunch,
                "rooms_available": len(spaces),
                "rooms_used": len(used_rooms),
                "rooms_free_all_week": len(spaces) - len(used_rooms),
                "room_hour_occupancy_pct": round(100 * total_hours / room_hours, 1),
                "busiest_room_hours": max(
                    (len(v) for v in occupancy.values()), default=0
                ),
            }
        )

    out = Path(args.out)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"{'period':32} {'hours':>6} {'06:00':>6} {'12-14':>6} {'obj':>5} "
          f"{'free rooms':>11} {'occupancy':>10}")
    for row in rows:
        print(
            f"  {row['name']:30} {row['class_hours']:6d} "
            f"{row['opening_hour_classes']:6d} {row['lunch_band_classes']:6d} "
            f"{row['objective_sum']:5d} "
            f"{row['rooms_free_all_week']:3d}/{row['rooms_available']:<7d} "
            f"{row['room_hour_occupancy_pct']:9.1f}%"
        )
    print(f"\nwritten to {out}")


if __name__ == "__main__":
    main()
