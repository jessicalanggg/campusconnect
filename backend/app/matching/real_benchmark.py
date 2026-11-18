"""Benchmark the matchers on REAL request pools (anonymized), to back "on real data" claims.

    # 1) Export anonymized pools from the production database (no names, emails, ids or timestamps):
    python -m app.matching.real_benchmark --export-anonymized ../docs/results/pools-2026-03.json
    # 2) Run greedy vs local search vs ILP on them (works offline from the exported file):
    python -m app.matching.real_benchmark --from-file ../docs/results/pools-2026-03.json --out ../docs/results/benchmark-real.md

A pool is every request submitted for one course in one exam cycle, i.e. the students who could have been
matched with each other. Exported pools keep only what the matcher sees: weekly free hours, goal, pace and
preferred group size, in shuffled order.
"""
import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select

from app.matching.engine import MatchConfig, Student, solve_all

MIN_POOL = 3


def export_pools(seed: int = 0) -> list[dict]:
    from app.db.session import SessionLocal
    from app.models.entities import Course, Exam, MatchRequest

    with SessionLocal() as db:
        rows = db.execute(select(MatchRequest, Course.code, Exam.name)
                          .join(Course, MatchRequest.course_id == Course.id)
                          .outerjoin(Exam, MatchRequest.exam_id == Exam.id)).all()
    pools: dict[tuple, list] = defaultdict(list)
    for req, code, exam in rows:
        pools[(code, exam or "no exam window")].append({
            "slots": sorted(req.availability), "goal": req.goal, "pace": req.pace,
            "preferred_size": req.preferred_size})
    rng = random.Random(seed)
    out = []
    for (code, exam), students in sorted(pools.items()):
        rng.shuffle(students)
        out.append({"pool": f"{code} · {exam}", "students": students})
    return out


def run(pools: list[dict], cfg: MatchConfig | None = None) -> str:
    cfg = cfg or MatchConfig()
    lines = ["| Pool | Students | Algorithm | Placed | Avg quality | Shared hrs/week |", "|---|---:|---|---:|---:|---:|"]
    totals: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for pool in pools:
        students = [Student(i, frozenset(s["slots"]), s["goal"], s["pace"], s["preferred_size"])
                    for i, s in enumerate(pool["students"])]
        if len(students) < MIN_POOL:
            continue
        for name, (_, ev) in solve_all(students, cfg).items():
            totals[name].append((len(students), ev))
            lines.append(f"| {pool['pool']} | {len(students)} | {name} | {ev['coverage']:.1%} | "
                         f"{ev['avg_quality']:.3f} | {ev['avg_common_hours']:.2f} |")
    if not totals:
        return "No pools with at least 3 students yet."

    def weighted(name, key):
        rows = totals[name]
        return sum(n * ev[key] for n, ev in rows) / sum(n for n, _ in rows)

    gq, iq = weighted("greedy", "avg_quality"), weighted("ilp", "avg_quality")
    gh, ih = weighted("greedy", "avg_common_hours"), weighted("ilp", "avg_common_hours")
    gc, ic = weighted("greedy", "coverage"), weighted("ilp", "coverage")
    n = sum(n for n, _ in totals["ilp"])
    summary = [
        "", f"Across {len(totals['ilp'])} real pools ({n} requests), weighted by pool size:", "",
        f"- Students placed: greedy {gc:.1%} → ILP {ic:.1%}",
        f"- Match quality: greedy {gq:.3f} → ILP {iq:.3f} ({100 * (iq - gq) / gq:+.1f}%)" if gq else "",
        f"- Shared free hours/week: greedy {gh:.2f} → ILP {ih:.2f} ({100 * (ih - gh) / gh:+.1f}%)" if gh else "",
    ]
    return "\n".join(lines + summary)


def main():
    parser = argparse.ArgumentParser()
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--export-anonymized", metavar="FILE", help="write anonymized pools from the database")
    src.add_argument("--from-db", action="store_true", help="benchmark directly on the database")
    src.add_argument("--from-file", metavar="FILE", help="benchmark an exported anonymized file")
    parser.add_argument("--out", help="write the markdown report here")
    args = parser.parse_args()
    if args.export_anonymized:
        pools = export_pools()
        Path(args.export_anonymized).parent.mkdir(parents=True, exist_ok=True)
        Path(args.export_anonymized).write_text(json.dumps(pools, indent=1) + "\n")
        print(f"Exported {len(pools)} pools, {sum(len(p['students']) for p in pools)} requests")
        return
    pools = export_pools() if args.from_db else json.loads(Path(args.from_file).read_text())
    report = "# Matching benchmark on real requests\n\n" + run(pools) + "\n"
    if args.out:
        Path(args.out).write_text(report)
    print(report)


if __name__ == "__main__":
    main()
