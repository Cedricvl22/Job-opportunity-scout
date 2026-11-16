"""Headless-browser fallback (Playwright) for career sites and job boards with no public feed.

Config-driven: each companies.yaml entry with `ats: browser` describes the page:

  - name: SAP                     # company name (or board name when board: true)
    ats: browser
    board: false                  # true = a job board listing many companies (company read from the card)
    urls: ["https://jobs.sap.com/search/?q=account&locationsearch=Belgium"]
    card: "tr.data-row"           # CSS selector for one job card
    link: "a.jobTitle-link"       # anchor inside the card (default: first <a>)
    title: "a.jobTitle-link"      # optional, default: link text
    location: ".jobLocation"      # optional
    company: ".company"           # boards only
    wait_for: "tr.data-row"       # optional selector to wait for
    location_hint: "Belgium"      # appended when the page is already filtered to Belgium

robots.txt is checked for every URL before the browser opens it; rate limiting
is shared with the HTTP client. Descriptions are fetched on demand (enrich).
"""
from __future__ import annotations

import os
import re
from urllib.parse import urljoin

from common import USER_AGENT, BotBlocked, Job, RobotsDisallowed, SourceError, client, html_to_text, remote_from_text

CHROMIUM = os.environ.get("PW_CHROMIUM_PATH", "/opt/pw-browsers/chromium")

_pw = None
_browser = None


def _get_browser():
    global _pw, _browser
    if _browser is None:
        from playwright.sync_api import sync_playwright

        _pw = sync_playwright().start()
        try:
            _browser = _pw.chromium.launch()
        except Exception:
            if not os.path.exists(CHROMIUM):
                raise
            _browser = _pw.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox"])
    return _browser


def close():
    global _pw, _browser
    if _browser:
        _browser.close()
        _browser = None
    if _pw:
        _pw.stop()
        _pw = None


def _page():
    ctx = _get_browser().new_context(user_agent=USER_AGENT, locale="en-GB")
    return ctx, ctx.new_page()


def _guard(url):
    c = client()
    if not c.allowed(url):
        raise RobotsDisallowed(f"robots.txt disallows {url}")
    from urllib.parse import urlparse

    c._wait(urlparse(url).netloc)


def fetch(entry):
    out = []
    ctx, page = _page()
    try:
        for url in entry["urls"]:
            _guard(url)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                if re.search(r"just a moment|attention required|security check", page.title() or "", re.I):
                    raise BotBlocked(f"{url} shows a bot-protection challenge; not bypassed")
                if entry.get("wait_for"):
                    page.wait_for_selector(entry["wait_for"], timeout=20000)
                else:
                    page.wait_for_load_state("networkidle", timeout=20000)
            except BotBlocked:
                raise
            except Exception as e:
                raise SourceError(f"page load failed for {url}: {str(e).splitlines()[0][:150]}")
            cards = page.query_selector_all(entry["card"])
            for card in cards:
                a = card.query_selector(entry.get("link", "a")) if entry.get("link", "a") != ":self" else card
                if not a:
                    continue
                href = a.get_attribute("href") or ""
                if not href or href.startswith("javascript"):
                    continue
                t_el = card.query_selector(entry["title"]) if entry.get("title") else a
                title = " ".join((t_el.inner_text() if t_el else "").split())
                loc = ""
                if entry.get("location"):
                    l_el = card.query_selector(entry["location"])
                    loc = " ".join(l_el.inner_text().split()) if l_el else ""
                if entry.get("location_hint") and entry["location_hint"].lower() not in loc.lower():
                    loc = f"{loc}, {entry['location_hint']}".strip(", ")
                company = entry["name"]
                if entry.get("board"):
                    c_el = card.query_selector(entry["company"]) if entry.get("company") else None
                    company = " ".join(c_el.inner_text().split()) if c_el else ""
                if not title:
                    continue
                out.append(Job(
                    title=title, company=company, location=loc, url=urljoin(url, href),
                    source=f"browser:{entry.get('key', entry['name'])}", remote=remote_from_text(loc),
                    extra={"desc_selector": entry.get("description", "main")},
                ))
    finally:
        ctx.close()
    if not out:
        raise SourceError("page loaded but no job cards matched (selectors may be outdated)")
    return out


def enrich(job):
    _guard(job.url)
    ctx, page = _page()
    try:
        page.goto(job.url, wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        sel = job.extra.get("desc_selector") or "main"
        el = page.query_selector(sel) or page.query_selector("body")
        job.description = html_to_text(el.inner_html())[:20000] if el else ""
    finally:
        ctx.close()
    return job
