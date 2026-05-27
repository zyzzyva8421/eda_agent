"""Self-diagnostic helpers used by the ``eda-agent doctor`` subcommand.

The goal of this module is to give new users (or anyone hitting a broken
install) a single command that surfaces *all* the common setup problems
at once instead of dribbling them out as random tracebacks the first
time the REPL tries to talk to the LLM, the DB, or the ORFS tree.

Each individual check returns a :class:`CheckResult` and is independent
of the others so a failure in one (e.g. no PostgreSQL) does not prevent
the rest from running.  The module deliberately has no hard dependency
on optional services — every external call is wrapped in ``try/except``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Callable

from eda_agent.console import style

# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

# Severity levels, ordered from least to most serious.
OK = "ok"
WARN = "warn"
FAIL = "fail"

_SEVERITY_ORDER = {OK: 0, WARN: 1, FAIL: 2}


@dataclass
class CheckResult:
    """Outcome of a single diagnostic check.

    Attributes
    ----------
    name:
        Short label printed in the checklist (e.g. ``"MiniMax API key"``).
    status:
        One of :data:`OK`, :data:`WARN`, :data:`FAIL`.
    detail:
        One-line explanation shown after the status icon.
    hint:
        Optional remediation hint (printed indented on the next line).
    """

    name: str
    status: str
    detail: str = ""
    hint: str = ""

    @property
    def is_failure(self) -> bool:
        return self.status == FAIL


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_env_file(cwd: Path | None = None) -> CheckResult:
    """Report whether a ``.env`` file is discoverable in the CWD."""
    cwd = cwd or Path.cwd()
    env_path = cwd / ".env"
    example = cwd / ".env.example"
    if env_path.exists():
        return CheckResult(".env file", OK, f"found at {env_path}")
    if example.exists():
        return CheckResult(
            ".env file",
            WARN,
            "missing; values fall back to defaults",
            hint=f"cp {example} {env_path} && $EDITOR {env_path}",
        )
    return CheckResult(
        ".env file",
        WARN,
        "missing and no .env.example next to it",
        hint="create a .env in the project root with MINIMAX_API_KEY, POSTGRES_*, ORFS_ROOT",
    )


def check_minimax_key() -> CheckResult:
    """Verify that a MiniMax API key is configured."""
    try:
        from eda_agent.config import settings
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "MiniMax API key",
            FAIL,
            f"config failed to load: {exc}",
            hint="check your .env for syntax errors",
        )
    if not settings.minimax_api_key:
        return CheckResult(
            "MiniMax API key",
            FAIL,
            "MINIMAX_API_KEY is empty",
            hint="set MINIMAX_API_KEY=<your-key> in .env (see .env.example)",
        )
    if not settings.minimax_group_id:
        return CheckResult(
            "MiniMax API key",
            WARN,
            "MINIMAX_API_KEY set but MINIMAX_GROUP_ID is empty",
            hint="some MiniMax endpoints require the group id; set MINIMAX_GROUP_ID in .env",
        )
    return CheckResult(
        "MiniMax API key",
        OK,
        f"key set (model={settings.minimax_model})",
    )


def check_postgres() -> CheckResult:
    """Try to open a real connection to the configured PostgreSQL DSN."""
    try:
        from sqlalchemy import text  # local import so the check is cheap on import

        from eda_agent.config import settings
        from eda_agent.db.session import SessionLocal
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "PostgreSQL",
            FAIL,
            f"DB layer unavailable: {exc}",
            hint="`pip install -e '.[dev]'` to install database extras",
        )

    dsn_summary = (
        f"{settings.postgres_user}@{settings.postgres_host}:"
        f"{settings.postgres_port}/{settings.postgres_db}"
    )
    try:
        with SessionLocal() as sess:
            sess.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "PostgreSQL",
            FAIL,
            f"cannot connect to {dsn_summary}: {type(exc).__name__}",
            hint=(
                "is the database up?  `docker compose up -d` (see README), "
                "or set POSTGRES_HOST/PORT/USER/PASSWORD/DB in .env"
            ),
        )
    return CheckResult("PostgreSQL", OK, f"connected to {dsn_summary}")


def check_orfs_root() -> CheckResult:
    """Verify that the configured ORFS tree exists and looks plausible."""
    try:
        from eda_agent.config import settings
    except Exception as exc:  # noqa: BLE001
        return CheckResult("ORFS_ROOT", FAIL, f"config unavailable: {exc}")

    root = Path(settings.orfs_root)
    if not root.exists():
        return CheckResult(
            "ORFS_ROOT",
            WARN,
            f"{root} does not exist",
            hint=(
                "clone OpenROAD-flow-scripts and set ORFS_ROOT in .env "
                "(only required for running actual EDA flows)"
            ),
        )
    # ORFS layout: $ORFS_ROOT/flow/ contains Makefile and designs/
    flow = root / "flow"
    if not (flow / "Makefile").exists():
        return CheckResult(
            "ORFS_ROOT",
            WARN,
            f"{root} exists but does not look like an ORFS checkout",
            hint=f"expected {flow}/Makefile to exist",
        )
    return CheckResult("ORFS_ROOT", OK, f"{root}")


def check_api_secret() -> CheckResult:
    """Warn when the JWT signing key is still the placeholder."""
    try:
        from eda_agent.config import settings
    except Exception:  # noqa: BLE001
        return CheckResult("API secret key", FAIL, "config unavailable")
    if settings.api_secret_key == "insecure-change-me":
        return CheckResult(
            "API secret key",
            WARN,
            "still using the insecure default value",
            hint="generate one with `python -c 'import secrets; print(secrets.token_hex(32))'`",
        )
    if len(settings.api_secret_key) < 32:
        return CheckResult(
            "API secret key",
            WARN,
            f"API_SECRET_KEY is only {len(settings.api_secret_key)} chars (recommend >= 32)",
        )
    return CheckResult("API secret key", OK, "configured")


def check_parquet_archive() -> CheckResult:
    """Check that the Parquet archive directory is writable (or creatable)."""
    try:
        from eda_agent.config import settings
    except Exception:  # noqa: BLE001
        return CheckResult("Parquet archive dir", FAIL, "config unavailable")

    target = Path(settings.parquet_archive_dir)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return CheckResult(
            "Parquet archive dir",
            WARN,
            f"cannot create {target}: permission denied",
            hint=(
                "set PARQUET_ARCHIVE_DIR in .env to a writable path "
                "(only used for long-term run archival)"
            ),
        )
    except OSError as exc:
        return CheckResult(
            "Parquet archive dir",
            WARN,
            f"cannot create {target}: {exc}",
        )
    if not os.access(target, os.W_OK):
        return CheckResult(
            "Parquet archive dir",
            WARN,
            f"{target} is not writable by current user",
        )
    return CheckResult("Parquet archive dir", OK, f"{target}")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


# Order matters: critical checks first so users see blocking issues before
# best-effort warnings.
_DEFAULT_CHECKS: tuple[Callable[[], CheckResult], ...] = (
    check_env_file,
    check_minimax_key,
    check_postgres,
    check_orfs_root,
    check_api_secret,
    check_parquet_archive,
)


def run_checks(
    checks: tuple[Callable[[], CheckResult], ...] = _DEFAULT_CHECKS,
) -> list[CheckResult]:
    """Run *checks* sequentially and return the collected results."""
    results: list[CheckResult] = []
    for fn in checks:
        try:
            results.append(fn())
        except Exception as exc:  # noqa: BLE001 -- doctor must never crash
            results.append(
                CheckResult(
                    name=getattr(fn, "__name__", "check"),
                    status=FAIL,
                    detail=f"check itself raised: {type(exc).__name__}: {exc}",
                )
            )
    return results


def format_result(result: CheckResult, *, stream: IO[str] | None = None) -> str:
    """Render a single :class:`CheckResult` for terminal output."""
    icon_styles = {
        OK: ("✓", ("green", "bold")),
        WARN: ("!", ("yellow", "bold")),
        FAIL: ("✗", ("red", "bold")),
    }
    icon, colour = icon_styles.get(result.status, ("?", ("dim",)))
    icon_str = style(icon, *colour, stream=stream)
    detail = f" — {result.detail}" if result.detail else ""
    line = f"  {icon_str} {result.name}{detail}"
    if result.hint and result.status != OK:
        line += "\n      " + style(f"hint: {result.hint}", "dim", stream=stream)
    return line


def render_report(results: list[CheckResult], *, stream: IO[str] | None = None) -> str:
    """Render the full diagnostic report (header + per-check + summary)."""
    header = style("EDA Agent — environment check", "bold", stream=stream)
    body_lines = [format_result(r, stream=stream) for r in results]
    worst = worst_status(results)
    if worst == FAIL:
        summary = style(
            f"\n{count(results, FAIL)} blocking issue(s) found.  See hints above.",
            "red",
            "bold",
            stream=stream,
        )
    elif worst == WARN:
        summary = style(
            f"\nAll critical checks passed, but {count(results, WARN)} warning(s) remain.",
            "yellow",
            stream=stream,
        )
    else:
        summary = style("\nAll checks passed.  Have fun!", "green", "bold", stream=stream)
    return "\n".join([header, *body_lines, summary])


def worst_status(results: list[CheckResult]) -> str:
    """Return the highest-severity status seen in *results* (OK if empty)."""
    return max((r.status for r in results), key=lambda s: _SEVERITY_ORDER.get(s, 0), default=OK)


def count(results: list[CheckResult], status: str) -> int:
    """Return the number of results with the given *status*."""
    return sum(1 for r in results if r.status == status)
