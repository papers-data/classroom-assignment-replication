# Classroom Assignment: Replication Package

Data, instances, models, and scripts for *Classroom Assignment: A Two-Stage
Constraint Formulation*.

Everything needed to reproduce every table and figure in the paper is here.
Nothing in this package identifies a person.

## What is in it

```
data/         the institutional snapshot, as CSV
instances/    MiniZinc instances derived from it, plus the conflict audit
models/       the timetabling model and the three room-stage formulations
scripts/      the code that produced everything above
results/      statistics and solver timings reported in the paper
```

### `data/`

A snapshot of eight consecutive academic periods (2023-I to 2026-II) from the
scheduling system of the Tuluá campus of Universidad del Valle.

| File | Rows | Contents |
|---|--:|---|
| `assignments.csv` | 2 924 | one row per scheduled class block: day, entry and departure time, room, subject, group, weekly hours, program, teacher label, period |
| `spaces.csv` | 31 | bookable spaces with capacity, building, and a virtual-space flag |
| `teacher-availability.csv` | 6 035 | free slots per teacher label, day, band, and period, as recorded by the system. **Read the caveat below before using this file.** |
| `subjects.csv` | 1 061 | subject catalog: official code, weekly hours, credits, semester, program |
| `time-slots.csv` | 13 | the institutional time bands |
| `days-time-slots.csv` | 68 | valid day and band pairs |
| `periods.csv` | 10 | academic periods with their date ranges |
| `programs.csv` | 12 | academic programs |
| `hour-profile.csv` | 16 | mean class hours per hour of the day |
| `model-vs-practice.csv` | 8 | the manual schedules scored on the model's objectives |
| `search-space.csv` | 24 | search-space size against instance size |

**Teacher availability is not an independent declaration.** The source system
stores availability per teacher and period, and it is tempting to read those
records as what each teacher said they were free to do. The data does not
support that reading. Comparing the two tables:

- 98.0% of scheduled class hours fall inside the availability recorded for
  the same teacher and period;
- for 379 of 1 078 teacher-periods (35%) the availability recorded is
  *exactly* the set of hours that teacher ends up teaching, hour for hour;
- the median ratio of recorded availability to actual teaching load is 1.20,
  meaning the typical record grants a teacher 20% more free time than they
  use.

An independently declared availability would be far looser than the schedule
it constrains, and exact equality would be rare. These figures instead
indicate that the records are largely fitted to, or back-filled from, the
assignments rather than collected before them.

Two consequences for anyone using this data. Treating the file as a genuine
constraint makes an instance far tighter than the institution's real
flexibility, because the model is told each teacher is free almost exactly
when they teach; this is part of why the faithful instances in `instances/`
are unsatisfiable. And the residual 2.0% of class hours that fall outside the
recorded availability should not be read as teachers being scheduled against
their stated wishes, since the baseline is not a statement of wishes. The
`-availability` instance variants absorb that residue by construction.

Sixty-one teacher-periods carry availability with no assignments, so the
table is not a pure derivation; some records are independent of the schedule.

### Provenance, rights, and personal data

**The class schedules are public.** Universidad del Valle publishes the
schedule of every course group through its scheduling system, readable without
credentials. The room catalogue with capacities and the availability records
sit behind authentication; those were obtained with the institutional
credentials of one of the authors, who is a member of the teaching staff of
the campus concerned.

**The research is internal to the institution.** Both authors belong to the
Escuela de Ingeniería de Sistemas y Computación of Universidad del Valle,
Seccional Tuluá, and the study analyses the scheduling process of that same
campus. It is not third-party scraping of another institution's records.

**Rights in the underlying data belong to Universidad del Valle.** The
institution is the owner and the data controller. What this package releases
is a derived, anonymised extract, distributed under CC BY 4.0 so that the
analysis can be reproduced. That licence covers this extract; it does not
transfer any right over the institution's own records, and it does not
constitute a licence granted by the institution.

**De-identification, and the audit behind it.** Under Colombian Law 1581 of
2012 a personal datum is any information that can be associated with a
determined *or determinable* natural person, so the test is not whether a
name appears but whether a person can be singled out. We audited this package
against that test and it failed on the first pass; what follows is what the
audit found and what was changed.

*Direct identifiers.* The scheduling API returns each teacher's given and
family names alongside every assignment and availability record. Those fields
are dropped before anything is written to disk, and the name-to-label mapping
is never committed to version control.

*Keys into the source system.* Removing names is not sufficient. The public,
unauthenticated endpoint of the source system returns the internal teacher
identifier **next to the teacher's name**, so releasing that identifier
publishes the name by reference: a single request resolves it. The same holds
for the surrogate keys of the assignment and availability rows, which the same
endpoint also returns. All of these have been removed or replaced. Teachers
now carry labels `T001`–`T249`, assigned by sorting the source identifiers and
numbering them, which exist only in this package. The row-level surrogate keys
`id_schedule_professor_subject` and `id_teacher_availability` are dropped
entirely, as they served no analytical purpose. The MiniZinc instances were
already unaffected: they number teachers `1..n` internally.

*What remains re-identifiable, stated plainly.* A schedule is close to being
an identifier in itself. Anyone holding this package can take a row's day,
time, room, subject, and group, query the institution's public schedule page
for the same term, and recover the teacher's name. No transformation short of
destroying the analytical content prevents this, because the schedule *is* the
data. We therefore do not claim these files are anonymous in the strong sense.
Using the taxonomy of the Colombian institutional practice on the matter, what
we perform is suppression of direct identifiers plus pseudonymisation of the
remaining ones; the residual risk is that the underlying schedules were
already published by the institution itself, so the package reveals no
teaching assignment that was not public before it.

*Students.* No student-level data was collected. The system publishes none and
the study needs none.

**No personal datum of any individual has been estimated or inferred.** This
matters because one caveat in this file concerns estimation, and the two must
not be confused. Where we say the availability records appear fitted to the
assignments, the claim is about how the *institution's own records* relate to
each other. We did not reconstruct, impute, or infer any person's schedule,
preferences, workload, or availability. The only approximated quantities in
this package are the enrolment cap and required resource of a course group,
both properties of a course rather than of a person, and each is flagged in
the header of every instance file that uses it.

### `instances/`

MiniZinc data files for the two models, in the format they read.

- `p03` … `p10`: the eight real periods, faithful to the records.
- `p03-availability` … `p10-availability`: the same periods with each
  teacher's declared availability extended to cover the hours they actually
  teach. Both variants are provided because the faithful ones are
  unsatisfiable, which is one of the paper's findings.
- `syn0025` … `syn0400`: synthetic instances calibrated on the distributions
  of the real ones. Feasibility is guaranteed by construction.
- `syn0050-infeasible`, `syn0200-infeasible`: instances made unsatisfiable on
  purpose, with the cause named in the file header.
- `historical-conflicts.csv`: the audit of each real period against the
  model's hard constraints, described below.

Every `.dzn` carries a header stating how it was built and which quantities
are approximations.

### The conflict audit, and the scarcity test

These two are the measurement the accompanying article is built on, so they are
worth documenting rather than leaving to be read out of the code.

`instances/historical-conflicts.csv` carries one row per academic period and one
column per hard constraint the model declares:

| Column | Counts hours in which |
|---|---|
| `teacher_clashes` | one teacher is scheduled in two rooms at once |
| `room_double_bookings` | one room hosts two course groups at once |
| `program_semester_overlaps` | two courses of the same program and semester collide |
| `hours_outside_availability` | a class falls outside the availability recorded for its teacher |
| `teachers_without_availability` | a teacher has assignments but no availability record |

Counts are hour-level incidences, not distinct pairs: a two-hour clash counts
twice. All eight periods carry violations in at least three of the four
categories, which is the article's central observation.

The scarcity test asks whether those violations reflect a shortage of rooms, and
it is reported at three strengths because the answer depends on what counts as a
substitute. `analyze_assignments.py` computes all three:

| Free rooms counted as substitutes | Median free | Violations with none free |
|---|--:|--:|
| any idle room among the thirty | 14 | 0.0% |
| same resource kind | 7 | 14.5% |
| same resource kind and same sub-site | 3 | 22.8% |

The first is too generous. The thirty rooms fall into seven resource kinds and
five of those exist as a single room, so idle general classrooms are worth
nothing to a group that needs the physics laboratory. The third adds the
sub-site, since the three are physically separate and the campus reaches for the
farthest only when the others fill. Read at the strictest setting, scarcity
explains roughly one double-booking in four.

Capacity is deliberately absent from all three. The enrollment cap of a course
group is not recorded anywhere in the source, so any capacity filter would rest
on an estimate, and this package does not estimate. The 241 double-booked rooms
break down by resource kind as 184 general classrooms, 51 computer rooms, and
three each in the sports hall and the food laboratory; the last six are
singleton kinds, where no substitute can exist by construction.

### `models/`

- `Horarios.mzn`: the timetabling stage, from the original implementation.
- `Salones.mzn`, `SalonesCount.mzn`, `SalonesGC.mzn`: the three room-stage
  formulations. `SalonesCount` is the deployed one; the other two were
  recovered from commented code in the same source and differ only in how
  they forbid a group from occupying two rooms at once.

### `scripts/`

| Script | Produces |
|---|---|
| `fetch.py` | the CSV snapshot, from the scheduling API |
| `make_instances.py` | the real instances and the conflict audit |
| `make_synthetic.py` | the synthetic instances |
| `search_space.py` | `search-space.csv` |
| `analyze_assignments.py` | the statistics in `results/statistics/` |
| `compare_model_practice.py` | `model-vs-practice.csv` |
| `benchmark.sh` | timetabling-stage solver timings |
| `variant_study.sh` | room-stage formulation and solver timings |

## Upstream sources

The tool described in the article is split across two repositories, neither
of which is vendored here:

| Repository | Contents |
|---|---|
| [BackEndAsignacionSalones](https://github.com/JAlexanderVelasquez/BackEndAsignacionSalones) | Flask API and the MiniZinc models. The models in `models/` come from here. |
| [Asignacion-de-Salones](https://github.com/JAlexanderVelasquez/Asignacion-de-Salones) | React front end (branch `develop`, subdirectory `asignacion-salones/`): authentication, user administration, the two-file upload, and the help module that documents the input formats. |

Both are the work of Jhojan Alexander Velásquez Erazo and predate this
package.

## Reproducing

The Python scripts need `numpy`, `pandas`, `scipy`, and `statsmodels`. The
shell scripts need Docker and pull `minizinc/minizinc:latest`.

```bash
# instances from the snapshot already in data/
python scripts/make_instances.py --data data --out instances --period all
python scripts/make_synthetic.py --data data --out instances \
       --subjects 25 50 100 200 400

# statistics and derived tables
python scripts/analyze_assignments.py --data data --out results/statistics
python scripts/search_space.py --data data --out data/search-space.csv
python scripts/compare_model_practice.py --data data \
       --out data/model-vs-practice.csv

# solver runs
bash scripts/benchmark.sh instances models results/timings.csv syn0025 syn0050
bash scripts/variant_study.sh instances models results/variants.csv syn0025
```

Refreshing the snapshot from the API needs `ACADEMIAPP_USER` and
`ACADEMIAPP_PASSWORD` in the environment; class schedules are public but
rooms, capacities, and availability are not. The committed snapshot makes
that step unnecessary for reproduction.

Reported timings were measured on an AMD Ryzen 5 3600 (six cores, twelve
threads, 31 GB) with MiniZinc 2.10.0 in a container, one run per cell.

## Reuse

The instances are usable outside this paper. Three features distinguish them
from the standard educational timetabling benchmarks: a program is taught
wholly in the day or wholly in the evening, rooms sit in three physically
separate sub-sites, and how a course may be split across days depends on its
weekly intensity. Translating them into the curriculum-based course
timetabling format means discarding those rules, which is why they are
released in the models' own format.

## License

Code and scripts: MIT. Data and instances: CC BY 4.0.

## Citation

Cite the article. This package is archived on Zenodo under the DOI
[10.5281/zenodo.21852370](https://doi.org/10.5281/zenodo.21852370), which
always resolves to the most recent version.

Version 1.0.0 of that deposit is superseded and should not be used. It was cut
from a commit that predated the de-identification described above, and its two
largest tables still carry the source system's own teacher identifiers. Anyone
holding a copy should discard it and use the current version instead.
