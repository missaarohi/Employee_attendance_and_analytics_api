<!-- # DECISIONS.md

1. **Indexes.** `employees`: unique `emp_code` (uniqueness guarantee) and `(department, emp_code)` (department filter with emp_code sort). `attendance_logs`: unique `(emp_code, date)` (one record per day, race-safe punch-in, monthly employee query), `(date desc, emp_code)` (list sort and month-range analytics), `(status, date desc, emp_code)` (status filter) and `(emp_code, punch_in desc)` (finding the latest punch-in for punch-out). I rejected a separate `emp_code` index on logs because the unique compound index already covers it.
2. **Punch-in race.** Both requests try `insert_one` on the same `(emp_code, date)`. The unique index lets exactly one succeed (201); the other gets `DuplicateKeyError`, which I return as 409. There is no check-then-insert.
3. **Ties.** I rank with `$setWindowFields` and `$rank` (1, 2, 2, 4) and then keep `rank <= limit`. All tied employees at the cutoff are returned, so there can be more than `limit` rows. Rows are ordered by late minutes, then `emp_code`.
4. **Headcount.** Headcount is a separate aggregation on `employees` only (`joined_on` before the next month starts), so employees with zero logs are counted. I merge it with the log stats by department.
5. **100x data.** I would replace skip/limit pagination with keyset pagination, and store the department on each log (or pre-aggregate monthly totals) to avoid the `$lookup` on every log. -->

# DECISIONS.md

1. **Indexes.** `employees`: `emp_code` (unique) and `(department, emp_code)`. `attendance_logs`: `(emp_code, date)` unique, `(date -1, emp_code)`, `(status, date -1, emp_code)` and `(emp_code, punch_in -1)`. They serve identity, one record per day, list sorting, month and range scans, the status filter and the punch-out lookup. I rejected storing the department in every log: it goes stale and the date range is already selective.

2. **Punch-in race.** Both requests compute the same date and call `insert_one`. The unique `(emp_code, date)` index lets one succeed; the other raises `DuplicateKeyError`, which I return as 409. There is no find-then-insert gap.

3. **Ties.** `$rank` in `$setWindowFields` gives tied employees one rank and skips the next. `limit` is applied as `rank <= limit`, so everyone tied at the cutoff is returned, ordered by `emp_code`.

4. **Headcount.** It is counted from `employees` alone (department, `joined_on` before the next month) and merged by department with the log totals, so people with no logs count and future joiners do not.

5. **100x data.** I would keep a pre-aggregated daily summary per department, updated on punch and regularization, so analytics read a few rows instead of scanning and joining a month of logs.