import random

from app.matching import evaluate as ev
from app.matching import penn_schedules as ps
from app.matching.engine import FIRST_HOUR, HOURS_PER_DAY


def slot(day, hour):
    return day * HOURS_PER_DAY + (hour - FIRST_HOUR)


def test_meeting_times_map_to_grid_hours():
    assert ps._minutes(10.15) == 615 and ps._minutes(11.14) == 674
    section = {"meetings": [["M", 615, 674], ["R", 1080, 1199]]}  # Mon 10:15-11:14, Thu 18:00-19:59
    assert ps.section_slots(section) == {slot(0, 10), slot(0, 11), slot(3, 18), slot(3, 19)}


def test_data_file_has_real_fall_2026_sections():
    data = ps.load()
    assert data["semester"] == "2026C" and len(data["courses"]) >= 10
    cis = data["courses"]["CIS-1200"]["sections"]
    assert {s["activity"] for s in cis} >= {"LEC", "REC"}


def test_free_time_never_overlaps_class_time():
    data = ps.load()
    rng = random.Random(7)
    for _ in range(50):
        busy = ps.class_schedule(rng, ["CIS-1200", "MATH-1400", "ECON-0100", "PHYS-0150"], data)
        free = ps.mark_free_time(rng, busy)
        assert free and not (free & busy) and 1 <= len(free) <= 16


def test_pools_are_reproducible():
    a = ps.generate_course_pool("CIS-1200", 30, seed=3)
    b = ps.generate_course_pool("CIS-1200", 30, seed=3)
    assert [s.slots for s in a] == [s.slots for s in b]
    assert [s.slots for s in a] != [s.slots for s in ps.generate_course_pool("CIS-1200", 30, seed=4)]


def test_quick_penn_evaluation_reports():
    res = ev.run_penn(ev.PENN_QUICK)
    text = ev.report_penn(res)
    assert "real Penn class schedules" in text and "CIS 1200" in text
    assert res["results"]["CIS-1200"]["paired"]["never_worse_on_objective"]
