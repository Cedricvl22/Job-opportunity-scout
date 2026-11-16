"""Workable public widget API: https://apply.workable.com/api/v1/widget/accounts/{account}?details=true"""
from common import Job, client, html_to_text, iso_date


def fetch(entry):
    acc = entry["id"]
    data = client().get_json(f"https://apply.workable.com/api/v1/widget/accounts/{acc}?details=true")
    out = []
    for j in data.get("jobs", []):
        locs = j.get("locations") or [{"city": j.get("city"), "country": j.get("country"), "countryCode": j.get("country_code")}]
        loc = " / ".join(", ".join(x for x in [l.get("city"), l.get("region"), l.get("country")] if x) for l in locs)
        remote = "remote" if j.get("telecommuting") else ("hybrid" if (j.get("workplace") or "") == "hybrid" else "unknown")
        out.append(Job(
            title=j.get("title", "").strip(), company=entry["name"], location=loc,
            url=j.get("url") or j.get("shortlink") or f"https://apply.workable.com/{acc}/j/{j.get('shortcode')}/",
            source=f"workable:{acc}", remote=remote,
            posted=iso_date(j.get("published_on") or j.get("created_at")),
            description=html_to_text(j.get("description")) + "\n" + html_to_text(j.get("requirements")),
            country=(locs[0].get("countryCode") or "").upper() if locs else "",
        ))
    return out
