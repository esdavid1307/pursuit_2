"""Local Git history access and tolerant Markdown internship-table parsing."""

from dataclasses import dataclass
from html import unescape
from pathlib import Path
import os
import re
import subprocess


@dataclass(frozen=True)
class Listing:
    company: str
    role: str
    location: str
    apply_url: str | None
    date_posted: str


@dataclass(frozen=True)
class HistoricalDocument:
    commit_sha: str
    committed_at: str
    path: str
    content: str


def load_dotenv(path: Path) -> None:
    """Load a minimal KEY=VALUE .env without overriding the real environment."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _clean_cell(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"!?(?:\[([^]]*)\])\([^)]*\)", r"\1", value)
    value = unescape(value).replace("**", "").replace("__", "")
    return re.sub(r"\s+", " ", value).strip()


def _split_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [part.replace(r"\|", "|").strip() for part in re.split(r"(?<!\\)\|", text)]


def _header_key(cell: str) -> str:
    return re.sub(r"[^a-z]", "", _clean_cell(cell).lower())


def extract_apply_url(cell: str) -> str | None:
    if "closed" in _clean_cell(cell).lower():
        return None
    markdown_urls = re.findall(r"\]\(\s*(https?://[^\s)]+)", cell, flags=re.IGNORECASE)
    html_urls = re.findall(r"href\s*=\s*[\"'](https?://[^\"']+)", cell, flags=re.IGNORECASE)
    plain_urls = re.findall(r"https?://[^\s<>\])\"']+", cell, flags=re.IGNORECASE)
    candidates = markdown_urls + html_urls + plain_urls
    for url in reversed(candidates):
        cleaned = unescape(url).strip()
        if "shields.io" not in cleaned.lower():
            return cleaned
    return None


def parse_markdown_tables(content: str) -> tuple[list[Listing], int]:
    listings: list[Listing] = []
    skipped = 0
    header: dict[str, int] | None = None
    current_company: str | None = None

    for line in content.splitlines():
        if "|" not in line:
            header = None
            current_company = None
            continue
        cells = _split_row(line)
        keys = [_header_key(cell) for cell in cells]
        if "company" in keys and "role" in keys and "location" in keys and "apply" in keys:
            header = {key: index for index, key in enumerate(keys) if key}
            current_company = None
            continue
        if header is None:
            continue
        if all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells):
            continue
        needed = max(header.get(name, -1) for name in ("company", "role", "location", "apply"))
        if needed < 0 or len(cells) <= needed:
            skipped += 1
            continue
        raw_company = _clean_cell(cells[header["company"]])
        if raw_company == "↳":
            if not current_company:
                skipped += 1
                continue
            company = current_company
        else:
            company = raw_company
            if company:
                current_company = company
        if not company:
            skipped += 1
            continue
        date_index = header.get("dateposted", header.get("date"))
        date_posted = _clean_cell(cells[date_index]) if date_index is not None and date_index < len(cells) else ""
        listings.append(
            Listing(
                company=company,
                role=_clean_cell(cells[header["role"]]),
                location=_clean_cell(cells[header["location"]]),
                apply_url=extract_apply_url(cells[header["apply"]]),
                date_posted=date_posted,
            )
        )
    return listings, skipped


class GitRepository:
    def __init__(self, slug: str, files: list[str], cache_root: Path, token: str | None, timeout: int = 180):
        self.slug = slug
        self.files = files
        self.mirror = cache_root / f"{slug.replace('/', '__')}.git"
        self.remote_url = f"https://github.com/{slug}.git"
        self.token = token
        self.timeout = timeout

    def _command(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        command = ["git"]
        if self.token:
            # Configure the header through the environment so a timeout or exception
            # cannot expose the token by rendering the command-line arguments.
            env["GIT_CONFIG_COUNT"] = "1"
            env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
            env["GIT_CONFIG_VALUE_0"] = f"Authorization: Bearer {self.token}"
        command.extend(args)
        return subprocess.run(
            command, cwd=cwd, env=env, text=True, capture_output=True,
            timeout=self.timeout, check=check,
        )

    def prepare(self) -> str:
        self.mirror.parent.mkdir(parents=True, exist_ok=True)
        if self.mirror.exists():
            self._command("fetch", "--prune", "origin", cwd=self.mirror)
        else:
            self._command("clone", "--mirror", self.remote_url, str(self.mirror))
        return self._command("rev-parse", "HEAD", cwd=self.mirror).stdout.strip()

    def is_ancestor(self, older: str, newer: str) -> bool:
        result = self._command("merge-base", "--is-ancestor", older, newer, cwd=self.mirror, check=False)
        return result.returncode == 0

    def commits(self, head: str, after: str | None = None) -> list[str]:
        revision = f"{after}..{head}" if after else head
        result = self._command("rev-list", "--reverse", revision, "--", *self.files, cwd=self.mirror)
        return [line for line in result.stdout.splitlines() if line]

    def documents_at(self, sha: str) -> list[HistoricalDocument]:
        changed = self._command(
            "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "-m", sha,
            cwd=self.mirror,
        ).stdout.splitlines()
        selected = [path for path in self.files if path in set(changed)]
        committed_at = self._command("show", "-s", "--format=%cI", sha, cwd=self.mirror).stdout.strip()
        documents: list[HistoricalDocument] = []
        for path in selected:
            shown = self._command("show", f"{sha}:{path}", cwd=self.mirror, check=False)
            if shown.returncode == 0:
                documents.append(HistoricalDocument(sha, committed_at, path, shown.stdout))
        return documents
