"""Background matcher: `python -m app.matching.scheduler` (loops) or `--once` (single pass, e.g. from cron)."""
import argparse
import logging
import time

from app.core.config import settings
from app.db.session import SessionLocal
from app.matching.service import courses_due, run_course_matching

log = logging.getLogger("matcher")


def run_once() -> int:
    with SessionLocal() as db:
        due = courses_due(db)
    runs = 0
    for course_id in due:
        with SessionLocal() as db:
            try:
                run = run_course_matching(db, course_id, trigger="scheduled")
            except Exception:  # keep matching other courses if one fails
                db.rollback()
                log.exception("matching failed for course %s", course_id)
                continue
            if run:
                runs += 1
                log.info("course %s: %s/%s students placed in %s groups (ILP quality %.3f vs greedy %.3f)",
                         course_id, run.assigned, run.students, run.groups_created, run.ilp_quality,
                         run.greedy_quality)
    return runs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    while True:
        run_once()
        if args.once:
            break
        time.sleep(settings.match_interval_minutes * 60)


if __name__ == "__main__":
    main()
