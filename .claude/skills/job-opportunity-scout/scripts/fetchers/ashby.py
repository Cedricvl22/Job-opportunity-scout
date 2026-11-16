"""Ashby job board API: https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true"""
from common import Job, client, html_to_text, iso_date


def fetch(entry):
    org = entry["id"]
    data = client().get_json(f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true")
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        addr = ((j.get("address") or {}).get("postalAddress") or {})
        loc = " / ".join(l for l in locs if l)
        if addr.get("addressCountry") and addr["addressCountry"].lower() not in loc.lower():
            loc += f", {addr['addressCountry']}"
        wt = (j.get("workplaceType") or "").lower()
        remote = "remote" if j.get("isRemote") or wt == "remote" else ("hybrid" if wt == "hybrid" else ("onsite" if wt == "onsite" else "unknown"))
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        out.append(Job(
            title=j.get("title", "").strip(), company=entry["name"], location=loc,
            url=j.get("jobUrl", ""), source=f"ashby:{org}", remote=remote,
            posted=iso_date(j.get("publishedAt")),
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
            salary=comp,
        ))
    return out
