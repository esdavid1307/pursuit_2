"""SmartRecruiters public postings API adapter."""

import requests

from monitor.sources import Job, SourceError, request_json, target_value


PAGE_SIZE = 100
MAX_PAGES = 10


def _location(item) -> str:
    location = item.get("location") or {}
    country = (location.get("country") or "").strip()
    country = "Canada" if country.casefold() == "ca" else country.upper()
    parts = [location.get("city") or "", location.get("region") or "", country]
    text = ", ".join(part for part in parts if part)
    if location.get("remote"):
        text = f"Remote, {text}" if text else "Remote"
    return text


def fetch_jobs(target, timeout: int, session: requests.Session | None = None) -> list[Job]:
    session = session or requests.Session()
    company = target_value(target, "ats_identifier") or target_value(target, "ats_site")
    if not company:
        raise SourceError("missing SmartRecruiters company identifier")
    endpoint = f"https://api.smartrecruiters.com/v1/companies/{company}/postings"
    jobs: list[Job] = []
    offset = 0
    for _ in range(MAX_PAGES):
        data = request_json(session, "GET", endpoint, timeout, params={"limit": PAGE_SIZE, "offset": offset})
        postings = data.get("content") or []
        for item in postings:
            posting_id = item.get("id")
            url = f"https://jobs.smartrecruiters.com/{company}/{posting_id}" if posting_id else ""
            jobs.append(Job(str(posting_id) if posting_id is not None else None,
                            target_value(target, "company"), item.get("name") or "Untitled role",
                            _location(item), url, "smartrecruiters", item.get("releasedDate")))
        offset += len(postings)
        total = int(data.get("totalFound", offset))
        if not postings or offset >= total:
            break
    return [job for job in jobs if job.url]
