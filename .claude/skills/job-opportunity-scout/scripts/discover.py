#!/usr/bin/env python3
"""Find which applicant-tracking system a company uses and add it to companies.yaml.

Usage:
  python3 scripts/discover.py "Datadog" "Collibra"                 # probe ATS APIs by name-derived slugs
  python3 scripts/discover.py --url https://salesforce.wd12.myworkdayjobs.com/External_Career_Site
  python3 scripts/discover.py "Showpad" --bucket B --industry SaaS --add
  python3 scripts/discover.py --check                             # re-test every entry in companies.yaml

Probing only calls the public job APIs (the same ones the fetchers use) and
reports how many jobs each hit returns. With --add, the best hit is appended
to companies.yaml (comments in the file are preserved; new entries go at the end).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetchers  # noqa: E402
from common import CONFIG_DIR, SourceError, client, load_yaml  # noqa: E402

PROBES = {
    "greenhouse": lambda s: f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs",
    "lever": lambda s: f"https://api.lever.co/v0/postings/{s}?mode=json&limit=1",
    "lever-eu": lambda s: f"https://api.eu.lever.co/v0/postings/{s}?mode=json&limit=1",
    "ashby": lambda s: f"https://api.ashbyhq.com/posting-api/job-board/{s}",
    "smartrecruiters": lambda s: f"https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=1",
    "workable": lambda s: f"https://apply.workable.com/api/v1/widget/accounts/{s}",
    "recruitee": lambda s: f"https://{s}.recruitee.com/api/offers/",
    "personio": lambda s: f"https://{s}.jobs.personio.de/xml",
    "personio-com": lambda s: f"https://{s}.jobs.personio.com/xml",
    "teamtailor": lambda s: f"https://{s}.teamtailor.com/jobs.rss",
}


def slugs(name: str) -> list[str]:
    base = name.lower().strip()
    base = re.sub(r"\b(inc|nv|bv|sa|ltd|gmbh|group|technologies|technology|software)\b\.?", "", base).strip()
    a = re.sub(r"[^a-z0-9]+", "", base)
    b = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    out = [a, b]
    return list(dict.fromkeys(s for s in out if s))


def count_jobs(kind: str, r) -> int:
    try:
        if kind in ("personio", "personio-com"):
            return r.text.count("<position>")
        if kind == "teamtailor":
            return r.text.count("<item>")
        d = r.json()
    except ValueError:
        return -1
    if kind == "greenhouse":
        return len(d.get("jobs", []))
    if kind.startswith("lever"):
        return len(d) if isinstance(d, list) else -1
    if kind == "ashby":
        return len(d.get("jobs", []))
    if kind == "smartrecruiters":
        return d.get("totalFound", 0) if d.get("content") is not None else -1
    if kind == "workable":
        return len(d.get("jobs", [])) if "jobs" in d else -1
    if kind == "recruitee":
        return len(d.get("offers", []))
    return -1


def probe(name: str) -> list[dict]:
    hits = []
    for s in slugs(name):
        for kind, mk in PROBES.items():
            url = mk(s)
            try:
                r = client().request("GET", url, retries=0)
            except SourceError:
                continue
            if r.status_code != 200:
                continue
            n = count_jobs(kind, r)
            if kind == "smartrecruiters" and n == 0:
                continue  # SmartRecruiters returns 200 + empty list for any unknown id
            if n >= 0:
                ats = kind.split("-")[0]
                e = {"name": name, "ats": ats, "id": s, "jobs": n}
                if kind == "lever-eu":
                    e["region"] = "eu"
                if kind == "personio-com":
                    e["domain"] = "jobs.personio.com"
                hits.append(e)
    return sorted(hits, key=lambda h: -h["jobs"])


def from_url(url: str) -> dict | None:
    p = urlparse(url)
    host, parts = p.netloc.lower(), [x for x in p.path.split("/") if x]
    m = re.match(r"([^.]+)\.(wd\d+)\.myworkdayjobs\.com", host)
    if m:
        parts = [x for x in parts if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", x)]
        return {"ats": "workday", "id": m.group(1), "wd": m.group(2), "site": parts[0] if parts else "External"}
    if "greenhouse.io" in host and parts:
        return {"ats": "greenhouse", "id": parts[-1] if "boards" in host and len(parts) == 1 else parts[0]}
    if "lever.co" in host and parts:
        return {"ats": "lever", "id": parts[0], **({"region": "eu"} if ".eu." in host else {})}
    if "ashbyhq.com" in host and parts:
        return {"ats": "ashby", "id": parts[0]}
    if "smartrecruiters.com" in host and parts:
        return {"ats": "smartrecruiters", "id": parts[0]}
    if "workable.com" in host and parts:
        return {"ats": "workable", "id": parts[0]}
    for suffix, ats in ((".recruitee.com", "recruitee"), (".jobs.personio.de", "personio"), (".jobs.personio.com", "personio"), (".teamtailor.com", "teamtailor")):
        if host.endswith(suffix):
            e = {"ats": ats, "id": host[: -len(suffix)]}
            if suffix == ".jobs.personio.com":
                e["domain"] = "jobs.personio.com"
            return e
    return None


def test_entry(e: dict) -> tuple[bool, str]:
    try:
        jobs = fetchers.get(e["ats"]).fetch(e)
        return True, f"{len(jobs)} jobs"
    except Exception as err:  # noqa: BLE001
        return False, f"{type(err).__name__}: {str(err)[:160]}"


def append_yaml(entry: dict):
    path = CONFIG_DIR / "companies.yaml"
    existing = load_yaml("companies.yaml")["companies"]
    if any(c["name"].lower() == entry["name"].lower() for c in existing):
        print(f"  {entry['name']} already in companies.yaml, not added")
        return
    fields = ["name", "ats", "id", "wd", "site", "region", "domain", "bucket", "industry", "notes"]
    lines = [f"  - name: {entry['name']!r}".replace("'", '"')]
    for f in fields[1:]:
        if entry.get(f):
            lines.append(f"    {f}: {entry[f]}")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n" + "\n".join(lines) + "\n")
    print(f"  added {entry['name']} -> {entry['ats']}:{entry['id']}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--url")
    ap.add_argument("--add", action="store_true")
    ap.add_argument("--bucket", default="")
    ap.add_argument("--industry", default="")
    ap.add_argument("--name", help="company name when using --url")
    ap.add_argument("--check", action="store_true", help="test every companies.yaml entry")
    args = ap.parse_args(argv)

    if args.check:
        bad = 0
        for e in load_yaml("companies.yaml")["companies"]:
            if e.get("enabled", True) is False or e["ats"] == "browser":
                continue
            ok, msg = test_entry(e)
            bad += not ok
            print(f"{'OK  ' if ok else 'FAIL'} {e['name']:<28} {e['ats']}:{e.get('id')}  {msg}")
        return 1 if bad else 0

    if args.url:
        e = from_url(args.url)
        if not e:
            print("Could not recognise an ATS in that URL. Supported: Workday, Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Personio, Teamtailor.")
            return 1
        e["name"] = args.name or e["id"].capitalize()
        ok, msg = test_entry(e)
        print(f"{e['ats']}:{e['id']} -> {'OK' if ok else 'FAIL'} {msg}")
        if ok and args.add:
            append_yaml(dict(e, bucket=args.bucket, industry=args.industry))
        return 0 if ok else 1

    import concurrent.futures as cf

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        found = dict(zip(args.names, ex.map(probe, args.names)))
    for name in args.names:
        hits = found[name]
        if not hits:
            print(f"{name}: no public ATS feed found. Try --url with the company's job-board link, or add an `ats: browser` entry.")
            continue
        print(f"{name}:")
        for h in hits:
            print(f"  {h['ats']}:{h['id']}  ({h['jobs']} jobs)")
        if args.add:
            append_yaml(dict(hits[0], bucket=args.bucket, industry=args.industry))
    return 0


if __name__ == "__main__":
    sys.exit(main())
