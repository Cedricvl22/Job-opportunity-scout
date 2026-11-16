"""Greenhouse job board API: https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"""
from common import Job, client, html_to_text, iso_date, remote_from_text


def fetch(entry):
    token = entry["id"]
    data = client().get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true&pay_transparency=true")
    out = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        offices = ", ".join(o.get("name", "") for o in j.get("offices") or [] if o.get("name"))
        if offices and offices.lower() not in loc.lower():
            loc = f"{loc} ({offices})" if loc else offices
        desc = html_to_text(j.get("content"))
        pay = []
        for p in j.get("pay_input_ranges") or []:
            if p.get("min_cents"):
                label = html_to_text(p.get("title"))[:80]
                ote = "OTE" if "on-target" in (label + html_to_text(p.get("blurb"))).lower() or "ote" in html_to_text(p.get("blurb")).lower() else "range"
                pay.append(f"{p['min_cents'] // 100:,}-{p['max_cents'] // 100:,} {p.get('currency_type', '')} ({ote}, stated: {label})")
        out.append(Job(
            title=j.get("title", "").strip(), company=entry["name"], location=loc,
            url=j.get("absolute_url", ""), source=f"greenhouse:{token}",
            remote=remote_from_text(loc, j.get("title", "")),
            posted=iso_date(j.get("first_published") or j.get("updated_at")),
            description=desc, salary="; ".join(pay),
        ))
    return out
