"""Database initialization routines and interrupted job recovery (P5-12, P5-12b)."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select, update

from src.core.contracts.enums import RoleName
from src.core.db.models import Document, Role, User
from src.core.db.session import SessionLocal
from src.core.security import hash_password


def run_migrations() -> None:
    """Apply Alembic migrations to head."""
    root_dir = Path(__file__).resolve().parents[3]
    alembic_ini_path = root_dir / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option(
        "script_location", str(root_dir / "src" / "core" / "db" / "migrations")
    )
    command.upgrade(alembic_cfg, "head")


def init_db() -> None:
    """Initialize database, create initial admin, and recover interrupted documents."""
    run_migrations()

    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD")
    if not admin_password:
        raise RuntimeError("ADMIN_PASSWORD environment variable must be set.")

    with SessionLocal() as session:
        stmt_role = select(Role).where(Role.name == RoleName.ADMIN.value)
        admin_role = session.scalars(stmt_role).first()

        assert (
            admin_role is not None
        ), "Role 'admin' not found in database. Ensure migrations ran successfully."

        admin_role_id = admin_role.id

        stmt_user = select(User).where(User.username == admin_username)
        existing_admin = session.scalars(stmt_user).first()
        if existing_admin is None:
            new_admin = User(
                username=admin_username,
                hashed_password=hash_password(admin_password),
                role_id=admin_role_id,
            )
            session.add(new_admin)

        # P5-12b : Transition vers 'failed' pour les statuts inachevés
        stmt_recover = (
            update(Document)
            .where(Document.status.in_(["received", "extracting", "chunked"]))
            .values(
                status="failed",
                error="interrupted",
            )
        )
        session.execute(stmt_recover)

        session.commit()


if __name__ == "__main__":
    init_db()
