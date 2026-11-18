from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.matching.engine import NUM_SLOTS


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)


class Login(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    name: str


class MeOut(UserOut):
    is_admin: bool = False


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class EmailIn(BaseModel):
    email: EmailStr


class VerifyIn(BaseModel):
    token: str = Field(min_length=10, max_length=2000)


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    title: str
    department: str


class GroupCreate(BaseModel):
    course_id: int
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=3000)
    max_members: int = Field(default=8, ge=2, le=100)


class GroupUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=3000)
    max_members: int | None = Field(default=None, ge=2, le=100)


class GroupOut(BaseModel):
    id: int
    course_id: int
    course_code: str
    owner_id: int | None
    title: str
    description: str
    max_members: int
    member_count: int
    created_at: datetime
    kind: Literal["manual", "matched"] = "manual"
    match_quality: float | None = None
    common_slots: list[int] = []
    waitlist_count: int = 0
    meetings_reported: int = 0
    viewer_status: Literal["member", "waitlisted"] | None = None
    viewer_waitlist_position: int | None = None


class Page(BaseModel):
    items: list[GroupOut]
    total: int
    page: int
    page_size: int


Goal = Literal["exam_prep", "homework", "concepts", "projects"]


def _check_slots(v: list[int]) -> list[int]:
    slots = sorted(set(v))
    if any(s < 0 or s >= NUM_SLOTS for s in slots):
        raise ValueError(f"availability slots must be between 0 and {NUM_SLOTS - 1}")
    if len(slots) < 2:
        raise ValueError("select at least 2 free hours per week")
    return slots


class MatchRequestCreate(BaseModel):
    course_id: int
    goal: Goal
    pace: int = Field(ge=1, le=3)
    preferred_size: int = Field(ge=3, le=6)
    availability: list[int] = Field(max_length=NUM_SLOTS * 2)
    _slots = field_validator("availability")(_check_slots)


class MatchRequestUpdate(BaseModel):
    goal: Goal | None = None
    pace: int | None = Field(default=None, ge=1, le=3)
    preferred_size: int | None = Field(default=None, ge=3, le=6)
    availability: list[int] | None = Field(default=None, max_length=NUM_SLOTS * 2)

    @field_validator("availability")
    @classmethod
    def slots(cls, v):
        return None if v is None else _check_slots(v)


class MatchRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    course_id: int
    course_code: str
    exam_id: int | None
    goal: str
    pace: int
    preferred_size: int
    availability: list[int]
    status: str
    group_id: int | None
    created_at: datetime
    matched_at: datetime | None


class ExamCreate(BaseModel):
    course_id: int
    name: str = Field(min_length=1, max_length=120)
    exam_date: date


class ExamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    course_id: int
    name: str
    exam_date: date


class CheckinCreate(BaseModel):
    met: bool
    met_on: date


class MatchRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    course_id: int
    exam_id: int | None
    trigger: str
    algorithm: str
    students: int
    assigned: int
    groups_created: int
    greedy_quality: float
    local_search_quality: float
    ilp_quality: float
    greedy_overlap_hours: float
    ilp_overlap_hours: float
    runtime_ms: int
    created_at: datetime
