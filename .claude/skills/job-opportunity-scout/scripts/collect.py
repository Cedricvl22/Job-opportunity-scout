#!/usr/bin/env python3
"""Step 1 of a scout run: collect -> normalise -> dedupe -> pre-filter -> store.

Usage:
  python3 scripts/collect.py                 # full run
  python3 scripts/collect.py --only datadog  # one company / source (name or id, comma-separated)
  python3 scripts/collect.py --no-browser    # skip Playwright sources
  python3 scripts/collect.py --dry-run       # do not write to the database

Writes data/runs/<date>/candidates.json (jobs awaiting Claude's scoring) and
prints a per-source success/failure report. A failed source is always listed.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402
import fetchers  # noqa: E402
from common import DATA_DIR, CONFIG_DIR, Job, SourceError, company_title_key, dump_json, load_yaml, norm_company, normalize_url  # noqa: E402
from filters import PreFilter  # noqa: E402

DESC_LIMIT = 3500  # characters of description handed to scoring
STATUS = {"MissingKey": "skipped-no-key", "RobotsDisallowed": "blocked-robots", "BotBlocked": "blocked-bot-protection"}


def load_fortune_names() -> set[str]:
    names = set()
    p = CONFIG_DIR / "fortune500.txt"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            if line:
                names.add(norm_company(line))
    return names


def source_label(entry: dict) -> str:
    return f"{entry['ats']}:{entry.get('id') or entry.get('key') or entry['name']}"


def run_fetch(entry: dict):
    mod = fetchers.get(entry["ats"])
    t0 = time.monotonic()
    jobs = mod.fetch(entry)
    return jobs, time.monotonic() - t0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated company names/ids or aggregator names")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-aggregators", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)

    companies = load_yaml("companies.yaml")["companies"]
    sources_cfg = load_yaml("sources.yaml")
    only = {x.strip().lower() for x in args.only.split(",")} if args.only else None
    fortune = load_fortune_names()
    by_company = {norm_company(c["name"]): c for c in companies}
    pf = PreFilter()

    con = db.connect()
    run_id = 0 if args.dry_run else db.start_run(con)
    today = dt.date.today().isoformat()

    # ------------------------------------------------------------ which sources
    entries = []
    disabled = []
    for c in companies:
        if c.get("enabled", True) is False:
            disabled.append(c)
            continue
        if only and c["name"].lower() not in only and str(c.get("id", "")).lower() not in only:
            continue
        if args.no_browser and c["ats"] == "browser":
            continue
        entries.append(c)
    if not args.no_aggregators:
        for name, cfg in (sources_cfg.get("aggregators") or {}).items():
            if only and name not in only:
                continue
            if cfg.get("enabled", True) is False:
                disabled.append(dict(cfg, name=name, ats=name, key=name))
                continue
            entries.append(dict(cfg, name=name, ats=name, key=name, aggregator=True))

    log = []  # per-source report rows

    def record(entry, status, fetched=0, kept=0, secs=0.0, error=""):
        label = source_label(entry)
        log.append({"source": label, "company": entry["name"], "status": status, "fetched": fetched, "kept": kept, "seconds": round(secs, 1), "error": error})
        if not args.dry_run:
            db.log_source(con, run_id, label, status, fetched, kept, secs, error)

    for e in disabled:
        if not only or e["name"].lower() in only:
            record(e, "disabled", error=e.get("disabled_reason", "switched off in config"))

    # ------------------------------------------------------------ fetch (threaded, browser in main thread)
    results: list[tuple[dict, list[Job], float]] = []
    http_entries = [e for e in entries if e["ats"] != "browser"]
    browser_entries = [e for e in entries if e["ats"] == "browser"]
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_fetch, e): e for e in http_entries}
        for f in cf.as_completed(futs):
            e = futs[f]
            try:
                jobs, secs = f.result()
                results.append((e, jobs, secs))
            except Exception as err:  # noqa: BLE001 - every failure must be reported
                status = STATUS.get(type(err).__name__, "failed")
                record(e, status, error=f"{type(err).__name__}: {err}")
    for e in browser_entries:
        try:
            jobs, secs = run_fetch(e)
            results.append((e, jobs, secs))
        except Exception as err:  # noqa: BLE001
            status = STATUS.get(type(err).__name__, "failed")
            record(e, status, error=f"{type(err).__name__}: {str(err)[:300]}")

    # ------------------------------------------------------------ normalise, dedupe, pre-filter
    total_fetched = 0
    seen_urls, seen_keys = set(), set()
    stage = []  # (entry, job, basic verdict)
    per_source_kept: dict[str, int] = {}
    drop_reasons: dict[str, int] = {}
    already_known = 0
    for e, jobs, secs in results:
        total_fetched += len(jobs)
        for j in jobs:
            if not j.url or not j.title:
                continue
            # company metadata
            meta = e if not e.get("aggregator") else by_company.get(norm_company(j.company))
            if meta:
                j.bucket = meta.get("bucket", "")
                j.industry = meta.get("industry", "")
            elif norm_company(j.company) in fortune:
                j.bucket = "A"
            u, k = normalize_url(j.url), company_title_key(j.company, j.title)
            if u in seen_urls or k in seen_keys:
                continue
            seen_urls.add(u)
            seen_keys.add(k)
            v = pf.check_basic(j)
            if not v.keep:
                key = v.reason.split(" (")[0]
                drop_reasons[key] = drop_reasons.get(key, 0) + 1
                continue
            if db.is_known(con, j):
                already_known += 1
                if not args.dry_run:
                    db.touch_seen(con, j)
                continue
            stage.append((e, j, v))

    # ------------------------------------------------------------ enrich descriptions where needed
    def enrich(item):
        e, j, v = item
        mod = fetchers.get(e["ats"])
        if hasattr(mod, "enrich") and (not j.description or len(j.description) < 200):
            mod.enrich(j)
        return item

    enrich_errors: dict[str, list[str]] = {}
    enriched = []
    http_stage = [s for s in stage if s[0]["ats"] != "browser"]
    br_stage = [s for s in stage if s[0]["ats"] == "browser"]
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(enrich, s): s for s in http_stage}
        for f in cf.as_completed(futs):
            s = futs[f]
            try:
                enriched.append(f.result())
            except Exception as err:  # noqa: BLE001
                enrich_errors.setdefault(source_label(s[0]), []).append(f"{s[1].title}: {err}")
                enriched.append(s)  # keep with list data; scoring sees the missing description
    for s in br_stage:
        try:
            enriched.append(enrich(s))
        except Exception as err:  # noqa: BLE001
            enrich_errors.setdefault(source_label(s[0]), []).append(f"{s[1].title}: {err}")
            enriched.append(s)
    try:
        fetchers.get("browser").close()
    except Exception:  # noqa: BLE001
        pass

    new_candidates = 0
    for e, j, v in enriched:
        v2 = pf.check_full(j, v)
        if not v2.keep:
            key = v2.reason.split(" (")[0]
            drop_reasons[key] = drop_reasons.get(key, 0) + 1
            continue
        j.extra["location_class"] = v2.location_class
        if not j.description:
            j.extra["description_missing"] = True
        new_candidates += 1
        per_source_kept[source_label(e)] = per_source_kept.get(source_label(e), 0) + 1
        if not args.dry_run:
            db.add_candidate(con, j)
    if not args.dry_run:
        con.commit()

    for e, jobs, secs in results:
        lbl = source_label(e)
        err = "; ".join(enrich_errors.get(lbl, [])[:3])
        status = "ok" if not err else "ok-partial"
        record(e, status, len(jobs), per_source_kept.get(lbl, 0), secs, (f"detail fetch failed for {len(enrich_errors[lbl])} job(s): " + err) if err else "")

    # ------------------------------------------------------------ output for scoring
    pending = db.pending_candidates(con) if not args.dry_run else [j.to_dict() for _, j, _ in enriched]
    for p in pending:
        p["id"] = Job(**{k: p[k] for k in Job.__dataclass_fields__}).id
        if p.get("description") and len(p["description"]) > DESC_LIMIT:
            p["description"] = p["description"][:DESC_LIMIT] + " …[truncated]"
    stats = {
        "date": today, "run_id": run_id,
        "collected": total_fetched,
        "unique": len(seen_urls),
        "already_known": already_known,
        "new_after_filter": new_candidates,
        "pending_for_scoring": len(pending),
        "drop_reasons": dict(sorted(drop_reasons.items(), key=lambda x: -x[1])),
        "sources_ok": sum(1 for r in log if r["status"].startswith("ok")),
        "sources_failed": [r for r in log if not r["status"].startswith("ok")],
    }
    out_dir = DATA_DIR / "runs" / today
    n = 2
    while (out_dir / "report.md").exists():  # today's run was already finalized: start a new folder
        out_dir = DATA_DIR / "runs" / f"{today}_{n}"
        n += 1
    dump_json(out_dir / "candidates.json", {"stats": stats, "candidates": pending})
    dump_json(out_dir / "source_log.json", sorted(log, key=lambda r: (r["status"].startswith("ok"), r["source"])))
    if not args.dry_run:
        db.finish_run(con, run_id, stats)

    # ------------------------------------------------------------ report
    print(f"# Collect report {today}")
    print(f"collected={total_fetched} unique={len(seen_urls)} already_known={already_known} new_after_filter={new_candidates} pending_for_scoring={len(pending)}")
    print(f"sources ok: {stats['sources_ok']} / {len(log)}")
    bad = [r for r in log if not r["status"].startswith("ok") or r["error"]]
    if bad:
        print("\n## Sources with problems (not silently skipped)")
        for r in sorted(bad, key=lambda r: r["status"]):
            print(f"- {r['source']} [{r['status']}] {r['error'][:220]}")
    print(f"\ndrop reasons: {stats['drop_reasons']}")
    print(f"\ncandidates file: {out_dir / 'candidates.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
