"""The BFF's read of a scheduled job's saved output.

The gateway has no per-run route, so this module reads the profile's own
`cron/output/<job_id>/` directory (`cron/jobs.py` `save_job_output`). The tests pin the four
things that make that safe rather than a file browser: the engine's id shapes, containment
(including a planted symlink), the read cap, and the empty answers — a profile with no job, a
job with no runs, a run the engine has pruned.

Run from the repo root:

    PYTHONPATH=core/src:app/server python -m unittest discover -s app/server/tests -t app/server/tests
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "core" / "src"))
sys.path.insert(0, str(REPO_ROOT / "app" / "server"))

from pantler_core import PackRegistry, Store  # noqa: E402

import job_runs  # noqa: E402
import pantler_server  # noqa: E402
from engine_settings import EngineProfile  # noqa: E402
from pantler_server import ApiError, Bff  # noqa: E402

JOB_ID = "0123456789ab"
OTHER_JOB = "fedcba987654"
OLD_RUN = "2026-10-20_06-30-00"
NEW_RUN = "2026-10-27_07-00-00"


class JobRunsModuleTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.profile = Path(self._dir.name)
        self.output = self.profile / "cron" / "output" / JOB_ID
        self.output.mkdir(parents=True)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def write_run(self, stem: str, text: str, at: float) -> Path:
        path = self.output / f"{stem}.md"
        path.write_text(text, encoding="utf-8")
        os.utime(path, (at, at))
        return path

    def test_lists_runs_newest_first_with_a_preview(self) -> None:
        self.write_run(
            OLD_RUN,
            "# Monday\n\nTwo invoices are outstanding, and the beans are ready.\n",
            1_700_000_000,
        )
        self.write_run(NEW_RUN, "One line\nsecond line\n", 1_700_003_600)

        runs = job_runs.list_runs(self.profile, JOB_ID)

        self.assertEqual([run["id"] for run in runs], [NEW_RUN, OLD_RUN])
        self.assertTrue(runs[0]["at"].startswith("2023-11-1"))
        self.assertEqual(runs[0]["preview"], "One line second line")
        self.assertGreater(runs[1]["size"], 0)

    def test_a_job_that_never_ran_has_no_runs(self) -> None:
        self.assertEqual(job_runs.list_runs(self.profile, OTHER_JOB), [])

    def test_ignores_files_the_engine_did_not_write(self) -> None:
        (self.output / "readme.md").write_text("not a run", encoding="utf-8")
        (self.output / f"{NEW_RUN}.txt").write_text("not markdown", encoding="utf-8")
        (self.output / "a-directory.md").mkdir()
        self.write_run(NEW_RUN, "the run", 1_700_000_000)

        self.assertEqual([run["id"] for run in job_runs.list_runs(self.profile, JOB_ID)], [NEW_RUN])

    def test_reads_one_run_and_marks_a_long_one_truncated(self) -> None:
        self.write_run(NEW_RUN, "hello", 1_700_000_000)
        run = job_runs.read_run(self.profile, JOB_ID, NEW_RUN)
        self.assertEqual(run["content"], "hello")
        self.assertFalse(run["truncated"])

        self.write_run(OLD_RUN, "x" * (job_runs.MAX_RUN_BYTES + 10), 1_700_000_000)
        big = job_runs.read_run(self.profile, JOB_ID, OLD_RUN)
        self.assertTrue(big["truncated"])
        self.assertEqual(len(big["content"]), job_runs.MAX_RUN_BYTES)

    def test_a_pruned_run_is_missing_not_an_error(self) -> None:
        with self.assertRaises(FileNotFoundError):
            job_runs.read_run(self.profile, JOB_ID, NEW_RUN)

    def test_ids_are_the_engines_own_shapes(self) -> None:
        for job_id in ("../../../etc", "0123456789AB", "0123456789a", "0123456789abc", ""):
            with self.subTest(job_id=job_id):
                with self.assertRaises(ValueError):
                    job_runs.list_runs(self.profile, job_id)
        for run_id in ("../../secret", "2026-10-27 07-00-00", "2026-10-27_07:00:00", ""):
            with self.subTest(run_id=run_id):
                with self.assertRaises(ValueError):
                    job_runs.read_run(self.profile, JOB_ID, run_id)

    def test_a_planted_symlink_is_not_read(self) -> None:
        secret = self.profile / "secret.txt"
        secret.write_text("not for this dialog", encoding="utf-8")
        (self.output / f"{NEW_RUN}.md").symlink_to(secret)

        self.assertEqual(job_runs.list_runs(self.profile, JOB_ID), [])
        with self.assertRaises(ValueError):
            job_runs.read_run(self.profile, JOB_ID, NEW_RUN)


class JobRunsRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.store = Store(self.root / "records.db")
        self.registry = PackRegistry([])
        self.profile_dir = self.root / "profiles" / "pantler"
        self.profile_dir.mkdir(parents=True)
        (self.profile_dir / "config.yaml").write_text("model: {}\n", encoding="utf-8")
        (self.profile_dir / "cron" / "output" / JOB_ID).mkdir(parents=True)
        (self.profile_dir / "cron" / "output" / JOB_ID / f"{NEW_RUN}.md").write_text(
            "the briefing", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.store.close()
        self._dir.cleanup()

    def bff(self) -> Bff:
        return Bff(self.store, self.registry, profile=EngineProfile(self.profile_dir))

    def test_the_two_routes_are_wired_with_the_engine_id_shapes(self) -> None:
        list_route = next(route for route in pantler_server.ROUTES if route.handler == "list_job_runs")
        run_route = next(route for route in pantler_server.ROUTES if route.handler == "get_job_run")

        match = list_route.match("GET", f"/api/jobs/{JOB_ID}/runs")
        self.assertIsNotNone(match)
        self.assertEqual(match.group("job_id"), JOB_ID)
        self.assertIsNone(list_route.match("GET", "/api/jobs/not-a-job/runs"))

        run = run_route.match("GET", f"/api/jobs/{JOB_ID}/runs/{NEW_RUN}")
        self.assertIsNotNone(run)
        self.assertEqual(run.group("run_id"), NEW_RUN)

    def test_lists_and_reads_for_the_profiles_own_job(self) -> None:
        status, payload = self.bff().list_job_runs({"job_id": JOB_ID})
        self.assertEqual(status, 200)
        self.assertTrue(payload["available"])
        self.assertEqual([run["id"] for run in payload["runs"]], [NEW_RUN])

        status, payload = self.bff().get_job_run({"job_id": JOB_ID, "run_id": NEW_RUN})
        self.assertEqual(status, 200)
        self.assertEqual(payload["run"]["content"], "the briefing")

    def test_no_profile_is_an_available_false_answer_for_the_list(self) -> None:
        status, payload = Bff(self.store, self.registry).list_job_runs({"job_id": JOB_ID})
        self.assertEqual(status, 200)
        self.assertFalse(payload["available"])
        self.assertEqual(payload["runs"], [])
        self.assertIn("profile", payload["reason"])

    def test_a_missing_run_is_a_404(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.bff().get_job_run({"job_id": JOB_ID, "run_id": OLD_RUN})
        self.assertEqual(caught.exception.status, 404)

    def test_a_malformed_id_is_a_400(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.bff().list_job_runs({"job_id": "../../etc"})
        self.assertEqual(caught.exception.status, 400)


if __name__ == "__main__":
    unittest.main()
