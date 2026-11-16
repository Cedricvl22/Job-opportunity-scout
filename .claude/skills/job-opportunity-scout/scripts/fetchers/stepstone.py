"""StepStone.be public listing pages /vacatures/<slug> (allowed by robots.txt; query-string
search pages are disallowed, so we only use path slugs). Detail pages carry JobPosting JSON-LD."""
from common import Job, remote_from_text
from fetchers._html import enrich_from_page, get_soup


def fetch(cfg):
    out = []
    for slug in cfg.get("slugs", []):
        soup, _ = get_soup(f"https://www.stepstone.be/vacatures/{slug}")
        for art in soup.select('article[data-at="job-item"]'):
            a = art.select_one('a[data-at="job-item-title"]')
            if not a or not a.get("href"):
                continue
            company = art.select_one('[data-at="job-item-company-name"]')
            loc = art.select_one('[data-at="job-item-location"]')
            loc_t = loc.get_text(" ", strip=True) if loc else ""
            out.append(Job(title=a.get_text(" ", strip=True), company=company.get_text(" ", strip=True) if company else "",
                           location=(loc_t + ", Belgium").strip(", "), url=a["href"], source="stepstone",
                           remote=remote_from_text(loc_t), country="BE"))
    return out


enrich = enrich_from_page
