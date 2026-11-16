#!/usr/bin/env python3
"""Step 3 of a scout run: take Claude's scores, verify links, enforce the rules,
update the database and tracker, and print the markdown report.

Usage:
  python3 scripts/finalize.py data/runs/<date>/scores.json [--no-verify] [--dry-run]

scores.json is a list with one object per candidate id from candidates.json:
  {
    "id": "a1b2c3d4e5f6",
    "keep": true,                       # false = drop (give drop_reason)
    "drop_reason": "",
    "bucket": "A" | "B",
    "role_type": "Enterprise AE" | "Strategic/Named Account Manager" | "Partner/Channel Manager" | ...,
    "scores": {"builds": 0-3, "aspirations": 0-3, "pay": 0-2, "location": 0-2},
    "ote_low": 85000, "ote_high": 110000,           # EUR, integers
    "pay_confidence": "stated" | "good estimate" | "rough guess",
    "why": "one or two sentences",
    "risk": "main risk in one sentence"
  }
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402
import tracker  # noqa: E402
import verify  # noqa: E402
from common import DATA_DIR, dump_json  # noqa: E402

PAY_FLOOR = 85000
BUCKET_B_CAP = 5
VALID_CONF = {"stated", "good estimate", "rough guess"}


def fmt_k(v) -> str:
    return f"{round(int(v) / 1000)}K"


def cell(s: str) -> str:
    return " ".join(str(s or "").replace("|", "/").split())


def validate(s: dict) -> list[str]:
    errs = []
    if not s.get("keep"):
        return errs
    sc = s.get("scores") or {}
    lim = {"builds": 3, "aspirations": 3, "pay": 2, "location": 2}
    for k, mx in lim.items():
        v = sc.get(k)
        if not isinstance(v, (int, float)) or not 0 <= v <= mx:
            errs.append(f"scores.{k} must be 0..{mx}")
    for k in ("ote_low", "ote_high"):
        if not isinstance(s.get(k), (int, float)):
            errs.append(f"{k} must be a number (EUR)")
    if s.get("pay_confidence") not in VALID_CONF:
        errs.append(f"pay_confidence must be one of {sorted(VALID_CONF)}")
    if s.get("bucket") not in ("A", "B"):
        errs.append("bucket must be A or B")
    for k in ("why", "risk", "role_type"):
        if not s.get(k):
            errs.append(f"{k} is required")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("scores")
    ap.add_argument("--no-verify", action="store_true", help="skip link checks (testing only)")
    ap.add_argument("--dry-run", action="store_true", help="do not write DB or tracker")
    args = ap.parse_args(argv)

    scores_path = Path(args.scores)
    scores = json.loads(scores_path.read_text(encoding="utf-8"))
    cand_path = scores_path.parent / "candidates.json"
    cand = json.loads(cand_path.read_text(encoding="utf-8"))
    stats = cand["stats"]
    jobs = {c["id"]: c for c in cand["candidates"]}

    con = db.connect()
    problems = []
    kept, dropped = [], []
    for s in scores:
        if s.get("id") not in jobs:
            problems.append(f"unknown id {s.get('id')}")
            continue
        errs = validate(s)
        if errs:
            problems.append(f"{s['id']}: " + "; ".join(errs))
            continue
        job = jobs[s["id"]]
        if not s.get("keep"):
            dropped.append((job, s, s.get("drop_reason") or "dropped at scoring"))
            continue
        if s["ote_high"] < PAY_FLOOR:
            dropped.append((job, s, f"pay floor: est. OTE {fmt_k(s['ote_low'])}-{fmt_k(s['ote_high'])}"))
            continue
        s["fit"] = sum(s["scores"].values())
        kept.append((job, s))
    if problems:
        print("## scores.json problems (fix and re-run finalize):")
        for p in problems:
            print("-", p)
        return 2
    missing = set(jobs) - {s["id"] for s in scores}
    if missing:
        print(f"## {len(missing)} candidates have no score yet; they stay pending for the next finalize: {sorted(missing)[:10]}")

    # ---------------------------------------------------------------- link verification
    verdicts = {}
    if args.no_verify:
        verdicts = {j["id"]: ("live", "not checked (--no-verify)") for j, _ in kept}
    else:
        with cf.ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(verify.check, j): j["id"] for j, _ in kept}
            for f in cf.as_completed(futs):
                try:
                    verdicts[futs[f]] = f.result()
                except Exception as e:  # noqa: BLE001
                    verdicts[futs[f]] = ("unverified", f"check error: {e}")
    live = [(j, s) for j, s in kept if verdicts[j["id"]][0] == "live"]
    dead = [(j, s) for j, s in kept if verdicts[j["id"]][0] == "dead"]
    unver = [(j, s) for j, s in kept if verdicts[j["id"]][0] == "unverified"]

    # ---------------------------------------------------------------- bucket split and cap
    order = lambda x: (-x[1]["fit"], -x[1]["ote_high"])  # noqa: E731
    a = sorted([x for x in live if x[1]["bucket"] == "A"], key=order)
    b_all = sorted([x for x in live if x[1]["bucket"] == "B"], key=order)
    b, b_held = b_all[:BUCKET_B_CAP], b_all[BUCKET_B_CAP:]
    shown = a + b

    # ---------------------------------------------------------------- persist
    today = dt.date.today().isoformat()
    if not args.dry_run:
        for j, s, reason in dropped:
            db.set_state(con, j["id"], "dropped", None, dict(s, drop_reason=reason))
        for j, s in dead:
            db.set_state(con, j["id"], "dropped", s["fit"], dict(s, drop_reason=f"link dead: {verdicts[j['id']][1]}"))
        for j, s in unver:
            db.set_state(con, j["id"], "unverified", s["fit"], dict(s, verify=verdicts[j["id"]][1]))
        for j, s in b_held:
            db.set_state(con, j["id"], "scored", s["fit"], dict(s, note="over Bucket B cap"))
        for j, s in shown:
            db.set_state(con, j["id"], "shown", s["fit"], s)
        con.commit()
        rows = [{
            "Date found": today, "Job Title": j["title"], "Company": j["company"],
            "Bucket": "Fortune 500" if s["bucket"] == "A" else "Start-up/Scale-up", "Role type": s["role_type"],
            "Location": j["location"], "Link": j["url"], "Fit score": s["fit"],
            "Est. OTE range": f"{fmt_k(s['ote_low'])}-{fmt_k(s['ote_high'])} EUR", "Pay confidence": s["pay_confidence"],
            "Why it fits": s["why"], "Main risk": s["risk"], "Status": "New", "Notes": "",
        } for j, s in shown]
        added = tracker.append(rows)
    else:
        added = 0

    # ---------------------------------------------------------------- report
    out = []
    out.append(f"**{today}** · {stats['collected']} postings collected · {stats['pending_for_scoring']} after filtering · {len(shown)} shown")
    failed = stats.get("sources_failed") or []
    if failed:
        groups: dict[str, list[str]] = {}
        for r in failed:
            groups.setdefault(r["status"], []).append(r.get("company") or r["source"])
        parts = [f"{len(v)} {k} ({', '.join(v[:6])}{', …' if len(v) > 6 else ''})" for k, v in sorted(groups.items(), key=lambda x: -len(x[1]))]
        out.append(f"\n> ⚠️ {len(failed)} source(s) did not deliver this run: " + "; ".join(parts) + ". Details: source_log.json")

    def table(title, items):
        out.append(f"\n### {title}\n")
        if not items:
            out.append("_No qualifying roles this run._")
            return
        out.append("| Job Title | Company | Link | Fit | Why (and main risk) |")
        out.append("|---|---|---|---|---|")
        for j, s in items:
            why = f"{cell(s['why'])} Est. OTE {fmt_k(s['ote_low'])}-{fmt_k(s['ote_high'])} ({s['pay_confidence']}). **Risk:** {cell(s['risk'])}"
            out.append(f"| {cell(j['title'])} | {cell(j['company'])} | [Open]({j['url']}) | {s['fit']:g}/10 | {why} |")

    table("Fortune 500", a)
    table(f"Start-ups / Scale-ups (max {BUCKET_B_CAP})", b)
    if unver:
        out.append(f"\n_{len(unver)} scored role(s) not shown because their link could not be verified: " + "; ".join(f"{cell(j['title'])} @ {cell(j['company'])} ({verdicts[j['id']][1][:60]})" for j, _ in unver[:8]) + "_")
    if dead:
        out.append(f"\n_{len(dead)} role(s) dropped because the posting is no longer live._")
    if shown:
        j, s = max(shown, key=lambda x: (x[1]["fit"], x[1]["ote_high"]))
        out.append(f"\n**Best match:** {j['title']} at {j['company']} ({s['fit']:g}/10): {cell(s['why'])}")
    else:
        out.append("\n**Best match:** none this run; nothing cleared the bar.")
    out.append(f"\n_Tracker: {added} new row(s) appended to {tracker.CSV_PATH} and {tracker.XLSX_PATH}_")
    report = "\n".join(out)
    (scores_path.parent / "report.md").write_text(report, encoding="utf-8")
    dump_json(scores_path.parent / "shown.json", [dict(j, scoring=s, verify=verdicts[j["id"]]) for j, s in shown])
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
