import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ats_parser import parse_ats
from database import Database
from github_parser import Listing, extract_apply_url, parse_markdown_tables


class MarkdownTests(unittest.TestCase):
    def test_table_badge_inheritance_and_closed(self):
        markdown = """
| Company | Role | Location | Apply | Date Posted |
|---|---|---|---|---|
| Kepler Communications | Embedded Intern | Toronto | [![Apply](https://img.shields.io/badge/apply-blue)](https://jobs.lever.co/kepler/abc) | Aug 19 |
| ↳ | FPGA Intern | Toronto | [Apply](https://jobs.lever.co/kepler/def) | Aug 20 |
| Autodesk | Developer | Montreal | Closed🔒 | Aug 21 |
"""
        rows, skipped = parse_markdown_tables(markdown)
        self.assertEqual(3, len(rows))
        self.assertEqual("Kepler Communications", rows[1].company)
        self.assertEqual("https://jobs.lever.co/kepler/abc", rows[0].apply_url)
        self.assertIsNone(rows[2].apply_url)
        self.assertEqual(0, skipped)

    def test_orphan_inheritance_is_skipped(self):
        markdown = "| Company | Role | Location | Apply |\n|---|---|---|---|\n| ↳ | Role | Here | Closed🔒 |"
        rows, skipped = parse_markdown_tables(markdown)
        self.assertEqual([], rows)
        self.assertEqual(1, skipped)


class ATSTests(unittest.TestCase):
    def test_supported_systems(self):
        cases = [
            ("https://job-boards.greenhouse.io/kensingtontours/jobs/5209507007", "greenhouse", "kensingtontours", "kensingtontours"),
            ("https://jobs.lever.co/kepler/2ad02ce3-1d56-4aee-9f1d-5199c780c0c1/", "lever", "kepler", "kepler"),
            ("https://autodesk.wd1.myworkdayjobs.com/Ext/job/x", "workday", "autodesk", "Ext"),
            ("https://capitalone.wd12.myworkdayjobs.com/Capital_One/job/x", "workday", "capitalone", "Capital_One"),
        ]
        for url, ats_name, identifier, site in cases:
            with self.subTest(url=url):
                ats = parse_ats(url)
                self.assertIsNotNone(ats)
                self.assertEqual((ats_name, identifier, site), (ats.ats, ats.ats_identifier, ats.ats_site))

    def test_unknown_and_invalid(self):
        ats = parse_ats("HTTPS://Example.com/job/123/#fragment")
        self.assertEqual("unknown", ats.ats)
        self.assertEqual("unknown|https://example.com/job/123", ats.identity_key)
        self.assertIsNone(parse_ats("not a URL"))


class DatabaseTests(unittest.TestCase):
    def test_dedup_and_export(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "test.db")
            listing = Listing("RBC", "Intern", "Toronto", "https://jobs.lever.co/acme/one", "Aug 1")
            ats = parse_ats(listing.apply_url)
            first_id, created = db.record_listing(listing, ats, "owner/repo", "README.md", "a", "2026-01-01T00:00:00Z")
            better = Listing("Royal Bank of Canada", "Intern 2", "Toronto", "https://jobs.lever.co/acme/two", "Aug 2")
            second_id, created_again = db.record_listing(better, parse_ats(better.apply_url), "owner/repo", "README.md", "b", "2026-01-02T00:00:00Z")
            db.finish_sync("owner/repo", "b")
            self.assertEqual(first_id, second_id)
            self.assertTrue(created)
            self.assertFalse(created_again)
            self.assertEqual(1, db.total_companies())
            path = root / "companies.json"
            db.export_json(path)
            data = json.loads(path.read_text())
            self.assertEqual("Royal Bank of Canada", data[0]["company"])
            db.close()


if __name__ == "__main__":
    unittest.main()

