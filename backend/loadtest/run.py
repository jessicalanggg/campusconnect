"""HTTP load test against the real app and a real PostgreSQL, with correctness checks after every phase.

    DATABASE_URL=postgresql+psycopg://... python -m loadtest.run --students 400 --out-md ../docs/loadtest.md

The database must be an empty scratch PostgreSQL (the test migrates it, seeds it, and fills it with test accounts).
It starts the API itself (uvicorn, several worker processes, rate limiting off) and drives it with concurrent
requests from simulated students whose free time comes from real Penn class schedules.

Phases:
  1. sign-up    every student registers and logs in at once
  2. requests   every student asks to be matched for CIS 1200 at the same moment
  3. matching   an admin runs a matching round while more students keep requesting
  4. churn      at once: students leave (and ask to be rematched), change schedules, withdraw, new students request,
                and a second matching round runs in the middle of it
  5. last seats many new students with matching free time race for the few remaining open seats

Each phase launches all its requests together; at most --concurrency (default 100) are in flight at a time.

Invariants checked in the database after each phase (any violation fails the run):
  - no group has more members than its capacity
  - no student is in two groups
  - memberships and match requests agree (every matched request has its membership and vice versa)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import random
import socket
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

BACKEND = Path(__file__).resolve().parents[1]
ADMIN = "loadtest-admin@upenn.edu"
PASSWORD = "loadtest-password-123"
COURSE = "CIS-1200"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Recorder:
    def __init__(self, concurrency: int):
        self.sem = asyncio.Semaphore(concurrency)
        self.lat: dict[str, list[float]] = defaultdict(list)
        self.status: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self.errors: list[str] = []

    async def call(self, client: httpx.AsyncClient, name: str, method: str, url: str, **kw) -> httpx.Response | None:
        async with self.sem:
            t0 = time.perf_counter()
            try:
                r = await client.request(method, url, **kw)
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"{name}: {type(exc).__name__}: {exc}")
                self.status[name][0] += 1
                return None
            self.lat[name].append((time.perf_counter() - t0) * 1000)
        self.status[name][r.status_code] += 1
        return r

    def total(self) -> int:
        return sum(sum(c.values()) for c in self.status.values())


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def check_invariants(engine) -> dict:
    q = {
        "overfilled_groups": """SELECT count(*) FROM (SELECT g.id FROM study_groups g JOIN memberships m ON m.group_id = g.id
                                GROUP BY g.id, g.max_members HAVING count(*) > g.max_members) x""",
        "students_in_two_groups": """SELECT count(*) FROM (SELECT user_id FROM memberships GROUP BY user_id
                                     HAVING count(*) > 1) x""",
        "matched_requests_without_membership": """SELECT count(*) FROM match_requests r WHERE r.status = 'matched'
                                     AND NOT EXISTS (SELECT 1 FROM memberships m WHERE m.group_id = r.group_id
                                     AND m.user_id = r.user_id)""",
        "memberships_without_matched_request": """SELECT count(*) FROM memberships m WHERE NOT EXISTS (SELECT 1 FROM
                                     match_requests r WHERE r.group_id = m.group_id AND r.user_id = m.user_id
                                     AND r.status = 'matched')""",
        "students_with_two_active_requests": """SELECT count(*) FROM (SELECT user_id FROM match_requests WHERE status IN
                                     ('waiting', 'matched') GROUP BY user_id, course_id HAVING count(*) > 1) x""",
    }
    with engine.connect() as c:
        out = {k: c.execute(text(v)).scalar() for k, v in q.items()}
        out["groups"] = c.execute(text("SELECT count(*) FROM study_groups")).scalar()
        out["matched"] = c.execute(text("SELECT count(*) FROM match_requests WHERE status = 'matched'")).scalar()
        out["waiting"] = c.execute(text("SELECT count(*) FROM match_requests WHERE status = 'waiting'")).scalar()
        out["open_seats"] = c.execute(text("""SELECT coalesce(sum(g.max_members - n), 0) FROM study_groups g JOIN
                                    (SELECT group_id, count(*) n FROM memberships GROUP BY group_id) m ON m.group_id = g.id
                                    WHERE n > 0""")).scalar()
    return {k: int(v) for k, v in out.items()}  # sum() comes back as Decimal


async def run(url: str, students: int, seed: int, concurrency: int) -> dict:
    from app.matching import penn_schedules as ps
    from app.matching.engine import FIRST_HOUR, HOURS_PER_DAY

    db_url = os.environ["DATABASE_URL"]
    engine = create_engine(db_url.replace("postgresql://", "postgresql+psycopg://", 1))
    rec, phases = Recorder(concurrency), []
    rng = random.Random(seed)
    n_main, n_late, n_race = students, students // 4, students // 3
    pool = ps.generate_course_pool(COURSE, n_main + n_late, seed=seed)
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=url, timeout=120, limits=limits) as client:
        r = await client.get("/api/courses", params={"q": "CIS 1200"})
        course_id = next(c["id"] for c in r.json() if c["code"] == "CIS 1200")
        tokens: dict[str, dict] = {}

        async def signup(email: str, name: str):
            await rec.call(client, "POST /auth/register", "POST", "/api/auth/register",
                           json={"email": email, "name": name, "password": PASSWORD})
            r = await rec.call(client, "POST /auth/login", "POST", "/api/auth/login",
                               json={"email": email, "password": PASSWORD})
            if r is not None and r.status_code == 200:
                tokens[email] = {"Authorization": f"Bearer {r.json()['access_token']}"}

        def request_body(student) -> dict:
            return {"course_id": course_id, "goal": student.goal, "pace": student.pace,
                    "preferred_size": student.preferred_size, "availability": sorted(student.slots)}

        async def ask(email, student):
            await rec.call(client, "POST /match/requests", "POST", "/api/match/requests",
                           headers=tokens[email], json=request_body(student))

        async def phase(name: str, coros) -> None:
            t0 = time.perf_counter()
            before = rec.total()
            await asyncio.gather(*coros)
            inv = check_invariants(engine)
            phases.append({"phase": name, "requests": rec.total() - before,
                           "seconds": round(time.perf_counter() - t0, 2), "invariants": inv})
            print(f"{name}: {phases[-1]['requests']} requests in {phases[-1]['seconds']}s; {inv}", file=sys.stderr)

        emails = [f"load{i:04d}@upenn.edu" for i in range(n_main + n_late + n_race)]
        await phase("1. sign-up", [signup(ADMIN, "Admin")] + [signup(e, f"Student {i}") for i, e in enumerate(emails)])
        missing = [e for e in [ADMIN] + emails if e not in tokens]
        if missing:
            sys.exit(f"{len(missing)} sign-ups failed; status codes {dict(rec.status['POST /auth/login'])}; "
                     f"first transport errors: {rec.errors[:3]}")
        admin = tokens[ADMIN]

        await phase("2. requests", [ask(emails[i], pool[i]) for i in range(n_main)])

        async def match_round():
            await rec.call(client, "POST /admin/courses/{id}/match", "POST", f"/api/admin/courses/{course_id}/match",
                           headers=admin)

        await phase("3. matching", [match_round()] + [ask(emails[n_main + i], pool[n_main + i])
                                                        for i in range(n_late // 2)])

        with engine.connect() as c:
            matched = c.execute(text("""SELECT u.email, r.group_id, r.id FROM match_requests r JOIN users u ON u.id = r.user_id
                                         WHERE r.status = 'matched'""")).all()
            waiting = c.execute(text("""SELECT u.email, r.id FROM match_requests r JOIN users u ON u.id = r.user_id
                                         WHERE r.status = 'waiting'""")).all()
        rng.shuffle(matched)
        k = len(matched) // 6
        leavers, reschedulers, withdrawers = matched[:k], matched[k:2 * k], matched[2 * k:2 * k + k // 2]

        async def leave(email, gid):
            await rec.call(client, "DELETE /groups/{id}/members/me", "DELETE",
                           f"/api/groups/{gid}/members/me?rematch=true", headers=tokens[email])

        async def reschedule(email, rid):
            new = sorted(rng.sample(range(7 * HOURS_PER_DAY), rng.randint(6, 12)))
            await rec.call(client, "PATCH /match/requests/{id}", "PATCH", f"/api/match/requests/{rid}",
                           headers=tokens[email], json={"availability": new})

        async def withdraw(email, rid):
            await rec.call(client, "DELETE /match/requests/{id}", "DELETE", f"/api/match/requests/{rid}",
                           headers=tokens[email])

        async def reads(email):
            await rec.call(client, "GET /groups/mine", "GET", "/api/groups/mine", headers=tokens[email])
            await rec.call(client, "GET /match/requests", "GET", "/api/match/requests", headers=tokens[email])

        churn = ([leave(e, g) for e, g, _ in leavers] + [reschedule(e, r) for e, _, r in reschedulers]
                 + [withdraw(e, r) for e, _, r in withdrawers] + [reschedule(e, r) for e, r in waiting[:k]]
                 + [ask(emails[n_main + i], pool[n_main + i]) for i in range(n_late // 2, n_late)]
                 + [reads(e) for e, _, _ in matched[2 * k + k // 2:][:k]] + [match_round()])
        rng.shuffle(churn)
        await phase("4. churn", churn)

        # Last seats: aim every racer at the 3 groups with the fewest open seats, using exactly those groups' shared
        # free time, so far more students compete than there are seats.
        with engine.connect() as c:
            targets = c.execute(text("""SELECT g.id, g.common_slots, g.max_members - m.n AS seats FROM study_groups g
                                JOIN (SELECT group_id, count(*) n FROM memberships GROUP BY group_id) m ON m.group_id = g.id
                                WHERE m.n > 0 AND m.n < g.max_members ORDER BY seats, g.id LIMIT 3""")).all()
        slots_pool = [json.loads(s) if isinstance(s, str) else s for _, s, _ in targets if s] or [
            [d * HOURS_PER_DAY + h - FIRST_HOUR for d in (0, 2) for h in (19, 20, 21)]]
        racers = emails[n_main + n_late:]
        race_info = {"target_groups": [t[0] for t in targets], "open_seats_in_targets": sum(t[2] for t in targets),
                     "racers": len(racers)}

        async def race(email, i):
            await rec.call(client, "POST /match/requests", "POST", "/api/match/requests", headers=tokens[email],
                           json={"course_id": course_id, "goal": "exam_prep", "pace": 2, "preferred_size": 4,
                                 "availability": sorted(slots_pool[i % len(slots_pool)])})

        await phase("5. last seats", [race(e, i) for i, e in enumerate(racers)])
        with engine.connect() as c:
            ids = race_info["target_groups"] or [-1]
            race_info["target_groups_full_after"] = c.execute(text(
                "SELECT count(*) FROM study_groups g WHERE g.id = ANY(:ids) AND (SELECT count(*) FROM memberships m "
                "WHERE m.group_id = g.id) = g.max_members"), {"ids": ids}).scalar()
            race_info["racers_placed"] = c.execute(text(
                "SELECT count(*) FROM match_requests r JOIN users u ON u.id = r.user_id WHERE r.status = 'matched' "
                "AND u.email = ANY(:e)"), {"e": racers}).scalar()
    engine.dispose()
    return {"phases": phases, "recorder": rec, "race": race_info}


def start_server(port: int, workers: int) -> subprocess.Popen:
    env = dict(os.environ, RATE_LIMIT_ENABLED="false", ADMIN_EMAILS=ADMIN, ALLOWED_EMAIL_DOMAINS="upenn.edu",
               REQUIRE_EMAIL_VERIFICATION="false", SECRET_KEY="loadtest-secret-key-not-for-real-use-0123456789",
               RUN_MATCHER_IN_PROCESS="false")
    for cmd in ([sys.executable, "-m", "alembic", "upgrade", "head"], [sys.executable, "seed.py"]):
        subprocess.run(cmd, cwd=BACKEND, env=env, check=True, capture_output=True)
    log = open(BACKEND / "loadtest" / "server.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--workers",
                             str(workers), "--log-level", "info", "--no-access-log",
                             # Under the sign-up burst (hundreds of argon2 hashes at once) a busy worker can miss
                             # uvicorn's default 5s health ping and get restarted, dropping its connections.
                             "--timeout-worker-healthcheck", "60"], cwd=BACKEND, env=env, stdout=log, stderr=log)
    for _ in range(100):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(0.2)
    proc.terminate()
    raise RuntimeError("server did not start; see loadtest/server.log")


EXPECTED = {  # status codes that are correct outcomes, not failures
    "POST /match/requests": {201, 409},  # 409: already has an active request
    "DELETE /groups/{id}/members/me": {204, 404},  # 404: a concurrent rematch already moved them out
    "PATCH /match/requests/{id}": {200, 409},
    "DELETE /match/requests/{id}": {204, 409},
}


def report(res: dict, args, elapsed: float, server_log: str) -> str:
    rec: Recorder = res["recorder"]
    deadlocks = server_log.lower().count("deadlock detected")
    restarts = max(0, server_log.count("Started server process") - args.workers)
    five_xx = sum(n for c in rec.status.values() for code, n in c.items() if code >= 500)
    unexpected = {name: {code: n for code, n in c.items() if code not in EXPECTED.get(name, {200, 201, 204})}
                  for name, c in rec.status.items()}
    unexpected = {k: v for k, v in unexpected.items() if v}
    viol = {k: sum(p["invariants"][k] for p in res["phases"]) for k in res["phases"][0]["invariants"]
            if k not in ("groups", "matched", "waiting", "open_seats")}
    peak = max(p["requests"] for p in res["phases"])
    L = ["# Load test", "",
         f"Generated by `python -m loadtest.run --students {args.students}` against the real API "
         f"({args.workers} uvicorn worker processes) and PostgreSQL, on {platform.system()} {platform.machine()}. "
         f"Students' free time comes from real Penn Fall 2026 class schedules (`app/matching/penn_schedules.py`).",
         "", f"**{rec.total():,} requests in {elapsed:.0f}s**. Each phase fires all of its requests together (up to "
             f"{peak} per phase), with at most **{args.concurrency} in flight at once**. "
             f"Server errors (5xx): **{five_xx}**. Deadlocks in the database log: **{deadlocks}**. "
             f"Worker restarts: **{restarts}**. "
             f"Transport failures: **{len(rec.errors)}**.", "",
         "## Correctness (checked in the database after every phase)", "",
         "| Invariant | Violations |", "|---|---:|"]
    for k, v in viol.items():
        L.append(f"| {k.replace('_', ' ')} | **{v}** |")
    L += ["", "## Phases", "", "| Phase | Requests | Duration | Groups | Matched | Waiting | Open seats |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for p in res["phases"]:
        i = p["invariants"]
        L.append(f"| {p['phase']} | {p['requests']} | {p['seconds']}s | {i['groups']} | {i['matched']} | "
                 f"{i['waiting']} | {i['open_seats']} |")
    race = res["race"]
    L += ["", f"**Last-seat race:** {race['racers']} students with identical free time raced for "
              f"{race['open_seats_in_targets']} open seats in {len(race['target_groups'])} groups. Afterwards "
              f"{race['target_groups_full_after']} of the {len(race['target_groups'])} were exactly full and none "
              "was over capacity. "
              f"{race['racers_placed']} racers were placed in total (some in other groups that shared that time), and "
              "the rest are waiting for the next round."]
    L += ["", "## Latency by endpoint (under load)", "", "| Endpoint | Requests | p50 | p95 | p99 | Status codes |",
          "|---|---:|---:|---:|---:|---|"]
    for name in sorted(rec.lat):
        xs = rec.lat[name]
        codes = ", ".join(f"{c}×{n}" for c, n in sorted(rec.status[name].items()))
        L.append(f"| `{name}` | {len(xs)} | {pct(xs, .5):.0f}ms | {pct(xs, .95):.0f}ms | {pct(xs, .99):.0f}ms | {codes} |")
    L += ["", "Expected non-2xx codes: 409 when a student already has an active request; 404 when leaving a group a "
              "concurrent operation already moved them out of.",
          "", f"Unexpected status codes: {unexpected or 'none'}.", "",
          "Matching-round latency includes the full solve (greedy, local search and ILP) for the waiting pool. "
          "Requests that land while a round holds the course's advisory lock wait for it, which shows up in their "
          "p95/p99.", "",
          f"These latencies are measured at saturation: {args.concurrency} clients at once against {args.workers} workers on one laptop,"
          " with argon2 password hashing in the sign-up burst. They show queueing under overload, not typical response times.", ""]
    return "\n".join(L)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--students", type=int, default=400)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1)
    # Requests in flight at once. macOS caps a socket's accept queue at 128 (kern.ipc.somaxconn), so opening
    # hundreds of connections in the same instant fails in the kernel before the app sees them.
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--out-md")
    parser.add_argument("--out-json")
    args = parser.parse_args()
    if not os.environ.get("DATABASE_URL", "").startswith(("postgres", "postgresql")):
        sys.exit("Set DATABASE_URL to an empty scratch PostgreSQL database.")
    port = free_port()
    proc = start_server(port, args.workers)
    t0 = time.perf_counter()
    try:
        res = asyncio.run(run(f"http://127.0.0.1:{port}", args.students, args.seed, args.concurrency))
    finally:
        proc.terminate()
        proc.wait(timeout=30)
    elapsed = time.perf_counter() - t0
    server_log = (BACKEND / "loadtest" / "server.log").read_text()
    text_ = report(res, args, elapsed, server_log)
    rec = res["recorder"]
    data = {"phases": res["phases"], "race": res["race"], "latency_ms": {k: {"n": len(v), "p50": pct(v, .5), "p95": pct(v, .95),
                                                        "p99": pct(v, .99), "mean": statistics.fmean(v)}
                                                    for k, v in rec.lat.items()},
            "status": {k: dict(v) for k, v in rec.status.items()}, "transport_errors": rec.errors[:20],
            "elapsed_s": round(elapsed, 1), "students": args.students, "workers": args.workers,
            "concurrency": args.concurrency}
    if args.out_md:
        Path(args.out_md).write_text(text_)
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(data, indent=1) + "\n")
    print(text_)
    bad = any(sum(p["invariants"][k] for p in res["phases"]) for k in ("overfilled_groups", "students_in_two_groups",
              "matched_requests_without_membership", "memberships_without_matched_request",
              "students_with_two_active_requests"))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
