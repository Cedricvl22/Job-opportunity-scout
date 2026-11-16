"""Workday candidate-experience (cxs) JSON endpoints.

companies.yaml entry:  {name: Salesforce, ats: workday, id: salesforce, wd: wd12, site: External_Career_Site}
  list:   POST https://{id}.{wd}.myworkdayjobs.com/wday/cxs/{id}/{site}/jobs
  detail: GET  https://{id}.{wd}.myworkdayjobs.com/wday/cxs/{id}/{site}{externalPath}

Strategy: read the facets once; if the tenant exposes a country facet with
"Belgium", list everything in Belgium (small) and filter titles in code.
Otherwise fall back to keyword searches.
"""
import datetime as dt
import re

from common import Job, SourceError, client, html_to_text, remote_from_text

PAGE = 20
MAX_PAGES = 15
KEYWORDS = ["account executive", "account manager", "account director", "partner", "channel", "alliance", "client executive", "sales specialist", "territory"]
EXTRA_REMOTE_QUERIES = ["account executive EMEA", "partner manager EMEA"]


def _base(entry):
    host = entry.get("host") or f"{entry['id']}.{entry['wd']}.myworkdayjobs.com"
    return host, f"https://{host}/wday/cxs/{entry['id']}/{entry['site']}"


def _find_country_facet(facets, name="belgium"):
    """Return (facetParameter, id) for the Belgium value in any country-like facet."""
    def walk(nodes, param=None):
        for n in nodes or []:
            p = n.get("facetParameter", param)
            if (n.get("descriptor") or "").strip().lower() == name and param and re.search(r"countr|location", param, re.I):
                return param, n.get("id")
            r = walk(n.get("values"), p)
            if r:
                return r
        return None
    return walk(facets)


def _posted(s):
    s = (s or "").lower()
    today = dt.date.today()
    if "today" in s:
        return today.isoformat()
    if "yesterday" in s:
        return (today - dt.timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\+?\s*days?", s)
    if m:
        return (today - dt.timedelta(days=int(m.group(1)))).isoformat()
    return ""


def _search(api, payload):
    c = client()
    out, offset = [], 0
    total = None
    for _ in range(MAX_PAGES):
        payload = dict(payload, limit=PAGE, offset=offset)
        d = c.post_json(f"{api}/jobs", payload, headers={"Accept": "application/json"})
        posts = d.get("jobPostings") or []
        if total is None:
            total = d.get("total", 0)
        out.extend(posts)
        offset += PAGE
        if not posts or offset >= (total or 0):
            break
    return out


def fetch(entry):
    host, api = _base(entry)
    first = client().post_json(f"{api}/jobs", {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}, headers={"Accept": "application/json"})
    facet = _find_country_facet(first.get("facets"))
    postings = []
    if facet:
        postings += _search(api, {"appliedFacets": {facet[0]: [facet[1]]}, "searchText": ""})
        mode = f"facet {facet[0]}=Belgium"
    else:
        for kw in KEYWORDS:
            postings += _search(api, {"appliedFacets": {}, "searchText": f"{kw} belgium"})
        mode = "keyword search"
    for q in EXTRA_REMOTE_QUERIES:
        postings += _search(api, {"appliedFacets": {}, "searchText": q})
    seen, out = set(), []
    for p in postings:
        path = p.get("externalPath")
        if not path or path in seen:
            continue
        seen.add(path)
        loc = p.get("locationsText") or ""
        out.append(Job(
            title=(p.get("title") or "").strip(), company=entry["name"], location=loc,
            url=f"https://{host}/{entry['site']}{path}", source=f"workday:{entry['id']}",
            remote=remote_from_text(loc, " ".join(p.get("bulletFields") or [])), posted=_posted(p.get("postedOn")),
            extra={"detail": f"{api}{path}", "mode": mode},
        ))
    return out


def enrich(job):
    d = client().get_json(job.extra["detail"], headers={"Accept": "application/json"})
    info = d.get("jobPostingInfo") or {}
    if not info:
        raise SourceError("empty Workday detail")
    locs = [info.get("location") or ""] + list(info.get("additionalLocations") or [])
    job.location = " / ".join(l for l in locs if l) or job.location
    country = (info.get("country") or {}).get("descriptor", "")
    if country and country.lower() not in job.location.lower():
        job.location += f", {country}"
    job.description = html_to_text(info.get("jobDescription"))
    job.remote = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite"}.get(
        (info.get("remoteType") or "").lower(), job.remote if job.remote != "unknown" else remote_from_text(job.location))
    if info.get("startDate"):
        job.posted = info["startDate"][:10]
    if info.get("externalUrl"):
        job.url = info["externalUrl"]
    return job
