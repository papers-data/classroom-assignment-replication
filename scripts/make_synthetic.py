"""Generate synthetic classroom-assignment instances calibrated on real data.

The eight real periods span 286 to 391 course groups, which is a narrow band.
Studying how solving effort grows, or how far a language model can be pushed
before it breaks, needs instances above and below that band. This script
draws them from the distributions observed in the AcademiAPP snapshot rather
than from invented parameters, so a synthetic instance of the same size as a
real one looks like it.

Calibrated from the snapshot: the distribution of weekly intensity per group,
the share of evening groups, groups per teacher, teacher availability density,
room capacities, and the mix of room resources. Reported by `--report`.

Feasibility is guaranteed by construction. The generator first places every
subject greedily into a seed schedule that respects the model's hard rules,
then derives teacher availability from that schedule and widens it with whole
bands. The seed is a certificate that a solution exists, so a solver that
fails on one of these instances has hit a search limit rather than a
contradiction. `--slack` scales the room count relative to demand and
`--availability` scales how much of the week each teacher declares free.

`--infeasible` does the opposite on purpose: it takes one teacher's
availability below the load they carry and writes that teacher and those
numbers into the file header, so any explanation of the infeasibility can be
scored against a known cause.

Usage:
    bash containers/run.sh paper-data python scripts/academiapp/make_synthetic.py \\
        --data papers/timetabling-llm-individual/data \\
        --out papers/timetabling-llm-individual/data/instances \\
        --subjects 50 100 200 400 --seed 20260807
"""

import argparse
import csv
import random
from collections import Counter, defaultdict
from pathlib import Path

from make_instances import (
    DAY_SHIFT_HOURS,
    FIRST_HOUR,
    HOURS_PER_DAY,
    hour_span,
    resource_of,
    write_horarios,
    write_salones,
)

TOTAL_HOURS = 6 * HOURS_PER_DAY


def read_csv(path):
    with Path(path).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def calibrate(data):
    """Extract the empirical distributions the generator samples from."""
    assignments = read_csv(data / "assignments.csv")
    availability = read_csv(data / "teacher-availability.csv")
    spaces = [
        s for s in read_csv(data / "spaces.csv")
        if s["sw_virtual"] in ("0", "False", "false")
    ]

    groups = {}
    for row in assignments:
        key = (row["id_university_period"], row["id_university_subject"], row["group"])
        entry = groups.setdefault(
            key, {"hours": 0, "evening": False, "teacher": row["id_teacher"],
                  "program": int(row["id_program"]), "semester": int(row["semesters"] or 1),
                  "room": row["id_space"]}
        )
        entry["hours"] += len(hour_span(row["day"], row["entry_time"], row["departure_time"]))
        if int(row["entry_time"].split(":")[0]) >= 6 + DAY_SHIFT_HOURS:
            entry["evening"] = True

    intensities = [min(max(g["hours"], 1), DAY_SHIFT_HOURS) for g in groups.values()]
    evening_share = sum(1 for g in groups.values() if g["evening"]) / len(groups)

    per_teacher = Counter((k[0], g["teacher"]) for k, g in groups.items())
    load = Counter(per_teacher.values())

    room_by_id = {s["id_space"]: s for s in spaces}
    resources = Counter(
        resource_of(room_by_id[g["room"]]["name"])
        for g in groups.values()
        if g["room"] in room_by_id
    )

    slots_free = Counter()
    for row in availability:
        slots_free[(row["id_university_period"], row["id_teacher"])] += len(
            hour_span(row["day"], row["start_time"], row["end_time"])
        )
    density = (
        sum(slots_free.values()) / len(slots_free) / TOTAL_HOURS if slots_free else 0.5
    )

    # Teachers declare availability in whole bands, never in scattered hours,
    # and the model's contiguity constraint depends on that: three isolated
    # free hours cannot host a three-hour class.
    bands = []
    for slot in read_csv(data / "time-slots.csv"):
        start = int(slot["start_time"].split(":")[0])
        end = int(slot["end_time"].split(":")[0])
        if slot["end_time"].split(":")[1] != "00":
            end += 1
        offsets = [
            clock - FIRST_HOUR
            for clock in range(start, end)
            if 0 <= clock - FIRST_HOUR < HOURS_PER_DAY
        ]
        if len(offsets) >= 2:
            bands.append(offsets)

    # A cohort is one program-semester in one period: the set of courses a
    # student body takes together. The model forbids any two of them from
    # overlapping, so a cohort's total weekly hours cannot exceed the hours its
    # shift offers. Cohort size and load therefore have to be generated, not
    # sampled independently per subject.
    cohorts = Counter((k[0], g["program"], g["semester"]) for k, g in groups.items())
    cohort_load = Counter()
    for key, group in groups.items():
        cohort_load[(key[0], group["program"], group["semester"])] += min(
            max(group["hours"], 1), DAY_SHIFT_HOURS
        )

    return {
        "bands": bands,
        "cohort_sizes": list(cohorts.values()),
        "cohort_loads": list(cohort_load.values()),
        "intensities": intensities,
        "evening_share": evening_share,
        "groups_per_teacher": list(load.elements()),
        "capacities": [int(s["maximum_capacity"]) for s in spaces],
        "resource_weights": resources,
        "availability_density": density,
        "programs": sorted({g["program"] for g in groups.values()}),
        "semesters": [g["semester"] for g in groups.values()],
        "real_sizes": sorted(
            Counter(k[0] for k in groups).values()
        ),
    }


def sample_rooms(profile, count, rng):
    """A room set whose capacities and resources follow the campus mix."""
    kinds = list(profile["resource_weights"].keys())
    weights = [profile["resource_weights"][k] for k in kinds]
    rooms = []
    for index in range(count):
        rooms.append(
            {
                "id_space": index + 1,
                "name": f"Sintetico {index + 1}",
                "maximum_capacity": str(rng.choice(profile["capacities"])),
                "sw_virtual": "0",
                "_resource": rng.choices(kinds, weights=weights)[0],
            }
        )
    # At least one room of every resource kind, otherwise subjects requiring it
    # are unsatisfiable for a reason that has nothing to do with scale.
    for position, kind in enumerate(kinds):
        if not any(r["_resource"] == kind for r in rooms) and position < len(rooms):
            rooms[position]["_resource"] = kind
    for room in rooms:
        room["name"] = {
            "SalaSistemas": "Sala de Sistemas",
            "Coliseo": "Coliseo",
            "PlantaAlimentos": "Planta de Alimentos",
        }.get(room["_resource"], room["_resource"].replace("Lab", "Laboratorio de "))
        room["name"] = f"{room['name']} {room['id_space']}"
    return rooms


def build(profile, n_subjects, rng, slack, availability_factor):
    kinds = list(profile["resource_weights"].keys())
    weights = [profile["resource_weights"][k] for k in kinds]

    # Build cohort by cohort. Every subject in a cohort shares its program,
    # semester, and shift, and the cohort stops taking subjects before its
    # weekly load reaches the hours its shift offers, since none of them may
    # overlap. The margin keeps the instance off the exact frontier; the
    # frontier itself is what --infeasible targets.
    day_capacity = 6 * DAY_SHIFT_HOURS
    evening_capacity = 6 * (HOURS_PER_DAY - DAY_SHIFT_HOURS)
    margin = 0.7

    subjects = []
    cohort_id = 0
    while len(subjects) < n_subjects:
        cohort_id += 1
        evening = rng.random() < profile["evening_share"]
        budget = margin * (evening_capacity if evening else day_capacity)
        size = min(rng.choice(profile["cohort_sizes"]), n_subjects - len(subjects))
        # Program and semester identify the cohort, so they must not repeat:
        # two cohorts sharing them would merge under the no-overlap rule and
        # blow the budget just computed.
        programs = profile["programs"]
        program = programs[(cohort_id - 1) % len(programs)]
        semester = (cohort_id - 1) // len(programs) + 1
        load = 0
        for _ in range(max(1, size)):
            intensity = rng.choice(profile["intensities"])
            if load + intensity > budget:
                break
            load += intensity
            subjects.append(
                {
                    "program": program,
                    "semester": semester,
                    "cohort": cohort_id,
                    "code": 0,  # filled below; must be unique per group
                    "group": cohort_id,
                    "shift": 1 if evening else 0,
                    "intensity": intensity,
                    "resource": rng.choices(kinds, weights=weights)[0],
                    "enrollment": rng.choice(profile["capacities"]),
                }
            )
            if len(subjects) == n_subjects:
                break
    for position, subject in enumerate(subjects, start=1):
        subject["code"] = 100000 + position

    # Teachers: enough of them that the observed load per teacher is preserved.
    mean_load = sum(profile["groups_per_teacher"]) / len(profile["groups_per_teacher"])
    n_teachers = max(1, round(n_subjects / mean_load))
    teachers = {f"t{i}": i for i in range(1, n_teachers + 1)}
    for position, subject in enumerate(subjects):
        subject["teacher"] = position % n_teachers + 1

    # Rooms are placed after the seed schedule, because the binding number is
    # the peak concurrency rather than the total demand: the room stage fails
    # whenever one hour needs more rooms than exist, however light the week is
    # on average.
    rooms = None

    # Availability, granted in whole bands as the campus records it. A teacher
    # gets bands in each shift they actually teach in, enough to cover their
    # load with the observed density as the floor.
    seed = seed_schedule(subjects, rng)
    if seed is None:
        return None

    # Peak concurrency per resource kind, not overall: the room stage matches
    # a group to a room of its own kind, so a week with plenty of ordinary
    # rooms still fails if two computer-room groups collide in one hour.
    concurrency = defaultdict(Counter)
    for subject in subjects:
        for hour in seed[id(subject)]:
            concurrency[subject["resource"]][hour] += 1

    rooms, next_id = [], 1
    for kind, per_hour in concurrency.items():
        needed = max(1, round(slack * max(per_hour.values())))
        for _ in range(needed):
            rooms.append({
                "id_space": next_id,
                "name": f"{kind} {next_id}",
                "maximum_capacity": str(max(profile["capacities"])),
                "sw_virtual": "0",
                "_resource": kind,
            })
            next_id += 1

    # Enrollment must fit the rooms that can host the group, so capacity never
    # becomes the reason an instance fails.
    for subject in subjects:
        ceiling = min(
            int(r["maximum_capacity"]) for r in rooms
            if r["_resource"] == subject["resource"]
        )
        subject["enrollment"] = min(subject["enrollment"], ceiling)

    # Availability is derived from the seed schedule and then widened with
    # whole bands. Deriving it guarantees the instance has at least one
    # solution; widening it keeps the seed from being the only one, so solving
    # time reflects search rather than a single forced assignment.
    day_hours, evening_hours = set(), set()
    day_bands, evening_bands = [], []
    for day in range(6):
        base = day * HOURS_PER_DAY
        day_hours |= set(range(base + 1, base + DAY_SHIFT_HOURS + 1))
        evening_hours |= set(range(base + DAY_SHIFT_HOURS + 1, base + HOURS_PER_DAY + 1))
        for offsets in profile["bands"]:
            block = frozenset(base + offset + 1 for offset in offsets)
            (day_bands if max(offsets) < DAY_SHIFT_HOURS else evening_bands).append(block)

    available = defaultdict(set)
    for subject in subjects:
        available[subject["teacher"]] |= seed[id(subject)]
    for index in teachers.values():
        for bands, pool in ((day_bands, day_hours), (evening_bands, evening_hours)):
            target = round(len(pool) * profile["availability_density"] * availability_factor)
            for block in rng.sample(bands, len(bands)):
                if len(available[index] & pool) >= target:
                    break
                available[index] |= block
    return subjects, teachers, dict(available), rooms


def blocks_for(intensity):
    """Split a weekly intensity into per-day blocks the model accepts.

    The model allows a day to hold either the whole intensity (up to three
    hours), or two, or three hours. Blocks of one hour are only valid when the
    subject itself lasts one hour, since anything longer must be contiguous.
    """
    if intensity <= 3:
        return [intensity]
    parts = []
    remaining = intensity
    while remaining > 3:
        parts.append(2 if remaining % 3 else 3)
        remaining -= parts[-1]
    if remaining:
        parts.append(remaining)
    return parts if all(p >= 2 for p in parts) else [2] * (intensity // 2) + (
        [3] if intensity % 2 else []
    )


def seed_schedule(subjects, rng):
    """Place every subject greedily, respecting the model's hard constraints.

    Returns the hours assigned to each subject, or None when the greedy pass
    fails. A successful pass is a certificate that the instance is
    satisfiable, which is what makes it usable for scaling experiments.
    """
    busy_teacher = defaultdict(set)
    busy_cohort = defaultdict(set)
    placement = {}

    for subject in sorted(subjects, key=lambda s: -s["intensity"]):
        cohort = (subject["program"], subject["semester"])
        offsets = (
            range(DAY_SHIFT_HOURS, HOURS_PER_DAY)
            if subject["shift"]
            else range(DAY_SHIFT_HOURS)
        )
        hours, used_days = set(), set()
        for length in blocks_for(subject["intensity"]):
            placed = False
            for day in rng.sample(range(6), 6):
                if day in used_days:
                    continue
                base = day * HOURS_PER_DAY
                starts = [o for o in offsets if o + length <= max(offsets) + 1]
                for start in rng.sample(starts, len(starts)):
                    window = {base + start + step + 1 for step in range(length)}
                    if window & busy_teacher[subject["teacher"]]:
                        continue
                    if window & busy_cohort[cohort]:
                        continue
                    hours |= window
                    busy_teacher[subject["teacher"]] |= window
                    busy_cohort[cohort] |= window
                    used_days.add(day)
                    placed = True
                    break
                if placed:
                    break
            if not placed:
                return None
        placement[id(subject)] = hours
    return placement


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="directory holding the CSVs")
    parser.add_argument("--out", required=True, help="directory for the .dzn files")
    parser.add_argument(
        "--subjects", type=int, nargs="+", default=[50, 100, 200, 400],
        help="instance sizes, in course groups",
    )
    parser.add_argument("--slack", type=float, default=1.6,
                        help="room count relative to the hour demand")
    parser.add_argument("--availability", type=float, default=1.0,
                        help="scales the observed teacher availability density")
    parser.add_argument("--infeasible", action="store_true",
                        help="emit instances tightened past feasibility")
    parser.add_argument("--seed", type=int, default=20260807)
    parser.add_argument("--report", action="store_true",
                        help="print the calibration profile and exit")
    args = parser.parse_args()

    data = Path(args.data)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    profile = calibrate(data)

    if args.report:
        counts = Counter(profile["intensities"])
        print("calibration profile")
        print(f"  real instance sizes      {profile['real_sizes']}")
        print("  weekly intensity         " + ", ".join(
            f"{h}h:{100 * c / len(profile['intensities']):.0f}%"
            for h, c in sorted(counts.items())))
        print(f"  evening groups           {100 * profile['evening_share']:.0f}%")
        print(f"  groups per teacher       mean "
              f"{sum(profile['groups_per_teacher']) / len(profile['groups_per_teacher']):.2f}")
        print(f"  availability density     {100 * profile['availability_density']:.0f}% of the week")
        print(f"  room capacities          {sorted(set(profile['capacities']))}")
        print("  resource mix             " + ", ".join(
            f"{k}:{100 * v / sum(profile['resource_weights'].values()):.0f}%"
            for k, v in profile["resource_weights"].most_common()))
        return

    rng = random.Random(args.seed)
    slack = args.slack
    availability_factor = args.availability

    print(f"{'instance':16} {'subjects':>9} {'teachers':>9} {'rooms':>6} {'hours':>6}")
    for size in args.subjects:
        built = None
        for _ in range(20):
            built = build(profile, size, rng, slack, availability_factor)
            if built is not None:
                break
        if built is None:
            print(f"{size}: greedy seed failed after 20 attempts, skipped")
            continue
        subjects, teachers, available, rooms = built

        cause = None
        if args.infeasible:
            # Take one teacher's availability below the load they carry. The
            # instance then has a single, localizable reason to be
            # unsatisfiable, which is the ground truth an explanation has to
            # recover.
            victim = max(
                teachers.values(),
                key=lambda t: sum(s["intensity"] for s in subjects if s["teacher"] == t),
            )
            load = sum(s["intensity"] for s in subjects if s["teacher"] == victim)
            keep = sorted(available[victim])[: max(0, load - 2)]
            available[victim] = set(keep)
            cause = (
                f"teacher {victim} carries {load} weekly hours but is left with "
                f"{len(keep)} free hours"
            )
        label = f"syn{size:04d}" + ("-infeasible" if args.infeasible else "")
        header = (
            f"% Synthetic instance, {size} course groups.\n"
            f"% Generated by scripts/academiapp/make_synthetic.py, calibrated on the\n"
            f"% AcademiAPP snapshot: intensity distribution, evening share, groups\n"
            f"% per teacher, availability density, room capacities and resource mix.\n"
            f"% seed={args.seed} slack={slack} availability={availability_factor}"
            + (f"\n% Deliberately infeasible: {cause}." if cause else "")
        )
        write_horarios(out / f"{label}-horarios.dzn", subjects, teachers, available, header)
        write_salones(out / f"{label}-salones.dzn", subjects, rooms, header)
        print(
            f"{label:16} {len(subjects):9d} {len(teachers):9d} {len(rooms):6d} "
            f"{sum(s['intensity'] for s in subjects):6d}"
        )


if __name__ == "__main__":
    main()
