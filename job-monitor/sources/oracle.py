"""Oracle Cloud Recruiting CandidateExperience API adapter."""

import requests

from sources import Job, SourceError, request_json, target_value


PAGE_SIZE = 100
MAX_PAGES = 30


def fetch_jobs(target, timeout: int, session: requests.Session | None = None) -> list[Job]:
    session = session or requests.Session()
    host = target_value(target, "ats_host")
    site = target_value(target, "ats_site")
    if not host or not site:
        raise SourceError("missing Oracle Cloud host or site")
    jobs: list[Job] = []
    offset = 0
    for _ in range(MAX_PAGES):
        # The finder syntax uses ; and , which Oracle rejects when percent-encoded,
        # so the query string is built by hand instead of via params=.
        url = (f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
               f"?onlyData=true&expand=requisitionList.secondaryLocations"
               f"&finder=findReqs;siteNumber={site},limit={PAGE_SIZE},offset={offset}")
        data = request_json(session, "GET", url, timeout, headers={"Accept": "application/json"})
        items = data.get("items") or []
        block = items[0] if items else {}
        requisitions = block.get("requisitionList") or []
        for item in requisitions:
            req_id = item.get("Id")
            locations = [item.get("PrimaryLocation") or ""]
            locations += [(loc.get("Name") or "") for loc in item.get("secondaryLocations") or []]
            location = ", ".join(part for part in locations if part)
            url = (f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{req_id}"
                   if req_id else "")
            jobs.append(Job(str(req_id) if req_id is not None else None,
                            target_value(target, "company"), item.get("Title") or "Untitled role",
                            location, url, "oracle", item.get("PostedDate")))
        offset += len(requisitions)
        total = int(block.get("TotalJobsCount") or offset)
        if not requisitions or offset >= total:
            break
    return [job for job in jobs if job.url]
