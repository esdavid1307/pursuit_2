"""Workday Candidate Experience public search adapter."""

import re
from urllib.parse import quote
import requests

from sources import Job, SourceError, request_json, target_value


PAGE_SIZE = 20
AMBIGUOUS_LOCATION = re.compile(r"^\s*\d+\s+(?:More\s+)?Locations?\s*$", re.IGNORECASE)


def has_ambiguous_location(job: Job) -> bool:
    return bool(AMBIGUOUS_LOCATION.match(job.location or ""))


def resolve_locations(target, job: Job, timeout: int, session: requests.Session | None = None) -> str:
    """The jobs search collapses multi-location postings into "N Locations"; the detail endpoint lists them."""
    session = session or requests.Session()
    host = (target_value(target, "ats_host") or "").strip().strip("/")
    site = (target_value(target, "ats_site") or "").strip().strip("/")
    prefix = f"https://{host}"
    if not host or not site or not job.url.startswith(prefix):
        return job.location
    path = job.url[len(prefix):]
    data = request_json(session, "GET", f"https://{host}/wday/cxs/{quote(_tenant(target))}/{quote(site)}{path}", timeout)
    info = data.get("jobPostingInfo") or {}
    locations = [info.get("location") or ""] + [str(item) for item in info.get("additionalLocations") or []]
    return ", ".join(part for part in locations if part) or job.location


def _tenant(target) -> str:
    host = (target_value(target, "ats_host") or "").casefold()
    identifier = target_value(target, "ats_identifier")
    if "myworkdayjobs.com" in host:
        return host.split(".", 1)[0]
    if "myworkdaysite.com" in host and identifier:
        return identifier
    return identifier or host.split(".", 1)[0]


def fetch_jobs(target, timeout: int, session: requests.Session | None = None) -> list[Job]:
    session = session or requests.Session()
    host = (target_value(target, "ats_host") or "").strip().strip("/")
    site = (target_value(target, "ats_site") or "").strip().strip("/")
    tenant = _tenant(target)
    if not host or not site or not tenant:
        raise SourceError("missing Workday host, tenant, or site")
    endpoint = f"https://{host}/wday/cxs/{quote(tenant)}/{quote(site)}/jobs"
    jobs: list[Job] = []
    offset = 0
    while True:
        data = request_json(session, "POST", endpoint, timeout,
                            json={"appliedFacets": {}, "limit": PAGE_SIZE, "offset": offset, "searchText": ""},
                            headers={"Accept": "application/json", "Content-Type": "application/json"})
        postings = data.get("jobPostings") or []
        for item in postings:
            path = item.get("externalPath") or ""
            url = path if path.startswith("http") else f"https://{host}{path}"
            source_id = item.get("bulletFields", [None])[0] if item.get("bulletFields") else None
            source_id = str(source_id) if source_id else (path.rstrip("/").split("/")[-1] or None)
            jobs.append(Job(source_id, target_value(target, "company"), item.get("title") or "Untitled role",
                            item.get("locationsText") or "", url, "workday", item.get("postedOn")))
        offset += len(postings)
        total = int(data.get("total", offset))
        if not postings or offset >= total:
            break
    return [job for job in jobs if job.url]
