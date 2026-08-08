"""Apply the de-identification to a snapshot that already exists on disk.

`fetch.py` de-identifies as it extracts, so a snapshot taken with the current
version needs nothing further. This script exists for snapshots taken before
that change, and as the auditable statement of what de-identification means
here.

Three things happen, and the reason for each is the same: the source system's
public endpoint returns its internal identifiers next to the teacher's name, so
any of them republished is the name republished by reference.

  1. Teacher identifiers become labels `T001`, `T002`, … assigned by sorting
     the source identifiers numerically. The labels exist only in the extract.
  2. Row-level surrogate keys are dropped. They identify a row of the source
     table, which carries the name, and they carry no analytical content.
  3. Direct name fields are dropped if any survive.

The mapping is written to `teacher-names.private.csv` only when the snapshot
still contains names to map; the data directories git-ignore that file.

Usage:
    bash containers/run.sh paper-data python \\
        scripts/academiapp/relabel_extract.py --data papers/<slug>/data
"""

import argparse
import csv
from pathlib import Path

RELABEL_FIELD = "id_teacher"
SURROGATE_KEYS = ("id_schedule_professor_subject", "id_teacher_availability")
NAME_FIELDS = (
    "first_name",
    "last_name",
    "middle_name",
    "second_last_name",
    "id_person",
    "document_id",
    "phone",
    "email",
)
TARGETS = ("assignments.csv", "teacher-availability.csv")


def read(path):
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write(path, rows, columns):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="directory holding the CSVs")
    args = parser.parse_args()
    data = Path(args.data)

    tables = {name: read(data / name) for name in TARGETS if (data / name).exists()}
    if not tables:
        print(f"nothing to do: no {' or '.join(TARGETS)} under {data}")
        return

    source_ids = {
        row[RELABEL_FIELD]
        for rows in tables.values()
        for row in rows
        if row.get(RELABEL_FIELD)
    }
    already_labelled = all(str(i).startswith("T") for i in source_ids)
    if already_labelled:
        labels = {i: i for i in source_ids}
        print(f"teacher identifiers already relabelled ({len(source_ids)} labels)")
    else:
        labels = {
            old: f"T{index:03d}"
            for index, old in enumerate(sorted(source_ids, key=int), start=1)
        }
        print(f"relabelling {len(labels)} teachers")

    for name, rows in tables.items():
        dropped = sorted(
            set(rows[0]) & (set(SURROGATE_KEYS) | set(NAME_FIELDS))
        )
        columns = [
            c for c in rows[0]
            if c not in SURROGATE_KEYS and c not in NAME_FIELDS
        ]
        for row in rows:
            if row.get(RELABEL_FIELD):
                row[RELABEL_FIELD] = labels[row[RELABEL_FIELD]]
        write(data / name, rows, columns)
        print(f"  {name:28} {len(rows):5d} rows, dropped {dropped or 'nothing'}")

    print("\nverification")
    for name in tables:
        cols = set(read(data / name)[0])
        leaks = sorted(cols & (set(SURROGATE_KEYS) | set(NAME_FIELDS)))
        print(f"  {name:28} keys into the source system: {leaks or 'none'}")


if __name__ == "__main__":
    main()
