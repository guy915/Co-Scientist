"""Check 3 re-check: bare DBOS, no workflows and none of the prototype. Counts write transactions over 30 s idle."""
import collections, os, sys, tempfile, threading, time
from sqlalchemy import event
from sqlalchemy.engine import Engine
from dbos import DBOS

log = []
@event.listens_for(Engine, "connect")
def _t(conn, _):
    conn.set_trace_callback(lambda s: log.append((time.time(), threading.current_thread().name, s.split(" ")[0] + " " + " ".join(s.split()[1:3]))))

d = tempfile.mkdtemp()
DBOS(config={"name": "bare", "system_database_url": f"sqlite:///{d}/bare.db", "log_level": "ERROR"})
DBOS.launch()
time.sleep(3)
start = time.time(); time.sleep(30); end = time.time()
w = [x for x in log if start <= x[0] <= end]
print("BEGIN IMMEDIATE in 30s:", sum(1 for x in w if x[2].startswith("BEGIN IMMEDIATE")))
print(collections.Counter((t, s) for _, t, s in w if s.split()[0] in ("UPDATE", "INSERT", "DELETE")).most_common())
DBOS.destroy()
