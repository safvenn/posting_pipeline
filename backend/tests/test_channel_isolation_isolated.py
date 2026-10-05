"""AST-only synthetic checks; execute only in the approved isolated harness."""
from __future__ import annotations
import ast
import json
import re
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1] / "services"


def definitions(name, selected=None):
    tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and (selected is None or node.name in selected):
            nodes.append(node)
        elif isinstance(node, ast.Assign) and isinstance(node.value, (ast.Constant, ast.List, ast.Dict)):
            nodes.append(node)
    code = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
    env = dict(json=json, re=re, logger=MagicMock())
    exec(compile(ast.fix_missing_locations(code), name, "exec"), env)
    return env


class ChannelIsolationTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.cfg = SimpleNamespace(sheet_id="sky-sheet", sheet_tab="Sky", seo_tags="")
        self.db.query.return_value.filter.return_value.first.return_value = self.cfg
        session = MagicMock()
        session.return_value.__enter__.return_value = self.db
        database = ModuleType("backend.database")
        database.SessionLocal = session
        models = ModuleType("backend.models")
        models.ChannelConfig = MagicMock()
        self.imports = patch.dict(sys.modules, {"backend.database": database, "backend.models": models})
        self.imports.start()
        self.addCleanup(self.imports.stop)
        self.settings = SimpleNamespace(google_sheets_id_channel_a="food-sheet",
            google_sheets_tab_channel_a="Food", google_sheets_id_channel_b="legacy-b",
            google_sheets_tab_channel_b="B", seo_tags_for=lambda channel: [])

    def sheets(self):
        env = definitions("sheets.py", {"_sheet", "_extract_sheet_id", "get_all_rows", "_resolve_sheet_config"})
        env.update(settings=self.settings, _gc=MagicMock(), httpx=MagicMock())
        return env

    def test_configured_channel_resolves_own_sheet_and_tab(self):
        env = self.sheets()
        env["_sheet"]("sky_keepers")
        gc = env["_gc"].return_value
        gc.open_by_key.assert_called_once_with("sky-sheet")
        gc.open_by_key.return_value.worksheet.assert_called_once_with("Sky")

    def test_unconfigured_custom_channel_never_falls_back(self):
        self.cfg.sheet_id = None
        env = self.sheets()
        with self.assertRaises(ValueError):
            env["_sheet"]("sky_keepers")
        env["_gc"].return_value.open_by_key.assert_not_called()

    def test_database_failure_never_falls_back(self):
        self.db.query.side_effect = RuntimeError("synthetic database unavailable")
        env = self.sheets()
        with self.assertRaises((RuntimeError, ValueError)):
            env["_sheet"]("sky_keepers")
        env["_gc"].return_value.open_by_key.assert_not_called()

    def test_legacy_b_read_does_not_use_channel_a_csv(self):
        self.db.query.return_value.filter.return_value.first.return_value = None
        self.settings.google_sheets_id_channel_a = "https://docs.google.com/spreadsheets/d/e/2PACX-food/pub?output=csv"
        env = self.sheets()
        env["_sheet"] = MagicMock()
        env["get_all_rows"]("channel_b")
        env["httpx"].get.assert_not_called()
        env["_sheet"].assert_called_once_with("channel_b")

    def test_legacy_channel_b_binding_remains_supported(self):
        self.db.query.return_value.filter.return_value.first.return_value = None
        env = self.sheets()
        env["_sheet"]("channel_b")
        env["_gc"].return_value.open_by_key.assert_called_once_with("legacy-b")

    def test_gemini_prompt_is_grounded_in_target_content(self):
        env = definitions("enrichment.py", {"_build_prompt"})
        prompt = env["_build_prompt"]("sky_keepers", {"snippet": {"title": "Sky Keepers"}}, [],
            "2026-10-05T12:00:00+05:30", [],
            {"id": "1", "title": "FPV mountain flight", "prompt": "Drone flies over snowy mountains"})
        self.assertIn("Drone flies over snowy mountains", prompt)
        self.assertIn("FPV mountain flight", prompt)
        self.assertNotIn("miniature cooking", prompt.lower())
        self.assertNotIn("indianfood", prompt.lower())
        self.assertNotIn("dish", env["_SYSTEM_MESSAGE"].lower())

    def test_fallback_does_not_invent_food_content(self):
        env = definitions("_enrichment_rules.py")
        env["settings"] = self.settings
        for title in ("FPV mountain flight", "Snowy summit", "Ocean panorama", "Desert flight"):
            result = env["enrich_post"]("sky_keepers", title, "Drone over mountains", "drone;FPV", 0)
            output = json.dumps(result).lower()
            for unrelated in ("cooking", "tiny food", "miniature", "dish", "recipe", "indianfood", "crispy"):
                self.assertNotIn(unrelated, output)
            self.assertIn("drone over mountains", output)
            self.assertIn("fpv", output)

    def test_custom_channel_does_not_inherit_legacy_seo(self):
        env = definitions("_enrichment_rules.py")
        self.settings.seo_tags_for = MagicMock(return_value=["miniature cooking", "tiny food"])
        env["settings"] = self.settings
        result = env["enrich_post"]("sky_keepers", "FPV mountain flight", "Drone over mountains", "drone;FPV", 0)
        self.assertNotIn("cooking", json.dumps(result).lower())
        self.settings.seo_tags_for.assert_not_called()

    def test_channel_name_substrings_do_not_invent_food_content(self):
        env = definitions("_enrichment_rules.py")
        env["settings"] = self.settings
        for channel in ("swedish_landscapes", "indian_aviation"):
            result = env["enrich_post"](channel, "FPV mountain flight", "Drone over mountains", "drone;FPV", 0)
            output = json.dumps(result).lower()
            for unrelated in ("cooking", "miniature", "eating", "recipe"):
                self.assertNotIn(unrelated, output)

    def test_nonfood_gemini_does_not_invent_drone_niche(self):
        env = definitions("enrichment.py", {"_build_prompt"})
        prompt = env["_build_prompt"]("math_lessons", {"snippet": {"title": "Math Lessons"}}, [],
            "2026-10-05T12:00:00+05:30", [],
            {"id": "1", "title": "Solving quadratic equations", "prompt": "Explain the quadratic formula"})
        for unrelated in ("fpvdrone", "timelapse", "architecture", "landmark"):
            self.assertNotIn(unrelated, prompt.lower())

    def test_sheet_resolution_errors_are_not_swallowed(self):
        env = self.sheets()
        env["_resolve_sheet_config"] = MagicMock(side_effect=RuntimeError("synthetic unavailable"))
        env["_sheet"] = MagicMock()
        with self.assertRaises(RuntimeError):
            env["get_all_rows"]("sky_keepers")
        env["_sheet"].assert_not_called()

    def test_supplied_cooking_metadata_is_preserved(self):
        env = definitions("_enrichment_rules.py")
        env["settings"] = self.settings
        result = env["enrich_post"]("the_indian_kitchen", "Cooking biryani", "Miniature cooking of biryani", "biryani;cooking", 0)
        self.assertIn("biryani", result["enriched_title"].lower())
        self.assertIn("Miniature cooking of biryani", result["enriched_description"])
        self.assertIn("biryani", result["enriched_tags"])


if __name__ == "__main__":
    unittest.main()
