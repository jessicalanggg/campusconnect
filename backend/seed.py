from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.entities import Course

COURSES = [
    ("CIS 1200", "Programming Languages and Techniques I", "Computer Science"),
    ("CIS 1210", "Data Structures and Algorithms", "Computer Science"),
    ("CIS 1600", "Mathematical Foundations of Computer Science", "Computer Science"),
    ("MATH 1400", "Calculus, Part I", "Mathematics"),
    ("PHYS 0150", "Principles of Physics I", "Physics"),
    ("ECON 0100", "Introduction to Microeconomics", "Economics"),
    ("CIS 2400", "Introduction to Computer Systems", "Computer Science"),
]
with SessionLocal() as db:
    for code, title, department in COURSES:
        if not db.scalar(select(Course).where(Course.code == code)):
            db.add(Course(code=code, title=title, department=department))
    db.commit()
print("Courses seeded")
