import os
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "TEST_SECRET_NOT_FOR_PRODUCTION"
os.environ["ADMIN_EMAILS"] = "admin@upenn.edu"
os.environ["ILP_TIME_LIMIT_SECONDS"] = "5"
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.db.session import Base, get_db
from app.main import app
from app.models.entities import Course

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestSession = sessionmaker(bind=engine, expire_on_commit=False)

@pytest.fixture
def client():
    from app.core import email, ratelimit
    ratelimit.reset()
    email.OUTBOX.clear()
    Base.metadata.create_all(engine)
    with TestSession() as db:
        db.add(Course(code="CIS 1200", title="Programming", department="CS"))
        db.commit()
    def override_db():
        with TestSession() as db:
            yield db
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)

@pytest.fixture
def session_factory():
    """Direct DB access for tests that need to adjust state (e.g. backdating). Use with the client fixture."""
    return TestSession
