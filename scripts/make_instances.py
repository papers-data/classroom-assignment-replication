"""Turn the AcademiAPP CSV snapshot into MiniZinc instances.

The thesis model (Velasquez 2022) reads two data files per instance:

    <name>-horarios.dzn   subjects, teachers, availability, day/night hour sets
    <name>-salones.dzn    rooms with capacity and resource, subject requirements

Hour grid, inherited from the model: six days of sixteen hours starting at
06:00, so hour index h = (day - 1) * 16 + (clock_hour - 6) + 1, h in 1..96.
Hours 1..12 of each day are the day shift and 13..16 the evening shift.

Two fields the API does not publish have to be approximated, and both
approximations are written into the header of every generated file so they
travel with the instance:

  * enrollment cap per group (`Ae` in the model). Options are `room-proxy`
    (the capacity of the room the campus actually used, which leaks part of
    the historical solution and is therefore only sound as an upper bound),
    `sample` (drawn from the observed capacity distribution), and `zero`
    (turns the capacity constraint inert).
  * resource required by a subject (`Ar`). Taken from the room the campus
    used. No endpoint states the requirement itself.

Usage:
    bash containers/run.sh paper-data python scripts/academiapp/make_instances.py \\
        --data papers/timetabling-llm-individual/data \\
        --out papers/timetabling-llm-individual/data/instances \\
        --period all
"""

import argparse
import csv
import random
import re
from collections import defaultdict
from pathlib import Path

HOURS_PER_DAY = 16
FIRST_HOUR = 6  # the grid starts at 06:00
DAY_SHIFT_HOURS = 12  # hours 1..12 of each day are the day shift
DAY_INDEX = {
    "Monday": 1,
    "Tuesday": 2,
    "Wednesday": 3,
    "Thursday": 4,
    "Friday": 5,
    "Saturday": 6,
}


def read_csv(path):
    with Path(path).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def hour_index(day_name, clock_hour):
    """Map a weekday and a clock hour onto the model's 1..96 grid."""
    day = DAY_INDEX.get(day_name)
    if day is None or not FIRST_HOUR <= clock_hour < FIRST_HOUR + HOURS_PER_DAY:
        return None
    return (day - 1) * HOURS_PER_DAY + (clock_hour - FIRST_HOUR) + 1


def hour_span(day_name, entry, departure):
    """Every hour index a class occupies, from its entry and departure times.

    The clock hour of the departure time is exclusive, including when the
    departure carries minutes. The institution's evening band runs 18:20 to
    21:20 and its own `hours` column calls that three hours, not four: a class
    that starts twenty minutes into an hour also ends twenty minutes into one,
    so it spans as many grid hours as its declared length. Rounding the
    departure up instead added an hour to all 569 rows whose band ends off the
    hour, inflating total teaching time by 565 hours and room occupancy with
    it.

    Four rows remain where the source disagrees with itself: three declare
    three hours between 13:00 and 15:00, and one declares three hours from
    05:00 when the grid opens at 06:00. Both are left as the clock reads,
    since the times are the more specific record.
    """
    start = int(entry.split(":")[0])
    end = int(departure.split(":")[0])
    span = []
    for clock in range(start, end):
        index = hour_index(day_name, clock)
        if index is not None:
            span.append(index)
    return span


def resource_of(room_name):
    """Resource kind of a room, inferred from its name."""
    name = room_name.strip().lower()
    if "sistemas" in name:
        return "SalaSistemas"
    if "coliseo" in name:
        return "Coliseo"
    if "planta" in name:
        return "PlantaAlimentos"
    if "laboratorio" in name:
        return "Lab" + re.sub(r"[^A-Za-z]", "", room_name.split("de")[-1]).title()
    return "Ninguno"


def shift_sets():
    """The `diurno` and `nocturno` hour sets the model expects."""
    day_hours, evening_hours = [], []
    for day in range(6):
        base = day * HOURS_PER_DAY
        day_hours += list(range(base + 1, base + DAY_SHIFT_HOURS + 1))
        evening_hours += list(range(base + DAY_SHIFT_HOURS + 1, base + HOURS_PER_DAY + 1))
    return day_hours, evening_hours


def audit(rows, availability):
    """Check the schedule the campus actually ran against the model's hard rules.

    The historical solution turns out to violate several of them, so an
    instance built faithfully from the data is unsatisfiable. Reporting the
    violations is more useful than hiding them: they are the ground truth for
    any study of infeasibility diagnosis, and they bound what the model can
    claim about the campus.
    """
    occupied = defaultdict(list)
    for row in rows:
        for hour in hour_span(row["day"], row["entry_time"], row["departure_time"]):
            occupied[hour].append(row)

    findings = {
        "teacher_clashes": 0,
        "room_double_bookings": 0,
        "program_semester_overlaps": 0,
        "hours_outside_availability": 0,
        "teachers_without_availability": 0,
    }
    for items in occupied.values():
        by_teacher, by_room, by_cohort = (
            defaultdict(set),
            defaultdict(set),
            defaultdict(set),
        )
        for row in items:
            group = (row["id_university_subject"], row["group"])
            by_teacher[row["id_teacher"]].add(group)
            by_room[row["id_space"]].add(group)
            by_cohort[(row["id_program"], row["semesters"])].add(
                row["id_university_subject"]
            )
        findings["teacher_clashes"] += sum(1 for v in by_teacher.values() if len(v) > 1)
        findings["room_double_bookings"] += sum(1 for v in by_room.values() if len(v) > 1)
        findings["program_semester_overlaps"] += sum(
            1 for v in by_cohort.values() if len(v) > 1
        )

    declared = defaultdict(set)
    for row in availability:
        declared[row["id_teacher"]].update(
            hour_span(row["day"], row["start_time"], row["end_time"])
        )
    for row in rows:
        if row["id_teacher"] not in declared:
            findings["teachers_without_availability"] += 1
            continue
        findings["hours_outside_availability"] += sum(
            1
            for hour in hour_span(row["day"], row["entry_time"], row["departure_time"])
            if hour not in declared[row["id_teacher"]]
        )
    return findings


def build_period(rows, availability, spaces, enrollment, rng, repair="none"):
    """Assemble one instance from the rows of a single academic period."""
    groups = defaultdict(list)
    for row in rows:
        key = (row["id_university_subject"], row["group"])
        groups[key].append(row)

    subjects, teachers = [], {}
    for key, occurrences in sorted(groups.items()):
        first = occurrences[0]
        teacher = first["id_teacher"]
        teachers.setdefault(teacher, len(teachers) + 1)
        hours = sum(len(hour_span(o["day"], o["entry_time"], o["departure_time"]))
                    for o in occurrences)
        evening = any(int(o["entry_time"].split(":")[0]) >= FIRST_HOUR + DAY_SHIFT_HOURS
                      for o in occurrences)
        rooms_used = {o["id_space"] for o in occurrences}
        subjects.append(
            {
                "program": int(first["id_program"]),
                "semester": int(first["semesters"] or 1),
                "code": int(first["id_university_subject"]),
                "group": int(first["group"]),
                "shift": 1 if evening else 0,
                "intensity": max(1, min(hours, DAY_SHIFT_HOURS)),
                "teacher": teachers[teacher],
                "rooms_used": rooms_used,
            }
        )

    space_by_id = {s["id_space"]: s for s in spaces}
    capacities = [int(s["maximum_capacity"]) for s in spaces
                  if s["sw_virtual"] in ("0", "False", "false")]

    for subject in subjects:
        room = next((space_by_id[r] for r in subject["rooms_used"] if r in space_by_id),
                    None)
        subject["resource"] = resource_of(room["name"]) if room else "Ninguno"
        if enrollment == "room-proxy":
            subject["enrollment"] = int(room["maximum_capacity"]) if room else 0
        elif enrollment == "sample":
            subject["enrollment"] = rng.choice(capacities)
        else:
            subject["enrollment"] = 0

    # Availability grid: teachers x hours. A teacher with no record in this
    # period is treated as fully available, which is the permissive reading.
    available = defaultdict(set)
    for row in availability:
        index = teachers.get(row["id_teacher"])
        if index is None:
            continue
        available[index].update(
            hour_span(row["day"], row["start_time"], row["end_time"])
        )
    for index in teachers.values():
        if not available[index]:
            available[index] = set(range(1, 6 * HOURS_PER_DAY + 1))

    if repair == "availability":
        # Some teachers teach hours they never declared free. Add those hours
        # to their availability so the contradiction disappears; the model's
        # remaining constraints are left untouched.
        for row in rows:
            index = teachers.get(row["id_teacher"])
            if index is not None:
                available[index].update(
                    hour_span(row["day"], row["entry_time"], row["departure_time"])
                )

    return subjects, teachers, available


def write_horarios(path, subjects, teachers, available, header):
    day_hours, evening_hours = shift_sets()
    total_hours = 6 * HOURS_PER_DAY
    lines = [header, ""]
    lines.append("diurno = {" + ", ".join(map(str, day_hours)) + "};")
    lines.append("nocturno = {" + ", ".join(map(str, evening_hours)) + "};")
    lines.append(f"H = {total_hours};")
    lines.append(f"asignaturas = {len(subjects)};")
    lines.append(f"docentes = {len(teachers)};")
    lines.append("")

    rows = [
        f"|{s['program']}, {s['semester']}, {s['code']}, {s['group']}, "
        f"{s['shift']}, {s['intensity']}"
        for s in subjects
    ]
    lines.append("A=[" + "\n".join(rows) + "\n|];")

    per_teacher = defaultdict(list)
    for position, subject in enumerate(subjects, start=1):
        per_teacher[subject["teacher"]].append(position)
    lines.append(
        "Da=["
        + ",\n".join(
            "{" + ", ".join(map(str, per_teacher[t])) + "}"
            for t in sorted(teachers.values())
        )
        + "\n];"
    )
    lines.append("Ad=[" + ", ".join(str(s["teacher"]) for s in subjects) + "];")

    grid = []
    for hour in range(1, total_hours + 1):
        grid.append(
            "|"
            + ", ".join(
                "true " if hour in available[t] else "false"
                for t in sorted(teachers.values())
            )
        )
    lines.append("D=[" + "\n".join(grid) + "\n|];")
    Path(path).write_text("\n".join(lines) + "\n")


def write_salones(path, subjects, spaces, header):
    rooms = [s for s in spaces if s["sw_virtual"] in ("0", "False", "false")]
    # A generated room carries its resource explicitly; a real one is
    # classified from its name.
    def room_resource(room):
        return room.get("_resource") or resource_of(room["name"])

    resources = sorted(
        {room_resource(r) for r in rooms} | {s["resource"] for s in subjects}
    )
    lines = [header, ""]
    lines.append("Recursos=[" + ", ".join(resources) + "];")
    lines.append(f"sede={len(rooms)};")
    lines.append(f"salones={len(rooms)};")
    lines.append("Sc=[" + ",".join(r["maximum_capacity"] for r in rooms) + "];")
    lines.append("Sr=[" + ", ".join(room_resource(r) for r in rooms) + "];")
    lines.append(f"N={6 * HOURS_PER_DAY};")
    lines.append("ini=1;")
    lines.append(f"fin={len(subjects)};")
    lines.append(f"Asig={len(subjects)};")
    lines.append("Ar=[" + ",".join(s["resource"] for s in subjects) + "];")
    lines.append("Ae=[" + ",".join(str(s["enrollment"]) for s in subjects) + "];")
    Path(path).write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="directory holding the CSVs")
    parser.add_argument("--out", required=True, help="directory for the .dzn files")
    parser.add_argument("--period", default="all", help="period id, or 'all'")
    parser.add_argument(
        "--enrollment",
        choices=("room-proxy", "sample", "zero"),
        default="room-proxy",
        help="how to approximate the enrollment cap the API does not publish",
    )
    parser.add_argument(
        "--repair",
        choices=("none", "availability"),
        default="none",
        help="'none' stays faithful to the campus data; 'availability' extends "
        "each teacher's declared free hours to cover what they actually teach",
    )
    parser.add_argument("--seed", type=int, default=20260807)
    args = parser.parse_args()

    data = Path(args.data)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    assignments = read_csv(data / "assignments.csv")
    availability = read_csv(data / "teacher-availability.csv")
    spaces = read_csv(data / "spaces.csv")
    periods = {p["id_university_period"]: p["name"] for p in read_csv(data / "periods.csv")}

    wanted = (
        sorted({r["id_university_period"] for r in assignments}, key=int)
        if args.period == "all"
        else [args.period]
    )

    suffix = "" if args.repair == "none" else f"-{args.repair}"
    conflicts = []
    print(f"{'instance':18} {'subjects':>9} {'teachers':>9} {'rooms':>6} {'hours':>6}")
    for pid in wanted:
        rows = [r for r in assignments if r["id_university_period"] == pid]
        if not rows:
            print(f"period {pid}: no rows")
            continue
        period_availability = [
            a for a in availability if a["id_university_period"] == pid
        ]
        findings = audit(rows, period_availability)
        conflicts.append({"id_university_period": pid,
                          "name": periods.get(pid, ""), **findings})
        subjects, teachers, available = build_period(
            rows, period_availability, spaces, args.enrollment, rng, args.repair
        )
        label = f"p{int(pid):02d}{suffix}"
        header = (
            f"% Real instance from AcademiAPP, period {pid} "
            f"({periods.get(pid, 'unknown')}).\n"
            f"% Generated by scripts/academiapp/make_instances.py from the CSV\n"
            f"% snapshot. Enrollment caps: {args.enrollment} (the API does not\n"
            f"% publish them); subject resource requirements are inferred from the\n"
            f"% room the campus used. Both are approximations, not campus data.\n"
            f"% Availability repair: {args.repair}. The schedule the campus ran\n"
            f"% violates the model's hard constraints (teacher clashes "
            f"{findings['teacher_clashes']}, rooms double-booked "
            f"{findings['room_double_bookings']}, same-cohort overlaps "
            f"{findings['program_semester_overlaps']}, hours taught outside the\n"
            f"% declared availability {findings['hours_outside_availability']}), so\n"
            f"% this instance can be unsatisfiable for reasons present in the data."
        )
        write_horarios(out / f"{label}-horarios.dzn", subjects, teachers, available, header)
        write_salones(out / f"{label}-salones.dzn", subjects, spaces, header)
        rooms = len([s for s in spaces if s["sw_virtual"] in ("0", "False", "false")])
        print(
            f"{label:18} {len(subjects):9d} {len(teachers):9d} {rooms:6d} "
            f"{sum(s['intensity'] for s in subjects):6d}"
        )

    report = out / "historical-conflicts.csv"
    with report.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(conflicts[0].keys()))
        writer.writeheader()
        writer.writerows(conflicts)
    print(f"\nconflicts in the schedules the campus actually ran -> {report.name}")
    for row in conflicts:
        print(
            f"  {row['name']:32} teacher={row['teacher_clashes']:3d} "
            f"room={row['room_double_bookings']:3d} "
            f"cohort={row['program_semester_overlaps']:3d} "
            f"outside-availability={row['hours_outside_availability']:3d}"
        )


if __name__ == "__main__":
    main()
