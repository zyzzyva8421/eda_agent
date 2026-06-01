"""Tests for the async task queue (store, worker, CLI commands).

All tests use an in-memory (tmp_path) SQLite database so they never touch
the default ``~/.eda_agent/jobs.db``.
"""

from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eda_agent.queue.store import Job, JobStatus, JobStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_store(tmp_path: Path) -> JobStore:
    return JobStore(db_path=tmp_path / "test_jobs.db")


def _submit(store: JobStore, **overrides) -> Job:
    defaults = dict(
        backend="orfs",
        stage="synth",
        design_name="aes",
        design_config="/path/to/config.mk",
        pdk="sky130hd",
        params={},
    )
    defaults.update(overrides)
    return store.create_job(**defaults)


# ---------------------------------------------------------------------------
# JobStore – CRUD
# ---------------------------------------------------------------------------


class TestJobStore:
    def test_create_and_get(self, tmp_path):
        store = make_store(tmp_path)
        job = _submit(store, stage="route", params={"CORE_UTILIZATION": "40"})

        assert job.job_id
        assert job.status == JobStatus.PENDING
        assert job.stage == "route"
        assert job.params == {"CORE_UTILIZATION": "40"}

        fetched = store.get_job(job.job_id)
        assert fetched is not None
        assert fetched.job_id == job.job_id
        assert fetched.params == {"CORE_UTILIZATION": "40"}

    def test_get_nonexistent_returns_none(self, tmp_path):
        store = make_store(tmp_path)
        assert store.get_job("no-such-id") is None

    def test_list_all(self, tmp_path):
        store = make_store(tmp_path)
        _submit(store, stage="synth")
        _submit(store, stage="route")
        jobs = store.list_jobs()
        assert len(jobs) == 2

    def test_list_filter_by_status(self, tmp_path):
        store = make_store(tmp_path)
        j1 = _submit(store, stage="synth")
        _submit(store, stage="route")

        # Mark first job as done
        store.mark_done(j1.job_id, status=JobStatus.SUCCESS, run_db_id=99)

        pending = store.list_jobs(status=JobStatus.PENDING)
        success = store.list_jobs(status=JobStatus.SUCCESS)
        assert len(pending) == 1
        assert len(success) == 1
        assert success[0].run_db_id == 99

    def test_claim_pending_job_marks_running(self, tmp_path):
        store = make_store(tmp_path)
        job = _submit(store)

        claimed = store.claim_pending_job()
        assert claimed is not None
        assert claimed.job_id == job.job_id
        assert claimed.status == JobStatus.RUNNING
        assert claimed.started_at is not None

    def test_claim_returns_none_when_empty(self, tmp_path):
        store = make_store(tmp_path)
        assert store.claim_pending_job() is None

    def test_claim_oldest_first(self, tmp_path):
        store = make_store(tmp_path)
        j1 = _submit(store, stage="synth")
        time.sleep(0.01)
        _submit(store, stage="route")

        claimed = store.claim_pending_job()
        assert claimed is not None
        assert claimed.job_id == j1.job_id  # oldest first

    def test_cancel_pending_job(self, tmp_path):
        store = make_store(tmp_path)
        job = _submit(store)
        ok = store.cancel_job(job.job_id)
        assert ok is True
        updated = store.get_job(job.job_id)
        assert updated is not None
        assert updated.status == JobStatus.CANCELLED

    def test_cancel_running_job_fails(self, tmp_path):
        store = make_store(tmp_path)
        job = _submit(store)
        store.claim_pending_job()  # marks as running

        ok = store.cancel_job(job.job_id)
        assert ok is False
        still_running = store.get_job(job.job_id)
        assert still_running is not None
        assert still_running.status == JobStatus.RUNNING

    def test_cancel_nonexistent_returns_false(self, tmp_path):
        store = make_store(tmp_path)
        assert store.cancel_job("ghost-id") is False

    def test_mark_done_success(self, tmp_path):
        store = make_store(tmp_path)
        job = _submit(store)
        store.claim_pending_job()
        store.mark_done(
            job.job_id,
            status=JobStatus.SUCCESS,
            run_db_id=42,
            log_path="/var/log/run.log",
        )

        done = store.get_job(job.job_id)
        assert done is not None
        assert done.status == JobStatus.SUCCESS
        assert done.run_db_id == 42
        assert done.log_path == "/var/log/run.log"
        assert done.finished_at is not None

    def test_mark_done_failed_with_error(self, tmp_path):
        store = make_store(tmp_path)
        job = _submit(store)
        store.claim_pending_job()
        store.mark_done(
            job.job_id,
            status=JobStatus.FAILED,
            error_message="make exited with code 2",
        )

        done = store.get_job(job.job_id)
        assert done is not None
        assert done.status == JobStatus.FAILED
        assert "code 2" in done.error_message

    def test_params_roundtrip_json(self, tmp_path):
        store = make_store(tmp_path)
        params = {"CORE_UTILIZATION": "40", "CLOCK_PERIOD": "1.5", "EXTRA": 99}
        job = _submit(store, params=params)
        fetched = store.get_job(job.job_id)
        assert fetched is not None
        assert fetched.params == params

    def test_db_persists_across_instances(self, tmp_path):
        db_path = tmp_path / "shared.db"
        store1 = JobStore(db_path=db_path)
        job = _submit(store1)

        store2 = JobStore(db_path=db_path)
        fetched = store2.get_job(job.job_id)
        assert fetched is not None
        assert fetched.job_id == job.job_id


# ---------------------------------------------------------------------------
# Worker – _execute_job
# ---------------------------------------------------------------------------


class TestWorkerExecuteJob:
    def test_successful_job_marked_success(self, tmp_path):
        from eda_agent.queue.worker import _execute_job

        store = make_store(tmp_path)
        job = _submit(store)
        store.claim_pending_job()

        fake_result = {
            "run_id": 7,
            "status": "success",
            "log_path": "/tmp/run.log",
            "error": "",
        }
        with patch("eda_agent.agent.tools._run_eda_stage", return_value=fake_result):
            _execute_job(job, store)

        done = store.get_job(job.job_id)
        assert done is not None
        assert done.status == JobStatus.SUCCESS
        assert done.run_db_id == 7
        assert done.log_path == "/tmp/run.log"

    def test_failed_stage_marked_failed(self, tmp_path):
        from eda_agent.queue.worker import _execute_job

        store = make_store(tmp_path)
        job = _submit(store)
        store.claim_pending_job()

        fake_result = {
            "run_id": None,
            "status": "failed",
            "log_path": None,
            "error": "make exit code 1",
        }
        with patch("eda_agent.agent.tools._run_eda_stage", return_value=fake_result):
            _execute_job(job, store)

        done = store.get_job(job.job_id)
        assert done is not None
        assert done.status == JobStatus.FAILED

    def test_exception_marks_job_failed(self, tmp_path):
        from eda_agent.queue.worker import _execute_job

        store = make_store(tmp_path)
        job = _submit(store)
        store.claim_pending_job()

        with patch(
            "eda_agent.agent.tools._run_eda_stage", side_effect=RuntimeError("DB down")
        ):
            _execute_job(job, store)

        done = store.get_job(job.job_id)
        assert done is not None
        assert done.status == JobStatus.FAILED
        assert "DB down" in done.error_message


# ---------------------------------------------------------------------------
# Worker – run_worker (short idle exit)
# ---------------------------------------------------------------------------


class TestRunWorker:
    def test_exits_on_idle_timeout(self, tmp_path):
        """Worker should exit quickly when max_idle_seconds is set and queue is empty."""
        from eda_agent.queue.worker import run_worker

        with patch("eda_agent.queue.worker._write_pid_file"), patch(
            "eda_agent.queue.worker._remove_pid_file"
        ):
            # max_idle_seconds=0.1 → exits after 0.1 s of idleness
            run_worker(poll_interval=0.05, max_idle_seconds=0.1, db_path=tmp_path / "w.db")
        # If we reach here the worker exited cleanly

    def test_processes_one_job(self, tmp_path):
        db_path = tmp_path / "w.db"
        store = JobStore(db_path=db_path)
        job = _submit(store)

        fake_result = {"run_id": 5, "status": "success", "log_path": None, "error": ""}

        from eda_agent.queue.worker import run_worker

        with patch("eda_agent.agent.tools._run_eda_stage", return_value=fake_result), patch(
            "eda_agent.queue.worker._write_pid_file"
        ), patch("eda_agent.queue.worker._remove_pid_file"):
            run_worker(poll_interval=0.05, max_idle_seconds=0.2, db_path=db_path)

        done = store.get_job(job.job_id)
        assert done is not None
        assert done.status == JobStatus.SUCCESS


# ---------------------------------------------------------------------------
# CLI – submit command
# ---------------------------------------------------------------------------


def _run_cli_cmd(argv: list[str]) -> tuple[str, str, int]:
    """Run cli.main() with the given argv; return (stdout, stderr, exit_code)."""
    from eda_agent.cli import main

    out = io.StringIO()
    err = io.StringIO()
    exit_code = 0
    with patch("sys.argv", ["eda-agent"] + argv):
        with patch("sys.stdout", out), patch("sys.stderr", err):
            try:
                main()
            except SystemExit as exc:
                exit_code = int(exc.code) if exc.code is not None else 0
    return out.getvalue(), err.getvalue(), exit_code


class TestCLIJobCommands:
    def test_submit_creates_job(self, tmp_path):
        cfg = tmp_path / "config.mk"
        cfg.write_text("DESIGN_NAME=aes\n")
        with patch("eda_agent.queue.store._DEFAULT_DB_PATH", tmp_path / "j.db"), patch(
            "eda_agent.cli._ensure_worker"
        ):
            out, err, code = _run_cli_cmd(
                [
                    "submit",
                    "--stage", "synth",
                    "--design", "aes",
                    "--config", str(cfg),
                    "--pdk", "sky130hd",
                    "--no-worker",
                ]
            )
        assert code == 0
        assert "Job submitted" in out
        assert "aes" in out
        assert "synth" in out

    def test_list_empty(self, tmp_path):
        with patch("eda_agent.queue.store._DEFAULT_DB_PATH", tmp_path / "j.db"):
            out, err, code = _run_cli_cmd(["list"])
        assert code == 0
        assert "No jobs found" in out

    def test_list_shows_job(self, tmp_path):
        db_path = tmp_path / "j.db"
        store = JobStore(db_path=db_path)
        _submit(store, stage="route")

        with patch("eda_agent.queue.store._DEFAULT_DB_PATH", db_path):
            out, err, code = _run_cli_cmd(["list"])
        assert code == 0
        assert "route" in out

    def test_status_not_found(self, tmp_path):
        with patch("eda_agent.queue.store._DEFAULT_DB_PATH", tmp_path / "j.db"):
            out, err, code = _run_cli_cmd(["status", "no-such-id"])
        assert code != 0
        assert "not found" in err

    def test_status_found(self, tmp_path):
        db_path = tmp_path / "j.db"
        store = JobStore(db_path=db_path)
        job = _submit(store, stage="cts")

        with patch("eda_agent.queue.store._DEFAULT_DB_PATH", db_path):
            out, err, code = _run_cli_cmd(["status", job.job_id])
        assert code == 0
        assert job.job_id in out
        assert "cts" in out

    def test_cancel_pending(self, tmp_path):
        db_path = tmp_path / "j.db"
        store = JobStore(db_path=db_path)
        job = _submit(store)

        with patch("eda_agent.queue.store._DEFAULT_DB_PATH", db_path):
            out, err, code = _run_cli_cmd(["cancel", job.job_id])
        assert code == 0
        assert "cancelled" in out.lower()

        updated = store.get_job(job.job_id)
        assert updated is not None
        assert updated.status == JobStatus.CANCELLED

    def test_cancel_not_found(self, tmp_path):
        with patch("eda_agent.queue.store._DEFAULT_DB_PATH", tmp_path / "j.db"):
            out, err, code = _run_cli_cmd(["cancel", "ghost"])
        assert code != 0

    def test_unknown_list_status_exits(self, tmp_path):
        with patch("eda_agent.queue.store._DEFAULT_DB_PATH", tmp_path / "j.db"):
            out, err, code = _run_cli_cmd(["list", "--status", "bogus"])
        assert code != 0
        assert "unknown status" in err.lower()

    def test_submit_with_params(self, tmp_path):
        db_path = tmp_path / "j.db"
        cfg = tmp_path / "cfg.mk"
        cfg.write_text("DESIGN_NAME=aes\n")
        with patch("eda_agent.queue.store._DEFAULT_DB_PATH", db_path), patch(
            "eda_agent.cli._ensure_worker"
        ):
            out, err, code = _run_cli_cmd(
                [
                    "submit",
                    "--stage", "route",
                    "--design", "aes",
                    "--config", str(cfg),
                    "--param", "CORE_UTILIZATION=40",
                    "--param", "CLOCK_PERIOD=1.5",
                    "--no-worker",
                ]
            )
        assert code == 0
        # Verify params were stored in the DB
        store = JobStore(db_path=db_path)
        jobs = store.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].params == {"CORE_UTILIZATION": "40", "CLOCK_PERIOD": "1.5"}


# ---------------------------------------------------------------------------
# CLI – REPL still works (backward compatibility)
# ---------------------------------------------------------------------------


class TestCLIReplBackwardCompat:
    def test_no_args_launches_repl(self):
        """main() with no argv must call cli_repl(), not crash."""
        with patch("sys.argv", ["eda-agent"]), patch(
            "eda_agent.cli.cli_repl"
        ) as mock_repl:
            from eda_agent.cli import main

            main()
            mock_repl.assert_called_once()

    def test_repl_exit_command(self):
        """Existing REPL test: exit command prints Goodbye."""
        from eda_agent.cli import cli_repl

        captured = io.StringIO()
        inputs = iter(["exit"])
        with patch("builtins.input", side_effect=inputs), patch("sys.stdout", captured):
            cli_repl()
        assert "Goodbye" in captured.getvalue()
