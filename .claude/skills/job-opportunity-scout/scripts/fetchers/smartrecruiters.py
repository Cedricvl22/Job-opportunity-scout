"""SmartRecruiters Posting API (public):
   list:   https://api.smartrecruiters.com/v1/companies/{id}/postings?limit=100&offset=N
   detail: https://api.smartrecruiters.com/v1/companies/{id}/postings/{postingId}
"""
from common import Job, client, html_to_text, iso_date

MAX_PAGES = 30


def fetch(entry):
    cid = entry["id"]
    out, offset = [], 0
    params = "&country=be" if entry.get("country_filter", True) else ""
    for _ in range(MAX_PAGES):
        data = client().get_json(f"https://api.smartrecruiters.com/v1/companies/{cid}/postings?limit=100&offset={offset}{params}")
        content = data.get("content", [])
        for j in content:
            l = j.get("location") or {}
            loc = ", ".join(x for x in [l.get("city"), l.get("region"), l.get("country", "").upper()] if x)
            remote = "remote" if l.get("remote") else ("hybrid" if l.get("hybrid") else "unknown")
            out.append(Job(
                title=j.get("name", "").strip(), company=entry["name"], location=loc,
                url=f"https://jobs.smartrecruiters.com/{cid}/{j.get('id')}", source=f"smartrecruiters:{cid}",
                remote=remote, posted=iso_date(j.get("releasedDate")), country=(l.get("country") or "").upper(),
                extra={"detail": j.get("ref") or f"https://api.smartrecruiters.com/v1/companies/{cid}/postings/{j.get('id')}"},
            ))
        offset += len(content)
        if not content or offset >= data.get("totalFound", 0):
            break
    return out


def enrich(job):
    d = client().get_json(job.extra["detail"])
    secs = ((d.get("jobAd") or {}).get("sections") or {})
    job.description = "\n".join(html_to_text((secs.get(k) or {}).get("text")) for k in ("jobDescription", "qualifications", "additionalInformation", "companyDescription"))
    if d.get("postingUrl"):
        job.url = d["postingUrl"]
    return job
