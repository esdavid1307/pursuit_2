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
    },
    {
        "repo": "SimplifyJobs/Summer2027-Internships",
        "branch": "dev",
        # This bot-generated repository has tens of thousands of commits and
        # maintains closed listings in dedicated current files.
        "history_mode": "snapshot",
        "files": [
            "README.md",
            "README-Inactive.md",
            "README-Off-Season.md",
            "archived/README-2026.md",
        ],
    },
]

# Large history-only repositories can have mirrors hundreds of megabytes in size.
GIT_TIMEOUT_SECONDS = 900
