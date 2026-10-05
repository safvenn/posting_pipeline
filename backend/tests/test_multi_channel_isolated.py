"""Synthetic AST-only multi-channel regressions for the isolated remote harness."""
from __future__ import annotations

import argparse
import ast
import contextlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


def load_definitions(source):
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in {
            "PipelineClient", "run_worker_cycle", "main", "WorkerLockError"
        }:
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "DEFAULT_CHANNEL"
            for target in node.targets
        ):
            selected.append(node)
    code = ast.Module(body=[ast.ImportFrom(module="__future__", names=[
        ast.alias(name="annotations")], level=0), *selected], type_ignores=[])
    ast.fix_missing_locations(code)
    env = dict(DEFAULT_PIPELINE_URL="https://pipeline.invalid", DEFAULT_API_KEY="dummy",
               DEFAULT_MAX_VIDEOS=1, DEFAULT_DELAY_SEC=45,
               LOCK_FILE=Path("/synthetic.lock"), logger=MagicMock(),
               httpx=SimpleNamespace(Client=MagicMock(), HTTPStatusError=RuntimeError,
                                     TimeoutException=TimeoutError, NetworkError=OSError),
               os=SimpleNamespace(getenv=lambda key, default=None:
                                  "legacy_channel" if key == "CHANNEL" else default),
               time=SimpleNamespace(sleep=MagicMock()), argparse=argparse,
               sys=SimpleNamespace(exit=sys.exit),
               WorkerLock=lambda _: contextlib.nullcontext(),
               run_worker_batch=MagicMock(return_value=1))
    exec(compile(code, str(source), "exec"), env)
    return env


class MultiChannelCases:
    def setUp(self):
        self.env = load_definitions(self.source)
        self.api = self.env["PipelineClient"]("https://pipeline.invalid", "dummy")
        self.http = self.env["httpx"].Client.return_value.__enter__.return_value

    def response(self, data, status=200):
        response = MagicMock(status_code=status, text="synthetic response")
        response.json.return_value = data
        if status >= 400:
            response.raise_for_status.side_effect = RuntimeError("synthetic HTTP error")
        self.http.get.return_value = response
        return response

    def cycle_client(self, channels):
        client = MagicMock()
        client.warmup.return_value = True
        client.discover_channels.return_value = channels
        self.env["PipelineClient"] = MagicMock(return_value=client)
        return client

    def test_discovery_uses_authenticated_endpoint_and_configured_channels(self):
        self.response([
            {"id": "first", "sheet_id": "sheet-one"},
            {"id": "google_drive", "sheet_id": "drive-sheet"},
            {"id": "unset", "sheet_id": None},
            {"id": "blank", "sheet_id": "   "},
            {"id": "second", "sheet_id": "sheet-two"},
        ])
        self.assertEqual(self.api.discover_channels(), ["first", "second"])
        self.assertEqual(self.http.get.call_args.args[0],
                         "https://pipeline.invalid/api/extension/channels")
        headers = self.env["httpx"].Client.call_args.kwargs["headers"]
        self.assertIn("dummy", headers.values())

    def test_discovery_deduplicates(self):
        self.response([{"id": "first", "sheet_id": "s"}] * 2)
        self.assertEqual(self.api.discover_channels(), ["first"])

    def test_discovery_empty_list_is_valid(self):
        self.response([])
        self.assertEqual(self.api.discover_channels(), [])

    def test_discovery_rejects_malformed_payloads(self):
        for payload in ({"channels": []}, None, "first", [None],
                        [{"sheet_id": "s"}], [{"id": 123, "sheet_id": "s"}],
                        [{"id": " ", "sheet_id": "s"}]):
            with self.subTest(payload=payload):
                self.response(payload)
                with self.assertRaises((RuntimeError, ValueError)):
                    self.api.discover_channels()

    def test_discovery_http_failure_raises(self):
        for status in (401, 403, 503):
            with self.subTest(status=status):
                self.response([], status=status)
                with self.assertRaises((RuntimeError, ValueError)):
                    self.api.discover_channels()

    def test_each_channel_gets_full_limit_and_configuration(self):
        self.cycle_client(["first", "second"])
        result = self.env["run_worker_cycle"](
            pipeline_url="https://pipeline.invalid", api_key="dummy", channel="all",
            max_videos=3, delay_sec=7, headless=False)
        calls = self.env["run_worker_batch"].call_args_list
        self.assertEqual([call.kwargs["channel"] for call in calls], ["first", "second"])
        for call in calls:
            self.assertEqual(call.kwargs["max_videos"], 3)
            self.assertEqual(call.kwargs["delay_sec"], 7)
            self.assertFalse(call.kwargs["headless"])
            self.assertEqual(call.kwargs["api_key"], "dummy")
        self.assertEqual(result, 2)

    def test_new_channels_are_discovered_on_next_cycle(self):
        client = self.cycle_client([])
        client.discover_channels.side_effect = [["first"], ["first", "new_channel"]]
        self.env["run_worker_cycle"](channel="all")
        self.env["run_worker_cycle"](channel="all")
        self.assertEqual(client.discover_channels.call_count, 2)
        self.assertEqual([call.kwargs["channel"] for call in
                          self.env["run_worker_batch"].call_args_list],
                         ["first", "first", "new_channel"])

    def test_channel_failure_does_not_prevent_remaining_channels(self):
        for outcome in (-1, RuntimeError("synthetic failure")):
            with self.subTest(outcome=outcome):
                self.cycle_client(["first", "second"])
                batch = self.env["run_worker_batch"]
                batch.reset_mock()
                batch.side_effect = [outcome, 1]
                self.assertEqual(self.env["run_worker_cycle"](channel="all"), -1)
                self.assertEqual(batch.call_count, 2)

    def test_empty_discovery_does_not_use_legacy_default(self):
        self.cycle_client([])
        self.assertEqual(self.env["run_worker_cycle"](channel="all"), 0)
        self.env["run_worker_batch"].assert_not_called()

    def test_discovery_failure_fails_closed(self):
        client = self.cycle_client([])
        client.discover_channels.side_effect = RuntimeError("synthetic unavailable")
        self.assertEqual(self.env["run_worker_cycle"](channel="all"), -1)
        self.env["run_worker_batch"].assert_not_called()

    def test_explicit_channel_bypasses_discovery(self):
        client = self.cycle_client([])
        self.assertEqual(self.env["run_worker_cycle"](channel="selected"), 1)
        client.discover_channels.assert_not_called()
        self.assertEqual(self.env["run_worker_batch"].call_args.kwargs["channel"], "selected")

    def test_cli_defaults_all_despite_legacy_environment(self):
        self.assertEqual(self.env["DEFAULT_CHANNEL"], "all")
        cycle = self.env["run_worker_cycle"] = MagicMock(return_value=0)
        with patch.object(sys, "argv", ["worker"]):
            self.env["main"]()
        self.assertEqual(cycle.call_args.kwargs["channel"], "all")

    def test_cli_explicit_channel_and_failure_exit(self):
        cycle = self.env["run_worker_cycle"] = MagicMock(return_value=-1)
        with patch.object(sys, "argv", ["worker", "--channel", "selected"]):
            with self.assertRaises(SystemExit) as raised:
                self.env["main"]()
        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(cycle.call_args.kwargs["channel"], "selected")


class PackagedTests(MultiChannelCases, unittest.TestCase):
    source = Path(__file__).resolve().parents[1] / "jobs/auto_generate_worker.py"


if __name__ == "__main__":
    unittest.main()
