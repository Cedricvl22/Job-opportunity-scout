"""Teamtailor public RSS feed: https://{company}.teamtailor.com/jobs.rss
(Teamtailor's JSON API needs a company token, the RSS feed is public.)"""
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from common import Job, SourceError, client, html_to_text, remote_from_text

NS = {"tt": "https://teamtailor.com/locations"}


def fetch(entry):
    sub = entry["id"]
    host = entry.get("host", f"{sub}.teamtailor.com")
    r = client().request("GET", f"https://{host}/jobs.rss")
    if r.status_code != 200:
        raise SourceError(f"HTTP {r.status_code} for {host}/jobs.rss")
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        raise SourceError(f"bad RSS from {host}: {e}")
    out = []
    for it in root.iter("item"):
        locs = []
        # Teamtailor nests locations as <tt:locations><tt:location><tt:city>...; collect their text
        for el in it:
            if "location" in el.tag.lower():
                txt = " ".join(t.strip() for t in el.itertext() if t.strip())
                if txt:
                    locs.append(txt)
        desc = html_to_text(it.findtext("description"))
        pub = it.findtext("pubDate") or ""
        try:
            posted = parsedate_to_datetime(pub).date().isoformat() if pub else ""
        except (TypeError, ValueError):
            posted = ""
        remote_status = next((el.text for el in it if el.tag.lower().endswith("remotestatus") and el.text), "")
        loc = " / ".join(dict.fromkeys(locs))
        out.append(Job(
            title=(it.findtext("title") or "").strip(), company=entry["name"], location=loc,
            url=(it.findtext("link") or "").strip(), source=f"teamtailor:{sub}",
            remote={"fully": "remote", "temporary": "remote", "hybrid": "hybrid", "none": "onsite"}.get(remote_status.lower(), remote_from_text(loc)),
            posted=posted, description=desc,
        ))
    return out
