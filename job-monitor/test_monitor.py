import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from database import Database, job_key
from discord import DiscordClient
from filters import canada_first, is_canadian_location, is_relevant_job
from sources import Job
from sources import greenhouse, lever, workday


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
                    {"ats": "ashby", "ats_provider_known": True, "ats_identifier": "x", "ats_host": "jobs.ashbyhq.com", "ats_site": "x"},
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
