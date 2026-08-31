"""Configuration for repositories and local runtime paths."""

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = DATA_DIR / "companies.db"
EXPORT_PATH = DATA_DIR / "companies.json"
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
        "historical_windows": [
            {
                "name": "winter-2026-july-2025-february-2026",
                "file": "README-Off-Season.md",
                "start": "2025-07-01T00:00:00Z",
                "end": "2026-02-28T23:59:59Z",
                "term": "Winter 2026",
            }
        ],
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
