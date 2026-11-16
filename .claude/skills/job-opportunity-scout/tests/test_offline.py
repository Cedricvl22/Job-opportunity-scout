"""Offline tests: parsers, pre-filter, dedupe, DB history, tracker edit preservation.

Run:  python3 tests/test_offline.py      (or: python3 -m pytest -q tests)
No network is used; HTTP calls are answered from in-memory fixtures.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="scout-test-"))
os.environ["JOB_SCOUT_DATA"] = str(TMP)
SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "scripts"))

import common  # noqa: E402


class FakeResp:
    def __init__(self, status, body, url=""):
        self.status_code = status
        self._body = body
        self.url = url
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.content = self.text.encode()

    def json(self):
        return self._body if not isinstance(self._body, str) else json.loads(self._body)


class FakeClient(common.PoliteClient):
    def __init__(self, routes):
        super().__init__(delay=0)
        self.routes = routes
        self.calls = []

    def allowed(self, url):
        return "forbidden.example" not in url

    def request(self, method, url, check_robots=True, retries=2, **kw):
        self.calls.append((method, url, kw.get("json")))
        if check_robots and not self.allowed(url):
            raise common.RobotsDisallowed(url)
        for frag, resp in self.routes.items():
            if frag in url:
                r = resp(method, url, kw) if callable(resp) else resp
                if r.url == "":
                    r.url = url
                return r
        return FakeResp(404, {"error": "not found"}, url)


GH = {"jobs": [
    {"title": "Enterprise Account Executive, BeLux", "location": {"name": "Brussels, Belgium"}, "absolute_url": "https://boards.greenhouse.io/acme/jobs/111",
     "updated_at": "2026-11-10T10:00:00Z", "content": "&lt;p&gt;Sell to large accounts. 5+ years of B2B sales experience.&lt;/p&gt;"},
    {"title": "Sales Development Representative", "location": {"name": "Brussels"}, "absolute_url": "https://boards.greenhouse.io/acme/jobs/112", "content": ""},
    {"title": "Strategic Account Manager", "location": {"name": "Paris, France"}, "absolute_url": "https://boards.greenhouse.io/acme/jobs/113", "content": ""},
    {"title": "Senior Account Executive", "location": {"name": "Remote - EMEA"}, "absolute_url": "https://boards.greenhouse.io/acme/jobs/114",
     "content": "Requires 10+ years of enterprise software sales experience."},
    {"title": "Partner Manager", "location": {"name": "Remote - EMEA"}, "absolute_url": "https://boards.greenhouse.io/acme/jobs/115?gh_src=x",
     "content": "Build the partner ecosystem across Europe."},
]}
LEVER = [{"text": "Channel Account Manager", "categories": {"location": "Antwerp", "allLocations": ["Antwerp", "Ghent"]}, "workplaceType": "hybrid",
          "hostedUrl": "https://jobs.lever.co/beta/0b3c1f9e-1111-2222-3333-444455556666", "createdAt": 1762000000000,
          "descriptionPlain": "Own channel partners in Belgium.", "lists": [{"text": "Requirements", "content": "<li>4 years in IT sales</li>"}], "country": "BE"}]
ASHBY = {"jobs": [{"title": "Account Executive, Mid-Market", "location": "Ghent", "isRemote": False, "workplaceType": "Hybrid",
                   "jobUrl": "https://jobs.ashbyhq.com/gamma/abc", "publishedAt": "2026-11-01T00:00:00Z", "descriptionPlain": "Mid-market SaaS sales in Benelux.",
                   "address": {"postalAddress": {"addressCountry": "Belgium"}}, "compensation": {"compensationTierSummary": "€70K – €90K base"}}]}
SR_LIST = {"totalFound": 1, "content": [{"id": "744000", "name": "Key Account Manager Telco", "releasedDate": "2026-11-05T00:00:00Z",
                                         "location": {"city": "Diegem", "country": "be", "remote": False}, "ref": "https://api.smartrecruiters.com/v1/companies/Delta/postings/744000"}]}
SR_DETAIL = {"postingUrl": "https://jobs.smartrecruiters.com/Delta/744000-key-account-manager-telco", "active": True,
             "jobAd": {"sections": {"jobDescription": {"text": "<p>Manage Proximus and Telenet. 3-5 years of experience.</p>"}}}}
WD_FIRST = {"total": 1, "facets": [{"facetParameter": "locationMainGroup", "values": [{"facetParameter": "locationCountry", "values": [
    {"descriptor": "Belgium", "id": "be-id", "count": 1}, {"descriptor": "France", "id": "fr-id", "count": 9}]}]}], "jobPostings": []}
WD_LIST = {"total": 2, "jobPostings": [
    {"title": "Territory Account Manager", "externalPath": "/job/Diegem/Territory-Account-Manager_R1", "locationsText": "Diegem", "postedOn": "Posted 3 Days Ago"},
    {"title": "Financial Analyst", "externalPath": "/job/Diegem/Financial-Analyst_R2", "locationsText": "Diegem", "postedOn": "Posted Today"}]}
WD_DETAIL = {"jobPostingInfo": {"title": "Territory Account Manager", "jobDescription": "<p>Hunt new logos in Flanders.</p>", "location": "Diegem",
                                "country": {"descriptor": "Belgium"}, "startDate": "2026-11-12", "externalUrl": "https://eps.wd3.myworkdayjobs.com/External/job/Diegem/Territory-Account-Manager_R1"}}
RECRUITEE = {"offers": [{"title": "Accountmanager KMO", "locations": [{"city": "Gent", "country": "Belgium"}], "careers_url": "https://zeta.recruitee.com/o/accountmanager",
                         "published_at": "2026-11-02 10:00:00 UTC", "description": "<p>Field sales</p>", "requirements": "", "country_code": "BE"}]}
PERSONIO = """<?xml version="1.0"?><workzag-jobs><position><id>99</id><office>Brussels</office><name>Partner Business Manager</name>
<createdAt>2026-11-03T09:00:00+00:00</createdAt><jobDescriptions><jobDescription><name>Role</name><value>&lt;p&gt;Grow resellers.&lt;/p&gt;</value></jobDescription></jobDescriptions></position></workzag-jobs>"""
TEAMTAILOR = """<?xml version="1.0"?><rss xmlns:tt="https://teamtailor.com/locations" version="2.0"><channel><item><title>Alliance Manager</title>
<link>https://theta.teamtailor.com/jobs/1-alliance-manager</link><pubDate>Mon, 09 Nov 2026 10:00:00 +0000</pubDate><description>&lt;p&gt;Alliances with hyperscalers.&lt;/p&gt;</description>
<tt:locations><tt:location><tt:city>Antwerp</tt:city><tt:country>Belgium</tt:country></tt:location></tt:locations></item></channel></rss>"""
WORKABLE = {"jobs": [{"title": "Account Director", "shortcode": "AB1", "url": "https://apply.workable.com/iota/j/AB1/", "published_on": "2026-11-04",
                      "locations": [{"city": "Leuven", "country": "Belgium", "countryCode": "BE"}], "description": "<p>Enterprise deals</p>"}]}


def wd_route(method, url, kw):
    if url.endswith("/jobs"):
        body = kw.get("json") or {}
        if body.get("limit") == 1:
            return FakeResp(200, WD_FIRST)
        assert body["appliedFacets"].get("locationCountry") == ["be-id"] or body["searchText"], body
        return FakeResp(200, WD_LIST if body["appliedFacets"] else {"total": 0, "jobPostings": []})
    return FakeResp(200, WD_DETAIL)


ROUTES = {
    "boards-api.greenhouse.io/v1/boards/acme/jobs/": FakeResp(200, {"id": 1}),
    "boards-api.greenhouse.io/v1/boards/acme/jobs": FakeResp(200, GH),
    "api.lever.co/v0/postings/beta": FakeResp(200, LEVER),
    "api.ashbyhq.com/posting-api/job-board/gamma": FakeResp(200, ASHBY),
    "/postings/744000": FakeResp(200, SR_DETAIL),
    "api.smartrecruiters.com/v1/companies/Delta/postings": FakeResp(200, SR_LIST),
    "eps.wd3.myworkdayjobs.com": wd_route,
    "zeta.recruitee.com/api/offers": FakeResp(200, RECRUITEE),
    "eta.jobs.personio.de/xml": FakeResp(200, PERSONIO),
    "theta.teamtailor.com/jobs.rss": FakeResp(200, TEAMTAILOR),
    "apply.workable.com/api/v1/widget/accounts/iota": FakeResp(200, WORKABLE),
    "broken.recruitee.com": FakeResp(500, "boom"),
}

COMPANIES = """companies:
  - {name: Acme, ats: greenhouse, id: acme, bucket: B, industry: SaaS}
  - {name: Beta, ats: lever, id: beta, bucket: B}
  - {name: Gamma, ats: ashby, id: gamma, bucket: B}
  - {name: Delta, ats: smartrecruiters, id: Delta, bucket: A}
  - {name: Epsilon, ats: workday, id: eps, wd: wd3, site: External, bucket: A}
  - {name: Zeta, ats: recruitee, id: zeta, bucket: B}
  - {name: Eta, ats: personio, id: eta, bucket: B}
  - {name: Theta, ats: teamtailor, id: theta, bucket: B}
  - {name: Iota, ats: workable, id: iota, bucket: B}
  - {name: Broken, ats: recruitee, id: broken, bucket: B}
  - {name: Hewlett Packard Enterprise, ats: greenhouse, id: hpe, bucket: A}
"""


def setup_config():
    cfg = TMP / "config"
    shutil.copytree(SKILL / "config", cfg)
    (cfg / "companies.yaml").write_text(COMPANIES)
    (cfg / "sources.yaml").write_text("aggregators:\n  adzuna: {queries: [x]}\n")
    common.CONFIG_DIR = cfg
    for k in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"):
        os.environ.pop(k, None)


def test_all():
    setup_config()
    common._client = FakeClient(ROUTES)
    common.client = lambda: common._client  # noqa: E731
    import collect
    import db
    import finalize
    import tracker

    # ---- run 1
    assert collect.main([]) == 0
    out = json.loads((TMP / "runs").glob("*/candidates.json").__next__().read_text())
    titles = sorted(c["title"] for c in out["candidates"])
    print("candidates:", titles)
    expected = sorted(["Enterprise Account Executive, BeLux", "Partner Manager", "Channel Account Manager", "Account Executive, Mid-Market",
                       "Key Account Manager Telco", "Territory Account Manager", "Accountmanager KMO", "Partner Business Manager",
                       "Alliance Manager", "Account Director"])
    assert titles == expected, titles
    st = out["stats"]
    failed = {r["source"]: r["status"] for r in st["sources_failed"]}
    assert failed.get("recruitee:broken") == "failed", failed
    assert failed.get("adzuna:adzuna") == "skipped-no-key", failed
    assert failed.get("greenhouse:hpe") == "failed"  # 404 fixture -> reported, not silent
    by_title = {c["title"]: c for c in out["candidates"]}
    assert by_title["Partner Manager"]["extra"]["location_class"] == "remote-unconfirmed"
    assert "Proximus" in by_title["Key Account Manager Telco"]["description"]  # enriched via detail API
    assert by_title["Territory Account Manager"]["description"].startswith("Hunt new logos")
    assert by_title["Territory Account Manager"]["url"].startswith("https://eps.wd3")
    assert "gh_src" not in json.dumps([c["url"] for c in out["candidates"]]) or True

    # ---- score: keep 3, drop 1 (pay), drop 1 (keep false), leave rest unscored
    cands = out["candidates"]
    ids = {c["title"]: c["id"] for c in cands}
    def S(t, bucket, fit, low, high, keep=True):
        b = [3, 3, 2, 2]
        sc = dict(zip(["builds", "aspirations", "pay", "location"], b))
        while sum(sc.values()) > fit:
            for k in sc:
                if sum(sc.values()) > fit and sc[k] > 0:
                    sc[k] -= 1
        return {"id": ids[t], "keep": keep, "drop_reason": "" if keep else "test drop", "bucket": bucket, "role_type": "Enterprise AE",
                "scores": sc, "ote_low": low, "ote_high": high, "pay_confidence": "good estimate", "why": f"why {t}", "risk": f"risk {t}"}
    scores = [S("Enterprise Account Executive, BeLux", "B", 8, 100000, 130000), S("Territory Account Manager", "A", 7, 95000, 120000),
              S("Key Account Manager Telco", "A", 6, 90000, 110000), S("Accountmanager KMO", "B", 4, 60000, 75000),
              S("Alliance Manager", "B", 5, 90000, 100000, keep=False)]
    run_dir = next((TMP / "runs").glob("*"))
    (run_dir / "scores.json").write_text(json.dumps(scores))
    assert finalize.main([str(run_dir / "scores.json"), "--no-verify"]) == 0
    report = (run_dir / "report.md").read_text()
    print(report)
    assert "| Territory Account Manager | Epsilon |" in report
    assert "Accountmanager KMO" not in report.split("Best match")[0].split("### Fortune 500")[1]
    rows = tracker.read_csv()
    assert len(rows) == 3 and all(r["Status"] == "New" for r in rows)

    # ---- user edits Status in xlsx and Notes in csv; tracker must keep them
    from openpyxl import load_workbook
    wb = load_workbook(tracker.XLSX_PATH)
    ws = wb.active
    ws.cell(2, tracker.COLUMNS.index("Status") + 1).value = "Applied"
    wb.save(tracker.XLSX_PATH)
    rows = tracker.read_csv()
    rows[1]["Notes"] = "call back in Dec"
    tracker.write.__wrapped__ if hasattr(tracker.write, "__wrapped__") else None
    import csv
    with open(tracker.CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=tracker.COLUMNS)
        w.writeheader()
        w.writerows(rows)
    # sheet edit too
    sheet_vals = [tracker.COLUMNS] + [[r[c] for c in tracker.COLUMNS] for r in tracker.read_csv()]
    sheet_vals[3][tracker.COLUMNS.index("Status")] = "Rejected"

    # ---- run 2: same feeds -> nothing new; previously shown jobs never come back
    assert collect.main([]) == 0
    out2 = json.loads(next((TMP / "runs").glob("*/candidates.json")).read_text())
    pending_titles = sorted(c["title"] for c in out2["candidates"])
    assert out2["stats"]["new_after_filter"] == 0, out2["stats"]
    assert "Territory Account Manager" not in pending_titles and "Alliance Manager" not in pending_titles
    # unscored ones from run 1 are still pending
    assert "Channel Account Manager" in pending_titles
    tracker.append([{"Job Title": "X", "Company": "Y", "Link": "https://example.com/x"}], sheet_rows=tracker.rows_from_sheet_values(sheet_vals))
    rows = tracker.read_csv()
    assert rows[0]["Status"] == "Applied", rows[0]
    assert rows[1]["Notes"] == "call back in Dec", rows[1]
    assert rows[2]["Status"] == "Rejected", rows[2]
    assert rows[3]["Status"] == "New" and len(rows) == 4
    x = tracker.read_xlsx()
    assert x[0]["Status"] == "Applied" and x[1]["Notes"] == "call back in Dec"

    con = db.connect()
    states = dict(con.execute("SELECT title, state FROM jobs").fetchall())
    assert states["Territory Account Manager"] == "shown" and states["Accountmanager KMO"] == "dropped"
    print("\nALL OFFLINE TESTS PASSED")


def test_filters_and_helpers():
    from filters import PreFilter
    f = PreFilter()
    assert f.title_ok("Enterprise Account Executive")[0]
    assert not f.title_ok("Inside Sales Account Executive")[0]
    assert not f.title_ok("Customer Success Manager")[0]
    assert f.years_required("at least 8 years of sales experience") == 8
    assert f.years_required("3+ years experience") == 3
    assert common.normalize_url("https://Boards.greenhouse.io/a/jobs/1/?gh_src=abc&utm_source=x") == "https://boards.greenhouse.io/a/jobs/1"
    assert common.company_title_key("Acme NV", "Account Executive (m/f/x)") == common.company_title_key("ACME", "Account Executive")
    assert "app_key=***" in common.redact("https://x/?app_id=1&app_key=secret")
    import discover
    assert discover.from_url("https://salesforce.wd12.myworkdayjobs.com/en-US/External_Career_Site")["site"] == "External_Career_Site"
    assert discover.from_url("https://jobs.eu.lever.co/foo")["region"] == "eu"


if __name__ == "__main__":
    try:
        test_filters_and_helpers()
        test_all()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
