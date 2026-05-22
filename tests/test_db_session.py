"""Tests for db/session.py – get_db_dependency commit/rollback behaviour."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from eda_agent.db.session import get_db_dependency, SessionLocal


def test_get_db_dependency_commits_on_success():
    """get_db_dependency must commit after yielding when no exception occurs."""
    mock_session = MagicMock()

    with patch(
        "eda_agent.db.session.SessionLocal", return_value=mock_session
    ):
        gen = get_db_dependency()
        db = next(gen)  # enter the dependency (yield db)

        # Resume the generator to simulate successful request completion.
        # This runs db.commit(), then the generator finishes with StopIteration.
        try:
            next(gen)
        except StopIteration:
            pass

    # After normal exit, commit + close must be called
    mock_session.commit.assert_called_once()
    mock_session.close.assert_called_once()
    mock_session.rollback.assert_not_called()


def test_get_db_dependency_rolls_back_on_exception():
    """get_db_dependency must rollback when an exception is raised in the
    FastAPI path function, then re-raise so the framework can handle it."""
    mock_session = MagicMock()

    with patch(
        "eda_agent.db.session.SessionLocal", return_value=mock_session
    ):
        gen = get_db_dependency()
        db = next(gen)

        # Simulate an exception in the path function
        with pytest.raises(ValueError, match="simulated"):
            gen.throw(ValueError("simulated"))

    mock_session.rollback.assert_called_once()
    mock_session.close.assert_called_once()
    mock_session.commit.assert_not_called()


def test_get_db_dependency_yields_usable_session():
    """The dependency yields a functional session."""
    mock_session = MagicMock()
    with patch(
        "eda_agent.db.session.SessionLocal", return_value=mock_session
    ):
        gen = get_db_dependency()
        db = next(gen)
        assert db is mock_session
