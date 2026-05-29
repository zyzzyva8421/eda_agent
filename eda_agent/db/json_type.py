"""Dialect-agnostic JSON column type.

On PostgreSQL the native ``JSONB`` type is used for its binary storage and
indexing advantages.  On all other dialects (MySQL, SQLite, …) the standard
``JSON`` type is used instead so that migrations and runtime queries work
without any PostgreSQL-specific features.

Usage in ORM models and migration scripts::

    from eda_agent.db.json_type import JSON_OR_JSONB

    class MyModel(Base):
        data: Mapped[dict] = mapped_column(JSON_OR_JSONB, nullable=False, default=dict)
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB as _PG_JSONB

#: Use JSONB on PostgreSQL, plain JSON on every other dialect.
JSON_OR_JSONB: sa.types.TypeEngine = sa.JSON().with_variant(_PG_JSONB(), "postgresql")
