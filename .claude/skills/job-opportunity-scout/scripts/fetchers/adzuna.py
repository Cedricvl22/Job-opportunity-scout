"""Adzuna Belgium search API. Needs ADZUNA_APP_ID and ADZUNA_APP_KEY (free at https://developer.adzuna.com).
   GET https://api.adzuna.com/v1/api/jobs/be/search/{page}?app_id=..&app_key=..&what=..&results_per_page=50
"""
import os

from common import Job, SourceError, client, html_to_text, iso_date, remote_from_text
from urllib.parse import urlencode


class MissingKey(SourceError):
    pass


def fetch(cfg):
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        raise MissingKey("ADZUNA_APP_ID / ADZUNA_APP_KEY not set")
    out = []
    for q in cfg.get("queries", []):
        for page in range(1, cfg.get("pages", 2) + 1):
            params = {"app_id": app_id, "app_key": app_key, "what": q, "results_per_page": 50,
                      "max_days_old": cfg.get("max_days_old", 45), "content-type": "application/json"}
            d = client().get_json(f"https://api.adzuna.com/v1/api/jobs/be/search/{page}?{urlencode(params)}")
            res = d.get("results", [])
            for j in res:
                loc = (j.get("location") or {}).get("display_name", "")
                sal = ""
                if j.get("salary_min") and str(j.get("salary_is_predicted")) != "1":
                    sal = f"{int(j['salary_min'])}-{int(j.get('salary_max') or j['salary_min'])} EUR (stated)"
                out.append(Job(
                    title=html_to_text(j.get("title")), company=(j.get("company") or {}).get("display_name", ""),
                    location=loc + ", Belgium", url=j.get("redirect_url", ""), source="adzuna",
                    remote=remote_from_text(loc, j.get("title", "")), posted=iso_date(j.get("created")),
                    description=html_to_text(j.get("description")), salary=sal, country="BE",
                    extra={"snippet_only": True},
                ))
            if len(res) < 50:
                break
    return out
