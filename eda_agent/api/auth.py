"""JWT-based authentication helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import text
from sqlalchemy.orm import Session

from eda_agent.config import settings
from eda_agent.db.session import get_db_dependency

_ALGORITHM = "HS256"
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


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
