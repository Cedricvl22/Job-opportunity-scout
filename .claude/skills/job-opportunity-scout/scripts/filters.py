"""Code-side pre-filter: title keywords, location, seniority, excluded companies."""
from __future__ import annotations

import re
from dataclasses import dataclass

from common import Job, load_yaml


@dataclass
class Verdict:
    keep: bool
    reason: str  # why it was dropped, or the location class when kept
    location_class: str = ""  # belgium | remote-unconfirmed | vague


class PreFilter:
    def __init__(self, cfg: dict | None = None):
        cfg = cfg or load_yaml("filters.yaml")
        c = lambda pats: [re.compile(p, re.I) for p in pats]
        self.t_inc = c(cfg["title"]["include"])
        self.t_exc = c(cfg["title"]["exclude"])
        self.loc_be = c(cfg["location"]["belgium"])
        self.loc_remote = c(cfg["location"]["remote_region"])
        self.max_years = int(cfg["experience"]["max_years_required"])
        self.co_exc = c(cfg["exclude_companies"])

    # --- individual checks -------------------------------------------------
    def title_ok(self, title: str) -> tuple[bool, str]:
        t = title or ""
        for p in self.t_exc:
            if p.search(t):
                return False, f"title excluded ({p.pattern})"
        for p in self.t_inc:
            if p.search(t):
                return True, ""
        return False, "title not a target role"

    def company_ok(self, company: str) -> bool:
        return not any(p.search(company or "") for p in self.co_exc)

    def _is_be(self, text: str) -> bool:
        return any(p.search(text or "") for p in self.loc_be)

    def location_class(self, job: Job) -> str:
        loc = job.location or ""
        if (job.country or "").upper() in ("BE", "BEL", "BELGIUM") or self._is_be(loc):
            return "belgium"
        remoteish = job.remote == "remote" or re.search(r"\bremote\b", loc, re.I)
        if remoteish and any(p.search(loc) for p in self.loc_remote):
            return "remote-unconfirmed"
        vague = (not loc.strip()) or re.search(r"\b\d+\s+locations?\b|multiple|various|several|flexible", loc, re.I)
        if remoteish and not vague:
            leftover = re.sub(r"(?i)\b(remote|fully|100%|work from home|wfh|home[- ]based)\b|[^a-z]", "", loc.lower())
            if not leftover and not job.country:
                # bare "Remote" with no region: check the description for a region / Belgium
                vague = True
        if vague:
            return "vague"
        return "outside"

    def years_required(self, text: str) -> int:
        """Largest *minimum* years-of-experience requirement found in the text (0 if none)."""
        best = 0
        for m in re.finditer(
            r"(?:at least|minimum(?: of)?|min\.?|minstens|au moins)?\s*(\d{1,2})\s*(?:\+|-\s*\d{1,2}|to\s*\d{1,2})?\s*\+?\s*(?:years?|yrs|jaar|ans|année?s)",
            text or "",
            re.I,
        ):
            ctx = text[m.end(): m.end() + 80].lower()
            if re.search(r"experience|ervaring|expérience|in (enterprise|b2b|saas|software|sales|selling|a quota)|of (enterprise|b2b|saas|software|sales|selling|quota|closing)|selling|sales", ctx):
                n = int(m.group(1))
                if n <= 15:  # larger numbers are company age ("30+ years in the market"), not a requirement
                    best = max(best, n)
        return best

    # --- combined ------------------------------------------------------------
    def check_basic(self, job: Job) -> Verdict:
        """Cheap checks on list data (before description enrichment)."""
        if not self.company_ok(job.company):
            return Verdict(False, "excluded company")
        ok, why = self.title_ok(job.title)
        if not ok:
            return Verdict(False, why)
        lc = self.location_class(job)
        if lc == "outside":
            return Verdict(False, f"location outside target ({job.location[:60]})")
        return Verdict(True, lc, lc)

    def check_full(self, job: Job, basic: Verdict) -> Verdict:
        """Checks that need the description (run after enrichment)."""
        lc = basic.location_class
        if lc == "vague":
            desc = job.description or ""
            if self._is_be(job.location) or self._is_be(desc[:4000]):
                lc = "belgium"
            elif re.search(r"\bremote\b", (job.location or "") + " " + desc, re.I) and any(
                p.search(desc[:4000]) for p in self.loc_remote
            ):
                lc = "remote-unconfirmed"
            else:
                return Verdict(False, "location not confirmed as Belgium/remote-Europe")
        yrs = self.years_required(job.description)
        if yrs >= self.max_years:
            return Verdict(False, f"requires {yrs}+ years")
        return Verdict(True, lc, lc)
