"""Synthetic student populations for benchmarking and tests (NOT real usage data)."""
import random

from app.matching.engine import GOALS, HOURS_PER_DAY, Student

# Rough archetypes of when students are free outside class: (weekday hour range, weekend probability)
ARCHETYPES = [
    ((10, 14), 0.2),  # midday gaps between classes
    ((16, 20), 0.3),  # late afternoon / early evening
    ((19, 22), 0.4),  # night owls
    ((8, 12), 0.2),   # early birds
]


PROFILES = {
    # name: (weekday free probability, block length range, scattered extra hours, goal weights, archetypes)
    "baseline": (0.6, (1, 3), (0, 4), [5, 3, 2, 1], ARCHETYPES),
    # Busy students: free on fewer days, shorter blocks, no scattered hours. Overlap is scarce.
    "sparse": (0.3, (1, 2), (0, 0), [5, 3, 2, 1], ARCHETYPES),
    # Everyone is free in the same evening window: overlap is easy, so even greedy should do well.
    "concentrated": (0.6, (1, 3), (0, 2), [5, 3, 2, 1], [((18, 22), 0.3)]),
    # Preferences spread evenly (goal, pace, size): compatible groups are harder to form.
    "diverse": (0.6, (1, 3), (0, 4), [1, 1, 1, 1], ARCHETYPES),
}


def generate(n: int, seed: int = 0, profile: str = "baseline") -> list[Student]:
    weekday_p, (len_lo, len_hi), (extra_lo, extra_hi), goal_weights, archetypes = PROFILES[profile]
    rng = random.Random(seed)
    students = []
    for i in range(n):
        (lo, hi), weekend_p = rng.choice(archetypes)
        slots = set()
        for day in range(5):
            if rng.random() < weekday_p:
                start = rng.randint(lo, hi - 1)
                length = rng.randint(len_lo, len_hi)
                for h in range(start, min(start + length, 22)):
                    slots.add(day * HOURS_PER_DAY + (h - 8))
        for day in (5, 6):
            if rng.random() < weekend_p:
                start = rng.randint(10, 18)
                for h in range(start, start + rng.randint(2, 4)):
                    slots.add(day * HOURS_PER_DAY + (h - 8))
        for _ in range(rng.randint(extra_lo, extra_hi)):
            slots.add(rng.randrange(7 * HOURS_PER_DAY))
        goal = rng.choices(GOALS, weights=goal_weights)[0]
        if profile == "diverse":
            pace, size = rng.choice((1, 2, 3)), rng.choice((3, 4, 5, 6))
        else:
            pace, size = rng.choice((1, 2, 2, 3)), rng.choice((3, 4, 4, 5))
        students.append(Student(id=i, slots=frozenset(slots), goal=goal, pace=pace, preferred_size=size))
    return students
