"""Reproducible evaluation suite for the matchers.

    python -m app.matching.evaluate --out-md ../docs/benchmark.md --out-json ../docs/benchmark_results.json
    python -m app.matching.evaluate --quick        # a few seconds; used by the tests

Every trial is paired: greedy, local search and the ILP (and each ILP ablation) run on the SAME generated student
population, so differences come from the algorithms rather than from luck in the sample. Populations are synthetic
(app/matching/synthetic.py), seeded and therefore reproducible. CP-SAT is multi-threaded, so ILP results can vary
very slightly between runs; wall-clock runtimes depend on the machine.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import sys
import time
from dataclasses import replace

from app.matching.baselines import BASELINES
from app.matching.engine import MatchConfig, Student, evaluate, greedy, ilp, ilp_auto, local_search
from app.matching.synthetic import generate

FULL = {
    "main": {"profile": "baseline", "sizes": {30: 100, 100: 100, 250: 100, 500: 50}},
    "profiles": {"size": 250, "seeds": 50, "names": ["sparse", "concentrated", "diverse"]},
    "ablations": {"size": 250, "seeds": 50},
    "scaling": {"sizes": {1000: 5, 2000: 3}},
}
QUICK = {
    "main": {"profile": "baseline", "sizes": {30: 3, 60: 3}},
    "profiles": {"size": 60, "seeds": 2, "names": ["sparse", "concentrated", "diverse"]},
    "ablations": {"size": 60, "seeds": 2},
    "scaling": {"sizes": {320: 1}},
}
ABLATIONS = {
    "ilp": ({}, {}),
    "no_warm_start": ({"use_hint": False}, {}),
    "no_baseline_groups_in_pool": ({"seed_pool": False}, {}),
    "previous_candidate_pool_12_4": ({}, {"neighbours": 12, "beam_width": 4}),
    "small_candidate_pool_6_2": ({}, {"neighbours": 6, "beam_width": 2}),
    "extra_large_candidate_pool_30_8": ({}, {"neighbours": 30, "beam_width": 8}),
}
BASELINE_MAX_N = 500  # the clustering baseline's distance matrix grows with n^2
STRATEGIES = ["random", "first_come", "clustering", "greedy", "local_search", "ilp"]
# Two-sided 95% t critical values by degrees of freedom (nearest lower df is used).
T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 9: 2.26, 19: 2.09, 29: 2.05, 49: 2.01, 99: 1.98, 1000: 1.96}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def metrics(ev: dict) -> dict:
    return {"coverage": ev["coverage"], "quality": ev["avg_quality"], "hours": ev["avg_common_hours"],
            "runtime_ms": ev["runtime_ms"], "assigned": ev["assigned"]}


def trial(n: int, seed: int, profile: str, cfg: MatchConfig, ablations: bool = False,
          students: list[Student] | None = None) -> dict:
    students = students if students is not None else generate(n, seed, profile)
    by_id = {s.id: s for s in students}
    g = greedy(students, cfg)
    ls = local_search(students, cfg, g)
    out = {"n": n, "seed": seed, "profile": profile,
           "greedy": metrics(evaluate(g, by_id, cfg)), "local_search": metrics(evaluate(ls, by_id, cfg))}
    if n <= BASELINE_MAX_N:
        for name, fn in BASELINES.items():
            out[name] = metrics(evaluate(fn(students, cfg, seed=seed), by_id, cfg))

    def run_ilp(sol, vcfg):
        return {**metrics(evaluate(sol, by_id, vcfg)), "status": sol.stats.get("status"),
                "quality_gap_pct": sol.stats.get("quality_gap_pct"), "candidates": sol.stats.get("candidates"),
                "decomposed": sol.stats.get("decomposed")}

    # "ilp" is exactly what production runs: one ILP, or decomposition for very large classes.
    out["ilp"] = run_ilp(ilp_auto(students, cfg, [g, ls]), cfg)
    if n > cfg.decompose_above:
        out["single_ilp"] = run_ilp(ilp(students, cfg, [g, ls]), cfg)
    if ablations:
        for name, (kwargs, cfg_changes) in ABLATIONS.items():
            if name == "ilp":
                continue
            vcfg = replace(cfg, **cfg_changes)
            out[name] = run_ilp(ilp(students, vcfg, [g, ls], **kwargs), vcfg)
    return out


# ------------------------------------------------------------------------------------------------ statistics

def summarize(values: list[float]) -> dict:
    n = len(values)
    mean = statistics.fmean(values) if values else float("nan")
    sd = statistics.stdev(values) if n > 1 else 0.0
    t = T95[max(k for k in T95 if k <= max(1, n - 1))] if n > 1 else float("nan")
    half = t * sd / math.sqrt(n) if n > 1 else float("nan")
    return {"n": n, "mean": mean, "sd": sd, "ci95": [mean - half, mean + half] if n > 1 else None}


def pct(values: list[float], q: float) -> float:
    xs = sorted(values)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def paired(trials: list[dict], a: str = "greedy", b: str = "ilp") -> dict:
    """ILP vs greedy on the same populations: relative quality/hours gains and placement difference."""
    rel_q = [100 * (t[b]["quality"] / t[a]["quality"] - 1) for t in trials if t[a]["quality"] > 0]
    rel_h = [100 * (t[b]["hours"] / t[a]["hours"] - 1) for t in trials if t[a]["hours"] > 0]
    cov = [100 * (t[b]["coverage"] - t[a]["coverage"]) for t in trials]
    wins = sum(1 for t in trials if t[b]["quality"] > t[a]["quality"] + 1e-12)
    never_worse = all((t[b]["assigned"], t[b]["quality"] * t[b]["assigned"]) >=
                      (t[a]["assigned"], t[a]["quality"] * t[a]["assigned"]) for t in trials)
    return {"quality_gain_pct": summarize(rel_q), "hours_gain_pct": summarize(rel_h),
            "placement_gain_pp": summarize(cov), "quality_win_rate": wins / len(trials) if trials else None,
            "never_worse_on_objective": never_worse}


def algo_summary(trials: list[dict], name: str) -> dict:
    rows = [t[name] for t in trials]
    out = {k: summarize([r[k] for r in rows]) for k in ("coverage", "quality", "hours")}
    rt = [r["runtime_ms"] for r in rows]
    out["runtime_ms"] = {"p50": pct(rt, 0.5), "p95": pct(rt, 0.95), "max": max(rt)}
    if "status" in rows[0]:
        out["optimal_share"] = sum(r["status"] == "OPTIMAL" for r in rows) / len(rows)
        gaps = [r["quality_gap_pct"] for r in rows if r["quality_gap_pct"] is not None]
        out["quality_gap_pct"] = {"median": pct(gaps, 0.5), "p95": pct(gaps, 0.95), "max": max(gaps)} if gaps else None
        cands = [r["candidates"] for r in rows if r.get("candidates") is not None]
        out["candidates"] = summarize(cands) if cands else None
    return out


# ---------------------------------------------------------------------------------------------------- runner

def run(plan: dict, cfg: MatchConfig | None = None) -> dict:
    cfg = cfg or MatchConfig()
    started = time.perf_counter()
    raw: dict[str, list[dict]] = {}

    def block(key: str, n: int, seeds: int, profile: str, ablations: bool = False):
        rows = []
        for seed in range(1, seeds + 1):
            rows.append(trial(n, seed, profile, cfg, ablations))
            if seed % 10 == 0 or seed == seeds:
                log(f"  {key}: {seed}/{seeds} trials ({time.perf_counter() - started:.0f}s elapsed)")
        raw[key] = rows
        return rows

    results: dict = {"main": {}, "profiles": {}, "ablations": {}, "scaling": {}}
    for n, seeds in plan["main"]["sizes"].items():
        log(f"main n={n}")
        rows = block(f"main_{n}", n, seeds, plan["main"]["profile"])
        results["main"][n] = {a: algo_summary(rows, a) for a in ("greedy", "local_search", "ilp")}
        results["main"][n]["paired"] = paired(rows)
    p = plan["profiles"]
    for name in p["names"]:
        log(f"profile {name}")
        rows = block(f"profile_{name}", p["size"], p["seeds"], name)
        results["profiles"][name] = {a: algo_summary(rows, a) for a in ("greedy", "local_search", "ilp")}
        results["profiles"][name]["paired"] = paired(rows)
    a = plan["ablations"]
    log("ablations")
    rows = block("ablations", a["size"], a["seeds"], "baseline", ablations=True)
    results["ablations"] = {name: {**algo_summary(rows, name), "paired_vs_greedy": paired(rows, "greedy", name)}
                            for name in ABLATIONS}
    for n, seeds in plan["scaling"]["sizes"].items():
        log(f"scaling n={n}")
        rows = block(f"scaling_{n}", n, seeds, "baseline")
        results["scaling"][n] = {a: algo_summary(rows, a) for a in ("greedy", "local_search", "ilp")}
        results["scaling"][n]["paired"] = paired(rows)

    for section in ("main", "scaling"):
        for n, r in results[section].items():
            rows = raw[f"{section}_{n}"]
            for extra in ("single_ilp", *BASELINES):
                if extra in rows[0]:
                    r[extra] = algo_summary(rows, extra)
    import ortools
    results["meta"] = {"plan": plan, "ilp_seconds": cfg.ilp_seconds, "local_search_seconds": cfg.local_search_seconds,
                       "neighbours": cfg.neighbours, "beam_width": cfg.beam_width,
                       "decompose_above": cfg.decompose_above, "subpool_size": cfg.subpool_size,
                       "ortools": ortools.__version__, "python": platform.python_version(),
                       "machine": f"{platform.system()} {platform.machine()}",
                       "elapsed_s": round(time.perf_counter() - started, 1)}
    results["raw"] = raw
    return results


# ---------------------------------------------------------------------------------------------------- report

def _ci(s: dict, fmt: str = "{:+.1f}", unit: str = "%") -> str:
    if not s["ci95"]:
        return fmt.format(s["mean"]) + unit
    lo, hi = s["ci95"]
    return f"{fmt.format(s['mean'])}{unit} (95% CI {fmt.format(lo)} to {fmt.format(hi)})"


def _ms(x: float) -> str:
    return f"{x / 1000:.1f}s" if x >= 1000 else f"{x:.0f}ms"


def strategies_section(res: dict, heading: str, key: str | None = None) -> list[str]:
    """Placement and quality for every strategy on the same trials, plus the ILP's paired gain over each."""
    if key is None:
        size = next((n for n in (250, 100) if n in res["main"]), next(iter(res["main"])))
        rows, label = res["raw"][f"main_{size}"], f"{size} students"
    else:
        rows, label = res["raw"][key], key
    if "first_come" not in rows[0]:
        return []
    L = ["", f"{heading} ({label}, {len(rows)} paired trials)", "",
         "| Strategy | Placed | Avg match quality | Shared hrs/week | ILP quality gain over it |", "|---|---:|---:|---:|---|"]
    for name in STRATEGIES:
        vals = [t[name] for t in rows]
        placed = statistics.fmean(v["coverage"] for v in vals)
        q = statistics.fmean(v["quality"] for v in vals)
        h = statistics.fmean(v["hours"] for v in vals)
        gain = "—" if name == "ilp" else (_ci(paired(rows, name, "ilp")["quality_gain_pct"])
                                           if placed >= 0.10 else "n/a (places almost no one)")
        L.append(f"| {name} | {100 * placed:.1f}% | {q:.3f} | {h:.2f} | {gain} |")
    L += ["", "- **random:** shuffle and cut into groups of 4",
          "- **first_come:** a sign-up sheet; join the first group with room that still has shared time",
          "- **clustering:** balanced k-means on free time into groups of about 4, with greedy repair",
          "- **greedy / local_search:** the baselines that seed the ILP"]
    return L


def report(res: dict) -> str:
    m = res["meta"]
    main_seeds = ", ".join(f"{s} at {n}" for n, s in m["plan"]["main"]["sizes"].items())
    L = [
        "# Matching benchmark",
        "",
        f"Generated by `python -m app.matching.evaluate` (OR-Tools {m['ortools']}, Python {m['python']}, "
        f"{m['machine']}; {m['elapsed_s'] / 60:.0f} minutes). Raw per-trial data: "
        "[`benchmark_results.json`](benchmark_results.json).",
        "",
        "**Method.**",
        "- Every trial is **paired**: greedy, local search and the ILP run on the same generated students, so the "
        "comparison isolates the algorithm.",
        f"- Populations are **synthetic and seeded** (`app/matching/synthetic.py`), with {main_seeds} trials.",
        "- Quality is per student in [0, 1]: 40% shared free time, 25% goal, 15% pace, 20% size preference.",
        "- Placed = share of students put in a feasible group (3–6 people, at least 2 shared free hours a week).",
        f"- Solver settings match production: ILP limit {m['ilp_seconds']:g}s (8 threads), local search "
        f"{m['local_search_seconds']:g}s, candidate pool {m['neighbours']} partners / beam {m['beam_width']}, and "
        f"decomposition above {m['decompose_above']} students.",
        "- Confidence intervals are 95% t-intervals on the per-trial paired differences.",
        "",
        "## ILP vs greedy by class size",
        "",
        "| Students | Trials | Match quality gain | Shared free time gain | Placement gain | ILP better quality |",
        "|---:|---:|---|---|---|---:|",
    ]
    for n, r in res["main"].items():
        p = r["paired"]
        L.append(f"| {n} | {p['quality_gain_pct']['n']} | {_ci(p['quality_gain_pct'])} | {_ci(p['hours_gain_pct'])} | "
                 f"{_ci(p['placement_gain_pp'], unit=' pp')} | {100 * p['quality_win_rate']:.0f}% of trials |")
    never = all(r["paired"]["never_worse_on_objective"] for r in res["main"].values())
    L += ["", f"The ILP was {'never' if never else 'sometimes'} worse than greedy on the objective it optimizes "
              "(students placed first, then total quality) in any trial.", "",
          "## Absolute results (mean ± standard deviation)", "",
          "| Students | Algorithm | Placed | Avg match quality | Shared hrs/week | Runtime p50 | Runtime p95 |",
          "|---:|---|---:|---:|---:|---:|---:|"]
    for n, r in res["main"].items():
        for a in ("greedy", "local_search", "ilp"):
            s = r[a]
            L.append(f"| {n} | {a} | {100 * s['coverage']['mean']:.1f}% ± {100 * s['coverage']['sd']:.1f} | "
                     f"{s['quality']['mean']:.3f} ± {s['quality']['sd']:.3f} | {s['hours']['mean']:.2f} ± "
                     f"{s['hours']['sd']:.2f} | {_ms(s['runtime_ms']['p50'])} | {_ms(s['runtime_ms']['p95'])} |")
    L += ["", "## Optimality", "",
          "CP-SAT reports a proven bound, so each run shows how much quality could still be gained **within its "
          "candidate pool**. That isn't the global optimum over every possible grouping, which is intractable at "
          "this size.", "",
          "| Students | Proven optimal (over pool) | Remaining quality gap: median | p95 | Candidate groups |",
          "|---:|---:|---:|---:|---:|"]
    for n, r in res["main"].items():
        s = r["ilp"]
        g = s["quality_gap_pct"]
        cands = f"{s['candidates']['mean']:.0f}" if s.get("candidates") else "per sub-pool"
        L.append(f"| {n} | {100 * s['optimal_share']:.0f}% of runs | {g['median']:.2f}% | {g['p95']:.2f}% | {cands} |"
                 if g else f"| {n} | {100 * s['optimal_share']:.0f}% | – | – | {cands} |")
    L += strategies_section(res, "## Against simpler strategies")
    big = [(n, r) for n, r in list(res["main"].items()) + list(res["scaling"].items()) if "single_ilp" in r]
    if big:
        L += ["", "## Large classes: decomposition", "",
              f"Above {m['decompose_above']} students, one ILP can't search its candidate pool within the time limit. "
              "Production splits the class into availability clusters of about "
              f"{m['subpool_size']} students, solves each, then places leftovers. If the result were ever worse than "
              "local search on the whole class, it would keep local search instead.", "",
              "| Students | Trials | Single ILP vs greedy | Decomposed vs greedy | Decomposed vs single ILP | "
              "Runtime p50 (single → decomposed) |", "|---:|---:|---|---|---|---:|"]
        for n, r in big:
            rows = res["raw"].get(f"main_{n}") or res["raw"].get(f"scaling_{n}")
            single, dec, vs = paired(rows, "greedy", "single_ilp"), paired(rows, "greedy", "ilp"), paired(rows, "single_ilp", "ilp")
            L.append(f"| {n} | {len(rows)} | {_ci(single['quality_gain_pct'])} | {_ci(dec['quality_gain_pct'])} | "
                     f"{_ci(vs['quality_gain_pct'])} | {_ms(r['single_ilp']['runtime_ms']['p50'])} → "
                     f"{_ms(r['ilp']['runtime_ms']['p50'])} |")
    size = m["plan"]["profiles"]["size"]
    L += ["", f"## Harder and easier populations ({size} students, {m['plan']['profiles']['seeds']} trials each)", "",
          "| Population | Greedy placed | ILP placed | Quality gain | Shared time gain |", "|---|---:|---:|---|---|"]
    rows = [("baseline", res["main"].get(size))] + list(res["profiles"].items())
    for name, r in rows:
        if not r:
            continue
        p = r["paired"]
        L.append(f"| {name} | {100 * r['greedy']['coverage']['mean']:.1f}% | {100 * r['ilp']['coverage']['mean']:.1f}% | "
                 f"{_ci(p['quality_gain_pct'])} | {_ci(p['hours_gain_pct'])} |")
    L += ["", "- **sparse:** busy students with fewer, shorter free blocks",
          "- **concentrated:** everyone free in the same evening window",
          "- **diverse:** goals, pace and size preferences spread evenly",
          "", f"## Ablations ({m['plan']['ablations']['size']} students, {m['plan']['ablations']['seeds']} paired trials)",
          "", "| ILP variant | Quality gain vs greedy | Placed | Runtime p50 | Proven optimal |", "|---|---|---:|---:|---:|"]
    for name, s in res["ablations"].items():
        L.append(f"| {name} | {_ci(s['paired_vs_greedy']['quality_gain_pct'])} | {100 * s['coverage']['mean']:.1f}% | "
                 f"{_ms(s['runtime_ms']['p50'])} | {100 * s['optimal_share']:.0f}% |")
    L += ["", "## Scaling (fewer trials; runtime-focused)", "",
          "| Students | Trials | Quality gain | Greedy runtime p50 | Local search p50 | ILP p50 (incl. candidates) |",
          "|---:|---:|---:|---:|---:|---:|"]
    for n, r in res["scaling"].items():
        p = r["paired"]  # production ILP (decomposed at these sizes) vs greedy
        L.append(f"| {n} | {p['quality_gain_pct']['n']} | {p['quality_gain_pct']['mean']:+.1f}% | "
                 f"{_ms(r['greedy']['runtime_ms']['p50'])} | {_ms(r['local_search']['runtime_ms']['p50'])} | "
                 f"{_ms(r['ilp']['runtime_ms']['p50'])} |")
    L += ["", "## Limitations", "",
          "- **Synthetic data.** These numbers compare algorithms under identical conditions. They are not usage "
          "results; `python -m app.matching.real_benchmark` reruns the comparison on anonymized real request pools.",
          "- **Pool-optimal, not globally optimal.** The ILP is optimal over generated candidate groups (always "
          "including the greedy and local-search groups), not over every possible grouping.",
          "- **Time-limited.** At larger sizes CP-SAT stops at its time limit; see the optimality table.",
          "- **Machine-dependent runtimes**; CP-SAT's multi-threaded search makes ILP results vary slightly between runs.",
          ""]
    return "\n".join(L)


# ------------------------------------------------------------------------------------------ Penn schedules

PENN = {"courses": ["CIS-1200", "MATH-1400", "ECON-0100", "PHYS-0150"], "size": 250, "seeds": 50}
PENN_QUICK = {"courses": ["CIS-1200"], "size": 40, "seeds": 2}


def run_penn(plan: dict, cfg: MatchConfig | None = None) -> dict:
    from app.matching import penn_schedules as ps
    cfg = cfg or MatchConfig()
    started = time.perf_counter()
    data = ps.load()
    results, raw = {}, {}
    for course in plan["courses"]:
        log(f"penn {course}")
        rows = []
        for seed in range(1, plan["seeds"] + 1):
            pool = ps.generate_course_pool(course, plan["size"], seed, data)
            rows.append(trial(plan["size"], seed, f"penn:{course}", cfg, students=pool))
            if seed % 10 == 0 or seed == plan["seeds"]:
                log(f"  {course}: {seed}/{plan['seeds']} trials ({time.perf_counter() - started:.0f}s elapsed)")
        raw[course] = rows
        results[course] = {a: algo_summary(rows, a) for a in ("greedy", "local_search", "ilp")}
        results[course]["paired"] = paired(rows)
    import ortools
    results_meta = {"plan": plan, "source": data["source"], "semester": data["semester"],
                    "fetched_at": data["fetched_at"], "courses_in_data": sorted(data["courses"]),
                    "ilp_seconds": cfg.ilp_seconds, "ortools": ortools.__version__,
                    "machine": f"{platform.system()} {platform.machine()}",
                    "elapsed_s": round(time.perf_counter() - started, 1)}
    return {"results": results, "meta": results_meta, "raw": raw}


def report_penn(res: dict) -> str:
    m = res["meta"]
    L = ["# Matching benchmark on real Penn class schedules", "",
         f"Generated by `python -m app.matching.evaluate --penn` ({m['elapsed_s'] / 60:.0f} minutes, OR-Tools "
         f"{m['ortools']}, {m['machine']}). Raw data: [`benchmark_penn_results.json`](benchmark_penn_results.json).", "",
         "**Students are simulated, but their class schedules are real:**",
         f"- **Source:** meeting times for every section of {len(m['courses_in_data'])} large Penn courses in "
         f"{m['semester']} (Fall 2026), from {m['source']}, fetched {m['fetched_at']}.",
         "- **Pools:** each pool is one course's matching pool. Every simulated student takes that course plus 3 others "
         "from the list.",
         "- **Sections:** each student registers for one section per activity (lecture, recitation, lab), weighted by "
         "section capacity and avoiding time conflicts.",
         "- **Free time (the modelling assumption):** of the hours they're not in class (08:00–22:00), each student "
         "marks 6–14 hours a week as free, in 1–3 hour blocks. Evenings are likelier than daytime, and weekends least "
         "likely.",
         "- **Preferences:** goal, pace and group size use the same mix as the main benchmark.",
         "- **Trials:** paired, so all three algorithms see the same students in every trial, and each course has its "
         "own seeds.",
         "", f"## Results ({m['plan']['size']}-student pools, {m['plan']['seeds']} paired trials per course)", "",
         "| Course | Greedy placed | ILP placed | Greedy quality | ILP quality | Match quality gain | "
         "Shared free time gain | ILP better |",
         "|---|---:|---:|---:|---:|---|---|---:|"]
    for course, r in res["results"].items():
        p = r["paired"]
        L.append(f"| {course.replace('-', ' ')} | {100 * r['greedy']['coverage']['mean']:.1f}% | "
                 f"{100 * r['ilp']['coverage']['mean']:.1f}% | {r['greedy']['quality']['mean']:.3f} | "
                 f"{r['ilp']['quality']['mean']:.3f} | {_ci(p['quality_gain_pct'])} | {_ci(p['hours_gain_pct'])} | "
                 f"{100 * p['quality_win_rate']:.0f}% of trials |")
    all_rows = [t for rows in res["raw"].values() for t in rows]
    pooled = paired(all_rows)
    strat = strategies_section({"raw": {"all": all_rows}, "main": {}}, "## Against simpler strategies", key="all")
    L += ["", f"**All courses pooled ({len(all_rows)} paired trials):** match quality {_ci(pooled['quality_gain_pct'])}, "
              f"shared free time {_ci(pooled['hours_gain_pct'])}, placement {_ci(pooled['placement_gain_pp'], unit=' pp')}.",
          *[line.replace("(all,", "(all courses,") for line in strat],
          "", "| Course | Shared hrs/week (greedy → ILP) | ILP runtime p50 / p95 | Proven optimal (over pool) |",
          "|---|---:|---:|---:|"]
    for course, r in res["results"].items():
        L.append(f"| {course.replace('-', ' ')} | {r['greedy']['hours']['mean']:.2f} → {r['ilp']['hours']['mean']:.2f} | "
                 f"{_ms(r['ilp']['runtime_ms']['p50'])} / {_ms(r['ilp']['runtime_ms']['p95'])} | "
                 f"{100 * r['ilp']['optimal_share']:.0f}% |")
    L += ["", "## Limitations", "",
          "- The class schedules are real, but the students and the free hours they mark are simulated. These are "
          "algorithm comparisons, not usage results.",
          "- Real course combinations aren't random: majors cluster. Each student here takes 3 random other courses "
          "from the list.",
          "- An hour counts as busy if any class meeting overlaps it, so a 10:15–11:14 class blocks two grid hours.",
          ""]
    return "\n".join(L)


def _int_keys(x):
    """JSON turns the integer class-size keys into strings; turn them back."""
    if isinstance(x, dict):
        return {int(k) if isinstance(k, str) and k.isdigit() else k: _int_keys(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_int_keys(v) for v in x]
    return x


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="tiny plan for smoke tests")
    parser.add_argument("--penn", action="store_true", help="benchmark on real Penn class schedules instead")
    parser.add_argument("--out-md")
    parser.add_argument("--out-json")
    parser.add_argument("--from-json", help="rebuild the report from a saved results file instead of rerunning")
    args = parser.parse_args()
    if args.from_json:
        with open(args.from_json) as f:
            res = _int_keys(json.load(f))
        text = report_penn(res) if args.penn else report(res)
    elif args.penn:
        res = run_penn(PENN_QUICK if args.quick else PENN)
        text = report_penn(res)
    else:
        res = run(QUICK if args.quick else FULL)
        text = report(res)
    if args.out_json and not args.from_json:
        with open(args.out_json, "w") as f:
            json.dump(res, f, indent=1, default=str)
    if args.out_md:
        with open(args.out_md, "w") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()
