"""Local Git history access and tolerant Markdown internship-table parsing."""

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
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
    terms: str = ""


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
    if html_urls:
        for url in html_urls:
            cleaned = unescape(url).strip()
            host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", cleaned, flags=re.IGNORECASE).split("/", 1)[0].lower())
            if host != "simplify.jobs" and "i.imgur.com" not in host and "shields.io" not in host:
                return cleaned
    candidates = markdown_urls + plain_urls
    for url in reversed(candidates):
        cleaned = unescape(url).strip()
        if "shields.io" not in cleaned.lower():
            return cleaned
    return None


def _clean_company(value: str) -> str:
    value = _clean_cell(value)
    return re.sub(r"^(?:🔥|🛂|🇺🇸|🎓|🔒)\s*", "", value).strip()


class _HTMLTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[tuple[str, list[str]]]]] = []
        self.table: list[list[tuple[str, list[str]]]] | None = None
        self.row: list[tuple[str, list[str]]] | None = None
        self.cell_text: list[str] | None = None
        self.cell_links: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell_text, self.cell_links = [], []
        elif tag == "a" and self.cell_links is not None:
            href = dict(attrs).get("href")
            if href:
                self.cell_links.append(href)
        elif tag == "br" and self.cell_text is not None:
            self.cell_text.append(" ")

    def handle_data(self, data: str) -> None:
        if self.cell_text is not None:
            self.cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self.row is not None and self.cell_text is not None:
            self.row.append(("".join(self.cell_text), list(self.cell_links or [])))
            self.cell_text = self.cell_links = None
        elif tag == "tr" and self.table is not None and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def _parse_html_tables(content: str) -> tuple[list[Listing], int]:
    parser = _HTMLTableParser()
    parser.feed(content)
    listings: list[Listing] = []
    skipped = 0
    for table in parser.tables:
        if not table:
            continue
        header_keys = [_header_key(cell[0]) for cell in table[0]]
        aliases = {"application": "apply", "age": "dateposted"}
        header_keys = [aliases.get(key, key) for key in header_keys]
        if not {"company", "role", "location", "apply"}.issubset(header_keys):
            continue
        header = {key: index for index, key in enumerate(header_keys) if key}
        current_company: str | None = None
        for row in table[1:]:
            needed = max(header[name] for name in ("company", "role", "location", "apply"))
            if len(row) <= needed:
                skipped += 1
                continue
            raw_company = _clean_company(row[header["company"]][0])
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
            apply_cell = row[header["apply"]]
            synthetic_links = " ".join(f'href="{url}"' for url in apply_cell[1])
            date_index = header.get("dateposted")
            listings.append(Listing(
                company=company,
                role=_clean_cell(row[header["role"]][0]),
                location=_clean_cell(row[header["location"]][0]),
                apply_url=extract_apply_url(synthetic_links or apply_cell[0]),
                date_posted=_clean_cell(row[date_index][0]) if date_index is not None and date_index < len(row) else "",
                terms=_clean_cell(row[header["terms"]][0]) if "terms" in header and header["terms"] < len(row) else "",
            ))
    return listings, skipped


def parse_markdown_tables(content: str) -> tuple[list[Listing], int]:
    listings, skipped = _parse_html_tables(content)
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
        raw_company = _clean_company(cells[header["company"]])
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
    def __init__(self, slug: str, files: list[str], cache_root: Path, token: str | None, timeout: int = 180, branch: str | None = None, shallow: bool = False):
        self.slug = slug
        self.files = files
        self.mirror = cache_root / f"{slug.replace('/', '__')}.git"
        self.remote_url = f"https://github.com/{slug}.git"
        self.token = token
        self.timeout = timeout
        self.branch = branch
        self.shallow = shallow

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
            if self.branch:
                revision = f"refs/heads/{self.branch}"
                local_head = self._command("rev-parse", revision, cwd=self.mirror).stdout.strip()
                advertised = self._command("ls-remote", "--heads", "origin", revision, cwd=self.mirror).stdout.split()
                if advertised and advertised[0] == local_head:
                    return local_head
            fetch_args = ["fetch", "--prune", "--filter=blob:none"]
            if self.shallow:
                fetch_args.extend(["--depth", "1"])
            fetch_args.append("origin")
            # clone --bare configures no fetch refspec, so a plain fetch only
            # writes FETCH_HEAD; an explicit refspec is required to advance
            # refs/heads/* past the commit captured at clone time.
            if self.branch:
                fetch_args.append(f"+refs/heads/{self.branch}:refs/heads/{self.branch}")
            else:
                fetch_args.append("+refs/heads/*:refs/heads/*")
            self._command(*fetch_args, cwd=self.mirror)
        else:
            clone_args = ["clone", "--bare", "--filter=blob:none"]
            if self.shallow:
                clone_args.extend(["--depth", "1"])
            if self.branch:
                clone_args.extend(["--single-branch", "--branch", self.branch])
            clone_args.extend([self.remote_url, str(self.mirror)])
            self._command(*clone_args)
        revision = f"refs/heads/{self.branch}" if self.branch else "HEAD"
        return self._command("rev-parse", revision, cwd=self.mirror).stdout.strip()

    def ensure_full_history(self) -> None:
        shallow = self._command("rev-parse", "--is-shallow-repository", cwd=self.mirror).stdout.strip() == "true"
        if shallow:
            self._command("fetch", "--unshallow", "--filter=blob:none", "origin", cwd=self.mirror)

    def daily_commits(self, path: str, start: str, end: str) -> list[str]:
        result = self._command(
            "log", "--reverse", "--format=%H%x09%cI", f"--since={start}", f"--until={end}",
            "HEAD", "--", path, cwd=self.mirror,
        )
        by_day: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "\t" not in line:
                continue
            sha, committed_at = line.split("\t", 1)
            by_day[committed_at[:10]] = sha
        return list(by_day.values())

    def is_ancestor(self, older: str, newer: str) -> bool:
        result = self._command("merge-base", "--is-ancestor", older, newer, cwd=self.mirror, check=False)
        return result.returncode == 0

    def commits(self, head: str, after: str | None = None) -> list[str]:
        revision = f"{after}..{head}" if after else head
        result = self._command("rev-list", "--reverse", revision, "--", *self.files, cwd=self.mirror)
        return [line for line in result.stdout.splitlines() if line]

    def documents_at(self, sha: str, all_files: bool = False) -> list[HistoricalDocument]:
        if all_files:
            selected = self.files
        else:
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
