"""Statistical analysis of eight semesters of classroom assignments.

Four questions, each with a test chosen for the data it has rather than for
familiarity:

  A. Is demand growing, and how fast? Eight periods is a short series, so the
     trend is read with a non-parametric Mann-Kendall test alongside ordinary
     least squares, and both are reported. Agreement between them is the
     evidence; a slope without the rank test would be over-claiming on n = 8.

  B. Is room pressure the reason rooms end up double-booked? Peak concurrent
     demand is compared against the room stock, and conflict counts are
     regressed on occupancy with a Poisson model, the natural family for
     counts.

  C. Does the problem keep the same shape as it grows? Intensity, shift, and
     program composition are compared across periods with chi-square tests of
     homogeneity and Cramér's V, so that instances from different semesters
     can be pooled, or not, on evidence.

  D. How dispersed is a cohort across the three sub-sites? This decides
     whether the model's free-room objective or a locality objective matches
     what the campus is doing.

Effect sizes and confidence intervals accompany every test. With eight
periods the power to detect anything but a strong trend is low, and the
report says so rather than reading non-significance as absence.

Usage:
    bash containers/run.sh paper-data python \\
        scripts/academiapp/analyze_assignments.py \\
        --data papers/timetabling-llm-individual/data \\
        --out papers/timetabling-llm-individual/data/statistics
"""

import argparse
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from make_instances import HOURS_PER_DAY, DAY_SHIFT_HOURS, hour_span, read_csv

TOTAL_HOURS = 6 * HOURS_PER_DAY


def mann_kendall(values):
    """Non-parametric monotone trend test, with Sen's slope as effect size."""
    n = len(values)
    s = sum(
        np.sign(values[j] - values[i]) for i, j in itertools.combinations(range(n), 2)
    )
    variance = n * (n - 1) * (2 * n + 5) / 18
    if s > 0:
        z = (s - 1) / np.sqrt(variance)
    elif s < 0:
        z = (s + 1) / np.sqrt(variance)
    else:
        z = 0.0
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    slopes = [
        (values[j] - values[i]) / (j - i) for i, j in itertools.combinations(range(n), 2)
    ]
    return {"S": int(s), "z": round(z, 3), "p": round(p, 4),
            "sen_slope": round(float(np.median(slopes)), 2)}


def ols_trend(values):
    """Least-squares slope with a 95% confidence interval."""
    x = np.arange(len(values), dtype=float)
    result = stats.linregress(x, values)
    half = result.stderr * stats.t.ppf(0.975, len(values) - 2)
    return {
        "slope": round(result.slope, 2),
        "ci95": [round(result.slope - half, 2), round(result.slope + half, 2)],
        "r2": round(result.rvalue ** 2, 3),
        "p": round(result.pvalue, 4),
    }


def gini(counts):
    """Concentration of teaching across rooms; 0 is perfectly even."""
    values = np.sort(np.asarray(counts, dtype=float))
    n = len(values)
    if n == 0 or values.sum() == 0:
        return 0.0
    index = np.arange(1, n + 1)
    return float((2 * (index * values).sum() - (n + 1) * values.sum()) / (n * values.sum()))


def cramers_v(table):
    chi2 = stats.chi2_contingency(table)[0]
    n = table.values.sum()
    return float(np.sqrt(chi2 / (n * (min(table.shape) - 1))))


def load(data):
    rows = read_csv(data / "assignments.csv")
    spaces = [
        s for s in read_csv(data / "spaces.csv")
        if s["sw_virtual"] in ("0", "False", "false")
    ]
    frame = pd.DataFrame(rows)
    frame["hours_list"] = [
        hour_span(r["day"], r["entry_time"], r["departure_time"]) for r in rows
    ]
    frame["n_hours"] = frame["hours_list"].str.len()
    frame["period"] = frame["id_university_period"].astype(int)
    frame["evening"] = frame["entry_time"].str.slice(0, 2).astype(int) >= 18
    frame["group_key"] = frame["id_university_subject"] + "-" + frame["group"]
    frame["cohort"] = frame["id_program"] + "-" + frame["semesters"]
    return frame, spaces


def section_a(frame, spaces, report):
    """Growth of demand across the eight periods."""
    periods = sorted(frame["period"].unique())
    series = {
        "course_groups": [frame[frame.period == p]["group_key"].nunique() for p in periods],
        "class_hours": [int(frame[frame.period == p]["n_hours"].sum()) for p in periods],
        "teachers": [frame[frame.period == p]["id_teacher"].nunique() for p in periods],
        "programs": [frame[frame.period == p]["id_program"].nunique() for p in periods],
        "rooms_used": [frame[frame.period == p]["id_space"].nunique() for p in periods],
    }
    room_hours = len(spaces) * TOTAL_HOURS
    series["occupancy_pct"] = [
        round(100 * h / room_hours, 2) for h in series["class_hours"]
    ]

    rows = []
    for name, values in series.items():
        mk = mann_kendall(values)
        ols = ols_trend(values)
        rows.append(
            {
                "metric": name,
                "first": values[0],
                "last": values[-1],
                "growth_pct": round(100 * (values[-1] / values[0] - 1), 1),
                "sen_slope_per_semester": mk["sen_slope"],
                "mk_p": mk["p"],
                "ols_slope": ols["slope"],
                "ols_ci95": ols["ci95"],
                "ols_r2": ols["r2"],
                "ols_p": ols["p"],
            }
        )
    report["A_growth"] = {"periods": periods, "series": series, "tests": rows}
    return pd.DataFrame(rows)


def section_b(frame, spaces, data, report):
    """Room pressure, concentration, and whether it explains the conflicts."""
    periods = sorted(frame["period"].unique())
    n_rooms = len(spaces)

    peaks, ginis, occupancy = [], [], []
    for period in periods:
        subset = frame[frame.period == period]
        concurrent = Counter()
        per_room = Counter()
        for _, row in subset.iterrows():
            for hour in row["hours_list"]:
                concurrent[hour] += 1
            per_room[row["id_space"]] += row["n_hours"]
        peaks.append(max(concurrent.values()) if concurrent else 0)
        counts = [per_room.get(s["id_space"], 0) for s in spaces]
        ginis.append(round(gini(counts), 3))
        occupancy.append(round(100 * subset["n_hours"].sum() / (n_rooms * TOTAL_HOURS), 2))

    conflicts = pd.read_csv(data / "instances" / "historical-conflicts.csv")
    conflicts = conflicts.sort_values("id_university_period")
    room_conflicts = conflicts["room_double_bookings"].tolist()

    # Poisson regression of room conflicts on occupancy. A count outcome with
    # eight observations: the coefficient is reported with its interval, and
    # the fit is not asked to carry more than a direction.
    import statsmodels.api as sm

    design = sm.add_constant(np.array(occupancy))
    model = sm.GLM(room_conflicts, design, family=sm.families.Poisson()).fit()
    coefficient = float(model.params[1])
    conf = model.conf_int()[1]

    spearman = stats.spearmanr(occupancy, room_conflicts)
    peak_ratio = [round(p / n_rooms, 3) for p in peaks]

    # The decisive check between the two readings of the conflicts. At each
    # hour where a room hosts two groups, count how many rooms sat empty. If
    # the campus had free rooms at that moment, capacity pressure is not the
    # explanation and the conflict is administrative.
    free_at_conflict, conflict_hours, saturated = [], 0, 0
    for period in periods:
        subset = frame[frame.period == period]
        per_hour = defaultdict(lambda: defaultdict(set))
        for _, row in subset.iterrows():
            for hour in row["hours_list"]:
                per_hour[hour][row["id_space"]].add(row["group_key"])
        for hour, rooms in per_hour.items():
            clashing = sum(1 for groups in rooms.values() if len(groups) > 1)
            if clashing:
                conflict_hours += 1
                free = n_rooms - len(rooms)
                free_at_conflict.append(free)
                if free == 0:
                    saturated += 1

    report["B_pressure"] = {
        "rooms": n_rooms,
        "peak_concurrent_classes": peaks,
        "peak_over_rooms": peak_ratio,
        "occupancy_pct": occupancy,
        "gini_room_usage": ginis,
        "room_conflicts": room_conflicts,
        "poisson_occupancy_coef": round(coefficient, 4),
        "poisson_ci95": [round(float(conf[0]), 4), round(float(conf[1]), 4)],
        "poisson_rate_ratio_per_point": round(float(np.exp(coefficient)), 3),
        "spearman_rho": round(float(spearman.statistic), 3),
        "spearman_p": round(float(spearman.pvalue), 4),
        "gini_trend": mann_kendall(ginis),
        "conflict_hours": conflict_hours,
        "free_rooms_at_conflict_mean": round(float(np.mean(free_at_conflict)), 2)
        if free_at_conflict else None,
        "free_rooms_at_conflict_median": float(np.median(free_at_conflict))
        if free_at_conflict else None,
        "pct_conflicts_with_zero_free_rooms": round(
            100 * saturated / conflict_hours, 1) if conflict_hours else None,
    }


def section_c(frame, report):
    """Does the problem keep its shape as it grows?"""
    groups = (
        frame.groupby(["period", "group_key"])
        .agg(hours=("n_hours", "sum"), evening=("evening", "any"),
             program=("id_program", "first"))
        .reset_index()
    )
    groups["intensity"] = groups["hours"].clip(1, DAY_SHIFT_HOURS)

    tests = {}
    for name, column in (("intensity", "intensity"), ("shift", "evening"),
                         ("program", "program")):
        table = pd.crosstab(groups["period"], groups[column])
        # Drop rare categories so the chi-square approximation holds: a
        # category needs at least five expected observations per period. A
        # binary variable is left alone, since dropping a level would leave
        # nothing to test.
        if table.shape[1] > 2:
            keep = [c for c in table.columns if table[c].sum() >= 5 * len(table)]
            if len(keep) >= 2:
                table = table.loc[:, keep]
        chi2, p, dof, expected = stats.chi2_contingency(table)
        tests[name] = {
            "chi2": round(float(chi2), 2),
            "dof": int(dof),
            "p": round(float(p), 4),
            "cramers_v": round(cramers_v(table), 3),
            "min_expected": round(float(expected.min()), 2),
            "categories": [str(c) for c in table.columns],
        }
    distribution = (
        pd.crosstab(groups["period"], groups["intensity"], normalize="index")
        .round(3)
        .to_dict("index")
    )
    report["C_shape"] = {"tests": tests, "intensity_share_by_period": distribution}


def section_d(frame, report):
    """How far a cohort's classes are spread over buildings and days."""
    per_cohort = defaultdict(lambda: {"buildings": set(), "days": set(), "hours": 0})
    for _, row in frame.iterrows():
        key = (row["period"], row["cohort"])
        per_cohort[key]["buildings"].add(row["id_building"])
        per_cohort[key]["days"].add(row["day"])
        per_cohort[key]["hours"] += row["n_hours"]

    buildings = [len(v["buildings"]) for v in per_cohort.values()]
    days = [len(v["days"]) for v in per_cohort.values()]
    share_multi = round(100 * sum(1 for b in buildings if b > 1) / len(buildings), 1)

    # Room changes within a single day for one cohort: the cost the model does
    # not represent.
    moves = []
    for (period, cohort), _ in per_cohort.items():
        subset = frame[(frame.period == period) & (frame.cohort == cohort)]
        for day in subset["day"].unique():
            rooms = subset[subset.day == day]["id_space"].nunique()
            moves.append(rooms)

    report["D_dispersion"] = {
        "cohorts": len(per_cohort),
        "buildings_per_cohort_mean": round(float(np.mean(buildings)), 2),
        "buildings_per_cohort_distribution": dict(Counter(buildings)),
        "pct_cohorts_in_more_than_one_building": share_multi,
        "teaching_days_per_cohort_mean": round(float(np.mean(days)), 2),
        "rooms_per_cohort_day_mean": round(float(np.mean(moves)), 2),
        "pct_cohort_days_in_more_than_one_room": round(
            100 * sum(1 for m in moves if m > 1) / len(moves), 1
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    data = Path(args.data)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    frame, spaces = load(data)
    report = {}

    growth = section_a(frame, spaces, report)
    section_b(frame, spaces, data, report)
    section_c(frame, report)
    section_d(frame, report)

    growth.to_csv(out / "growth-trends.csv", index=False)
    (out / "analysis.json").write_text(json.dumps(report, indent=1, default=str))

    print("A. Demand growth over eight periods")
    print(growth.to_string(index=False))
    b = report["B_pressure"]
    print(f"\nB. Room pressure ({b['rooms']} rooms)")
    print(f"   peak concurrent classes  {b['peak_concurrent_classes']}")
    print(f"   peak / rooms             {b['peak_over_rooms']}")
    print(f"   occupancy %              {[float(o) for o in b['occupancy_pct']]}")
    print(f"   Gini of room usage       {b['gini_room_usage']} "
          f"(trend p={b['gini_trend']['p']})")
    print(f"   room conflicts           {b['room_conflicts']}")
    print(f"   Poisson coef on occupancy {b['poisson_occupancy_coef']} "
          f"CI {b['poisson_ci95']}, rate ratio {b['poisson_rate_ratio_per_point']} per point")
    print(f"   Spearman rho             {b['spearman_rho']} (p={b['spearman_p']})")
    print(f"   hours with a room conflict {b['conflict_hours']}")
    print(f"   free rooms at those hours  mean {b['free_rooms_at_conflict_mean']}, "
          f"median {b['free_rooms_at_conflict_median']}")
    print(f"   conflicts with no free room {b['pct_conflicts_with_zero_free_rooms']}%")
    print("\nC. Stability of the problem shape across periods")
    for name, test in report["C_shape"]["tests"].items():
        print(f"   {name:10} chi2={test['chi2']:8.2f} dof={test['dof']:3d} "
              f"p={test['p']:.4f} V={test['cramers_v']:.3f} "
              f"min expected={test['min_expected']}")
    d = report["D_dispersion"]
    print(f"\nD. Cohort dispersion ({d['cohorts']} cohort-periods)")
    print(f"   buildings per cohort      mean {d['buildings_per_cohort_mean']} "
          f"{d['buildings_per_cohort_distribution']}")
    print(f"   cohorts in >1 building    {d['pct_cohorts_in_more_than_one_building']}%")
    print(f"   rooms per cohort-day      mean {d['rooms_per_cohort_day_mean']}")
    print(f"   cohort-days in >1 room    {d['pct_cohort_days_in_more_than_one_room']}%")
    print(f"\nwritten to {out}")


if __name__ == "__main__":
    main()
