"""JWT-based authentication helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.orm import Session

from eda_agent.config import settings
from eda_agent.db.session import get_db_dependency

_ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify password using SHA256 (development-friendly)."""
    # Simple SHA256 hash for development
    # In production, use proper bcrypt or argon2
    salt, stored_hash = hashed.split("$", 1) if "$" in hashed else ("", hashed)
    computed = hashlib.sha256(f"{salt}{plain}".encode()).hexdigest()
    return hmac.compare_digest(computed, stored_hash)


def hash_password(plain: str) -> str:
    """Hash password using SHA256 (development-friendly)."""
    # Simple SHA256 hash with random salt
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}{plain}".encode()).hexdigest()
    return f"{salt}${hashed}"


def create_access_token(data: dict[str, Any]) -> str:
    expire = datetime.now(tz=timezone.utc) + timedelta(
        minutes=settings.api_access_token_expire_minutes
    )
    return jwt.encode(
        {**data, "exp": expire},
        settings.api_secret_key,
        algorithm=_ALGORITHM,
    )


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db_dependency),
) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.api_secret_key, algorithms=[_ALGORITHM])
        username: str = payload.get("sub", "")
        if not username:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    row = db.execute(
        text("SELECT id, username, is_active, is_admin FROM users WHERE username = :u"),
        {"u": username},
    ).mappings().first()
    if row is None or not row["is_active"]:
        raise credentials_exception
    return dict(row)
