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

from app.matching.engine import MatchConfig, evaluate, greedy, ilp, local_search
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
    "scaling": {"sizes": {120: 1}},
}
ABLATIONS = {
    "ilp": ({}, {}),
    "no_warm_start": ({"use_hint": False}, {}),
    "no_baseline_groups_in_pool": ({"seed_pool": False}, {}),
    "small_candidate_pool": ({}, {"neighbours": 6, "beam_width": 2}),
    "large_candidate_pool": ({}, {"neighbours": 20, "beam_width": 6}),
}
# Two-sided 95% t critical values by degrees of freedom (nearest lower df is used).
T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 9: 2.26, 19: 2.09, 29: 2.05, 49: 2.01, 99: 1.98, 1000: 1.96}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def metrics(ev: dict) -> dict:
    return {"coverage": ev["coverage"], "quality": ev["avg_quality"], "hours": ev["avg_common_hours"],
            "runtime_ms": ev["runtime_ms"], "assigned": ev["assigned"]}


def trial(n: int, seed: int, profile: str, cfg: MatchConfig, ablations: bool = False) -> dict:
    students = generate(n, seed, profile)
    by_id = {s.id: s for s in students}
    g = greedy(students, cfg)
    ls = local_search(students, cfg, g)
    out = {"n": n, "seed": seed, "profile": profile,
           "greedy": metrics(evaluate(g, by_id, cfg)), "local_search": metrics(evaluate(ls, by_id, cfg))}
    variants = ABLATIONS if ablations else {"ilp": ABLATIONS["ilp"]}
    for name, (kwargs, cfg_changes) in variants.items():
        vcfg = replace(cfg, **cfg_changes)
        sol = ilp(students, vcfg, [g, ls], **kwargs)
        out[name] = {**metrics(evaluate(sol, by_id, vcfg)), "status": sol.stats.get("status"),
                     "quality_gap_pct": sol.stats.get("quality_gap_pct"), "candidates": sol.stats.get("candidates")}
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
        out["candidates"] = summarize([r["candidates"] for r in rows])
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

    import ortools
    results["meta"] = {"plan": plan, "ilp_seconds": cfg.ilp_seconds, "local_search_seconds": cfg.local_search_seconds,
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
        f"{m['local_search_seconds']:g}s.",
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
        L.append(f"| {n} | {100 * s['optimal_share']:.0f}% of runs | {g['median']:.2f}% | {g['p95']:.2f}% | "
                 f"{s['candidates']['mean']:.0f} |" if g else f"| {n} | {100 * s['optimal_share']:.0f}% | – | – | – |")
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
        p = r["paired"]
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="tiny plan for smoke tests")
    parser.add_argument("--out-md")
    parser.add_argument("--out-json")
    args = parser.parse_args()
    res = run(QUICK if args.quick else FULL)
    text = report(res)
    if args.out_json:
        with open(args.out_json, "w") as f:
            json.dump(res, f, indent=1, default=str)
    if args.out_md:
        with open(args.out_md, "w") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()
