"""Simple grouping strategies the matcher is compared against (in addition to greedy and local search).

Every baseline returns only FEASIBLE groups (3-6 students who share at least 2 free hours a week). Students
whose group couldn't meet are left unassigned, as they would be in practice.
"""
from __future__ import annotations

import random
import time

from app.matching.engine import (MatchConfig, Solution, Student, _balanced_clusters, best_insertion_for, greedy,
                                 score_group)


def _finish(name: str, groups: list[list[Student]], students: list[Student], cfg: MatchConfig, t0: float) -> Solution:
    feasible = [g for g in groups if score_group(g, cfg)]
    covered = {s.id for g in feasible for s in g}
    return Solution(name, [tuple(sorted(s.id for s in g)) for g in feasible],
                    sorted(s.id for s in students if s.id not in covered), int((time.perf_counter() - t0) * 1000))


def random_groups(students: list[Student], cfg: MatchConfig, seed: int = 0) -> Solution:
    """Shuffle and cut into groups of 4 (the most common preferred size). The floor any method should beat."""
    t0 = time.perf_counter()
    order = list(students)
    random.Random(seed).shuffle(order)
    return _finish("random", [order[i:i + 4] for i in range(0, len(order), 4)], students, cfg, t0)


def first_come(students: list[Student], cfg: MatchConfig, seed: int = 0) -> Solution:
    """A sign-up sheet: students arrive in random order; each joins the first group with room that still has
    shared free time (capacity = the group founder's preferred size), otherwise starts a new group."""
    t0 = time.perf_counter()
    order = list(students)
    random.Random(seed).shuffle(order)
    groups: list[list[Student]] = []
    for s in order:
        for g in groups:
            cap = min(cfg.max_size, max(cfg.min_size, g[0].preferred_size))
            if len(g) < cap and score_group(g + [s], cfg, ignore_size=len(g) + 1 < cfg.min_size):
                g.append(s)
                break
        else:
            groups.append([s])
    return _finish("first_come", groups, students, cfg, t0)


def availability_clusters(students: list[Student], cfg: MatchConfig, seed: int = 0) -> Solution:
    """Cluster students with similar free time into groups of ~4 (balanced k-means on the weekly grid), then
    repair: members of clusters that can't meet join a feasible group with room, and greedy groups the rest."""
    t0 = time.perf_counter()
    if len(students) < cfg.min_size:
        return _finish("clustering", [], students, cfg, t0)
    k = max(1, round(len(students) / 4))
    clusters = _balanced_clusters(students, k, seed=seed)
    good = [c for c in clusters if score_group(c, cfg)]
    members = dict(enumerate(good))
    unplaced = []
    for s in (s for c in clusters if not score_group(c, cfg) for s in c):
        gi = best_insertion_for(s, members, cfg, min_quality=0.0)
        if gi is None:
            unplaced.append(s)
        else:
            members[gi].append(s)
    # Second chance so the baseline isn't a strawman: group whoever is left with greedy.
    by_id = {s.id: s for s in unplaced}
    extra = [[by_id[i] for i in g] for g in greedy(unplaced, cfg).groups] if len(unplaced) >= cfg.min_size else []
    return _finish("clustering", list(members.values()) + extra, students, cfg, t0)


BASELINES = {"random": random_groups, "first_come": first_come, "clustering": availability_clusters}
