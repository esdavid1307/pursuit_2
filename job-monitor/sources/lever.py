"""Lever public postings API adapter."""

import requests

from sources import Job, SourceError, request_json, target_value


def fetch_jobs(target, timeout: int, session: requests.Session | None = None) -> list[Job]:
    session = session or requests.Session()
    site = target_value(target, "ats_site") or target_value(target, "ats_identifier")
    if not site:
        raise SourceError("missing Lever site")
    data = request_json(session, "GET", f"https://api.lever.co/v0/postings/{site}", timeout, params={"mode": "json"})
    jobs = []
    for item in data:
        categories = item.get("categories") or {}
        locations = categories.get("allLocations") or []
        location = ", ".join(locations) if locations else categories.get("location", "")
        jobs.append(Job(item.get("id"), target_value(target, "company"), item.get("text") or "Untitled role",
                        location, item.get("hostedUrl") or item.get("applyUrl") or "", "lever", None))
    return [job for job in jobs if job.url]
