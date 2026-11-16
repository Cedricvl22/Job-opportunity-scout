"""Personio public XML feed: https://{company}.jobs.personio.de/xml (or .com via `domain`)"""
import xml.etree.ElementTree as ET

from common import Job, SourceError, client, html_to_text, iso_date


def fetch(entry):
    sub = entry["id"]
    domain = entry.get("domain", "jobs.personio.de")
    base = f"https://{sub}.{domain}"
    r = client().request("GET", f"{base}/xml?language=en")
    if r.status_code != 200:
        raise SourceError(f"HTTP {r.status_code} for {base}/xml")
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        raise SourceError(f"bad XML from {base}: {e}")
    out = []
    for p in root.findall("position"):
        g = lambda tag: (p.findtext(tag) or "").strip()
        offices = [g("office")] + [o.text or "" for o in p.findall("additionalOffices/office")]
        desc = "\n".join(
            f"{(d.findtext('name') or '').strip()}\n{html_to_text(d.findtext('value'))}" for d in p.findall("jobDescriptions/jobDescription")
        )
        out.append(Job(
            title=g("name"), company=entry["name"], location=" / ".join(o for o in offices if o),
            url=f"{base}/job/{g('id')}", source=f"personio:{sub}",
            remote="unknown", posted=iso_date(g("createdAt")), description=desc,
            extra={"seniority": g("seniority"), "yearsOfExperience": g("yearsOfExperience")},
        ))
    return out
