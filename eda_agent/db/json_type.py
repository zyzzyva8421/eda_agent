"""Dialect-agnostic JSON column type.

On PostgreSQL >= 9.4 the native ``JSONB`` type is used for its binary storage
and indexing advantages. On older PostgreSQL versions (for example 9.2/9.3)
and all other dialects, standard ``JSON`` is used for compatibility.

Usage in ORM models and migration scripts::

    from eda_agent.db.json_type import JSON_OR_JSONB

    class MyModel(Base):
        data: Mapped[dict] = mapped_column(JSON_OR_JSONB, nullable=False, default=dict)
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB as _PG_JSONB


def _postgres_supports_jsonb(dialect: sa.engine.Dialect) -> bool:
    """Return ``True`` when PostgreSQL dialect version supports JSONB."""
    if dialect.name != "postgresql":
        return False
    ver_info = getattr(dialect, "server_version_info", None)
    if isinstance(ver_info, tuple) and len(ver_info) >= 2:
        return (int(ver_info[0]), int(ver_info[1])) >= (9, 4)
    return False


class _JSONOrJSONB(sa.types.TypeDecorator):
    """Choose JSONB only when connected PostgreSQL version supports it."""

    impl = sa.JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: sa.engine.Dialect) -> sa.types.TypeEngine:
        if _postgres_supports_jsonb(dialect):
            return dialect.type_descriptor(_PG_JSONB())
        return dialect.type_descriptor(sa.JSON())


#: Use JSONB only on PostgreSQL >= 9.4, otherwise plain JSON.
JSON_OR_JSONB: sa.types.TypeEngine = _JSONOrJSONB()
