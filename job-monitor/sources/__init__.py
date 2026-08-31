"""Shared ATS source types."""

from dataclasses import dataclass
import time
from typing import Any

import requests


@dataclass(frozen=True)
class Job:
    source_job_id: str | None
    company: str
    title: str
    location: str
    url: str
    ats: str
    posted_at: str | None = None


class SourceError(RuntimeError):
    pass


def target_value(target: Any, name: str, default=None):
    try:
        return target[name]
    except (KeyError, TypeError, IndexError):
        return getattr(target, name, default)


def _request(session: requests.Session, method: str, url: str, timeout: int, **kwargs):
    """Make a bounded request, retrying only temporary responses and network errors."""
    last_error = None
    for attempt in range(3):
        try:
            response = session.request(method, url, timeout=timeout, **kwargs)
            if response.status_code == 429:
                try:
                    retry = float(response.headers.get("Retry-After", "1"))
                except ValueError:
                    retry = 1.0
                if attempt < 2:
                    time.sleep(min(max(retry, 0.1), 10))
                    continue
            if response.status_code >= 500 and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            return response
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
        except requests.HTTPError as exc:
            raise SourceError(str(exc)) from exc
    raise SourceError(str(last_error or "request failed"))


def request_json(session: requests.Session, method: str, url: str, timeout: int, **kwargs):
    try:
        return _request(session, method, url, timeout, **kwargs).json()
    except ValueError as exc:
        raise SourceError(str(exc)) from exc


def request_text(session: requests.Session, method: str, url: str, timeout: int, **kwargs) -> str:
    return _request(session, method, url, timeout, **kwargs).text
