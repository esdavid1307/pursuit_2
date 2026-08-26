"""Rippling public ATS board API adapter."""

import requests

from sources import Job, SourceError, request_json, target_value


def _location(item) -> str:
    work_location = item.get("workLocation") or {}
    if work_location.get("label"):
        return work_location["label"]
    labels = [(entry or {}).get("label") or "" for entry in item.get("locations") or []]
    return ", ".join(part for part in labels if part)


def fetch_jobs(target, timeout: int, session: requests.Session | None = None) -> list[Job]:
    session = session or requests.Session()
    board = target_value(target, "ats_site") or target_value(target, "ats_identifier")
    if not board:
        raise SourceError("missing Rippling board name")
    data = request_json(session, "GET", f"https://api.rippling.com/platform/api/ats/v1/board/{board}/jobs", timeout)
    items = data if isinstance(data, list) else data.get("items") or []
    jobs = []
    for item in items:
        source_id = item.get("uuid") or item.get("id")
        jobs.append(Job(str(source_id) if source_id is not None else None,
                        target_value(target, "company"), item.get("name") or "Untitled role",
                        _location(item), item.get("url") or "", "rippling", None))
    return [job for job in jobs if job.url]
