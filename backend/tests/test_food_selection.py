"""Unit tests for food selection service — deterministic dedup, normalization, cycle reset."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from backend.services.asmr.food_selection import (
    normalize_food_name,
    select_next_food,
    add_food_item,
    get_current_cycle,
    seed_food_items,
    get_food_stats,
)
from backend.services.asmr.errors import DuplicateFoodError, NoFoodAvailableError
from backend.models import FoodItem


# ---- Normalization --------------------------------------------------------- #

def test_normalize_strips_whitespace():
    assert normalize_food_name("  Gulab Jamun  ") == "gulab jamun"

def test_normalize_lowercase():
    assert normalize_food_name("Chole Bhature") == "chole bhature"

def test_normalize_collapses_spaces():
    assert normalize_food_name("vada   pav") == "vada pav"

def test_normalize_single_word():
    assert normalize_food_name("samosa") == "samosa"

def test_normalize_empty_string():
    assert normalize_food_name("  ") == ""


# ---- Food selection with mock DB ------------------------------------------ #

class MockFoodItem:
    """Mock FoodItem that quacks like the ORM model."""
    def __init__(self, id, name, normalized_name, status="available", cycle_number=1):
        self.id = id
        self.name = name
        self.normalized_name = normalized_name
        self.status = status
        self.cycle_number = cycle_number
        self.used_at = None


@pytest.fixture
def mock_db():
    """Create a mock DB session with a pool of food items."""
    db = MagicMock()

    available_items = [
        MockFoodItem(1, "samosa", "samosa"),
        MockFoodItem(2, "jalebi", "jalebi"),
        MockFoodItem(3, "kulfi", "kulfi"),
    ]

    # Mock query chain for available items
    query_mock = MagicMock()
    filter_mock = MagicMock()
    filter_mock.all.return_value = available_items
    filter_mock.first.return_value = available_items[0] if available_items else None
    query_mock.filter.return_value = filter_mock
    db.query.return_value = query_mock

    return db


def test_select_picks_from_available(mock_db):
    """Selection returns an item from the available pool."""
    result = select_next_food(mock_db)
    assert result is not None
    assert result.status == "used"
    assert result.used_at is not None


def test_select_marks_as_used(mock_db):
    """Selected item gets status changed to 'used'."""
    result = select_next_food(mock_db)
    assert result.status == "used"


# ---- Duplicate prevention ------------------------------------------------- #

def test_add_duplicate_raises():
    """Adding a food item that already exists in current cycle raises error."""
    db = MagicMock()
    query_mock = MagicMock()
    filter_mock = MagicMock()

    # Simulate existing item found
    existing = MockFoodItem(1, "samosa", "samosa")
    filter_mock.first.return_value = existing
    query_mock.filter.return_value = filter_mock
    db.query.return_value = query_mock

    # Mock get_current_cycle
    from sqlalchemy import func
    with patch("backend.services.asmr.food_selection.get_current_cycle", return_value=1):
        with pytest.raises(DuplicateFoodError):
            add_food_item(db, "Samosa")


# ---- Master list ---------------------------------------------------------- #

def test_food_master_list_exists():
    """Verify food_master_list.yaml exists and has 36 items."""
    from pathlib import Path
    import yaml

    path = Path(__file__).parent.parent / "data" / "food_master_list.yaml"
    assert path.exists(), f"Food master list not found: {path}"

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    foods = data.get("foods", [])
    assert len(foods) == 36, f"Expected 36 food items, got {len(foods)}"


def test_food_master_list_no_duplicates():
    """Verify no duplicate entries in master list."""
    from pathlib import Path
    import yaml

    path = Path(__file__).parent.parent / "data" / "food_master_list.yaml"
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    foods = data.get("foods", [])
    normalized = [normalize_food_name(f) for f in foods]
    assert len(normalized) == len(set(normalized)), "Duplicate food items in master list"


def test_food_master_list_contains_key_items():
    """Verify critical items from n8n workflow exist."""
    from pathlib import Path
    import yaml

    path = Path(__file__).parent.parent / "data" / "food_master_list.yaml"
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    foods = [normalize_food_name(f) for f in data.get("foods", [])]
    expected = ["samosa", "jalebi", "gulab jamun", "pani puri", "vada pav", "pesarattu"]
    for item in expected:
        assert item in foods, f"Missing key item: {item}"
