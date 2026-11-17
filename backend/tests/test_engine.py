from app.matching.engine import (HOURS_PER_DAY, MatchConfig, Student, describe_slots, evaluate, greedy, ilp,
                                 local_search, score_group, solve_all)
from app.matching.synthetic import generate

CFG = MatchConfig(ilp_seconds=5, local_search_seconds=1)


def slots(day, start, end):
    return {day * HOURS_PER_DAY + h - 8 for h in range(start, end)}


def check_valid(solution, students):
    seen = [i for g in solution.groups for i in g]
    assert len(seen) == len(set(seen)), "a student was placed twice"
    assert set(seen) | set(solution.unassigned) == {s.id for s in students}
    for g in solution.groups:
        assert CFG.min_size <= len(g) <= CFG.max_size
        assert score_group([s for s in students if s.id in g], CFG) is not None


def test_score_requires_common_time_and_size():
    a = Student(1, frozenset(slots(0, 18, 21)), "exam_prep", 2, 3)
    b = Student(2, frozenset(slots(0, 19, 22)), "exam_prep", 2, 3)
    c = Student(3, frozenset(slots(0, 18, 20)), "exam_prep", 2, 3)
    far = Student(4, frozenset(slots(3, 8, 11)), "exam_prep", 2, 3)
    assert score_group([a, b], CFG) is None  # below min size
    good = score_group([a, b, c], CFG)
    assert good is None  # a∩b∩c = {19} only one shared hour
    d = Student(5, frozenset(slots(0, 19, 21)), "exam_prep", 2, 3)
    s = score_group([a, b, d], CFG)
    assert s and len(s.common) == 2 and s.goal == 1 and s.pace == 1 and s.size == 1
    assert score_group([a, b, far], CFG) is None


def test_quality_prefers_matching_goals_and_pace():
    base = frozenset(slots(1, 12, 18))
    same = [Student(i, base, "homework", 2, 3) for i in range(3)]
    mixed = [Student(0, base, "homework", 1, 3), Student(1, base, "projects", 3, 3), Student(2, base, "concepts", 2, 3)]
    assert score_group(same, CFG).quality > score_group(mixed, CFG).quality


def test_all_solvers_valid_and_ilp_dominates():
    students = generate(80, seed=7)
    by_id = {s.id: s for s in students}
    g = greedy(students, CFG)
    ls = local_search(students, CFG, g)
    opt = ilp(students, CFG, [g, ls])
    for sol in (g, ls, opt):
        check_valid(sol, students)
    eg, el, eo = (evaluate(s, by_id, CFG) for s in (g, ls, opt))
    # Lexicographic (coverage, quality) objective never gets worse along greedy -> local search -> ILP.
    assert (eo["assigned"], eo["objective"]) >= (el["assigned"], el["objective"]) >= (eg["assigned"], eg["objective"])


def test_impossible_students_stay_unassigned():
    lonely = [Student(i, frozenset(slots(i % 7, 8 + i, 10 + i)), "homework", 2, 3) for i in range(5)]
    results = solve_all(lonely, CFG)
    for sol, ev in results.values():
        assert sol.groups == [] and ev["assigned"] == 0


def test_describe_slots():
    assert describe_slots(slots(0, 18, 20) | slots(2, 9, 10)) == "Mon 18:00–20:00, Wed 09:00–10:00"
