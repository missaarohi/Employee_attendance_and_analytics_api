import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from pymongo import MongoClient

EXTRA_EMPLOYEES = [
    ("EMP0007", "Sales", "2026-07-01"),
    ("EMP0008", "Sales", "2026-07-20"),
    ("EMP0009", "Ops", "2026-08-05"),
]


def log(code, day, status="PRESENT", late=0, hours=None, half=False):
    return {
        "emp_code": code, "date": day, "status": status, "punch_in": None, "punch_out": None,
        "work_hours": hours, "late_minutes": late, "overtime_minutes": 0, "half_day": half, "history": [],
    }


EXTRA_LOGS = [
    log("EMP0001", "2026-07-08", late=20, hours=8.0),
    log("EMP0002", "2026-07-15", late=20, hours=8.5),
    log("EMP0004", "2026-07-09", status="ON_DUTY", late=20, hours=7.01),
    log("EMP0006", "2026-07-10", late=5, hours=8.0),
    log("EMP0007", "2026-07-11", hours=3.0, half=True),  # a Saturday
    log("EMP0003", "2026-07-13", status="WFH", hours=8.12),
    log("EMP0099", "2026-07-06", late=50),  # employee does not exist
]


def seed(db):
    now = datetime.now(timezone.utc)
    for code, dept, joined in EXTRA_EMPLOYEES:
        doc = {"emp_code": code, "name": code, "email": f"{code.lower()}@example.com", "department": dept,
               "shift_start": "09:30", "shift_end": "18:30", "joined_on": joined, "created_at": now}
        db.employees.replace_one({"emp_code": code}, doc, upsert=True)
    for doc in EXTRA_LOGS:
        db.attendance_logs.replace_one({"emp_code": doc["emp_code"], "date": doc["date"]}, doc, upsert=True)
    print(f"added {len(EXTRA_EMPLOYEES)} employees and {len(EXTRA_LOGS)} logs")


if __name__ == "__main__":
    load_dotenv()
    mongo = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"), tz_aware=True)
    seed(mongo[os.getenv("MONGO_DB", "attendance_db")])