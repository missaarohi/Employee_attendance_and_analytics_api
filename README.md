# Employee Attendance & Analytics API

FastAPI + MongoDB service for punch-in/out, manual corrections with an audit trail, and attendance analytics. All application code is in `app/main.py`.

## Run

Requires Python 3.11+ and MongoDB 6.0+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export MONGO_URI="mongodb://localhost:27017"
export MONGO_DB="attendance_db"
uvicorn app.main:app --port 8000
```

`MONGO_URI` and `MONGO_DB` are read from the environment (a local `.env` also works; real environment variables take priority). Indexes are created at startup, nothing to do by hand. Interactive docs are at `/docs`.

## Notes

- All 12 endpoints of the contract are implemented.
- Analytics use MongoDB aggregation pipelines. In the department trend, the daily counts and the gap filling (`$densify`) run in MongoDB; the daily rates and the 7-day moving average are computed in Python on the (at most 92) returned rows, so that rounding is exactly half-up.
- Tested by hand through Swagger on the sample data and on a generated dataset of 100,000 records (`/admin/explain` shows `IXSCAN` and no `COLLSCAN` for all five endpoints).
- `concurrency_check.py` fires parallel requests at a running server (create employee, punch-in, punch-out, regularize) and checks that exactly one request wins each race and that every successful regularization leaves exactly one history entry. Run it with `python concurrency_check.py http://127.0.0.1:8000`. There is no other automated test suite.