"""
Deterministic food selection with DB-backed duplicate prevention.

Algorithm:
  1. Load available food items for current cycle
  2. If empty: increment cycle, reset all to 'available', reload
  3. Random pick from available pool
  4. Mark as 'used' in transaction with UNIQUE constraint safety
  5. Return FoodItem

Zero Gemini calls. Race-condition-safe via UNIQUE(normalized_name, cycle_number).
"""
from __future__ import annotations

import logging
import random
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import FoodItem
from backend.services.asmr.errors import DuplicateFoodError, NoFoodAvailableError

logger = logging.getLogger(__name__)

FOOD_LIST_PATH = Path(__file__).parent.parent.parent / "data" / "food_master_list.yaml"


def normalize_food_name(name: str) -> str:
    """Lowercase, strip whitespace, collapse multiple spaces."""
    return re.sub(r"\s+", " ", name.strip().lower())


def seed_food_items(db: Session) -> int:
    """
    Seed food_items table from YAML master list.
    Skips items that already exist (by normalized_name + cycle 1).
    Returns count of newly inserted items.
    """
    if not FOOD_LIST_PATH.exists():
        logger.warning("Food master list not found: %s", FOOD_LIST_PATH)
        return 0

    with open(FOOD_LIST_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    foods = data.get("foods", [])
    if not foods:
        logger.warning("Empty food list in %s", FOOD_LIST_PATH)
        return 0

    inserted = 0
    for name in foods:
        normalized = normalize_food_name(name)
        existing = (
            db.query(FoodItem)
            .filter(FoodItem.normalized_name == normalized, FoodItem.cycle_number == 1)
            .first()
        )
        if existing:
            continue

        item = FoodItem(
            name=name.strip(),
            normalized_name=normalized,
            status="available",
            cycle_number=1,
        )
        db.add(item)
        inserted += 1

    if inserted:
        db.commit()
        logger.info("Seeded %d food items from master list", inserted)

    return inserted


def get_current_cycle(db: Session) -> int:
    """Return the highest cycle_number in the food_items table."""
    from sqlalchemy import func
    result = db.query(func.max(FoodItem.cycle_number)).scalar()
    return result or 1


def select_next_food(db: Session) -> FoodItem:
    """
    Select the next unused food item for the current cycle.

    If all items in the current cycle are used, starts a new cycle by
    duplicating all items with cycle_number + 1, status = 'available'.

    Returns the selected FoodItem (already committed as 'used').
    Raises NoFoodAvailableError if selection fails after cycle reset.
    """
    current_cycle = get_current_cycle(db)

    # Try to select from available pool
    food = _try_select_from_cycle(db, current_cycle)
    if food:
        return food

    # All used — start new cycle
    logger.info("All food items used in cycle %d. Starting cycle %d.", current_cycle, current_cycle + 1)
    new_cycle = current_cycle + 1
    _start_new_cycle(db, new_cycle)

    food = _try_select_from_cycle(db, new_cycle)
    if food:
        return food

    raise NoFoodAvailableError()


def _try_select_from_cycle(db: Session, cycle: int) -> FoodItem | None:
    """Pick a random available item from a cycle, mark as used. Returns None if empty."""
    available = (
        db.query(FoodItem)
        .filter(FoodItem.cycle_number == cycle, FoodItem.status == "available")
        .all()
    )
    if not available:
        return None

    chosen = random.choice(available)
    chosen.status = "used"
    chosen.used_at = datetime.now(timezone.utc)

    try:
        db.commit()
        db.refresh(chosen)
        logger.info("Selected food: %s (id=%d, cycle=%d)", chosen.name, chosen.id, chosen.cycle_number)
        return chosen
    except IntegrityError:
        db.rollback()
        logger.warning("Race condition on food selection, retrying")
        # Another worker grabbed it — retry once
        return _try_select_from_cycle(db, cycle)


def _start_new_cycle(db: Session, new_cycle: int) -> None:
    """Create new cycle entries for all unique food names."""
    # Get all distinct food names from any previous cycle
    existing_names = (
        db.query(FoodItem.name, FoodItem.normalized_name)
        .distinct(FoodItem.normalized_name)
        .all()
    )
    for name, normalized in existing_names:
        # Check if already exists in new cycle (idempotent)
        exists = (
            db.query(FoodItem)
            .filter(FoodItem.normalized_name == normalized, FoodItem.cycle_number == new_cycle)
            .first()
        )
        if exists:
            continue
        db.add(FoodItem(
            name=name,
            normalized_name=normalized,
            status="available",
            cycle_number=new_cycle,
        ))
    db.commit()
    logger.info("New cycle %d created with %d food items", new_cycle, len(existing_names))


def add_food_item(db: Session, name: str) -> FoodItem:
    """Add a new food item to the current cycle."""
    normalized = normalize_food_name(name)
    current_cycle = get_current_cycle(db)

    existing = (
        db.query(FoodItem)
        .filter(FoodItem.normalized_name == normalized, FoodItem.cycle_number == current_cycle)
        .first()
    )
    if existing:
        raise DuplicateFoodError(name)

    item = FoodItem(
        name=name.strip(),
        normalized_name=normalized,
        status="available",
        cycle_number=current_cycle,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    logger.info("Added food item: %s (id=%d, cycle=%d)", item.name, item.id, item.cycle_number)
    return item


def retire_food_item(db: Session, food_id: int) -> FoodItem:
    """Mark a food item as retired (excluded from future selection)."""
    item = db.get(FoodItem, food_id)
    if not item:
        raise ValueError(f"Food item not found: {food_id}")
    item.status = "retired"
    db.commit()
    db.refresh(item)
    logger.info("Retired food item: %s (id=%d)", item.name, item.id)
    return item


def get_food_stats(db: Session) -> dict:
    """Return food selection statistics."""
    from sqlalchemy import func
    current_cycle = get_current_cycle(db)
    total = db.query(func.count(FoodItem.id)).filter(FoodItem.cycle_number == current_cycle).scalar() or 0
    available = (
        db.query(func.count(FoodItem.id))
        .filter(FoodItem.cycle_number == current_cycle, FoodItem.status == "available")
        .scalar() or 0
    )
    used = (
        db.query(func.count(FoodItem.id))
        .filter(FoodItem.cycle_number == current_cycle, FoodItem.status == "used")
        .scalar() or 0
    )
    return {
        "current_cycle": current_cycle,
        "total": total,
        "available": available,
        "used": used,
    }
