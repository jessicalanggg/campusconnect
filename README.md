# CampusConnect

[![CI](https://github.com/jessicalanggg/campusconnect/actions/workflows/ci.yml/badge.svg)](https://github.com/jessicalanggg/campusconnect/actions/workflows/ci.yml)

**Study groups for students who don't know anyone in the class.** GroupMe and Discord work when you already have friends in a course. CampusConnect matches **strangers**: tell it when you're free, what you want to work on and how fast you like to go. In the two weeks before each exam it forms groups that can actually meet, then tracks whether they did.

React/TypeScript · FastAPI · PostgreSQL · OR-Tools (CP-SAT) · Docker · GitHub Actions

<p>
  <img src="docs/images/match.png" alt="Matching page: course, study goal, pace, preferred group size and a weekly availability grid" width="67%">
  <img src="docs/images/group.png" alt="A matched group showing the hours every member is free, the members, and a 'did your group meet?' check-in" width="30%">
</p>

## Results

Every matching round runs three algorithms on the same students and logs all three. On synthetic populations ([full benchmark](docs/benchmark.md), 5 random populations per size):

| 250 students | Students placed | Avg match quality | Shared free hours / week |
|---|---:|---:|---:|
| Greedy baseline | 97.9% | 0.561 | 2.05 |
| Local search | 98.5% | 0.623 | 2.24 |
| **ILP (OR-Tools CP-SAT)** | **99.1%** | **0.673** (+20%) | **2.52** (+23%) |

In small classes the main win is placement: with 30 students the ILP places **75%** of them versus **45%** for greedy, because it can choose whole groups that greedy's one-at-a-time choices rule out.

For real usage, the app tracks outcomes, not signups (`/api/metrics`, **Impact** tab):
- the share of matched groups that met at least once and at least twice, from members' check-ins
- retention across exams and courses
- median and p90 time to match

## How matching works

```mermaid
flowchart LR
    A["Match requests<br/>free hours, goal, pace, group size"] --> B["Candidate groups<br/>beam search over compatible partners"]
    A --> G["Greedy baseline"]
    G --> L["Local search"]
    G --> B
    L --> B
    B --> I["ILP · OR-Tools CP-SAT<br/>pick the best disjoint groups<br/>5s limit, seeded with local search"]
    I --> M["Matched groups"]
    M --> C["'Did your group meet?'<br/>check-ins"]
    C --> R["Outcome metrics"]
    M -. "someone leaves or their schedule changes" .-> A
```

Group formation is a **constrained assignment problem**:
- **Constraints:** groups of 3–6 students, and every member free during at least 2 common hours a week. Otherwise the group can't meet.
- **Quality score:** shared free time (40%), same study goal (25%), similar pace (15%), and closeness to each student's preferred group size (20%).

Shared time uses the **true group-wide overlap**, the hours when *everyone* is free. Three people can each overlap pairwise and still never all be free at once, so the ILP chooses whole groups rather than pairs. It starts from the local-search solution, so its result is never worse than either baseline.

**Lifecycle:**
- **Exam-aware rounds:** groups form automatically in the 14 days before each exam. Outside those windows, nobody waits more than about 24 hours.
- **Instant placement:** late sign-ups who fit go straight into an open seat.
- **Automatic rematching:** students are rematched when someone leaves or their schedule changes.

Design details: [docs/matching.md](docs/matching.md).

## Features

**Matching**
- Weekly availability grid (drag to paint), study goal, pace, preferred group size
- Exam-aware rounds, instant placement, rematching on leave or schedule change
- Greedy vs local search vs ILP on every round, recorded in `match_runs`
- "Did your group meet?" check-ins and an **Impact** page with outcome metrics
- Admin tools: add exam dates and run a matching round on demand

**Open groups**
- Create, search, filter and join student-run groups
- First-come, first-served waitlists for full groups, promoted under PostgreSQL row locks
- Owner-only edit and delete; capacity enforced under concurrent joins

**Engineering**
- FastAPI, SQLAlchemy and Alembic migrations; React and TypeScript with Vite
- JWT auth and Argon2 password hashing
- Pytest and Vitest suites in GitHub Actions CI; Docker Compose for local development

## Quick start (Docker)

Prerequisites: Docker Desktop with Compose.

```bash
cp .env.example .env
# Edit .env: set SECRET_KEY to a long random value and ADMIN_EMAILS to your account's email.
docker compose up --build
```

Open **http://localhost:5173** for the app, **http://localhost:8000/docs** for the interactive API docs, and **http://localhost:8000/health** for a health check.
- Migrations and course seeding run automatically. A fresh install starts with courses only, so register an account to begin.
- Compose also starts a `matcher` service that runs exam-aware matching every hour.

Stop with `docker compose down`. To delete local database data: `docker compose down -v` (destructive).

## Local development without Docker

Start PostgreSQL and set `DATABASE_URL` to a `postgresql+psycopg://...` URL, or use SQLite for prototyping. In `backend/`:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
export DATABASE_URL=sqlite:///./campusconnect.db   # PowerShell: $env:DATABASE_URL='sqlite:///./campusconnect.db'
export SECRET_KEY=replace-this-with-a-long-random-secret
alembic upgrade head
python seed.py
uvicorn app.main:app --reload
# optional, in another terminal: background matcher (or one pass with --once)
python -m app.matching.scheduler
```

In another terminal, run `cd frontend && npm install && npm run dev`.

Outside Docker, Vite can't reach the proxy host `backend`. Either set `VITE_API_URL=http://localhost:8000` in `frontend/.env.local`, or change the proxy target in `frontend/vite.config.ts`.

## Tests

```bash
cd backend && pip install -r requirements-dev.txt && pytest -q && ruff check app tests seed.py
cd frontend && npm install && npm run test && npm run lint && npm run build
python -m app.matching.benchmark --out ../docs/benchmark.md   # from backend/: regenerate the benchmark
```

## Limitations

These would need hardening before a wider deployment:
- **Authentication:** JWTs are kept in `sessionStorage`. HttpOnly cookies with CSRF protection would be safer. There's no email verification or password reset yet.
- **Abuse prevention:** no rate limiting yet.
- **Data entry:** students enter availability by hand. Calendar import is a natural next step.

More docs: [matching design](docs/matching.md) · [benchmark](docs/benchmark.md) · [architecture](docs/architecture.md) · [ER schema](docs/schema.md) · [API](docs/api.md)
