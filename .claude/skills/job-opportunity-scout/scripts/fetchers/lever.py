"""Lever postings API: https://api.lever.co/v0/postings/{site}?mode=json (EU: api.eu.lever.co)"""
from common import Job, client, html_to_text, iso_date, remote_from_text


def fetch(entry):
    site = entry["id"]
    host = "api.eu.lever.co" if entry.get("region") == "eu" else "api.lever.co"
    data = client().get_json(f"https://{host}/v0/postings/{site}?mode=json")
    out = []
    for j in data:
        cat = j.get("categories") or {}
        locs = cat.get("allLocations") or [cat.get("location", "")]
        loc = " / ".join(l for l in locs if l)
        wt = (j.get("workplaceType") or "").lower()
        remote = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite", "on-site": "onsite"}.get(wt) or remote_from_text(loc)
        desc = (j.get("descriptionPlain") or "") + "\n" + "\n".join(
            f"{l.get('text','')}: " + " ".join(html_to_text(l.get("content", "")).split()) for l in j.get("lists") or []
        ) + "\n" + (j.get("additionalPlain") or "")
        sal = j.get("salaryRange") or {}
        out.append(Job(
            title=j.get("text", "").strip(), company=entry["name"], location=loc,
            url=j.get("hostedUrl", ""), source=f"lever:{site}", remote=remote,
            posted=iso_date(j.get("createdAt")), description=desc.strip(),
            country=(j.get("country") or "").upper(),
            salary=f"{sal.get('min')}-{sal.get('max')} {sal.get('currency','')} {sal.get('interval','')}".strip() if sal.get("min") else "",
        ))
    return out
