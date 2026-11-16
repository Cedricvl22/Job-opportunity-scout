"""Helpers for HTML job boards: fetch a page politely, read schema.org JobPosting data."""
import json
import re

from bs4 import BeautifulSoup

from common import SourceError, client, html_to_text, iso_date


def get_soup(url):
    r = client().request("GET", url)
    if r.status_code != 200:
        raise SourceError(f"HTTP {r.status_code} for {url}")
    return BeautifulSoup(r.text, "html.parser"), r


def job_posting_ld(soup):
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(s.string or "")
        except (ValueError, TypeError):
            continue
        items = d if isinstance(d, list) else d.get("@graph", [d]) if isinstance(d, dict) else []
        for x in items:
            if isinstance(x, dict) and x.get("@type") == "JobPosting":
                return x
    return None


def enrich_from_page(job):
    soup, _ = get_soup(job.url)
    ld = job_posting_ld(soup)
    if ld:
        job.description = html_to_text(ld.get("description"))
        job.posted = iso_date(ld.get("datePosted")) or job.posted
        sal = ld.get("baseSalary") or {}
        if isinstance(sal, dict) and (sal.get("value") or {}).get("minValue"):
            v = sal["value"]
            job.salary = f"{v.get('minValue')}-{v.get('maxValue')} {sal.get('currency','')} {v.get('unitText','')} (stated)"
        if ld.get("jobLocationType") == "TELECOMMUTE":
            job.remote = "remote"
        if ld.get("validThrough"):
            job.extra["valid_through"] = ld["validThrough"]
        return job
    el = soup.find(attrs={"itemprop": "description"}) or soup.find("main") or soup.body
    parts = [e.get_text(" ", strip=True) for e in soup.find_all(attrs={"itemprop": "description"})] if soup.find(attrs={"itemprop": "description"}) else [el.get_text(" ", strip=True) if el else ""]
    job.description = re.sub(r"\s+", " ", " \n".join(parts))[:20000]
    return job
