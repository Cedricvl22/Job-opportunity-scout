"""Remotive remote-jobs API (no key; they ask for max ~4 calls/day): https://remotive.com/api/remote-jobs?category=sales-business"""
from common import Job, client, html_to_text, iso_date


def fetch(cfg):
    d = client().get_json(f"https://remotive.com/api/remote-jobs?category={cfg.get('category', 'sales-business')}")
    out = []
    for j in d.get("jobs", []):
        out.append(Job(
            title=j.get("title", "").strip(), company=j.get("company_name", ""),
            location="Remote - " + (j.get("candidate_required_location") or ""), url=j.get("url", ""),
            source="remotive", remote="remote", posted=iso_date(j.get("publication_date")),
            description=html_to_text(j.get("description")), salary=j.get("salary", ""),
        ))
    return out
