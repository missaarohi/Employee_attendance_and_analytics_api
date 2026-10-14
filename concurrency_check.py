import json 
import random
import sys
import threading
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

BASE= sys.argv[1] if len(sys.argv)>1 else "http://127.0.0.1:8000"
N=10

def call(method, path, body=None):
    data=json.dumps(body).encode() if body is not None else None
    req=urllib.request.Request(BASE+path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"null")

def fire(n, make_request):
    barrier=threading.Barrier(n)

    def worker(i):
        method, path, body=make_request(i)
        barrier.wait()
        return call(method, path, body)

    with ThreadPoolExecutor(n) as pool:
        return list(pool.map(worker, range(n)))

def report(name, ok, detail):
    print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
    return ok

code= f"EMP{random.randint(100000, 999999)}"
results=[]

res=fire(N, lambda i:("POST", "/employees", {"emp_code": code, "name":"Race Test", "email": "race@example.com", "department": "QA", "joined_on": "2026-01-01"}))
counts=Counter( s for s, _ in res)
results.append(report("create employee", counts.get(201)==1 and counts.get(409)==N-1, dict(counts)))

IN_AT, OUT_AT = 1783312500000, 1783344900000
res=fire(N, lambda i: ("POST", "/attendance/punch-in", {"emp_code": code, "punched_at": IN_AT}))
counts=Counter(s for s, _ in res)
results.append(report("punch-in", counts.get(201)==1 and counts.get(409)==N-1, dict(counts)))

res=fire(N, lambda i: ("POST", "/attendance/punch-out", {"emp_code": code, "punched_at": OUT_AT}))
counts=Counter(s for s, _ in res)
results.append(report("punch-out", counts.get(200)==1 and counts.get(409)==N-1, dict(counts)))

statuses=["WFH", "ON_DUTY"]
res=fire(8, lambda i:("PATCH", f"/attendance/{code}/2026-07-06", {"status": statuses[i%2], "reason": f"parellel edit {i}", "regularized_by": "race.test"}))

counts=Counter(s for s, _ in res)
_, page=call("GET", f"/attendance?emp_code={code}&date_from=2026-07-06&date_to=2026-07-06")
history=len(page["items"][0]["history"])
results.append(report("regularize", history==counts.get(200, 0) and counts.get(200, 0)>=1, f"{dict(counts)}, history entries={history} (must equal the number if 200s)"))

print("\nALL PASSED" if all (results) else "\nSOMETHING FAILED")