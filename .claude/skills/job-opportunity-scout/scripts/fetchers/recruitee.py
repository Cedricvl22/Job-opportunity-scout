"""Recruitee public careers API: https://{company}.recruitee.com/api/offers/"""
from common import Job, client, html_to_text, iso_date


def fetch(entry):
    sub = entry["id"]
    data = client().get_json(f"https://{sub}.recruitee.com/api/offers/")
    out = []
    for j in data.get("offers", []):
        locs = j.get("locations") or []
        loc = " / ".join(", ".join(x for x in [l.get("city"), l.get("country")] if x) for l in locs) or j.get("location", "")
        remote = "remote" if j.get("remote") else ("hybrid" if j.get("hybrid") else ("onsite" if j.get("on_site") else "unknown"))
        out.append(Job(
            title=(j.get("title") or "").strip(), company=entry["name"], location=loc,
            url=j.get("careers_url") or f"https://{sub}.recruitee.com/o/{j.get('slug')}",
            source=f"recruitee:{sub}", remote=remote, posted=iso_date(j.get("published_at") or j.get("created_at")),
            description=html_to_text(j.get("description")) + "\n" + html_to_text(j.get("requirements")),
            country=(j.get("country_code") or "").upper(),
            salary=str(j.get("salary") or "") if (j.get("salary") or {}).get("min") else "",
        ))
    return out
