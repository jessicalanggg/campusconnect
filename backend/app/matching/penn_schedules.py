"""Simulated students whose free time comes from REAL Penn class meeting times.

The data file holds Fall 2026 (2026C) section meeting times for large intro/2nd-year courses, fetched from Penn Labs'
public Penn Course Plan API. Refresh it with:

    python -m app.matching.penn_schedules --fetch            # writes app/matching/data/penn_2026C_sections.json

How a simulated student is built (see generate_course_pool):
1. They take the target course plus 3 other courses from the list (no course twice).
2. For each course they register for one section of every activity it has (lecture, recitation, lab, ...), chosen in
   proportion to section capacity, retrying to avoid time conflicts. Those meetings are their class schedule.
3. Of the hours they're NOT in class (08:00-22:00), they mark 6-14 hours a week as free for studying, in 1-3 hour
   blocks, with evenings more likely than daytime and weekends least likely (people also have clubs, work, meals).
   That marking step is the modelling assumption; the class schedules themselves are real.
Goals, pace and preferred group size use the same mix as app/matching/synthetic.py.
"""
from __future__ import annotations

import argparse
import json
import random
import ssl
import time
import urllib.request
from functools import lru_cache
from pathlib import Path

from app.matching.engine import FIRST_HOUR, GOALS, HOURS_PER_DAY, Student

SEMESTER = "2026C"
DATA_FILE = Path(__file__).parent / "data" / f"penn_{SEMESTER}_sections.json"
API = "https://penncourseplan.com/api/base/{semester}/courses/{code}/"
COURSES = [
    "CIS-1200", "CIS-1210", "CIS-1600", "CIS-2400", "MATH-1400", "MATH-1410", "MATH-1070",
    "PHYS-0150", "PHYS-0151", "ECON-0100", "ECON-0200", "CHEM-1011", "BIOL-1101", "STAT-1110", "ESE-2150",
]
DAY_INDEX = {"M": 0, "T": 1, "W": 2, "R": 3, "F": 4, "S": 5, "U": 6}
LAST_HOUR = FIRST_HOUR + HOURS_PER_DAY  # grid covers 08:00-22:00


# ---------------------------------------------------------------------------------------------------- fetching

def _minutes(t: float) -> int:
    """Penn Course Plan encodes 10:15 as 10.15."""
    hours = int(t)
    return hours * 60 + round((t - hours) * 100)


def _ssl_context() -> ssl.SSLContext:
    """Verified TLS; use certifi's CA bundle when available (python.org builds on macOS ship without one)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch(semester: str = SEMESTER, courses: list[str] = COURSES, out: Path = DATA_FILE) -> dict:
    data = {"source": "Penn Labs Penn Course Plan public API (penncourseplan.com/api/base)", "semester": semester,
            "fetched_at": time.strftime("%Y-%m-%d"), "courses": {}}
    for code in courses:
        req = urllib.request.Request(API.format(semester=semester, code=code),
                                     headers={"User-Agent": "campusconnect-benchmark (student project)"})
        try:
            with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as r:
                course = json.load(r)
        except Exception as exc:  # noqa: BLE001
            print(f"skip {code}: {exc}")
            continue
        sections = []
        for s in course.get("sections", []):
            meetings = [[m["day"], _minutes(m["start"]), _minutes(m["end"])] for m in s.get("meetings", [])
                        if m.get("day") in DAY_INDEX and m.get("start") is not None and m.get("end") is not None]
            if meetings and s.get("status") != "X":  # skip cancelled sections and ones without a time
                sections.append({"id": s["id"], "activity": s.get("activity") or "LEC",
                                 "capacity": max(1, int(s.get("capacity") or 1)), "meetings": meetings})
        if sections:
            data["courses"][code] = {"title": course.get("title", ""), "sections": sections}
            print(f"{code}: {len(sections)} timed sections")
        time.sleep(0.5)  # be gentle with Penn Labs' server
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1) + "\n")
    return data


# ------------------------------------------------------------------------------------------------- simulation

@lru_cache(maxsize=1)
def load(path: str = str(DATA_FILE)) -> dict:
    return json.loads(Path(path).read_text())


def section_slots(section: dict) -> frozenset[int]:
    """Grid hours a section occupies (any overlap with an hour counts as busy)."""
    busy = set()
    for day, start, end in section["meetings"]:
        d = DAY_INDEX[day]
        for hour in range(FIRST_HOUR, LAST_HOUR):
            if start < (hour + 1) * 60 and end > hour * 60:
                busy.add(d * HOURS_PER_DAY + (hour - FIRST_HOUR))
    return frozenset(busy)


def class_schedule(rng: random.Random, courses: list[str], data: dict) -> frozenset[int]:
    busy: set[int] = set()
    for code in courses:
        by_activity: dict[str, list[dict]] = {}
        for s in data["courses"][code]["sections"]:
            by_activity.setdefault(s["activity"], []).append(s)
        for sections in by_activity.values():
            choice = None
            for _ in range(8):  # capacity-weighted pick, retrying to avoid conflicts
                cand = rng.choices(sections, weights=[s["capacity"] for s in sections])[0]
                if not (section_slots(cand) & busy):
                    choice = cand
                    break
            busy |= section_slots(choice or cand)
    return frozenset(busy)


def _weight(slot: int) -> float:
    day, hour = divmod(slot, HOURS_PER_DAY)
    hour += FIRST_HOUR
    if day >= 5:
        return 0.6
    return 3.0 if hour >= 17 else 1.2


def mark_free_time(rng: random.Random, busy: frozenset[int]) -> frozenset[int]:
    open_slots = [s for s in range(7 * HOURS_PER_DAY) if s not in busy]
    target = rng.randint(6, 14)
    free: set[int] = set()
    for _ in range(60):
        if len(free) >= target or not open_slots:
            break
        start = rng.choices(open_slots, weights=[_weight(s) for s in open_slots])[0]
        for k in range(rng.randint(1, 3)):
            slot = start + k
            if slot // HOURS_PER_DAY != start // HOURS_PER_DAY or slot in busy:
                break
            free.add(slot)
    return frozenset(free)


def generate_course_pool(target: str, n: int, seed: int = 0, data: dict | None = None) -> list[Student]:
    """n simulated students who are all taking `target` (one course's matching pool)."""
    data = data or load()
    if target not in data["courses"]:
        raise KeyError(f"{target} not in {DATA_FILE.name}; available: {sorted(data['courses'])}")
    others = [c for c in data["courses"] if c != target]
    rng = random.Random(f"{target}:{seed}")
    students = []
    for i in range(n):
        courses = [target, *rng.sample(others, k=min(3, len(others)))]
        busy = class_schedule(rng, courses, data)
        students.append(Student(id=i, slots=mark_free_time(rng, busy), goal=rng.choices(GOALS, weights=[5, 3, 2, 1])[0],
                                pace=rng.choice((1, 2, 2, 3)), preferred_size=rng.choice((3, 4, 4, 5))))
    return students


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true", help="refresh the section data from Penn Course Plan")
    args = parser.parse_args()
    if args.fetch:
        fetch()
    data = load()
    print(f"{len(data['courses'])} courses from {data['source']} ({data['semester']}, fetched {data['fetched_at']})")


if __name__ == "__main__":
    main()
