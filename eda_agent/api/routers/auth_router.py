"""Authentication router – /auth/token and /auth/register."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from eda_agent.api.auth import create_access_token, hash_password, verify_password
from eda_agent.db.session import get_db_dependency

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest, db: Session = Depends(get_db_dependency)):
    existing = db.execute(
        text("SELECT id FROM users WHERE username = :u"), {"u": req.username}
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists.",
        )
    db.execute(
        text(
            "INSERT INTO users (username, hashed_password) VALUES (:u, :h)"
        ),
        {"u": req.username, "h": hash_password(req.password)},
    )
    db.commit()
    return {"message": f"User '{req.username}' created."}


@router.post("/token", response_model=TokenResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db_dependency),
):
    row = db.execute(
        text(
            "SELECT id, username, hashed_password, is_active "
            "FROM users WHERE username = :u"
        ),
        {"u": form_data.username},
    ).mappings().first()

    if row is None or not verify_password(form_data.password, row["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
        )
    if not row["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User is disabled."
        )

    token = create_access_token({"sub": row["username"]})
    return TokenResponse(access_token=token)
