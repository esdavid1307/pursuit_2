"""iCIMS hosted career portal adapter (parses the server-rendered search HTML)."""

import html as html_lib
import re

import requests

from monitor.sources import Job, SourceError, request_text, target_value


MAX_PAGES = 20
# iCIMS serves an empty shell to unknown clients; a browser UA gets the full table.
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

CARD_PATTERN = re.compile(r'<li class="iCIMS_JobCardItem">(.*?)</li>', re.S)
LINK_PATTERN = re.compile(r'href="([^"]*?/jobs/(\d+)/[^"]*?/job[^"]*)"')
TITLE_PATTERN = re.compile(r"<h3\s*>\s*(.*?)\s*</h3>", re.S)
LOCATION_PATTERN = re.compile(r'field-label">[^<]*Location[^<]*</span>\s*<span\s*>\s*([^<]+?)\s*</span>', re.S)
POSTED_PATTERN = re.compile(r'Posted Date</span>\s*<span title="([^"]+)"')


def fetch_jobs(target, timeout: int, session: requests.Session | None = None) -> list[Job]:
    session = session or requests.Session()
    host = target_value(target, "ats_host")
    if not host:
        identifier = target_value(target, "ats_identifier") or target_value(target, "ats_site")
        if not identifier:
            raise SourceError("missing iCIMS portal host")
        host = f"{identifier}.icims.com"
    jobs: list[Job] = []
    seen_ids: set[str] = set()
    for page in range(MAX_PAGES):
        url = f"https://{host}/jobs/search?ss=1&in_iframe=1&pr={page}"
        text = request_text(session, "GET", url, timeout, headers=HEADERS)
        before = len(seen_ids)
        for card in CARD_PATTERN.findall(text):
            link = LINK_PATTERN.search(card)
            title = TITLE_PATTERN.search(card)
            if not link or not title:
                continue
            job_id = link.group(2)
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            location = LOCATION_PATTERN.search(card)
            posted = POSTED_PATTERN.search(card)
            jobs.append(Job(job_id, target_value(target, "company"),
                            html_lib.unescape(title.group(1)).strip() or "Untitled role",
                            html_lib.unescape(location.group(1)).strip() if location else "",
                            link.group(1).split("?")[0], "icims",
                            posted.group(1) if posted else None))
        # Requesting past the last page repeats it, so stop when nothing new appears.
        if len(seen_ids) == before:
            break
    return jobs
