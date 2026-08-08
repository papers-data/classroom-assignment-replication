"""Snapshot the Univalle Tuluá academic data from AcademiAPP into CSV.

Run this once. Everything downstream reads the CSVs, so the API is not
queried again unless a newer snapshot is wanted.

Two access levels are used. Class schedules come from the same anonymous
endpoint the public web client at univalle.academiapp.app/#/class-schedule
reads. Rooms, capacities, teacher availabilities, subjects, and time slots
need a session; credentials come from the environment (never from the
command line or a file in the repository):

    ACADEMIAPP_USER, ACADEMIAPP_PASSWORD   (add them to the secrets export)

Teacher names are personal data under Colombian Law 1581 of 2012, and so are
the source system's teacher identifiers: its public endpoint returns them next
to the name, so publishing one publishes the other. The CSVs therefore carry
labels `T001`, `T002`, … that exist only in the extract, and the row-level
surrogate keys are dropped. The label-to-name mapping goes to a separate
`.private.csv` that the data directories git-ignore.

Files written to each --out directory:

    assignments.csv             one row per scheduled class hour block
    spaces.csv                  room catalog with maximum capacity
    teacher-availability.csv    per-teacher free slots, by period
    subjects.csv                subject catalog (code, hours, credits, program)
    time-slots.csv              the thirteen time bands
    periods.csv                 academic periods with their date ranges
    programs.csv                academic programs
    teacher-names.private.csv   identifier to name (git-ignored)

Usage:
    ( source "$HOME/repositorios/prompts-gpt/secrets/export.sh" \\
      && bash containers/run.sh paper-data python scripts/academiapp/fetch.py \\
           --out papers/timetabling-llm-individual/data \\
           --out papers/timetabling-cp-velasquez/data )
"""

import argparse
import csv
import json
import os
import urllib.request
from pathlib import Path

API = "https://apiunivalle.academiapp.app/api"

PERSONAL_FIELDS = (
    "first_name",
    "last_name",
    "middle_name",
    "second_last_name",
    "id_person",
    "document_id",
    "phone",
    "email",
)

# Identifiers that resolve to a name through the source system's own public
# endpoint, which returns them beside the teacher's name. Publishing them
# publishes the name by reference, so the teacher identifier is replaced with a
# label local to the extract and the row-level surrogate keys are dropped.
RELABEL_FIELD = "id_teacher"
SURROGATE_KEYS = ("id_schedule_professor_subject", "id_teacher_availability")


def request(endpoint, token=None, method="GET", body=None):
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{API}/{endpoint}", data=data, headers=headers, method=method
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.load(response)


def login():
    user = os.environ.get("ACADEMIAPP_USER")
    password = os.environ.get("ACADEMIAPP_PASSWORD")
    if not (user and password):
        return None
    return request(
        "login", method="POST", body={"username": user, "password": password}
    )["token"]


def build_labels(*row_groups):
    """Map each source teacher identifier to a label local to this extract.

    Labels are assigned by sorting the source identifiers numerically and
    numbering them, so the mapping is deterministic and does not depend on the
    order rows arrive in. The mapping itself is never written to the extract.
    """
    ids = {
        row[RELABEL_FIELD]
        for rows in row_groups
        for row in rows
        if row.get(RELABEL_FIELD)
    }
    return {
        old: f"T{index:03d}"
        for index, old in enumerate(sorted(ids, key=int), start=1)
    }


def deidentify(rows, labels):
    """Drop personal fields and system keys, and relabel the teacher."""
    cleaned = []
    for row in rows:
        out = {
            k: v
            for k, v in row.items()
            if k not in PERSONAL_FIELDS and k not in SURROGATE_KEYS
        }
        if out.get(RELABEL_FIELD):
            out[RELABEL_FIELD] = labels[row[RELABEL_FIELD]]
        cleaned.append(out)
    return cleaned


def write_csv(path, rows, columns=None):
    if not rows:
        path.write_text("")
        print(f"  {path.name:30} empty")
        return
    columns = columns or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {path.name:30} {len(rows):5d} rows")


def flatten_days_time_slots(payload):
    """days_time_slots nests time slots inside each day; flatten to pairs."""
    flat = []
    for day in payload:
        for slot in day.get("time_slots", []):
            flat.append(
                {
                    "id_day": day["id_day"],
                    "day": day["day"],
                    "value_day": day.get("value_day"),
                    "id_time_slot": slot["id_time_slot"],
                    "start_time": slot["start_time"],
                    "end_time": slot["end_time"],
                    "id_day_time_slot": (slot.get("pivot") or {}).get(
                        "id_day_time_slot"
                    ),
                }
            )
    return flat


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        action="append",
        required=True,
        help="output directory; repeat to write the snapshot to several papers",
    )
    args = parser.parse_args()

    token = login()
    if token is None:
        print("No ACADEMIAPP_USER/ACADEMIAPP_PASSWORD set: public data only.")

    assignments = request("class_schedules?sw_component_child=1")[
        "Schedule_Professor_Subject"
    ]
    periods = request("university_periods")["university_periods"]

    spaces, availability, subjects, time_slots, day_slots, programs = ([],) * 6
    if token:
        spaces = request("spaces", token)["spaces"]
        availability = request("teacher_availabilities", token)[
            "Teacher_Availabilities"
        ]
        subjects = request("university_subjects", token)["university_subjects"]
        time_slots = request("time_slots", token)["Time_Slots"]
        day_slots = flatten_days_time_slots(
            request("days_time_slots", token)["Days_Time_Slots"]
        )

    # Programs are not exposed as their own list; derive them from the schedule.
    programs = list(
        {
            row["id_program"]: {
                "id_program": row["id_program"],
                "program_code": row["program_code"],
                "program_full_name": row["program_full_name"],
            }
            for row in assignments
        }.values()
    )

    labels = build_labels(assignments, availability)

    names = [
        {
            "id_teacher": labels[row["id_teacher"]],
            "source_id": row["id_teacher"],
            "name": " ".join(
                filter(
                    None,
                    (
                        row.get("first_name"),
                        row.get("middle_name"),
                        row.get("last_name"),
                        row.get("second_last_name"),
                    ),
                )
            ),
        }
        for row in {r["id_teacher"]: r for r in assignments + availability}.values()
    ]

    for out in args.out:
        directory = Path(out)
        directory.mkdir(parents=True, exist_ok=True)
        print(f"\n{directory}")
        write_csv(directory / "assignments.csv", deidentify(assignments, labels))
        write_csv(directory / "spaces.csv", spaces)
        write_csv(directory / "teacher-availability.csv", deidentify(availability, labels))
        write_csv(directory / "subjects.csv", subjects)
        write_csv(directory / "time-slots.csv", time_slots)
        write_csv(directory / "days-time-slots.csv", day_slots)
        write_csv(directory / "periods.csv", periods)
        write_csv(directory / "programs.csv", programs)
        write_csv(directory / "teacher-names.private.csv", names)


if __name__ == "__main__":
    main()
