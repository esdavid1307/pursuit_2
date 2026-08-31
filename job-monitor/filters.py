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
    "brampton", "vaughan", "oakville", "scarborough", "north york", "etobicoke",
    "laval", "longueuil", "london, ontario",
)
PROVINCE_CODES = ("AB", "BC", "ON", "QC", "SK", "MB", "NS", "NB", "NL", "PE", "YT", "NT", "NU")
US_NAMES = (
    "united states", "usa", "u.s.", "alabama", "alaska", "arizona", "arkansas",
    "california", "colorado", "connecticut", "delaware", "florida", "georgia",
    "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire",
    "new jersey", "new mexico", "new york", "north carolina", "north dakota",
    "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "wisconsin", "wyoming", "district of columbia", "washington dc",
    "san francisco", "seattle", "boston", "chicago", "atlanta", "austin",
    "los angeles", "san jose", "san diego", "denver", "dallas", "houston",
)
# Kept case-sensitive: lowercase words like "in", "or", "me" appear in prose locations.
US_STATE_CODES = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "MA", "MD", "ME", "MI", "MN", "MO",
    "MS", "MT", "NC", "ND", "NE", "NH", "NJ", "NM", "NV", "NY", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WI",
    "WV", "WY", "DC",
)


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


def is_us_location(location: str) -> bool:
    """Check Canada first when classifying: "CA" and several city names are ambiguous."""
    location = location or ""
    folded = location.casefold()
    if any(name in folded for name in US_NAMES):
        return True
    return any(re.search(rf"(?:^|[\s,/(-]){code}(?:$|[\s,/)-])", location) for code in US_STATE_CODES)


def canada_first(jobs):
    return sorted(jobs, key=lambda job: not is_canadian_location(job.location))
