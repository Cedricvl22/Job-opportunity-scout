"""Shared building blocks: the Job schema, a polite HTTP client, and text helpers.

Every fetcher returns a list of `Job` objects. The HTTP client:
  * sends a clear, neutral User-Agent (no personal data),
  * checks robots.txt before every request and refuses disallowed URLs,
  * rate-limits per host,
  * retries transient errors (429 / 5xx / network) with backoff.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import threading
import time
import urllib.robotparser
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = SKILL_DIR / "config"
DATA_DIR = Path(os.environ.get("JOB_SCOUT_DATA", SKILL_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = os.environ.get(
    "JOB_SCOUT_USER_AGENT",
    "job-opportunity-scout/1.0 (personal job-search script; respects robots.txt; low request rate)",
)
DEFAULT_DELAY = float(os.environ.get("JOB_SCOUT_DELAY", "1.0"))  # seconds between requests to one host
TIMEOUT = 25


# --------------------------------------------------------------------------- schema
@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    source: str  # e.g. "greenhouse:datadog", "adzuna"
    remote: str = "unknown"  # onsite | hybrid | remote | unknown
    posted: str = ""  # ISO date (YYYY-MM-DD) when known
    description: str = ""
    # enrichment / metadata (not part of the user-facing schema but carried along)
    bucket: str = ""  # A | B | "" (unknown, Claude decides)
    industry: str = ""
    salary: str = ""  # only when the source states it
    country: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def id(self) -> str:
        return hashlib.sha1(normalize_url(self.url).encode()).hexdigest()[:12]


# --------------------------------------------------------------------------- errors
class SourceError(Exception):
    """A source failed in a way that must be reported."""


class RobotsDisallowed(SourceError):
    pass


class BotBlocked(SourceError):
    """The site serves a bot-protection challenge. We report it and never try to get around it."""


# --------------------------------------------------------------------------- http
class PoliteClient:
    def __init__(self, delay: float = DEFAULT_DELAY):
        self.delay = delay
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en,nl;q=0.8,fr;q=0.5"})
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()
        self.request_count = 0

    # robots ---------------------------------------------------------------
    def _robots_for(self, url: str):
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base in self._robots:
            if isinstance(self._robots[base], BotBlocked):
                raise self._robots[base]
            return self._robots[base]
        rp = urllib.robotparser.RobotFileParser()
        # RFC 9309: 4xx (incl. 401/403) = "unavailable" -> no restrictions;
        # 5xx / 429 / unreachable = assume complete disallow.
        try:
            self._wait(p.netloc)
            r = self.s.get(base + "/robots.txt", timeout=TIMEOUT)
            if r.headers.get("cf-mitigated") == "challenge":
                self._robots[base] = BotBlocked(f"{p.netloc} answers with a bot-protection challenge (Cloudflare); not bypassed")
                raise self._robots[base]
            if r.status_code == 429 or r.status_code >= 500:
                rp.parse(["User-agent: *", "Disallow: /"])
            elif r.status_code >= 400:
                rp = None
            else:
                rp.parse(r.text.splitlines())
        except requests.RequestException:
            rp = None  # network error: the real request will surface it
        self._robots[base] = rp
        return rp

    def allowed(self, url: str) -> bool:
        rp = self._robots_for(url)
        return True if rp is None else rp.can_fetch(USER_AGENT, url)

    # rate limit -----------------------------------------------------------
    def _wait(self, host: str):
        with self._lock:
            now = time.monotonic()
            last = self._last.get(host, 0)
            sleep = self.delay - (now - last)
            if sleep > 0:
                time.sleep(sleep)
            self._last[host] = time.monotonic()

    # requests -------------------------------------------------------------
    def request(self, method: str, url: str, *, check_robots: bool = True, retries: int = 2, **kw) -> requests.Response:
        if check_robots and not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        kw.setdefault("timeout", TIMEOUT)
        host = urlparse(url).netloc
        err: Exception | None = None
        for attempt in range(retries + 1):
            self._wait(host)
            try:
                self.request_count += 1
                r = self.s.request(method, url, **kw)
                if r.headers.get("cf-mitigated") == "challenge":
                    raise BotBlocked(f"{host} answers with a bot-protection challenge (Cloudflare); not bypassed")
                if r.status_code == 429 or r.status_code >= 500:
                    err = SourceError(f"HTTP {r.status_code} from {host}")
                    time.sleep(2 * (attempt + 1))
                    continue
                return r
            except requests.RequestException as e:
                err = SourceError(f"{type(e).__name__}: {str(e)[:200]}")
                time.sleep(2 * (attempt + 1))
        raise err or SourceError("unknown error")

    def get_json(self, url: str, **kw):
        r = self.request("GET", url, **kw)
        if r.status_code != 200:
            raise SourceError(f"HTTP {r.status_code} for {redact(url)}")
        try:
            return r.json()
        except ValueError:
            raise SourceError(f"non-JSON response from {redact(url)}")

    def post_json(self, url: str, payload: dict, **kw):
        r = self.request("POST", url, json=payload, **kw)
        if r.status_code != 200:
            raise SourceError(f"HTTP {r.status_code} for {redact(url)}")
        try:
            return r.json()
        except ValueError:
            raise SourceError(f"non-JSON response from {redact(url)}")


_client: PoliteClient | None = None


def client() -> PoliteClient:
    global _client
    if _client is None:
        _client = PoliteClient()
    return _client


# --------------------------------------------------------------------------- helpers
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")


def html_to_text(s: str | None) -> str:
    if not s:
        return ""
    s = html.unescape(s)  # Greenhouse double-escapes
    s = re.sub(r"(?i)<\s*(br|/p|/li|/h\d|/div)\s*/?>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = _TAG.sub(" ", s)
    s = html.unescape(s)
    s = _WS.sub(" ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def iso_date(v) -> str:
    """Accept epoch ms/s, ISO strings, or None -> 'YYYY-MM-DD' or ''."""
    if v in (None, "", 0):
        return ""
    if isinstance(v, (int, float)):
        if v > 1e11:
            v = v / 1000
        return time.strftime("%Y-%m-%d", time.gmtime(v))
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(v))
    return m.group(1) if m else ""


TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gh_src", "source", "ref", "lever-source", "src"}


def normalize_url(url: str) -> str:
    p = urlparse(url.strip())
    q = [(k, v) for k, v in parse_qsl(p.query) if k.lower() not in TRACKING_PARAMS]
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower() or "https", p.netloc.lower(), path, "", urlencode(q), ""))


_COMPANY_SUFFIX = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|plc|corp|corporation|co|company|nv|n\.v|bv|b\.v|sa|s\.a|srl|bvba|gmbh|ag|se|group|holding|holdings|belgium|benelux|europe|emea)\b\.?",
    re.I,
)


def norm_company(name: str) -> str:
    n = _COMPANY_SUFFIX.sub(" ", name or "")
    return re.sub(r"[^a-z0-9]+", "", n.lower())


def norm_title(t: str) -> str:
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", (t or "").lower())
    t = re.sub(r"\b(m/f/x|m/v/x|h/f|m/f|f/m|m/w/d|m/v)\b", " ", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def company_title_key(company: str, title: str) -> str:
    return f"{norm_company(company)}|{norm_title(title)}"


def redact(url: str) -> str:
    """Strip API keys from URLs before they reach logs."""
    url = re.sub(r"(app_id|app_key|api_key|key|token)=[^&]+", r"\1=***", url)
    url = re.sub(r"(jooble\.org/api/)[^/?]+", r"\1***", url)
    return url


def load_yaml(name: str):
    import yaml

    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def dump_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def remote_from_text(*texts: str) -> str:
    t = " ".join(x for x in texts if x).lower()
    if re.search(r"\bhybrid\b|hybride", t):
        return "hybrid"
    if re.search(r"\bremote\b|work from home|télétravail|thuiswerk|anywhere", t):
        return "remote"
    if re.search(r"on-?site|in office|op kantoor", t):
        return "onsite"
    return "unknown"
