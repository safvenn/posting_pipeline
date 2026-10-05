"""Synthetic selection regressions; run in the networkless fixture harness."""
import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


def definitions():
    source = Path(__file__).resolve().parents[1] / "services/flow_playwright.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    nodes += [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
    ns = dict(os=os, logger=MagicMock(), VIDEO_READY_TIMEOUT_MS=10,
              DEFAULT_FLOW_PROJECTS={}, time=SimpleNamespace(
                  time=MagicMock(side_effect=[0, 0, 0, 1, 1, 2, 2]), sleep=MagicMock()))
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(source), "exec"), ns)
    return ns


class SelectionTests(unittest.TestCase):
    def test_late_old_network_and_dom_video_are_never_accepted(self):
        ns = definitions()
        page = MagicMock()
        page.evaluate.return_value = "https://storage.googleapis.com/old-food.mp4"
        ns["_read_generation_cards"] = MagicMock(return_value=[])
        with self.assertRaises(ns["FlowError"]):
            ns["_wait_for_video"](page, ["https://storage.googleapis.com/old-food.mp4"],
                                   pre_gen_ids=set(), prompt="Drone over mountains")

    def test_unknown_channel_cannot_use_shared_project(self):
        ns = definitions()
        with patch.dict(os.environ, {"FLOW_PROJECT_URL": "https://flow.google.com/project/shared"}, clear=True):
            with self.assertRaises(ns["FlowError"]):
                ns["get_flow_project_url"]("new_channel")

    def test_verified_current_card_wins_over_unrelated_network_response(self):
        ns = definitions()
        ns["_read_generation_cards"] = MagicMock(return_value=[
            {"id": "new", "prompt": "Drone over mountains", "url": "https://storage.googleapis.com/new.mp4"}])
        result = ns["_wait_for_video"](MagicMock(), ["https://storage.googleapis.com/old.mp4"],
            pre_gen_ids={"old"}, prompt="Drone over mountains")
        self.assertEqual(result, "https://storage.googleapis.com/new.mp4")

    def test_old_card_with_identical_prompt_is_rejected(self):
        ns = definitions()
        ns["_read_generation_cards"] = MagicMock(return_value=[
            {"id": "old", "prompt": "Drone over mountains", "url": "https://storage.googleapis.com/old.mp4"}])
        with self.assertRaises(ns["FlowError"]):
            ns["_wait_for_video"](MagicMock(), [], pre_gen_ids={"old"}, prompt="Drone over mountains")

    def test_unrelated_new_card_is_rejected(self):
        ns = definitions()
        ns["_read_generation_cards"] = MagicMock(return_value=[
            {"id": "new", "prompt": "Cooking biryani", "url": "https://storage.googleapis.com/food.mp4"}])
        with self.assertRaises(ns["FlowError"]):
            ns["_wait_for_video"](MagicMock(), [], pre_gen_ids=set(), prompt="Drone over mountains")


if __name__ == "__main__":
    unittest.main()
