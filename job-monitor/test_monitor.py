import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from database import Database, job_key, target_key
from discord import DiscordClient
from filters import canada_first, is_canadian_location, is_relevant_job
from sources import Job
from sources import ashby, greenhouse, lever, rippling, smartrecruiters, workable, workday


class FakeResponse:
    def __init__(self, data=None, status=200, headers=None, text=""):
        self._data = data
        self.status_code = status
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)


class FilterTests(unittest.TestCase):
    def test_relevant_titles(self):
        self.assertTrue(is_relevant_job("Backend Software Developer Co-op"))
        self.assertTrue(is_relevant_job("Machine Learning Student"))
        self.assertFalse(is_relevant_job("Mechanical Engineering Intern"))
        self.assertFalse(is_relevant_job("Senior Software Developer"))
        self.assertFalse(is_relevant_job("International Software Developer"))

    def test_canada_detection_and_preference(self):
        self.assertTrue(is_canadian_location("Remote - Canada"))
        self.assertTrue(is_canadian_location("Toronto, ON"))
        self.assertFalse(is_canadian_location("Remote - United States"))
        jobs = [Job("1", "A", "Software Intern", "New York", "u1", "lever"),
                Job("2", "B", "Software Intern", "Calgary, AB", "u2", "lever")]
        self.assertEqual("B", canada_first(jobs)[0].company)

    def test_strict_canada_filter_drops_blank_and_foreign(self):
        for location in ("", "Remote", "New York, NY", "Remote - United States"):
            self.assertFalse(is_canadian_location(location), location)
        for location in ("Remote - Canada", "Toronto, ON / New York, NY", "Vaughan, Ontario", "London, ON"):
            self.assertTrue(is_canadian_location(location), location)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = Database(self.root / "jobs.db")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def _catalog(self):
        data = [{"company": "WinterCo", "recruiting_history": ["Winter 2027"], "ats_boards": [
                    {"ats": "lever", "ats_provider_known": True, "ats_identifier": "Acme", "ats_host": "jobs.lever.co", "ats_site": "Acme"},
                    {"ats": "lever", "ats_provider_known": True, "ats_identifier": "Acme", "ats_host": "jobs.lever.co", "ats_site": "Acme"},
                    {"ats": "icims", "ats_provider_known": True, "ats_identifier": "x", "ats_host": "careers.icims.com", "ats_site": "x"},
                ]}]
        path = self.root / "companies.json"
        path.write_text(json.dumps(data))
        return path

    def test_import_deduplicates_and_preserves_runtime(self):
        counts = self.db.import_targets(self._catalog(), 5, 30)
        self.assertEqual({"high": 1, "normal": 0, "unsupported": 1}, counts)
        self.assertEqual(1, self.db.table_count("monitor_targets"))
        row = self.db.all_targets()[0]
        self.assertEqual("high", row["priority"])
        self.assertEqual(5, row["poll_interval_minutes"])
        self.db.connection.execute("UPDATE monitor_targets SET failure_count=3,initialized=1")
        self.db.connection.commit()
        self.db.import_targets(self._catalog(), 7, 30)
        row = self.db.all_targets()[0]
        self.assertEqual(3, row["failure_count"])
        self.assertEqual(1, row["initialized"])
        self.assertEqual(7, row["poll_interval_minutes"])

    def test_per_target_baseline_then_queue_and_deduplicate(self):
        self.db.import_targets(self._catalog(), 5, 30)
        target = self.db.all_targets()[0]
        first = Job("one", "WinterCo", "Software Intern", "Toronto", "https://one", "lever")
        self.assertEqual((1, 0), self.db.record_success(target, [first], False))
        target = self.db.all_targets()[0]
        second = Job("two", "WinterCo", "Developer Co-op", "Boston", "https://two", "lever")
        self.assertEqual((1, 1), self.db.record_success(target, [first, second], False))
        self.assertEqual(2, self.db.table_count("seen_jobs"))
        self.assertEqual(1, self.db.table_count("notifications"))
        self.assertEqual((0, 0), self.db.record_success(self.db.all_targets()[0], [second], False))

    def test_first_scan_override_and_failure_backoff(self):
        self.db.import_targets(self._catalog(), 5, 30)
        target = self.db.all_targets()[0]
        job = Job(None, "WinterCo", "Software Intern", "Toronto", "https://one", "lever")
        self.assertEqual((1, 1), self.db.record_success(target, [job], True))
        self.assertEqual(job_key(job), self.db.pending_notifications()[0]["job_key"])
        target = self.db.all_targets()[0]
        self.db.record_failure(target, "x")
        target = self.db.all_targets()[0]
        self.db.record_failure(target, "x")
        target = self.db.all_targets()[0]
        self.assertEqual(2, target["failure_count"])


class AdapterTests(unittest.TestCase):
    def test_greenhouse(self):
        session = FakeSession([FakeResponse({"jobs": [{"id": 1, "title": "Software Intern", "location": {"name": "Toronto"}, "absolute_url": "https://apply"}]})])
        jobs = greenhouse.fetch_jobs({"company": "A", "ats_identifier": "a"}, 2, session)
        self.assertEqual(("1", "Toronto"), (jobs[0].source_job_id, jobs[0].location))

    def test_lever(self):
        session = FakeSession([FakeResponse([{"id": "x", "text": "Developer Co-op", "categories": {"allLocations": ["Ottawa", "Remote"]}, "hostedUrl": "https://apply"}])])
        jobs = lever.fetch_jobs({"company": "A", "ats_site": "a"}, 2, session)
        self.assertEqual("Ottawa, Remote", jobs[0].location)

    def test_workday_paginates(self):
        session = FakeSession([
            FakeResponse({"total": 2, "jobPostings": [{"title": "Software Intern", "externalPath": "/job/one", "locationsText": "Toronto", "bulletFields": ["JR1"]}]}),
            FakeResponse({"total": 2, "jobPostings": [{"title": "Developer Co-op", "externalPath": "/job/two", "locationsText": "Boston", "bulletFields": ["JR2"]}]}),
        ])
        target = {"company": "A", "ats_host": "acme.wd3.myworkdayjobs.com", "ats_identifier": "ignored", "ats_site": "Careers"}
        jobs = workday.fetch_jobs(target, 2, session)
        self.assertEqual(2, len(jobs))
        self.assertIn("/wday/cxs/acme/Careers/jobs", session.calls[0][1])
        self.assertEqual(1, session.calls[1][2]["json"]["offset"])

    def test_ashby_skips_unlisted_and_joins_locations(self):
        session = FakeSession([FakeResponse({"jobs": [
            {"id": "j1", "title": "Software Intern", "location": "Toronto",
             "secondaryLocations": [{"location": "Vancouver"}], "jobUrl": "https://apply", "isListed": True,
             "publishedAt": "2026-08-01"},
            {"id": "j2", "title": "Hidden Intern", "location": "Toronto", "jobUrl": "https://hidden", "isListed": False},
        ]})])
        jobs = ashby.fetch_jobs({"company": "A", "ats_site": "a"}, 2, session)
        self.assertEqual(1, len(jobs))
        self.assertEqual(("j1", "Toronto, Vancouver"), (jobs[0].source_job_id, jobs[0].location))

    def test_smartrecruiters_paginates_and_maps_country(self):
        session = FakeSession([
            FakeResponse({"totalFound": 2, "content": [
                {"id": "100", "name": "Software Intern",
                 "location": {"city": "Toronto", "region": "Ontario", "country": "ca"}}]}),
            FakeResponse({"totalFound": 2, "content": [
                {"id": "200", "name": "Developer Co-op",
                 "location": {"city": "Boston", "country": "us", "remote": True}}]}),
        ])
        jobs = smartrecruiters.fetch_jobs({"company": "A", "ats_identifier": "Acme"}, 2, session)
        self.assertEqual(2, len(jobs))
        self.assertEqual("Toronto, Ontario, Canada", jobs[0].location)
        self.assertEqual("https://jobs.smartrecruiters.com/Acme/100", jobs[0].url)
        self.assertEqual("Remote, Boston, US", jobs[1].location)
        self.assertEqual(0, session.calls[0][2]["params"]["offset"])
        self.assertEqual(1, session.calls[1][2]["params"]["offset"])

    def test_workable(self):
        session = FakeSession([FakeResponse({"jobs": [
            {"shortcode": "AB12", "title": "Software Intern", "city": "Waterloo", "state": "Ontario",
             "country": "Canada", "url": "https://apply", "published_on": "2026-08-01"}]})])
        jobs = workable.fetch_jobs({"company": "A", "ats_site": "acme"}, 2, session)
        self.assertEqual(("AB12", "Waterloo, Ontario, Canada"), (jobs[0].source_job_id, jobs[0].location))

    def test_rippling(self):
        session = FakeSession([FakeResponse([
            {"uuid": "r1", "name": "Software Intern", "workLocation": {"label": "Toronto, ON"}, "url": "https://apply"},
            {"id": "r2", "name": "Developer Co-op", "locations": [{"label": "Montreal"}, {"label": "Remote"}],
             "url": "https://apply2"},
        ])])
        jobs = rippling.fetch_jobs({"company": "A", "ats_identifier": "acme"}, 2, session)
        self.assertEqual(("r1", "Toronto, ON"), (jobs[0].source_job_id, jobs[0].location))
        self.assertEqual("Montreal, Remote", jobs[1].location)


class TargetKeyTests(unittest.TestCase):
    def test_new_ats_supported(self):
        for ats in ("ashby", "smartrecruiters", "workable", "rippling"):
            board = {"ats": ats, "ats_identifier": "Acme", "ats_host": "example.com", "ats_site": ""}
            self.assertEqual(f"{ats}:acme", target_key(board))

    def test_unsupported_ats_rejected(self):
        board = {"ats": "icims", "ats_identifier": "Acme", "ats_host": "careers.icims.com", "ats_site": "Acme"}
        self.assertIsNone(target_key(board))


class DiscordTests(unittest.TestCase):
    def test_success_and_rate_limit(self):
        success = DiscordClient("https://example", 2, FakeSession([FakeResponse(status=204)]))
        self.assertTrue(success.send_test().success)
        limited = DiscordClient("https://example", 2, FakeSession([FakeResponse({"retry_after": 2.2}, 429)]))
        result = limited.send_test()
        self.assertFalse(result.success)
        self.assertEqual(3, result.retry_after_seconds)


if __name__ == "__main__":
    unittest.main()
