import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from catalog.ats_parser import parse_ats
from catalog.database import Database
from catalog.github_parser import Listing, extract_apply_url, parse_markdown_tables


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

    def test_simplify_html_table_uses_employer_link_and_inheritance(self):
        html = """
<table><thead><tr><th>Company</th><th>Role</th><th>Location</th><th>Terms</th><th>Application</th><th>Age</th></tr></thead><tbody>
<tr><td><strong><a href="https://simplify.jobs/c/Sage">🔥 Sage</a></strong></td><td>Software Intern</td><td>NYC<br>Boston</td><td>Winter 2026</td><td><a href="https://job-boards.greenhouse.io/sage/jobs/123"><img src="apply.png"></a> <a href="https://simplify.jobs/p/secondary">Simplify</a></td><td>2d</td></tr>
<tr><td>↳</td><td>Backend Intern</td><td>NYC</td><td>Winter 2026</td><td><a href="https://job-boards.greenhouse.io/sage/jobs/456">Apply</a></td><td>1d</td></tr>
</tbody></table>
"""
        rows, skipped = parse_markdown_tables(html)
        self.assertEqual(2, len(rows))
        self.assertEqual("Sage", rows[0].company)
        self.assertEqual("Sage", rows[1].company)
        self.assertEqual("NYC Boston", rows[0].location)
        self.assertEqual("https://job-boards.greenhouse.io/sage/jobs/123", rows[0].apply_url)
        self.assertEqual("2d", rows[0].date_posted)
        self.assertEqual("Winter 2026", rows[0].terms)
        self.assertEqual(0, skipped)


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

    def test_additional_monitorable_systems(self):
        cases = [
            ("https://jobs.ashbyhq.com/sentry/job-id", "ashby", "sentry"),
            ("https://jobs.smartrecruiters.com/ATPCO1/123", "smartrecruiters", "ATPCO1"),
            ("https://apply.workable.com/botpress/j/ABC", "workable", "botpress"),
            ("https://ats.rippling.com/en-CA/journaltech/jobs/123", "rippling", "journaltech"),
            ("https://jobs.jobvite.com/windriver/job/123", "jobvite", "windriver"),
            ("https://careers-kinaxis.icims.com/jobs/123/job", "icims", "careers-kinaxis"),
            ("https://qualcomm.eightfold.ai/careers/job/123", "eightfold", "qualcomm"),
            ("https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/123", "oracle", "eeho"),
            ("https://wd3.myworkdaysite.com/recruiting/magna/Magna/job/123", "workday", "magna"),
        ]
        for url, provider, identifier in cases:
            with self.subTest(url=url):
                ats = parse_ats(url, "Company")
                self.assertEqual((provider, identifier), (ats.ats, ats.ats_identifier))

    def test_unknown_and_invalid(self):
        ats = parse_ats("HTTPS://Example.com/job/123/#fragment", "Example Inc.")
        self.assertEqual("unknown", ats.ats)
        self.assertEqual("unknown|exampleinc|example.com", ats.identity_key)
        self.assertIsNone(parse_ats("not a URL"))

    def test_unknown_jobs_share_company_host_identity(self):
        first = parse_ats("https://jobs.example.com/job/123", "Acme Corp")
        second = parse_ats("https://jobs.example.com/job/456", "ACME Corp.")
        other_company = parse_ats("https://jobs.example.com/job/123", "Other Corp")
        self.assertEqual(first.identity_key, second.identity_key)
        self.assertNotEqual(first.identity_key, other_company.identity_key)


class DatabaseTests(unittest.TestCase):
    def test_dedup_and_export(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "test.db")
            listing = Listing("RBC", "Intern", "Toronto", "https://jobs.lever.co/acme/one", "Aug 1")
            ats = parse_ats(listing.apply_url, listing.company)
            first_id, first_board, created, board_created = db.record_listing(listing, ats, "owner/repo", "README.md", "a", "2026-01-01T00:00:00Z")
            better = Listing("Royal Bank of Canada", "Intern 2", "Toronto", "https://jobs.lever.co/acme/two", "Aug 2", "Winter 2026")
            second_id, second_board, created_again, board_created_again = db.record_listing(better, parse_ats(better.apply_url, better.company), "owner/repo", "README.md", "b", "2026-01-02T00:00:00Z")
            db.record_recruiting_history(second_id, second_board, "Winter 2026", "owner/repo", "b", "2026-01-02T00:00:00Z")
            db.finish_sync("owner/repo", "b")
            self.assertEqual(first_id, second_id)
            self.assertEqual(first_board, second_board)
            self.assertTrue(created)
            self.assertTrue(board_created)
            self.assertFalse(created_again)
            self.assertFalse(board_created_again)
            self.assertEqual(1, db.total_companies())
            path = root / "companies.json"
            db.export_json(path)
            data = json.loads(path.read_text())
            self.assertEqual("Royal Bank of Canada", data[0]["company"])
            self.assertEqual("lever", data[0]["ats_boards"][0]["ats"])
            self.assertTrue(data[0]["ats_boards"][0]["ats_provider_known"])
            self.assertEqual(["Winter 2026"], data[0]["recruiting_history"])
            terms = db.connection.execute("SELECT terms FROM job_observations WHERE commit_sha='b'").fetchone()[0]
            self.assertEqual("Winter 2026", terms)
            db.close()

    def test_shared_board_merges_company_aliases(self):
        with TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.db")
            unknown = Listing("RBC", "Role", "Toronto", "https://jobs.rbc.com/one", "Aug 1")
            known = Listing("Royal Bank of Canada", "Role", "Toronto", "https://rbc.wd3.myworkdayjobs.com/en-US/job/one", "Aug 2")
            alias = Listing("RBC", "Role", "Toronto", "https://rbc.wd3.myworkdayjobs.com/en-US/job/two", "Aug 3")
            for index, listing in enumerate((unknown, known, alias)):
                db.record_listing(listing, parse_ats(listing.apply_url, listing.company), "owner/repo", "README.md", str(index), f"2026-01-0{index + 1}T00:00:00Z")
            self.assertEqual(1, db.total_companies())
            self.assertEqual(2, db.total_boards())
            aliases = db.connection.execute("SELECT count(*) FROM company_aliases").fetchone()[0]
            self.assertEqual(2, aliases)
            db.close()


if __name__ == "__main__":
    unittest.main()
