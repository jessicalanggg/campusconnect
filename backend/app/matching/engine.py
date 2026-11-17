"""Study-group formation as a constrained assignment problem.

Given students who each have a weekly availability grid, a study goal, a pace and a preferred group size,
partition them into groups of size [min_size, max_size] so that every group shares enough common free time
to actually meet, and total match quality is maximised.

Three solvers share one scoring function so their results are directly comparable:

* ``greedy``       – hardest-to-place first, best-fit insertion. The baseline.
* ``local_search`` – starts from greedy and applies improving move/swap steps until a local optimum.
* ``ilp``          – set-partitioning integer program over a generated pool of candidate groups, solved with
                     OR-Tools CP-SAT. The pool always contains the greedy and local-search groups and the solver is
                     hinted with the local-search solution, so the ILP is never worse than either baseline.

Group quality uses the *true* group-level schedule intersection (the hours when every member is free), which a
pairwise model can't express. That's why the ILP selects whole groups rather than pairwise assignments.
"""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations

# Weekly grid: 7 days x 14 one-hour slots (08:00–22:00). Slot index = day * 14 + (hour - 8).
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
FIRST_HOUR = 8
HOURS_PER_DAY = 14
NUM_SLOTS = len(DAYS) * HOURS_PER_DAY
GOALS = ("exam_prep", "homework", "concepts", "projects")


@dataclass(frozen=True)
class Student:
    id: int
    slots: frozenset[int]
    goal: str
    pace: int  # 1 = slow & thorough, 2 = steady, 3 = fast
    preferred_size: int


@dataclass(frozen=True)
class MatchConfig:
    min_size: int = 3
    max_size: int = 6
    min_common_slots: int = 2  # a group is infeasible if members share fewer free hours than this per week
    target_common_slots: int = 4  # overlap score saturates here; more shared hours don't add value
    size_tolerance: int = 2  # being this many people off your preferred size scores 0 on the size term
    w_overlap: float = 0.40
    w_goal: float = 0.25
    w_pace: float = 0.15
    w_size: float = 0.20
    neighbours: int = 12  # candidate generation: compatible partners considered per student
    beam_width: int = 4
    local_search_seconds: float = 2.0
    ilp_seconds: float = 5.0


@dataclass(frozen=True)
class GroupScore:
    quality: float  # 0..1
    common: frozenset[int]
    overlap: float
    goal: float
    pace: float
    size: float


@dataclass
class Solution:
    algorithm: str
    groups: list[tuple[int, ...]]  # student ids
    unassigned: list[int]
    runtime_ms: int = 0
    stats: dict = field(default_factory=dict)


def score_group(members: list[Student] | tuple[Student, ...], cfg: MatchConfig,
                ignore_size: bool = False) -> GroupScore | None:
    """Quality of a group in [0, 1], or None if the group is infeasible (too small/large or can't meet)."""
    n = len(members)
    if n == 0 or n > cfg.max_size or (not ignore_size and n < cfg.min_size):
        return None
    common = frozenset.intersection(*(m.slots for m in members))
    if len(common) < cfg.min_common_slots:
        return None
    overlap = min(len(common), cfg.target_common_slots) / cfg.target_common_slots
    goal = Counter(m.goal for m in members).most_common(1)[0][1] / n
    paces = [m.pace for m in members]
    pace = 1 - (max(paces) - min(paces)) / 2
    size = 1.0 if ignore_size else sum(1 - min(1, abs(n - m.preferred_size) / cfg.size_tolerance)
                                       for m in members) / n
    if ignore_size:
        quality = (cfg.w_overlap * overlap + cfg.w_goal * goal + cfg.w_pace * pace) / (1 - cfg.w_size)
    else:
        quality = cfg.w_overlap * overlap + cfg.w_goal * goal + cfg.w_pace * pace + cfg.w_size * size
    return GroupScore(quality, common, overlap, goal, pace, size)


def group_value(members, cfg: MatchConfig) -> float:
    """Contribution of a group to the objective: per-student quality summed over members (0 if infeasible)."""
    s = score_group(members, cfg)
    return len(members) * s.quality if s else 0.0


def evaluate(solution: Solution, students: dict[int, Student], cfg: MatchConfig) -> dict:
    """Metrics used to compare algorithms. Quality and overlap are averaged per assigned student."""
    assigned = qsum = hours = 0
    for g in solution.groups:
        s = score_group([students[i] for i in g], cfg)
        assert s is not None, f"{solution.algorithm} produced an infeasible group {g}"
        assigned += len(g)
        qsum += len(g) * s.quality
        hours += len(g) * len(s.common)
    total = len(students)
    return {
        "students": total,
        "assigned": assigned,
        "coverage": assigned / total if total else 0.0,
        "groups": len(solution.groups),
        "avg_quality": qsum / assigned if assigned else 0.0,
        "avg_common_hours": hours / assigned if assigned else 0.0,
        "objective": qsum,
        "runtime_ms": solution.runtime_ms,
    }


# --------------------------------------------------------------------------------------------- greedy baseline

def greedy(students: list[Student], cfg: MatchConfig) -> Solution:
    """Most-constrained-first, best-fit insertion; dissolves undersized groups at the end."""
    start = time.perf_counter()
    order = sorted(students, key=lambda s: (len(s.slots), s.id))
    groups: list[list[Student]] = []
    for s in order:
        best, best_gain = None, None
        for g in groups:
            # Don't grow a group past what the newcomer or the group's members asked for.
            if len(g) >= min(cfg.max_size, max(s.preferred_size, cfg.min_size),
                             max(max(m.preferred_size for m in g), cfg.min_size)):
                continue
            new = score_group(g + [s], cfg, ignore_size=len(g) + 1 < cfg.min_size)
            if new is None:
                continue
            old = score_group(g, cfg, ignore_size=len(g) < cfg.min_size)
            gain = (len(g) + 1) * new.quality - len(g) * (old.quality if old else 0)
            if best_gain is None or gain > best_gain:
                best, best_gain = g, gain
        if best is not None:
            best.append(s)
        else:
            groups.append([s])
    # Repair: undersized groups are dissolved; their members try to join any group with room.
    final = [g for g in groups if len(g) >= cfg.min_size]
    leftovers = [s for g in groups if len(g) < cfg.min_size for s in g]
    unassigned = []
    for s in leftovers:
        target = _best_insertion(s, final, cfg)
        if target is None:
            unassigned.append(s.id)
        else:
            target.append(s)
    return Solution("greedy", [tuple(sorted(m.id for m in g)) for g in final], sorted(unassigned),
                    int((time.perf_counter() - start) * 1000))


def _best_insertion(s: Student, groups: list[list[Student]], cfg: MatchConfig):
    best, best_gain = None, None
    for g in groups:
        if len(g) >= cfg.max_size:
            continue
        gain = group_value(g + [s], cfg) - group_value(g, cfg)
        if score_group(g + [s], cfg) and (best_gain is None or gain > best_gain):
            best, best_gain = g, gain
    return best


# ------------------------------------------------------------------------------------------------ local search

def local_search(students: list[Student], cfg: MatchConfig, start: Solution | None = None) -> Solution:
    """Hill-climb over move / swap / insert-unassigned neighbourhoods. Coverage is prioritised over quality."""
    t0 = time.perf_counter()
    by_id = {s.id: s for s in students}
    start = start or greedy(students, cfg)
    groups = [[by_id[i] for i in g] for g in start.groups]
    pool = [by_id[i] for i in start.unassigned]
    deadline = t0 + cfg.local_search_seconds
    values = [group_value(g, cfg) for g in groups]
    improved = True
    while improved and time.perf_counter() < deadline:
        improved = False
        # 1) place unassigned students (coverage first)
        for s in list(pool):
            target = _best_insertion(s, groups, cfg)
            if target is not None:
                k = groups.index(target)
                target.append(s)
                values[k] = group_value(target, cfg)
                pool.remove(s)
                improved = True
        # 2) pair up unassigned students into new groups
        for a, b in combinations(list(pool), 2):
            if a in pool and b in pool and score_group([a, b], cfg):
                groups.append([a, b])
                values.append(group_value([a, b], cfg))
                pool.remove(a)
                pool.remove(b)
                improved = True
        # 3) move one student between groups
        for i, gi in enumerate(groups):
            for s in list(gi):
                if len(gi) <= cfg.min_size:
                    break
                rest = [m for m in gi if m is not s]
                v_rest = group_value(rest, cfg)
                if v_rest == 0:
                    continue
                for j, gj in enumerate(groups):
                    if i == j or len(gj) >= cfg.max_size:
                        continue
                    v_new = group_value(gj + [s], cfg)
                    if v_new and v_rest + v_new > values[i] + values[j] + 1e-9:
                        gi.remove(s)
                        gj.append(s)
                        values[i], values[j] = v_rest, v_new
                        improved = True
                        break
                if time.perf_counter() > deadline:
                    break
        # 4) swap two students between groups
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                gi, gj = groups[i], groups[j]
                done = False
                for a in gi:
                    for b in gj:
                        ni = [m for m in gi if m is not a] + [b]
                        nj = [m for m in gj if m is not b] + [a]
                        vi, vj = group_value(ni, cfg), group_value(nj, cfg)
                        if vi and vj and vi + vj > values[i] + values[j] + 1e-9:
                            groups[i], groups[j], values[i], values[j] = ni, nj, vi, vj
                            improved = done = True
                            break
                    if done:
                        break
            if time.perf_counter() > deadline:
                break
    return Solution("local_search", [tuple(sorted(m.id for m in g)) for g in groups if g],
                    sorted(s.id for s in pool), int((time.perf_counter() - t0) * 1000))


# --------------------------------------------------------------------------------------------------------- ILP

def candidate_groups(students: list[Student], cfg: MatchConfig, seeds: list[Solution]) -> set[tuple[int, ...]]:
    """Generate feasible candidate groups: beam search from each student over compatible partners, plus seeds."""
    by_id = {s.id: s for s in students}
    neighbours: dict[int, list[int]] = {}
    for s in students:
        scored = []
        for t in students:
            if t.id != s.id:
                pair = score_group([s, t], cfg, ignore_size=True)
                if pair:
                    scored.append((pair.quality, t.id))
        scored.sort(reverse=True)
        neighbours[s.id] = [tid for _, tid in scored[:cfg.neighbours]]

    pool: set[tuple[int, ...]] = set()
    for seed in seeds:
        pool.update(seed.groups)
    for s in students:
        beam = [(s.id,)]
        for size in range(2, cfg.max_size + 1):
            expansions: dict[tuple[int, ...], float] = {}
            for g in beam:
                cands = {n for m in g for n in neighbours[m]} - set(g)
                for c in cands:
                    key = tuple(sorted(g + (c,)))
                    if key in expansions:
                        continue
                    sc = score_group([by_id[i] for i in key], cfg, ignore_size=size < cfg.min_size)
                    if sc:
                        expansions[key] = sc.quality
            if not expansions:
                break
            beam = [g for g, _ in sorted(expansions.items(), key=lambda kv: -kv[1])[:cfg.beam_width]]
            if size >= cfg.min_size:
                pool.update(beam)
    return {g for g in pool if score_group([by_id[i] for i in g], cfg)}


def ilp(students: list[Student], cfg: MatchConfig, seeds: list[Solution] | None = None) -> Solution:
    """Set-partitioning ILP: choose disjoint candidate groups maximising (coverage, then total quality)."""
    from ortools.sat.python import cp_model

    t0 = time.perf_counter()
    if seeds is None:
        g = greedy(students, cfg)
        seeds = [g, local_search(students, cfg, g)]
    by_id = {s.id: s for s in students}
    cands = sorted(candidate_groups(students, cfg, seeds))
    if not cands:
        return Solution("ilp", [], sorted(by_id), int((time.perf_counter() - t0) * 1000), {"candidates": 0})

    model = cp_model.CpModel()
    x = [model.NewBoolVar(f"g{k}") for k in range(len(cands))]
    covering: dict[int, list] = {i: [] for i in by_id}
    for k, g in enumerate(cands):
        for i in g:
            covering[i].append(x[k])
    for vars_ in covering.values():
        if vars_:
            model.AddAtMostOne(vars_)
    # Lexicographic objective: each covered student is worth more than any possible quality gain elsewhere.
    scale = 1000
    big = (len(students) + 1) * scale
    coeffs = [len(g) * big + round(group_value([by_id[i] for i in g], cfg) * scale) for g in cands]
    model.Maximize(sum(c * v for c, v in zip(coeffs, x)))
    best_seed = max(seeds, key=lambda s: (sum(map(len, s.groups)),
                                          sum(group_value([by_id[i] for i in g], cfg) for g in s.groups)))
    chosen = set(best_seed.groups)
    for k, g in enumerate(cands):
        model.AddHint(x[k], g in chosen)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = cfg.ilp_seconds
    solver.parameters.num_workers = 8
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        fallback = best_seed
        return Solution("ilp", fallback.groups, fallback.unassigned, int((time.perf_counter() - t0) * 1000),
                        {"candidates": len(cands), "status": solver.StatusName(status)})
    groups = [g for k, g in enumerate(cands) if solver.Value(x[k])]
    covered = {i for g in groups for i in g}
    return Solution("ilp", groups, sorted(set(by_id) - covered), int((time.perf_counter() - t0) * 1000),
                    {"candidates": len(cands), "status": solver.StatusName(status)})


def solve_all(students: list[Student], cfg: MatchConfig | None = None) -> dict[str, tuple[Solution, dict]]:
    """Run greedy, local search and ILP on the same pool; return each solution with its evaluation."""
    cfg = cfg or MatchConfig()
    by_id = {s.id: s for s in students}
    g = greedy(students, cfg)
    ls = local_search(students, cfg, g)
    opt = ilp(students, cfg, [g, ls])
    return {sol.algorithm: (sol, evaluate(sol, by_id, cfg)) for sol in (g, ls, opt)}


def best_insertion_for(student: Student, groups: dict[int, list[Student]], cfg: MatchConfig,
                       min_quality: float = 0.5) -> int | None:
    """Pick an existing group (by key) with room that the student fits best, used for instant fills."""
    best, best_gain = None, None
    for key, members in groups.items():
        if len(members) >= cfg.max_size:
            continue
        new = score_group(members + [student], cfg)
        if not new or new.quality < min_quality:
            continue
        gain = group_value(members + [student], cfg) - group_value(members, cfg)
        if best_gain is None or gain > best_gain:
            best, best_gain = key, gain
    return best


def describe_slots(slots) -> str:
    """Human-readable weekly windows, e.g. 'Mon 18:00–20:00, Wed 19:00–20:00'."""
    out = []
    for day in range(len(DAYS)):
        hours = sorted(s % HOURS_PER_DAY for s in slots if s // HOURS_PER_DAY == day)
        run_start = prev = None
        for h in hours + [None]:
            if h is not None and prev is not None and h == prev + 1:
                prev = h
                continue
            if run_start is not None:
                out.append(f"{DAYS[day]} {FIRST_HOUR + run_start:02d}:00–{FIRST_HOUR + prev + 1:02d}:00")
            run_start = prev = h
    return ", ".join(out)
