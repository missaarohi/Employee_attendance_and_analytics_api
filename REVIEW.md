<!-- # REVIEW.md

List every defect you found in the starter `app/main.py` (helpers and endpoints). For each one:

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | | | | |

Also note anything you looked at and decided was **not** a defect, and why. -->

# REVIEW.md

Defects found in the starter `app/main.py` (helpers and endpoints), with the example that exposes each one and the fix.

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | `compute_late_minutes` | Builds the shift start from the punch-in's own naive date and time, with no IST handling, so the result depends on the server's time zone. An overnight shift is not handled either. | On a UTC server, a punch-in at 10:05 IST (`punched_at=1783312500000`, shift 09:30) returns `0`; the rule gives `35`. On an IST laptop the bug hides. | Convert the instant to IST, take the attendance date from rule R1 (overnight aware), and build the shift start from that date in IST. |
| 2 | `compute_late_minutes` | Takes the floor in minutes first and then tests `> 10`, so a punch-in 1 to 59 seconds past the grace period counts as on time. | Shift 09:30, punch-in 09:40:01 returns `0`; R2 gives `10`. | Compare in seconds (`> 600`), then take whole minutes since `shift_start`. |
| 3 | `compute_work_hours` | Uses float `round()`, which is not half-up (R4). | 11250 seconds (3.125 h) returns `3.12`; R4 gives `3.13`. | Compute with `Decimal` and quantize with `ROUND_HALF_UP`. |
| 4 | `compute_overtime` | Subtracts an aware datetime from a naive one, so it raises. The shift end of an overnight shift falls on the same day instead of the next. There is no 30-minute minimum (R3). | Calling it with a naive `punch_out` raises `TypeError: can't subtract offset-naive and offset-aware datetimes`. For shift 22:00-06:00 the end is computed as 06:00 on the shift date instead of the next day. | `shift_end_dt` builds an aware IST end and adds a day for overnight shifts; overtime counts only when the floor of minutes is at least 30. |
| 5 | `EmployeeIn` | No validation: any `emp_code`, email, shift strings and `joined_on`; `shift_start == shift_end` is accepted. | `POST /employees` with `shift_start: "25:99"` or `joined_on: "not-a-date"` returns 201. | Pydantic constraints (patterns, lengths), a date validator for `joined_on`, and a model validator for the shifts. |
| 6 | `PunchInIn` | `punched_at` accepts numeric strings, whole-number floats and values in seconds; `status` accepts any string, including `ABSENT`. | `{"punched_at": 1783312500}` (seconds) or `{"status": "ABSENT"}` is accepted. | Strict integer epoch-millisecond type with a range check, and a `Literal` of the three presence statuses. |
| 7 | `create_employee` | Check-then-insert (`find_one`, then `insert_one`) with no unique index, so parallel creates can both succeed. `created_at` is local naive time and the response returns a datetime, not epoch milliseconds. | Two simultaneous requests with the same `emp_code` can both return 201. | Unique index on `emp_code`, catch `DuplicateKeyError` and return 409; store UTC and return milliseconds. |
| 8 | `list_employees` | `skip = page * page_size` skips the first page. `total` counts the whole collection, not the filter. No sort. No validation of `page` and `page_size`. `created_at` is a datetime. | `GET /employees?page=1` returns `items: []` with `total: 6`. `?department=Sales` still gives `total: 6`. `page=-1` gives a negative skip and a 500. `page_size=0` returns everything. | `(page - 1) * page_size`, `count_documents(filter)`, sort by `emp_code`, `Query(ge=1)` and `Query(ge=1, le=100)`, epoch milliseconds. |
| 9 | `punch_in` | An unknown employee makes `emp["shift_start"]` raise (500). The time comes from `datetime.fromtimestamp` in the server's local zone, the date ignores IST and overnight shifts, and the time is not truncated to whole seconds. Check-then-insert is racy. The response leaks `id` and returns raw datetimes. | `emp_code: "EMP9999"` returns 500. Two parallel punch-ins can both return 201. | 404 for an unknown employee; UTC time truncated to seconds; IST attendance date per R1; unique `(emp_code, date)` index with `DuplicateKeyError` mapped to 409; serializer without `_id` and with epoch milliseconds. |
| 10 | `list_attendance` | Loads every matching document into memory and sorts and pages it in Python. Sorts by date only (the contract adds `emp_code`). Exposes `id`. No validation of dates, `status`, `page` or `page_size`, and no 422 when `date_from > date_to`. Missing legacy fields (`history`, `half_day`) are not defaulted. | Slow at 100,000 records. `date_from=2026-07-09&date_to=2026-07-01` returns 200. Legacy records lack `half_day` and `history` in the response. | Filter, `sort([("date", -1), ("emp_code", 1)])`, `skip` and `limit` in MongoDB, backed by an index; validation with 422; defaults in the serializer. |
| 11 | `health` | Always returns `ok`, even when MongoDB is down. | Stop MongoDB and `GET /health` still returns 200. | Ping the database and return 503 on failure. |
| 12 | Startup and `MongoClient` | No indexes are created. The client returns naive datetimes (no `tz_aware`), and the default server selection timeout is 30 s. | `explain` shows `COLLSCAN`; naive and aware datetimes cannot be subtracted. | `create_indexes()` runs at startup (idempotent); `tz_aware=True`; `serverSelectionTimeoutMS=5000`. |

## Looked at and judged fine

- `load_dotenv()` does not override real environment variables by default, which is what the contract requires.
- The `IST` constant (`UTC+05:30`) is correct.
- Returning 409 for a duplicate `emp_code` is the right status; only the way it was detected (check-then-insert) was wrong.
- The `{"_id": 0}` projection in `list_employees` is correct.