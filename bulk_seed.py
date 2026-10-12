import os
import random
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"), tz_aware=True)
db=client["attendance_load"]
db.employees.drop()
db.attendance_logs.drop()

DEPTS=["Engineering", "Sales", "Support", "Ops", "HR"]
now=datetime.now(timezone.utc)
db.employees.insert_many([
    {"emp_code": f"EMP{i:04d}", "name": f"Emp{i}", "email": f"email{i}@example.com",
     "department": DEPTS[i%5], "shift_start": "09:30", "shift_end":"18:30", 
     "joined_on":"2025-01-01", "created_at": now}
     for i in range(1, 201)
])

days, d=[], date(2025, 1, 1)
while len(days)<500:
    if d.weekday()<5:
        days.append(d)
    d+=timedelta(days=1)
logs=[]
for i in range(1, 201):
    for day in days:
        m=random.randint(-10, 45)
        pin=datetime(day.year, day.month, day.day, 4, 0, tzinfo=timezone.utc)+timedelta(minutes=m)
        hours=round(random.uniform(4, 10), 2)
        logs.append({
            "emp_code": f"EMP{i:04d}", "date": day.isoformat(), "status": "PRESENT", 
            "punch_in": pin, "punch_out": pin+timedelta(hours=hours), "work_hours": hours,
            "late_minutes": m if m>10 else 0, "overtime_minutes": 0,
            "half_day": hours<4.5, "history":[],
        })

db.attendance_logs.insert_many(logs, ordered=False)
print(f"inserted{len(logs)} logs")