"""Link verification: is the posting still live?

For ATS sources we ask the ATS API for that exact posting (authoritative and
robots-friendly). For everything else we GET the page and look for HTTP errors,
redirects back to a search page, and "job closed" wording.

Returns (status, detail) where status is live | dead | unverified.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RobotsDisallowed, SourceError, client, html_to_text  # noqa: E402

CLOSED = re.compile(
    r"(no longer (available|accepting|open|active)|job (is )?(closed|expired|not found)|position has been filled|"
    r"this (job|position|vacancy|posting) (has been|is) (closed|filled|removed)|page (you are looking for )?(doesn.t|does not|can.t|cannot) (exist|be found)|"
    r"vacature is (niet meer|afgesloten)|niet langer beschikbaar|offre (n.est plus|expirée)|404 not found)",
    re.I,
)


_ASHBY: dict[str, set] = {}


def _api_check(job: dict):
    src = job.get("source", "")
    extra = job.get("extra") or {}
    c = client()
    if src.startswith("greenhouse:"):
        token = src.split(":", 1)[1]
        m = re.search(r"(?:gh_jid=|/jobs/)(\d+)", job["url"])
        if m:
            r = c.request("GET", f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{m.group(1)}")
            return ("live", "greenhouse API 200") if r.status_code == 200 else ("dead", f"greenhouse API {r.status_code}")
    if src.startswith("lever:"):
        site = src.split(":", 1)[1]
        m = re.search(r"lever\.co/[^/]+/([0-9a-f-]{36})", job["url"])
        if m:
            host = "api.eu.lever.co" if "eu.lever.co" in job["url"] else "api.lever.co"
            r = c.request("GET", f"https://{host}/v0/postings/{site}/{m.group(1)}")
            return ("live", "lever API 200") if r.status_code == 200 else ("dead", f"lever API {r.status_code}")
    if src.startswith("ashby:"):
        org = src.split(":", 1)[1]
        if org not in _ASHBY:
            d = c.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{org}")
            _ASHBY[org] = {j.get("jobUrl") for j in d.get("jobs", []) if j.get("isListed", True)}
        return ("live", "ashby board lists it") if job["url"] in _ASHBY[org] else ("dead", "no longer on the Ashby board")
    if src.startswith(("workday:", "smartrecruiters:")) and extra.get("detail"):
        r = c.request("GET", extra["detail"], headers={"Accept": "application/json"})
        if r.status_code == 200:
            try:
                d = r.json()
            except ValueError:
                return None
            if src.startswith("workday:") and not (d.get("jobPostingInfo") or {}).get("title"):
                return ("dead", "workday detail empty")
            if src.startswith("smartrecruiters:") and d.get("active") is False:
                return ("dead", "smartrecruiters posting inactive")
            return ("live", f"{src.split(':')[0]} API 200")
        return ("dead", f"{src.split(':')[0]} API {r.status_code}")
    return None


def check(job: dict) -> tuple[str, str]:
    try:
        res = _api_check(job)
        if res:
            return res
    except (SourceError, KeyError) as e:
        api_err = str(e)
    else:
        api_err = ""
    url = job["url"]
    try:
        r = client().request("GET", url, allow_redirects=True, retries=1)
    except RobotsDisallowed:
        return "unverified", "robots.txt disallows checking this page"
    except SourceError as e:
        return "unverified", f"could not reach page ({e}){' / ' + api_err if api_err else ''}"
    if r.status_code in (404, 410):
        return "dead", f"HTTP {r.status_code}"
    if r.status_code in (401, 403, 407):
        return "unverified", f"HTTP {r.status_code} (blocked)"
    if r.status_code >= 400:
        return "unverified", f"HTTP {r.status_code}"
    final = urlparse(r.url)
    orig = urlparse(url)
    if final.netloc == orig.netloc and len(final.path.rstrip("/")) < len(orig.path.rstrip("/")) * 0.5 and orig.path.count("/") > 1:
        return "dead", f"redirected to {r.url[:80]}"
    if "error=true" in r.url:
        return "dead", "redirected with error=true"
    # schema.org JobPosting with a validThrough date in the past = expired
    for m in re.finditer(r'"validThrough"\s*:\s*"(\d{4}-\d{2}-\d{2})', r.text):
        if m.group(1) < dt.date.today().isoformat():
            return "dead", f"validThrough {m.group(1)} has passed"
    visible = html_to_text(re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", r.text[:400000]))
    if CLOSED.search(visible[:20000]):
        return "dead", "page says the posting is closed"
    title = job.get("title") or ""
    words = [w for w in re.findall(r"[a-zà-ÿ]{4,}", title.lower())][:4]
    if words and not any(w in visible.lower() or w in r.text.lower() for w in words):
        return "unverified", "page loads but does not mention the job title (JavaScript-only page?)"
    return "live", f"HTTP {r.status_code}"


if __name__ == "__main__":
    for u in sys.argv[1:]:
        print(u, check({"url": u, "source": ""}))
