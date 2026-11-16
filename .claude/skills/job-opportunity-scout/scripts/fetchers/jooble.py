"""Jooble REST API. Needs JOOBLE_API_KEY (free at https://jooble.org/api/about).
   POST https://jooble.org/api/{key}  {"keywords": "...", "location": "Belgium", "page": 1}
"""
import os

from common import Job, SourceError, client, html_to_text, iso_date, remote_from_text


class MissingKey(SourceError):
    pass


def fetch(cfg):
    key = os.environ.get("JOOBLE_API_KEY")
    if not key:
        raise MissingKey("JOOBLE_API_KEY not set")
    out = []
    for q in cfg.get("queries", []):
        for page in range(1, cfg.get("pages", 2) + 1):
            d = client().post_json(f"https://jooble.org/api/{key}", {"keywords": q, "location": cfg.get("location", "Belgium"), "page": str(page)})
            res = d.get("jobs", [])
            for j in res:
                loc = j.get("location", "")
                out.append(Job(
                    title=html_to_text(j.get("title")), company=j.get("company", ""), location=loc,
                    url=j.get("link", ""), source="jooble", remote=remote_from_text(loc, j.get("type", "")),
                    posted=iso_date(j.get("updated")), description=html_to_text(j.get("snippet")),
                    salary=j.get("salary", ""), extra={"snippet_only": True, "via": j.get("source", "")},
                ))
            if len(res) < 20:
                break
    return out
