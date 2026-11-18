"""Save a dated snapshot of real-world outcome metrics, for the README's "Real-world results" section.

    python -m app.results --out ../docs/results      # writes results-YYYY-MM-DD.json and prints a summary

Run it after each exam round. Snapshots contain only aggregates (no names or emails).
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.matching.service import compute_metrics
from app.models.entities import Course, MatchRequest, MatchRun, StudyGroup, utcnow

METHOD = {
    "users": ("Accounts on the site. When email verification is on, only accounts that confirmed their email "
              "address; verified_users always counts confirmed accounts."),
    "students_requested_match": "Students who submitted at least one match request.",
    "pct_groups_met_at_least_once/twice": ("Share of matched groups at least 7 days old where members reported meeting "
                                           "on at least 1 / 2 distinct dates via the in-app check-in."),
    "retention_pct": "Students who requested matching in 2+ distinct course/exam cycles, out of all requesters.",
    "time_to_match_hours": "Hours from submitting a request to being placed in a group (median, p90).",
    "algorithm": "ILP vs greedy on the same real request pool each round, weighted by students placed.",
}


def snapshot() -> dict:
    with SessionLocal() as db:
        first, last = db.execute(select(func.min(MatchRequest.created_at), func.max(MatchRequest.created_at))).one()
        per_course = Counter(code for (code,) in db.execute(
            select(Course.code).join(MatchRequest, MatchRequest.course_id == Course.id)))
        groups = Counter(code for (code,) in db.execute(
            select(Course.code).join(StudyGroup, StudyGroup.course_id == Course.id).where(StudyGroup.kind == "matched")))
        return {
            "generated_at": utcnow().isoformat(timespec="seconds"),
            "period": {"first_request": first.isoformat() if first else None,
                       "last_request": last.isoformat() if last else None},
            "metrics": compute_metrics(db),
            "per_course": {code: {"match_requests": n, "matched_groups": groups.get(code, 0)}
                           for code, n in sorted(per_course.items())},
            "matching_rounds": db.scalar(select(func.count(MatchRun.id))) or 0,
            "method": METHOD,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="directory to write results-YYYY-MM-DD.json into")
    args = parser.parse_args()
    data = snapshot()
    m = data["metrics"]
    print(f"Period: {data['period']['first_request']} → {data['period']['last_request']}")
    print(f"Students: {m['users']} (verified email: {m['verified_users']}) · requested matching: {m['students_requested_match']} "
          f"· courses: {m['courses_with_requests']} · matched groups: {m['matched_groups']}")
    print(f"Met ≥1: {m['pct_groups_met_at_least_once']}% · met ≥2: {m['pct_groups_met_at_least_twice']}% "
          f"(of {m['groups_eligible_for_meeting_stats']} groups ≥7 days old)")
    print(f"Retention: {m['retention_pct']}% · time to match: median {m['time_to_match_hours_median']}h, "
          f"p90 {m['time_to_match_hours_p90']}h")
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"results-{data['generated_at'][:10]}.json"
        path.write_text(json.dumps(data, indent=2) + "\n")
        print(f"Saved {path}")


if __name__ == "__main__":
    main()
