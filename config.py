"""Configuration for repositories and local runtime paths."""

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "companies.db"
EXPORT_PATH = BASE_DIR / "companies.json"
REPO_CACHE_DIR = BASE_DIR / ".repo-cache"

REPOSITORIES = [
    {
        "repo": "negarprh/Canadian-Tech-Internships-2027",
        "files": ["README.md", "README-2026.md"],
    }
]

GIT_TIMEOUT_SECONDS = 180

