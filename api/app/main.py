"""FastAPI entrypoint for the SME Loyalty Platform."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .db import init_db
from .routers import auth, customers, merchants, settings_wallet, transactions, wallet_passes

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    from .db import SessionLocal
    from .models import AdminUser
    from .services.security import hash_password

    if settings.bootstrap_admin_password:
        with SessionLocal() as db:
            if (
                not db.query(AdminUser)
                .filter_by(username=settings.bootstrap_admin_username)
                .first()
            ):
                db.add(
                    AdminUser(
                        username=settings.bootstrap_admin_username,
                        password_hash=hash_password(settings.bootstrap_admin_password),
                        role="super_admin",
                    )
                )
                db.commit()
    yield


app = FastAPI(
    title="SME Loyalty Platform API",
    version="0.1.0",
    description="Wallet-based loyalty for Getnet merchants (MVP / pilot).",
    lifespan=lifespan,
)

# Admin origins are explicit; wallet callbacks and ingestion remain public.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.public_admin_url, "http://localhost:5173", "http://localhost:8080"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
def health() -> dict:
    return {"status": "ok"}


app.include_router(merchants.router)
app.include_router(customers.router)
app.include_router(transactions.router)
app.include_router(settings_wallet.router)
app.include_router(auth.router)
app.include_router(wallet_passes.router)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Never echo submitted credentials or accidentally supplied PAN in errors.
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()
            ]
        },
    )
