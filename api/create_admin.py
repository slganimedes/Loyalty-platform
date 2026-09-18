"""Provision an admin without putting passwords in command history."""

import argparse
from getpass import getpass

from app.db import SessionLocal, init_db
from app.models import AdminUser, Merchant
from app.services.security import hash_password


def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--role", choices=["sme_admin", "super_admin"], default="sme_admin")
    parser.add_argument("--merchant-id")
    args = parser.parse_args()
    init_db()
    with SessionLocal() as db:
        if args.role == "sme_admin" and not db.get(Merchant, args.merchant_id or ""):
            parser.error("SME admins require an existing --merchant-id")
        if db.query(AdminUser).filter_by(username=args.username).first():
            parser.error("Username already exists")
        password = getpass("Password: ")
        if len(password.encode()) < 12 or len(password.encode()) > 72:
            parser.error("Use a password of 12 to 72 UTF-8 bytes")
        if password != getpass("Repeat password: "):
            parser.error("Passwords differ")
        db.add(
            AdminUser(
                username=args.username,
                password_hash=hash_password(password),
                role=args.role,
                merchant_id=args.merchant_id if args.role == "sme_admin" else None,
            )
        )
        db.commit()
    print("Admin created.")


if __name__ == "__main__":
    run()
