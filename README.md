# CampusConnect — study groups for students who don't know anyone in the class

GroupMe and Discord work when you already know people in a course. CampusConnect matches **strangers**: tell it when you're free, what you want to work on and how fast you like to go. In the two weeks before each exam it forms groups that can actually meet, then tracks whether they did.

React/TypeScript · FastAPI · PostgreSQL · OR-Tools (CP-SAT) · Docker · GitHub Actions

**How matching works:** it's a constrained assignment problem. Students are split into groups of 3–6 who share at least 2 free hours a week, maximising a quality score built from shared time, goal, pace and size preference. Each round runs a greedy baseline, local search, and a set-partitioning ILP solved with OR-Tools on the same students. The ILP result is applied and all three are logged for comparison. On synthetic populations of 120–250 students the ILP raises average match quality by about 17–20% and shared free time by about 16–23% over greedy ([benchmark](docs/benchmark.md), [design](docs/matching.md)).

## Quick start (Docker)

Prerequisites: Docker Desktop with Compose.

```bash
cp .env.example .env
# Edit .env and set SECRET_KEY to a long random value.
docker compose up --build
```

Set `ADMIN_EMAILS` in `.env` to your account's email to add exam dates and run matching rounds from the **Impact** tab. Compose also starts a `matcher` service that runs exam-aware matching every hour.

Open **http://localhost:5173** for the app, **http://localhost:8000/docs** for Swagger, and **http://localhost:8000/health** for health. Database migrations and sample course seeding run automatically on backend startup. The initial database has courses but no users or groups; register and create the first group.

Stop with `docker compose down`. To delete local database data: `docker compose down -v` (destructive).

## Local development without Docker

Start PostgreSQL and set `DATABASE_URL` to a valid `postgresql+psycopg://...` URL, or use SQLite for local prototyping. In `backend/`:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
export DATABASE_URL=sqlite:///./campusconnect.db   # PowerShell: $env:DATABASE_URL='sqlite:///./campusconnect.db'
export SECRET_KEY=replace-this-with-a-long-random-secret
alembic upgrade head
python seed.py
uvicorn app.main:app --reload
# optional, in another terminal: background matcher (or run one pass with --once)
python -m app.matching.scheduler
```

In another terminal, `cd frontend && npm install && npm run dev`. For non-Docker local development, Vite's default proxy host `backend` is not resolvable: change the proxy target in `frontend/vite.config.ts` to `http://localhost:8000`, or set `VITE_API_URL=http://localhost:8000` in `frontend/.env.local` and restart Vite. Backend CORS defaults to `http://localhost:5173`.

## Tests

```bash
cd backend && pip install -r requirements-dev.txt && pytest -q && ruff check app tests seed.py
cd frontend && npm install && npm run test && npm run lint && npm run build
```

## Features
**Matching**
- Weekly availability grid (drag to paint), study goal, pace, preferred group size
- Exam-aware rounds: automatic matching in the 14 days before each exam; otherwise batched within 24 hours
- Greedy vs local search vs ILP (OR-Tools CP-SAT) on every round, recorded in `match_runs`
- Instant placement into open matched groups; automatic rematching when someone leaves or their schedule changes
- "Did your group meet?" check-ins

**Outcome metrics** (`/api/metrics`, **Impact** tab)
- % of matched groups that met at least once and at least twice
- Retention across exams and courses
- Median and p90 time to match
- ILP gain over greedy

**Open groups**
- Register, sign in, view current account, sign out
- Search seeded courses
- Browse, search, filter, paginate study groups
- Create, edit, delete groups (owner-only changes)
- Join/leave groups, view member roster, capacity enforcement
- First-come, first-served waitlists for full groups, promoted under PostgreSQL row locks
- Friendly loading, empty, validation and error states; responsive UI
- SQL migrations, seed data, containerized dev, GitHub Actions

## Security & scope
This is a working portfolio MVP, **not a fully hardened production service**. For public production use add HTTPS, a trusted auth provider or secure HttpOnly cookies and CSRF protection, rate limiting, abuse prevention, password reset, email verification, token revocation, monitoring, backup/restore, and security scanning. Never use example passwords or secrets in production. JWTs are stored in browser sessionStorage in this demo. Seeded course codes are examples, not an authoritative catalog.

See [matching design](docs/matching.md), [benchmark](docs/benchmark.md), [architecture](docs/architecture.md), [ER schema](docs/schema.md), and [API examples](docs/api.md).
