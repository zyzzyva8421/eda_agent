"""Rule weight management for Phase B feedback learning.

Each rule has a ``multiplier`` (default 1.0) that is adjusted after every
engineer confirmation.  The multipliers are persisted in the ``rule_weights``
PostgreSQL table and cached in-process for the lifetime of the worker.

Scoring with multiplier::

    adjusted_score = raw_score * multiplier(rule_id)

Update policy
-------------
Let ``top_ids`` = [h["cause_id"] for h in hypotheses] (ranked list from infer()).

Case 1 – confirmed cause IS top-1:
    top-1 rule  → +δ   (correct prediction, reinforce)

Case 2 – confirmed cause is in top-3 but NOT top-1:
    confirmed   → +δ   (it fired, just not ranked high enough)
    top-1       → -δ   (penalise the wrong leader)

Case 3 – confirmed cause NOT in top-3 at all:
    confirmed   → +δ   (rule underfit, boost it)
    all fired   → -δ/2 (mild penalty for every wrong candidate)

Bounds: multiplier ∈ [MIN_MULTIPLIER, MAX_MULTIPLIER]
δ is configurable (default DELTA = 0.05).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from eda_agent.db.session import get_db, supports_postgresql_on_conflict

logger = logging.getLogger(__name__)

DELTA: float = 0.05
MIN_MULTIPLIER: float = 0.10
MAX_MULTIPLIER: float = 2.00


def _clamp(v: float) -> float:
    return max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, v))


# ── Public API ────────────────────────────────────────────────────────────────

def get_multipliers() -> dict[str, float]:
    """Return {rule_id: multiplier} from DB.  Missing rules default to 1.0."""
    try:
        with get_db() as db:
            rows = db.execute(
                text("SELECT rule_id, multiplier FROM rule_weights")
            ).fetchall()
            return {row[0]: float(row[1]) for row in rows}
    except Exception:
        logger.warning("Could not load rule_weights from DB – using defaults", exc_info=True)
        return {}


def update_weights(
    confirmed_cause_id: str,
    top_hypotheses: list[dict],
    delta: float = DELTA,
) -> dict[str, float]:
    """Adjust multipliers based on confirmation feedback.

    Parameters
    ----------
    confirmed_cause_id:
        The cause_id the engineer confirmed as correct.
    top_hypotheses:
        The ``hypotheses`` list returned by ``infer()`` (already ranked).
    delta:
        Learning step size (default 0.05).

    Returns
    -------
    Updated multiplier snapshot ``{rule_id: new_multiplier}``.
    """
    # Current state from DB
    current = get_multipliers()

    top_ids = [h["cause_id"] for h in top_hypotheses]

    updates: dict[str, float] = {}  # rule_id → new multiplier

    def _adj(rule_id: str, change: float) -> None:
        base = current.get(rule_id, 1.0)
        updates[rule_id] = _clamp(base + change)

    if not top_ids:
        # No predictions were made – just boost the confirmed rule slightly
        _adj(confirmed_cause_id, delta)
    elif confirmed_cause_id == top_ids[0]:
        # Case 1: top-1 was correct
        _adj(confirmed_cause_id, delta)
    elif confirmed_cause_id in top_ids:
        # Case 2: correct but not top-1
        _adj(confirmed_cause_id, delta)
        _adj(top_ids[0], -delta)
    else:
        # Case 3: not in top-3 at all
        _adj(confirmed_cause_id, delta)
        for rule_id in top_ids:
            _adj(rule_id, -delta / 2)

    # Persist to DB using UPSERT
    _persist_updates(updates)
    return updates


def _persist_updates(updates: dict[str, float]) -> None:
    if not updates:
        return
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_db() as db:
            for rule_id, multiplier in updates.items():
                if supports_postgresql_on_conflict():
                    db.execute(
                        text(
                            """
                            INSERT INTO rule_weights
                                (rule_id, multiplier, confirm_count, updated_at)
                            VALUES (:rule_id, :multiplier, 1, :now)
                            ON CONFLICT (rule_id) DO UPDATE
                            SET multiplier     = :multiplier,
                                confirm_count  = rule_weights.confirm_count + 1,
                                updated_at     = :now
                            """
                        ),
                        {"rule_id": rule_id, "multiplier": multiplier, "now": now},
                    )
                else:
                    updated = db.execute(
                        text(
                            """
                            UPDATE rule_weights
                            SET multiplier = :multiplier,
                                confirm_count = confirm_count + 1,
                                updated_at = :now
                            WHERE rule_id = :rule_id
                            """
                        ),
                        {"rule_id": rule_id, "multiplier": multiplier, "now": now},
                    )
                    if updated.rowcount == 0:
                        db.execute(
                            text(
                                """
                                INSERT INTO rule_weights
                                    (rule_id, multiplier, confirm_count, updated_at)
                                VALUES (:rule_id, :multiplier, 1, :now)
                                """
                            ),
                            {"rule_id": rule_id, "multiplier": multiplier, "now": now},
                        )
        logger.info("Updated rule_weights: %s", updates)
    except Exception:
        logger.warning("Could not persist rule weight updates", exc_info=True)
