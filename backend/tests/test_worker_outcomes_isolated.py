"""Synthetic worker regressions; run only in the approved isolated environment.

Uses selected AST definitions, never imports the app, dotenv, browser or notifier.
Copy both worker sources with their relative layout into the isolated fixture root.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock


class FakeHTTPStatusError(Exception):
    pass


class FakeTimeout(Exception):
    pass


class FakeNetworkError(Exception):
    pass


class FakeCookiesExpired(Exception):
    pass


def load_definitions(source):
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    selected = [node for node in tree.body if
                isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in
                {"PipelineClient", "run_worker_batch", "run_worker_cycle", "main", "WorkerLockError"}]
    code = ast.Module(body=[ast.ImportFrom(module="__future__", names=[
        ast.alias(name="annotations")], level=0), *selected], type_ignores=[])
    ast.fix_missing_locations(code)
    httpx = SimpleNamespace(Client=MagicMock(), TimeoutException=FakeTimeout,
                            NetworkError=FakeNetworkError,
                            HTTPStatusError=FakeHTTPStatusError)
    env = dict(DEFAULT_PIPELINE_URL="https://pipeline.invalid", DEFAULT_API_KEY="dummy",
               DEFAULT_CHANNEL="synthetic", DEFAULT_MAX_VIDEOS=1, DEFAULT_DELAY_SEC=0,
               LOCK_FILE=Path("/synthetic.lock"), logger=MagicMock(), httpx=httpx,
               time=SimpleNamespace(time=MagicMock(return_value=0), sleep=MagicMock()),
               check_cookies_exist=MagicMock(return_value=True),
               notify_cookies_expired=MagicMock(), FlowCookiesExpiredError=FakeCookiesExpired,
               generate_video=MagicMock(), QueueItem=SimpleNamespace, argparse=argparse,
               sys=SimpleNamespace(exit=sys.exit), WorkerLock=lambda _: contextlib.nullcontext())
    exec(compile(code, str(source), "exec"), env)
    return env


class WorkerOutcomeCases:
    def setUp(self):
        self.env = load_definitions(self.source)
        self.client_class = self.env["PipelineClient"]
        self.api = self.client_class("https://pipeline.invalid", "dummy")
        self.http = self.env["httpx"].Client.return_value.__enter__.return_value

    def response(self, status=200, rows=None):
        response = MagicMock(status_code=status, text="synthetic response")
        response.json.return_value = {"rows": rows or []}
        if not 200 <= status < 300:
            response.raise_for_status.side_effect = FakeHTTPStatusError("synthetic HTTP error")
        return response

    def batch(self, outcomes):
        client = MagicMock()
        client.warmup.return_value = True
        client.update_status.return_value = True
        client.upload_video.return_value = {"message": "synthetic acceptance"}
        client.fetch_pending_queue.return_value = [SimpleNamespace(
            id=str(i), prompt="synthetic prompt", title=None, description=None, tags=None
        ) for i in range(len(outcomes))]
        self.env["PipelineClient"] = MagicMock(return_value=client)
        files = []
        values = []
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                values.append(outcome)
            else:
                video = MagicMock()
                video.exists.return_value = True
                files.append(video)
                values.append(video)
        self.env["generate_video"].side_effect = values
        return client, files

    def test_empty_queue_is_success(self):
        self.batch([])
        self.assertEqual(self.env["run_worker_batch"](), 0)

    def test_success_count_is_preserved(self):
        _, files = self.batch([True, True])
        self.assertEqual(self.env["run_worker_batch"](), 2)
        for video in files:
            video.unlink.assert_called_once_with(missing_ok=True)

    def test_generation_failure_is_negative(self):
        client, _ = self.batch([RuntimeError("synthetic generation failed")])
        self.assertLess(self.env["run_worker_batch"](), 0)
        client.update_status.assert_any_call("synthetic", "0", "failed")

    def test_partial_batch_failure_is_negative(self):
        self.batch([True, RuntimeError("synthetic generation failed"), True])
        self.assertLess(self.env["run_worker_batch"](), 0)
        self.assertEqual(self.env["generate_video"].call_count, 3)

    def test_expiry_after_success_still_fails(self):
        self.batch([True, FakeCookiesExpired("synthetic expiry"), True])
        self.assertLess(self.env["run_worker_batch"](), 0)
        self.assertEqual(self.env["generate_video"].call_count, 2)

    def test_upload_failure_is_negative_and_file_cleaned(self):
        client, files = self.batch([True])
        client.upload_video.side_effect = RuntimeError("synthetic upload failed")
        self.assertLess(self.env["run_worker_batch"](), 0)
        files[0].unlink.assert_called_once_with(missing_ok=True)

    def test_cannot_mark_generating_skips_generation(self):
        client, _ = self.batch([True])
        client.update_status.return_value = False
        self.assertLess(self.env["run_worker_batch"](), 0)
        self.env["generate_video"].assert_not_called()

    def test_failed_uploaded_status_is_failure_without_marking_upload_failed(self):
        client, _ = self.batch([True])
        client.update_status.side_effect = [True, False]
        self.assertLess(self.env["run_worker_batch"](), 0)
        self.assertEqual([call.args[2] for call in client.update_status.call_args_list],
                         ["generating", "uploaded"])

    def test_queue_authorization_errors_fail_fast_with_remediation(self):
        for status in (401, 403):
            with self.subTest(status=status):
                self.http.get.reset_mock()
                self.env["time"].sleep.reset_mock()
                self.http.get.return_value = self.response(status)
                with self.assertRaisesRegex(RuntimeError, "API_KEY"):
                    self.api.fetch_pending_queue("synthetic")
                self.http.get.assert_called_once()
                self.env["time"].sleep.assert_not_called()

    def test_transient_queue_error_retries(self):
        self.http.get.side_effect = [FakeTimeout("synthetic timeout"), self.response()]
        self.assertEqual(self.api.fetch_pending_queue("synthetic"), [])
        self.assertEqual(self.http.get.call_count, 2)
        self.env["time"].sleep.assert_called_once_with(10)

    def test_queue_server_error_retries(self):
        self.http.get.side_effect = [self.response(503), self.response()]
        self.assertEqual(self.api.fetch_pending_queue("synthetic"), [])
        self.assertEqual(self.http.get.call_count, 2)

    def test_health_rejects_non_success_statuses(self):
        for status in (301, 401, 403, 404, 500):
            with self.subTest(status=status):
                self.http.get.return_value = self.response(status)
                self.assertFalse(self.api.ping())
                self.assertFalse(self.api.warmup(max_attempts=1))

    def test_health_accepts_success_statuses(self):
        for status in (200, 204, 299):
            with self.subTest(status=status):
                self.http.get.return_value = self.response(status)
                self.assertTrue(self.api.ping())
                self.assertTrue(self.api.warmup(max_attempts=1))

    def test_cli_exits_nonzero_for_generation_failure(self):
        self.batch([RuntimeError("synthetic generation failed")])
        parser = MagicMock()
        parser.parse_args.return_value = SimpleNamespace(loop=0,
            pipeline_url="https://pipeline.invalid", api_key="dummy", channel="synthetic",
            max_videos=1, delay=0, headful=False)
        self.env["argparse"] = SimpleNamespace(ArgumentParser=MagicMock(return_value=parser))
        with self.assertRaises(SystemExit) as raised:
            self.env["main"]()
        self.assertEqual(raised.exception.code, 1)


class PackagedWorkerTests(WorkerOutcomeCases, unittest.TestCase):
    source = Path(__file__).resolve().parents[1] / "jobs/auto_generate_worker.py"


if __name__ == "__main__":
    unittest.main()
