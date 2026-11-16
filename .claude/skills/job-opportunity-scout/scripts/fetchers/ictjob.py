"""ICTjob.be (Belgian IT job board), public search pages. robots.txt allows /*/search-it-jobs and /*/job/."""
from urllib.parse import quote_plus

from common import Job, remote_from_text
from fetchers._html import enrich_from_page, get_soup


def fetch(cfg):
    out = []
    for q in cfg.get("queries", []):
        soup, _ = get_soup(f"https://www.ictjob.be/en/search-it-jobs?keywords={quote_plus(q)}")
        for li in soup.select("li.search-item"):
            a = li.select_one("a.job-title")
            if not a or not a.get("href"):
                continue
            title = a.get_text(" ", strip=True)
            company = (li.select_one(".job-company") or a).get_text(" ", strip=True)
            loc = " ".join(x.get_text(" ", strip=True) for x in li.select(".job-location"))
            out.append(Job(title=title, company=company, location=(loc + ", Belgium").strip(", "), url=a["href"].strip(),
                           source="ictjob", remote=remote_from_text(loc), country="BE"))
    return out


enrich = enrich_from_page
