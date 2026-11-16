"""SQLite store: every job ever seen, per-run stats and per-source logs.

A job is identified by its normalised URL *and* by company+title, so the same
posting arriving from Greenhouse and from Adzuna is only kept once, and a job
that was already scored or shown is never handed to scoring again.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from common import DATA_DIR, Job, company_title_key, normalize_url

DB_PATH = DATA_DIR / "jobs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    ckey TEXT NOT NULL,
    title TEXT, company TEXT, location TEXT, remote TEXT, posted TEXT,
    source TEXT, bucket TEXT,
    first_seen TEXT, last_seen TEXT,
    -- state: candidate (passed pre-filter, awaiting scoring) | scored | shown | dropped
    state TEXT NOT NULL DEFAULT 'candidate',
    fit REAL, data TEXT
);
CREATE INDEX IF NOT EXISTS jobs_ckey ON jobs(ckey);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started TEXT, finished TEXT, stats TEXT
);
CREATE TABLE IF NOT EXISTS source_log (
    run_id INTEGER, source TEXT, status TEXT, fetched INTEGER, kept INTEGER,
    seconds REAL, error TEXT
);
"""


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def start_run(con) -> int:
    cur = con.execute("INSERT INTO runs(started) VALUES (?)", (now(),))
    con.commit()
    return cur.lastrowid


def finish_run(con, run_id: int, stats: dict):
    con.execute("UPDATE runs SET finished=?, stats=? WHERE id=?", (now(), json.dumps(stats), run_id))
    con.commit()


def log_source(con, run_id, source, status, fetched=0, kept=0, seconds=0.0, error=""):
    con.execute(
        "INSERT INTO source_log VALUES (?,?,?,?,?,?,?)",
        (run_id, source, status, fetched, kept, round(seconds, 1), error[:500]),
    )
    con.commit()


def is_known(con, job: Job) -> bool:
    """True if this job (by URL or by company+title) is already in the DB in any state."""
    url = normalize_url(job.url)
    ckey = company_title_key(job.company, job.title)
    row = con.execute("SELECT 1 FROM jobs WHERE url=? OR ckey=? LIMIT 1", (url, ckey)).fetchone()
    return row is not None


def touch_seen(con, job: Job):
    con.execute(
        "UPDATE jobs SET last_seen=? WHERE url=? OR ckey=?",
        (now(), normalize_url(job.url), company_title_key(job.company, job.title)),
    )


def add_candidate(con, job: Job):
    con.execute(
        """INSERT OR IGNORE INTO jobs(id,url,ckey,title,company,location,remote,posted,source,bucket,
               first_seen,last_seen,state,data) VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'candidate', ?)""",
        (
            job.id, normalize_url(job.url), company_title_key(job.company, job.title), job.title, job.company,
            job.location, job.remote, job.posted, job.source, job.bucket, now(), now(),
            json.dumps(job.to_dict(), ensure_ascii=False),
        ),
    )


def pending_candidates(con) -> list[dict]:
    rows = con.execute("SELECT data FROM jobs WHERE state='candidate' ORDER BY first_seen").fetchall()
    return [json.loads(r["data"]) for r in rows]


def set_state(con, job_id: str, state: str, fit=None, extra: dict | None = None):
    row = con.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        return False
    data = json.loads(row["data"])
    if extra:
        data["scoring"] = extra
    con.execute("UPDATE jobs SET state=?, fit=?, data=? WHERE id=?", (state, fit, json.dumps(data, ensure_ascii=False), job_id))
    return True
