<!-- # Candidate kit

Read in this order:

1. `PROBLEM_STATEMENT.docx`: what you are asked to do, how it is evaluated.
2. `openapi.yaml`: the API contract and the business rules (R1 - R10).
3. `DATA_MODEL.md`: what is stored in MongoDB, with nine sample documents.
4. `app/main.py`: the starter. Put **all** your code in this one file. It must start with `uvicorn app.main:app --port 8000`.
5. `REVIEW.md`, `DECISIONS.md`: templates to fill in.

`sample_data/` holds the nine sample documents as MongoDB Extended JSON; `sample_seed.py` loads them. The grader's dataset is
much larger and contains cases they do not show.

## Local setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # set MONGO_URI / MONGO_DB (local docker: docker run -p 27017:27017 mongo:7)
python sample_seed.py
uvicorn app.main:app --port 8000 --reload
```
MongoDB **6.0 or newer** is required (the grader uses 7.0). MongoDB Atlas free tier (M0) works.

## Submit
A public Git repository with `app/main.py`, `requirements.txt`, `REVIEW.md`, `DECISIONS.md` and a short `README.md`.
No `.env`, no secrets, no Dockerfile. -->


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
- Tested by hand through Swagger on the sample data and on a generated dataset of 100,000 records (`/admin/explain` shows `IXSCAN` and no `COLLSCAN` for all five endpoints). There is no automated test suite, and parallel requests (punch-in, punch-out, regularization) rely on a unique index and conditional updates but were not stress-tested.