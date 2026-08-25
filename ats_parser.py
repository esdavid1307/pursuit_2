"""Turn individual job links into reusable ATS identities."""

from dataclasses import dataclass
from urllib.parse import unquote, urlsplit, urlunsplit
import re


@dataclass(frozen=True)
class ATSInfo:
    ats: str
    ats_identifier: str | None
    ats_host: str
    ats_site: str | None
    original_job_url: str
    identity_key: str


def normalize_url(value: str) -> str | None:
    value = value.strip().strip("<>")
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    host = parsed.hostname.lower()
    netloc = host
    if port and not ((parsed.scheme.lower() == "http" and port == 80) or (parsed.scheme.lower() == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


def _path_segments(url: str) -> list[str]:
    return [unquote(part) for part in urlsplit(url).path.split("/") if part]


def normalize_company_name(value: str) -> str:
    """Create a stable key while retaining meaningful letters and numbers."""
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def parse_ats(url: str, company_name: str | None = None) -> ATSInfo | None:
    normalized = normalize_url(url)
    if not normalized:
        return None
    parsed = urlsplit(normalized)
    host = parsed.hostname or ""
    parts = _path_segments(normalized)

    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and parts:
        identifier = parts[0]
        key = f"greenhouse|{host}|{identifier.lower()}"
        return ATSInfo("greenhouse", identifier, host, identifier, normalized, key)

    if host == "jobs.lever.co" and parts:
        identifier = parts[0]
        key = f"lever|{host}|{identifier.lower()}"
        return ATSInfo("lever", identifier, host, identifier, normalized, key)

    workday_match = re.fullmatch(r"([^.]+)\.wd\d+\.myworkdayjobs\.com", host)
    if workday_match and parts:
        identifier = workday_match.group(1)
        site = parts[0]
        key = f"workday|{host}|{site.lower()}"
        return ATSInfo("workday", identifier, host, site, normalized, key)

    # Unknown job boards often have one URL per job. Group those URLs by company
    # and host; the observations table still retains every individual job URL.
    company_key = normalize_company_name(company_name or "")
    identity = f"{company_key}|{host}" if company_key else normalized
    return ATSInfo("unknown", None, host, None, normalized, f"unknown|{identity}")
