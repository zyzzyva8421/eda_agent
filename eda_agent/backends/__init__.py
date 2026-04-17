"""backends sub-package – EDA tool abstraction layer.

Usage
-----
    from eda_agent.backends import get_backend, list_backends

    backend = get_backend("orfs")
    result  = backend.run_stage("route", design, params)
"""

from __future__ import annotations

from eda_agent.backends.base import (
    AbstractEDABackend,
    DesignSpec,
    ReportFile,
    RunResult,
    StageStatus,
)
from eda_agent.backends.icc2 import ICC2Backend
from eda_agent.backends.innovus import InnovusBackend
from eda_agent.backends.orfs import ORFSBackend

_REGISTRY: dict[str, AbstractEDABackend] = {
    "orfs": ORFSBackend(),
    "innovus": InnovusBackend(),
    "icc2": ICC2Backend(),
}


def get_backend(name: str) -> AbstractEDABackend:
    """Return the backend instance for *name*.

    Raises
    ------
    KeyError
        If no backend with that name is registered.
    """
    try:
        return _REGISTRY[name.lower()]
    except KeyError:
        available = list(_REGISTRY.keys())
        raise KeyError(
            f"Unknown backend '{name}'. Available backends: {available}"
        ) from None


def list_backends() -> list[str]:
    """Return sorted list of registered backend names."""
    return sorted(_REGISTRY.keys())


def register_backend(backend: AbstractEDABackend) -> None:
    """Register a custom backend instance at runtime.

    This is the extension point for your custom PR tool or any future backend.
    Call this before the application starts serving requests.
    """
    _REGISTRY[backend.name.lower()] = backend


__all__ = [
    "AbstractEDABackend",
    "DesignSpec",
    "ReportFile",
    "RunResult",
    "StageStatus",
    "ORFSBackend",
    "InnovusBackend",
    "ICC2Backend",
    "get_backend",
    "list_backends",
    "register_backend",
]
