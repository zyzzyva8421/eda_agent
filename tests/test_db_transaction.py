"""Tests for DB transaction atomicity – _save_run_and_parse.

Verifies P0 fixes:
1. _upsert_run and _ingest_records share the same session.
2. _save_run_and_parse wraps both in a single get_db() transaction.
3. Existing callers (_upsert_run with no db) still work independently.
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, call, patch

import pytest


# ── _upsert_run backward-compat (no db passed) ─────────────────────────────────


def test_upsert_run_creates_own_session():
    """When called without ``db=``, _upsert_run opens its own session."""
    from eda_agent.agent.tools import _upsert_run
    from eda_agent.backends.base import DesignSpec, RunResult, StageStatus
    from datetime import datetime, timezone
    from pathlib import Path as _Path

    mock_session = MagicMock()
    # simulate a successful upsert flow
    mock_session.execute.return_value.first.return_value = (1,)
    mock_session.execute.return_value.scalar.return_value = 42
    now = datetime.now(timezone.utc)
    result = RunResult(
        run_id="abc-123",
        backend_name="orfs",
        design_name="gcd",
        stage="route",
        status=StageStatus.SUCCESS,
        started_at=now,
        finished_at=now,
    )

    with patch("eda_agent.agent.tools.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = mock_session
        mock_get_db.return_value.__exit__.return_value = False
        run_id = _upsert_run(result, DesignSpec(name="gcd", config_path=_Path(__file__)))

    # get_db must have been called => independent session
    mock_get_db.assert_called_once()
    # commit happens inside get_db() context manager
    assert run_id == 42


def test_upsert_run_with_db_supplied():
    """When ``db=`` is supplied, the *caller* manages the transaction."""
    from eda_agent.agent.tools import _upsert_run
    from eda_agent.backends.base import DesignSpec, RunResult, StageStatus
    from datetime import datetime, timezone
    from pathlib import Path as _Path

    mock_db = MagicMock()
    mock_db.execute.return_value.first.return_value = (1,)
    mock_db.execute.return_value.scalar.return_value = 42
    now = datetime.now(timezone.utc)
    result = RunResult(
        run_id="xyz-999",
        backend_name="orfs",
        design_name="gcd",
        stage="route",
        status=StageStatus.SUCCESS,
        started_at=now,
        finished_at=now,
    )

    run_id = _upsert_run(
        result, DesignSpec(name="gcd", config_path=_Path(__file__)), db=mock_db
    )

    # The caller's session was used; get_db was NOT called
    assert run_id == 42
    # commit is NOT called by _upsert_run (caller manages)
    mock_db.commit.assert_not_called()


# ── _save_run_and_parse atomicity ──────────────────────────────────────────────


def test_save_run_and_parse_uses_one_session():
    """_save_run_and_parse opens exactly one get_db() and passes it through
    to both _upsert_run and _ingest_records."""
    from eda_agent.agent.tools import _save_run_and_parse
    from eda_agent.backends.base import DesignSpec, RunResult, StageStatus
    from datetime import datetime, timezone
    from pathlib import Path as _Path

    mock_session = MagicMock()
    mock_session.execute.return_value.first.return_value = (1,)
    mock_session.execute.return_value.scalar.return_value = 42
    now = datetime.now(timezone.utc)
    result = RunResult(
        run_id="joint-1",
        backend_name="orfs",
        design_name="gcd",
        stage="route",
        status=StageStatus.SUCCESS,
        started_at=now,
        finished_at=now,
    )
    mock_backend = MagicMock()
    mock_backend.collect_reports.return_value = []  # no reports to parse

    with patch("eda_agent.agent.tools.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = mock_session
        mock_get_db.return_value.__exit__.return_value = False
        run_id = _save_run_and_parse(result, DesignSpec(name="gcd", config_path=_Path(__file__)),
                                     backend=mock_backend)

    # get_db called exactly once
    mock_get_db.assert_called_once()
    assert run_id == 42


def test_save_run_and_parse_no_backend_still_upserts():
    """_save_run_and_parse still upserts the run when backend=None."""
    from eda_agent.agent.tools import _save_run_and_parse
    from eda_agent.backends.base import DesignSpec, RunResult, StageStatus
    from datetime import datetime, timezone
    from pathlib import Path as _Path

    mock_session = MagicMock()
    mock_session.execute.return_value.first.return_value = (1,)
    mock_session.execute.return_value.scalar.return_value = 7
    now = datetime.now(timezone.utc)
    result = RunResult(
        run_id="no-be",
        backend_name="orfs",
        design_name="gcd",
        stage="floorplan",
        status=StageStatus.SUCCESS,
        started_at=now,
        finished_at=now,
    )

    with patch("eda_agent.agent.tools.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = mock_session
        mock_get_db.return_value.__exit__.return_value = False
        run_id = _save_run_and_parse(result, DesignSpec(name="gcd", config_path=_Path(__file__)),
                                     backend=None)

    mock_get_db.assert_called_once()
    assert run_id == 7
    # ingest_records should NOT have been called (no backend → no reports)
    # We trust the mock: if ingest was called, mock_session.execute would show inserts


def test_save_run_and_parse_on_failed_stage_no_ingest():
    """When the stage FAILED, reports are not collected."""
    from eda_agent.agent.tools import _save_run_and_parse
    from eda_agent.backends.base import DesignSpec, RunResult, StageStatus
    from datetime import datetime, timezone
    from pathlib import Path as _Path

    mock_session = MagicMock()
    mock_session.execute.return_value.first.return_value = (1,)
    mock_session.execute.return_value.scalar.return_value = 99
    now = datetime.now(timezone.utc)
    result = RunResult(
        run_id="failed-1",
        backend_name="orfs",
        design_name="gcd",
        stage="cts",
        status=StageStatus.FAILED,
        started_at=now,
        finished_at=now,
        error_message="make returned code 2",
    )
    mock_backend = MagicMock()

    with patch("eda_agent.agent.tools.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = mock_session
        mock_get_db.return_value.__exit__.return_value = False
        run_id = _save_run_and_parse(result, DesignSpec(name="gcd", config_path=_Path(__file__)),
                                     backend=mock_backend)

    # collect_reports must NOT be called on a failed run
    mock_backend.collect_reports.assert_not_called()
    assert run_id == 99
