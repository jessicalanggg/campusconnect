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


def generate(n: int, seed: int = 0) -> list[Student]:
    rng = random.Random(seed)
    students = []
    for i in range(n):
        (lo, hi), weekend_p = rng.choice(ARCHETYPES)
        slots = set()
        for day in range(5):
            if rng.random() < 0.6:  # free on ~60% of weekdays in their usual window
                start = rng.randint(lo, hi - 1)
                length = rng.randint(1, 3)
                for h in range(start, min(start + length, 22)):
                    slots.add(day * HOURS_PER_DAY + (h - 8))
        for day in (5, 6):
            if rng.random() < weekend_p:
                start = rng.randint(10, 18)
                for h in range(start, start + rng.randint(2, 4)):
                    slots.add(day * HOURS_PER_DAY + (h - 8))
        for _ in range(rng.randint(0, 4)):  # scattered one-off free hours
            slots.add(rng.randrange(7 * HOURS_PER_DAY))
        goal = rng.choices(GOALS, weights=[5, 3, 2, 1])[0]
        students.append(Student(id=i, slots=frozenset(slots), goal=goal, pace=rng.choice((1, 2, 2, 3)),
                                preferred_size=rng.choice((3, 4, 4, 5))))
    return students
