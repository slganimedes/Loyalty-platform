"""Opaque, expiring admin sessions. Ingestion deliberately has no dependency here."""

import hashlib
import secrets
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..db import get_db
from ..services.security import verify_password

router = APIRouter(prefix="/api/v1", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> models.AdminUser:
    session = (
        db.get(models.AdminSession, token_hash(credentials.credentials)) if credentials else None
    )
    if not session or session.expires_at <= models._now():
        raise HTTPException(
            401, "Invalid or expired session", headers={"WWW-Authenticate": "Bearer"}
        )
    user = db.get(models.AdminUser, session.user_id)
    if not user:
        raise HTTPException(401, "Invalid session")
    return user


def super_admin(user: models.AdminUser = Depends(current_user)) -> models.AdminUser:
    if user.role != "super_admin":
        raise HTTPException(403, "Super admin required")
    return user


def authorize_merchant(merchant_id: str, user: models.AdminUser, db: Session) -> models.Merchant:
    if user.role != "super_admin" and user.merchant_id != merchant_id:
        raise HTTPException(403, "Merchant access denied")
    merchant = db.get(models.Merchant, merchant_id)
    if not merchant:
        raise HTTPException(404, "Merchant not found")
    return merchant


def merchant_access(
    merchant_id: str, user: models.AdminUser = Depends(current_user), db: Session = Depends(get_db)
) -> models.Merchant:
    return authorize_merchant(merchant_id, user, db)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=72)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    username: str
    role: str
    merchant_id: str | None
    language: str


class UserUpdate(BaseModel):
    language: Literal["es", "en"]


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)) -> dict:
    user = db.query(models.AdminUser).filter_by(username=body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid username or password")
    token = secrets.token_urlsafe(32)
    db.add(
        models.AdminSession(
            token_hash=token_hash(token),
            user_id=user.id,
            expires_at=models._now() + timedelta(hours=settings.session_hours),
        )
    )
    db.commit()
    return {"access_token": token, "token_type": "bearer", "user": UserOut.model_validate(user)}


@router.get("/users/me", response_model=UserOut)
def me(user: models.AdminUser = Depends(current_user)) -> models.AdminUser:
    return user


@router.patch("/users/me", response_model=UserOut)
def update_me(
    body: UserUpdate, user: models.AdminUser = Depends(current_user), db: Session = Depends(get_db)
) -> models.AdminUser:
    user.language = body.language
    db.commit()
    return user


@router.post("/auth/logout")
def logout(
    user: models.AdminUser = Depends(current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> dict:
    db.query(models.AdminSession).filter_by(token_hash=token_hash(credentials.credentials)).delete()
    db.commit()
    return {"status": "ok"}
