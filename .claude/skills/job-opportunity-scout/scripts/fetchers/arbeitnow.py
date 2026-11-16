"""Arbeitnow free job board API (no key): https://www.arbeitnow.com/api/job-board-api?page=N
Mostly DACH/EU jobs; useful for remote-Europe and occasional Belgian roles."""
from common import Job, client, html_to_text, iso_date


def fetch(cfg):
    out = []
    for page in range(1, cfg.get("pages", 5) + 1):
        d = client().get_json(f"https://www.arbeitnow.com/api/job-board-api?page={page}")
        data = d.get("data", [])
        for j in data:
            out.append(Job(
                title=j.get("title", "").strip(), company=j.get("company_name", ""), location=j.get("location", ""),
                url=j.get("url", ""), source="arbeitnow", remote="remote" if j.get("remote") else "unknown",
                posted=iso_date(j.get("created_at")), description=html_to_text(j.get("description")),
            ))
        if not (d.get("links") or {}).get("next"):
            break
    return out
