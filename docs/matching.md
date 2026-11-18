# How matching works

Short version: **group formation is a constrained assignment problem.** Students are partitioned into groups of 3–6 who share at least 2 free hours a week, maximising total match quality. It's solved as a set-partitioning integer linear program with OR-Tools CP-SAT. A greedy baseline and a local-search baseline run on the same input every round so the gain can be measured.

Code: [`backend/app/matching/engine.py`](../backend/app/matching/engine.py) (pure algorithm), [`service.py`](../backend/app/matching/service.py) (DB workflows), [`scheduler.py`](../backend/app/matching/scheduler.py) (background runner).

## Inputs

Each match request has:
- a weekly availability grid: 7 days × 14 one-hour slots, 08:00–22:00
- a goal: exam prep, homework, concepts or projects
- a pace: slow, steady or fast
- a preferred group size (3–6)

## Scoring a group

A group is **feasible** only if it has 3–6 members and every member is free during at least 2 common hours a week. Without that, the group can't actually meet.

Quality per student is a number in [0, 1]:

| Term | Weight | Definition |
|---|---:|---|
| Shared time | 0.40 | `min(|∩ availability|, 4) / 4`. Saturates at 4 shared hours |
| Goal | 0.25 | Share of members with the group's most common goal |
| Pace | 0.15 | `1 − (max pace − min pace) / 2` |
| Size | 0.20 | Mean over members of `1 − min(1, |size − preferred| / 2)` |

Shared time uses the **true group intersection**, not pairwise overlaps. Three people who pairwise overlap can still have no hour where all three are free. A pairwise model can't express this, so the ILP chooses whole groups.

## Solvers

1. **Greedy (baseline).** Hardest-to-place students go first (fewest free hours). Each one joins the existing group with the best marginal gain that stays feasible and doesn't grow past anyone's preferred size; otherwise they start a new group. Groups that end up undersized are dissolved, and their members are reinserted where possible.
2. **Local search.** Starts from greedy and hill-climbs over four moves: insert an unassigned student, pair up unassigned students, move a student, swap two students.
3. **ILP.**
   - Generate a candidate pool: from each student, beam-search over their 12 most compatible partners. Add every group from the greedy and local-search solutions.
   - Choose disjoint groups: binary `x_G` per candidate, `Σ_{G∋i} x_G ≤ 1` for each student.
   - Objective, lexicographic: maximise `Σ x_G · |G| · (BIG + quality(G))`. Coverage comes first (every placed student is worth more than any possible quality gain), then quality.
   - The solver is hinted with the local-search solution. Because those groups are in the pool, the ILP is **never worse** than either baseline.
   - Caveat: the result is optimal *over the candidate pool*, not over all possible groupings, which is intractable at this size.

## Lifecycle

- **Exam-aware rounds.** The scheduler (`python -m app.matching.scheduler`, the `matcher` service in Docker Compose) runs every hour. A course is matched when today is within 14 days of one of its exams. Outside exam windows it runs once the oldest waiting student has waited 24 hours.
- **Instant fill.** A new request is placed straight into an existing matched group with an open seat if the group stays feasible and quality is ≥ 0.5. Otherwise the student waits for the next round.
- **Rematch on leave.** "Find me a new group" requeues the student and records the group, so they're never put back into it. A group that drops below 2 members is dissolved and the remaining member is requeued. Open seats are refilled from the waiting pool.
- **Rematch on schedule change.** If an updated schedule breaks the group's shared time, the student leaves that group and is rematched. The group's shared time is recomputed and its seat refilled.
- **Concurrency.**
  - Every matching workflow takes a per-course PostgreSQL advisory transaction lock, so the scheduler and API requests never interleave on one course.
  - Underneath that, placing a student locks the student's request row and the group row (`SELECT … FOR UPDATE`), then re-checks capacity and fit before inserting. A group is never overfilled and a student is never placed twice, even without the advisory lock.
  - Open seats are offered to waiting students oldest first.
  - [`tests/test_concurrency_postgres.py`](../backend/tests/test_concurrency_postgres.py) races up to 10 simultaneous placements against a real PostgreSQL in CI. It fails on the code from before the re-check was added.

## Measuring it

- Every round writes a `match_runs` row with greedy, local-search and ILP quality and shared hours, all computed on the same students. `/api/metrics` aggregates these, weighted by students placed.
- [`benchmark.md`](benchmark.md) compares the solvers on synthetic populations. Regenerate it with `python -m app.matching.benchmark --out ../docs/benchmark.md`.
- Outcome metrics at `/api/metrics`:
  - % of matched groups (at least a week old) that reported meeting at least once and at least twice
  - retention: students who used matching in two or more course/exam cycles
  - time to match: median and p90 hours from request to placement
