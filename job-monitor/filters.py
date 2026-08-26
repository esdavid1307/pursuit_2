"""Easy-to-edit job relevance and Canadian-location filters."""

import re

INTERNSHIP_KEYWORDS = ("intern", "internship", "co-op", "coop", "co op", "student")
TECH_KEYWORDS = (
    "software", "developer", "development", "swe", "backend", "back-end",
    "frontend", "front-end", "full stack", "full-stack", "web developer",
    "application developer", "mobile developer", "cloud", "devops", "platform",
    "site reliability", "sre", "computer science", "data engineer",
    "machine learning", "ml", "ai",
)
GENERIC_ENGINEERING = ("mechanical", "civil", "chemical", "manufacturing")
CANADIAN_NAMES = (
    "canada", "alberta", "british columbia", "ontario", "quebec", "saskatchewan",
    "manitoba", "nova scotia", "new brunswick", "newfoundland", "labrador",
    "prince edward island", "yukon", "northwest territories", "nunavut", "toronto",
    "vancouver", "montreal", "montréal", "calgary", "edmonton", "ottawa", "waterloo",
    "kitchener", "mississauga", "markham", "burnaby", "victoria", "halifax",
    "winnipeg", "saskatoon", "regina", "quebec city", "gatineau", "surrey", "richmond",
)
PROVINCE_CODES = ("AB", "BC", "ON", "QC", "SK", "MB", "NS", "NB", "NL", "PE", "YT", "NT", "NU")


def _contains(text: str, keyword: str) -> bool:
    if keyword == "intern":
        return re.search(r"\bintern(?:ship)?s?\b", text, re.IGNORECASE) is not None
    if len(keyword) <= 3 and keyword.isalpha():
        return re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE) is not None
    return keyword.casefold() in text.casefold()


def is_relevant_job(title: str) -> bool:
    title = title or ""
    if not any(_contains(title, word) for word in INTERNSHIP_KEYWORDS):
        return False
    if not any(_contains(title, word) for word in TECH_KEYWORDS):
        return False
    if any(_contains(title, word) for word in GENERIC_ENGINEERING) and "software" not in title.casefold():
        return False
    return True


def is_canadian_location(location: str) -> bool:
    location = location or ""
    folded = location.casefold()
    if any(name in folded for name in CANADIAN_NAMES):
        return True
    return any(re.search(rf"(?:^|[\s,/(-]){code}(?:$|[\s,/)-])", location, re.IGNORECASE) for code in PROVINCE_CODES)


def canada_first(jobs):
    return sorted(jobs, key=lambda job: not is_canadian_location(job.location))
