"""
Employee Attendance & Analytics API

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience; real env vars win)
"""
import os
import re
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

load_dotenv()  # override=False by default, so real environment variables take priority

# tz_aware=True: PyMongo returns timezone-aware (UTC) datetimes instead of naive ones.
client = MongoClient(
    os.getenv("MONGO_URI", "mongodb://localhost:27017"),
    tz_aware=True,
    serverSelectionTimeoutMS=5000,
)
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

HHMM_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

Status = Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]
PresenceStatus = Literal["PRESENT", "WFH", "ON_DUTY"]

# Epoch milliseconds: strict int (no floats / strings), seconds-looking values rejected.
EpochMs = Annotated[int, Field(strict=True, ge=100_000_000_000, le=4_102_444_800_000)]


def create_indexes() -> None:
    """Idempotent: creating an index that already exists is a no-op."""
    db.employees.create_index("emp_code", unique=True)
    db.employees.create_index([("department", 1), ("emp_code", 1)])
    # One record per (emp_code, date): this is what makes punch-in race-safe.
    db.attendance_logs.create_index([("emp_code", 1), ("date", 1)], unique=True)
    # GET /attendance: sort date desc, emp_code asc (with and without a status filter)
    db.attendance_logs.create_index([("date", -1), ("emp_code", 1)])
    db.attendance_logs.create_index([("status", 1), ("date", -1), ("emp_code", 1)])
    db.attendance_logs.create_index([("emp_code", 1), ("punch_in", -1)])


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_indexes()
    yield


app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def to_ms(dt: datetime) -> int:
    """datetime -> epoch milliseconds (naive datetimes are treated as UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - EPOCH) // timedelta(milliseconds=1)


def to_ms_or_none(dt: Optional[datetime]) -> Optional[int]:
    return None if dt is None else to_ms(dt)


def from_ms(ms: int) -> datetime:
    """epoch milliseconds -> timezone-aware UTC datetime (no float maths)."""
    return EPOCH + timedelta(milliseconds=ms)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_hhmm(value: str) -> time:
    h, m = map(int, value.split(":"))
    return time(h, m)


def attendance_date(punch_in: datetime, shift_start: str, shift_end: str) -> str:
    """R1: the IST calendar date of the punch-in; for an overnight shift, a punch-in
    earlier than shift_end belongs to the shift that started the previous day."""
    ist = punch_in.astimezone(IST)
    d = ist.date()
    overnight = shift_end <= shift_start  # "HH:MM" zero-padded, so string compare works
    if overnight and ist.time() < parse_hhmm(shift_end):
        d -= timedelta(days=1)
    return d.isoformat()


def shift_start_dt(date_str: str, shift_start: str) -> datetime:
    return datetime.combine(date.fromisoformat(date_str), parse_hhmm(shift_start), tzinfo=IST)


def shift_end_dt(date_str: str, shift_start: str, shift_end: str) -> datetime:
    end = datetime.combine(date.fromisoformat(date_str), parse_hhmm(shift_end), tzinfo=IST)
    if shift_end <= shift_start:  # overnight shift ends on the next calendar day
        end += timedelta(days=1)
    return end


def compute_late_minutes(punch_in: datetime, shift_start: str, date_str: str) -> int:
    """R2: late only if strictly more than 10:00 after shift_start; then floor minutes since shift_start."""
    start = shift_start_dt(date_str, shift_start)
    seconds = int((punch_in - start).total_seconds())  # punch_in is already whole seconds
    return seconds // 60 if seconds > 600 else 0


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    """R4: seconds / 3600, rounded to 2 decimals half-up (Decimal, not float round())."""
    seconds = Decimal(int((punch_out - punch_in).total_seconds()))
    return float((seconds / Decimal(3600)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_overtime(punch_out: datetime, end: datetime) -> int:
    """R3: floor minutes after shift end, counted only if at least 30."""
    seconds = int((punch_out - end).total_seconds())
    minutes = seconds // 60
    return minutes if minutes >= 30 else 0


def serialize_attendance(doc: dict) -> dict:
    """Mongo document -> API shape: no _id, instants as epoch ms, defaults for legacy records."""
    history = []
    for h in doc.get("history") or []:
        changes = {}
        for key, change in (h.get("changes") or {}).items():
            if key in ("punch_in", "punch_out"):
                change = {
                    "from": to_ms_or_none(change.get("from")),
                    "to": to_ms_or_none(change.get("to")),
                }
            changes[key] = change
        history.append(
            {"at": to_ms(h["at"]), "by": h.get("by"), "reason": h.get("reason"), "changes": changes}
        )
    return {
        "emp_code": doc["emp_code"],
        "date": doc["date"],
        "status": doc["status"],
        "punch_in": to_ms_or_none(doc.get("punch_in")),
        "punch_out": to_ms_or_none(doc.get("punch_out")),
        "work_hours": doc.get("work_hours"),
        "late_minutes": doc.get("late_minutes", 0),
        "overtime_minutes": doc.get("overtime_minutes", 0),
        "half_day": doc.get("half_day", False),
        "history": history,
    }


def parse_date_param(value: Optional[str], name: str) -> Optional[str]:
    """Validate a YYYY-MM-DD query parameter (real calendar date) or raise 422."""
    if value is None:
        return None
    try:
        if not DATE_RE.match(value):
            raise ValueError
        date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, f"{name} must be a valid date in YYYY-MM-DD format")
    return value


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    department: str = Field(min_length=1, max_length=50)
    shift_start: str = Field(default="09:30", pattern=HHMM_PATTERN)
    shift_end: str = Field(default="18:30", pattern=HHMM_PATTERN)
    joined_on: str

    @field_validator("joined_on")
    @classmethod
    def joined_on_is_a_date(cls, v: str) -> str:
        if not DATE_RE.match(v):
            raise ValueError("joined_on must be YYYY-MM-DD")
        date.fromisoformat(v)  # rejects things like 2026-02-30
        return v

    @model_validator(mode="after")
    def shifts_differ(self):
        if self.shift_start == self.shift_end:
            raise ValueError("shift_start must differ from shift_end")
        return self


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[EpochMs] = None
    status: PresenceStatus = "PRESENT"

class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[EpochMs]=None


class RegularizeIn(BaseModel):
    status: Optional[Status] = None
    punch_in: Optional[EpochMs] = None
    punch_out: Optional[EpochMs] = None
    reason: str =Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def no_punch_time_with_absent_or_leave(self):
        if self.status in("ABSENT", "LEAVE") and (
            self.punch_in is not None or self.punch_out is not None
        ):
            raise ValueError("punch_in / punch_out cannot be sent with status ABSENT or LEAVE")
        return self
# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        client.admin.command("ping")
    except PyMongoError:
        raise HTTPException(503, "database unavailable")
    return {"status": "ok"}


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    now = utcnow()
    doc["created_at"] = now.replace(microsecond=(now.microsecond // 1000) * 1000)  # BSON keeps ms
    try:
        db.employees.insert_one(doc)  # the unique index decides, not a find_one beforehand
    except DuplicateKeyError:
        raise HTTPException(409, "emp_code already exists")
    doc.pop("_id", None)
    doc["created_at"] = to_ms(doc["created_at"])
    return doc


@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    q = {}
    if department:
        q["department"] = department
    skip = (page - 1) * page_size
    total = db.employees.count_documents(q)
    items = list(
        db.employees.find(q, {"_id": 0}).sort("emp_code", 1).skip(skip).limit(page_size)
    )
    for it in items:
        it["created_at"] = to_ms(it["created_at"])
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code}, {"_id": 0})
    if emp is None:
        raise HTTPException(404, "employee not found")
    ts = from_ms(body.punched_at) if body.punched_at is not None else utcnow()
    ts = ts.replace(microsecond=0)  # R1: truncate to whole seconds before any calculation
    d = attendance_date(ts, emp["shift_start"], emp["shift_end"])
    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts, emp["shift_start"], d),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    try:
        db.attendance_logs.insert_one(doc)  # unique (emp_code, date) index makes this race-safe
    except DuplicateKeyError:
        raise HTTPException(409, "already punched in for this date")
    return serialize_attendance(doc)


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp=db.employees.find_one({"emp_code": body.emp_code}, {"_id": 0})
    if emp is None:
        raise HTTPException(404, "employee not found")
    ts=from_ms(body.punched_at) if body.punched_at is not None else utcnow()
    ts=ts.replace(microsecond=0)

    rec=db.attendance_logs.find_one(
        {"emp_code":body.emp_code, "punch_in": {"$lte": ts}},
        sort=[("punch_in", -1)],
    )
    if rec is None:
        raise HTTPException(404, "no punch-in found")
    if rec.get("punch_out") is not None:
        raise HTTPException(409, "already punched out")
    punched_in = rec["punch_in"]
    if ts<=punched_in:
        raise HTTPException(422, "punched_at must be after punch_in")
    if ts-punched_in> timedelta(hours=24):
        raise HTTPException(422, "punch_out must be within 24 hours of punch_in")

    work_hours=compute_work_hours(punched_in, ts)
    end=shift_end_dt(rec["date"], emp["shift_start"], emp["shift_end"])

    updated=db.attendance_logs.find_one_and_update(
        {"_id": rec["_id"], "punch_out": None},
        {
            "$set": {
                "punch_out": ts,
                "work_hours": work_hours,
                "overtime_minutes": compute_overtime(ts, end),
                "half_day": work_hours < 4.5,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(409, "already punched out")
    return serialize_attendance(updated)

@app.patch("/attendance/{emp_code}/{date}")
def regularise_attendance(emp_code: str, date: str, body: RegularizeIn):
    rec_date = parse_date_param(date, "date")
    emp=db.employees.find_one({"emp_code": emp_code}, {"_id":0})
    if emp is None:
        raise HTTPException(404, "employee not found")
    rec=db.attendance_logs.find_one({"emp_code": emp_code, "date": rec_date})
    if rec is None:
        raise HTTPException(404, "no attendance record for that date")

    old_status=rec["status"]
    old_in=rec.get("punch_in")
    old_out=rec.get("punch_out")

    new_status=body.status or old_status
    new_in, new_out=old_in, old_out
    if body.punch_in is not None:
        new_in = from_ms(body.punch_in).replace(microsecond=0)
    if body.punch_out is not None:
        new_out=from_ms(body.punch_out).replace(microsecond=0)

    if new_status in("ABSENT", "LEAVE"):
        if body.punch_in is not None or body.punch_out is not None:
            raise HTTPException(422, "send a presence status together with punch times")
        new_in=new_out=None
    else:
        if new_in is None:
            raise HTTPException(422, "a presence status requires a punch_in")
        if body.punch_in is not None and(
            attendance_date(new_in, emp["shift_start"], emp["shift_end"]) !=rec_date
        ):
            raise HTTPException(422, "punch_in must stay on the record's attendance date")
        if new_out is not None:
            if new_out<=new_in:
                raise HTTPException(422, "punch_out must be after punch_in")
            if new_out - new_in> timedelta(hours=24):
                raise HTTPException(422, "punch_out must be within 24 hours of punch_in")

    if new_in is None:
        late, work_hours, overtime, half_day = 0, None, 0, False
    else:
        late=compute_late_minutes(new_in, emp["shift_start"], rec_date)
        if new_out is None:
            work_hours, overtime, half_day=None, 0, False
        else:
            work_hours = compute_work_hours(new_in, new_out)
            end=shift_end_dt(rec_date, emp["shift_start"], emp["shift_end"])
            overtime=compute_overtime(new_out, end)
            half_day=work_hours<4.5

    new_vals= {
        "status": new_status,
        "punch_in": new_in,
        "punch_out": new_out, 
        "work_hours": work_hours,
        "late_minutes": late,
        "overtime_minutes": overtime,
        "half_day": half_day,
    }

    old_vals={
        "status": old_status,
        "punch_in": old_in, 
        "punch_out": old_out,
        "work_hours" : rec.get("work_hours"),
        "late_minutes": rec.get("late_minutes", 0),
        "overtime_minutes": rec.get("overtime_minutes", 0),
        "half_day": rec.get("half_day", False),
    }
    changes={
        k:{"from": old_vals[k], "to": new_vals[k]} for k in new_vals if new_vals[k]!=old_vals[k]
    }
    if not changes:
        raise HTTPException(422, "request changes nothing")

    now =utcnow()
    entry={
        "at": now.replace(microsecond=(now.microsecond//1000) * 1000),
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": changes,
    }

    n=len(rec.get("history") or [])
    if n:
        history_guard = {"history": {"$size": n}}
    else:
        history_guard = {"$or": [{"history" : {"$exists": False}}, {"history": {"$size": 0}}]}
    updated = db.attendance_logs.find_one_and_update(
        {
            "_id": rec["_id"], 
            "status": old_status, 
            "punch_in": old_in, 
            "punch_out": old_out, 
            **history_guard,
        },
        {"$set": new_vals, "$push": {"history": entry}}, 
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(409, "record was modified concurrently, please retry")
    return serialize_attendance(updated)


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[Status] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    date_from = parse_date_param(date_from, "date_from")
    date_to = parse_date_param(date_to, "date_to")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must not be after date_to")
    q = {}
    if emp_code:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        q["status"] = status
    total = db.attendance_logs.count_documents(q)
    cursor = (
        db.attendance_logs.find(q, {"_id": 0})
        .sort([("date", -1), ("emp_code", 1)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [serialize_attendance(d) for d in cursor]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


# --------------------------------------------------------------------------- #
#TODO - the rest of the contract (see openapi.yaml):

#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #