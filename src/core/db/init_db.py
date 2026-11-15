"""Database initialization routines and interrupted job recovery (P5-12, P5-12b)."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select, update

from src.core.config import cfg
from src.core.contracts.enums import DocStatus, RoleName
from src.core.db.models import Document, Role, User
from src.core.db.session import SessionLocal
from src.core.security import hash_password


def run_migrations() -> None:
    """Apply Alembic migrations to head."""
    root_dir = Path(__file__).resolve().parents[3]
    ini = Path(os.getenv("ALEMBIC_INI", root_dir / "alembic.ini"))
    alembic_cfg = Config(str(ini))
    alembic_cfg.set_main_option(
        "script_location", str(root_dir / "src" / "core" / "db" / "migrations")
    )
    command.upgrade(alembic_cfg, "head")


def init_db() -> None:
    """Migrate, create the first admin if none exists, and recover interrupted documents."""
    run_migrations()

    with SessionLocal() as session:
        admin_role = session.scalars(select(Role).where(Role.name == RoleName.ADMIN.value)).first()
        if admin_role is None:
            raise RuntimeError("Role 'admin' not found: the migration did not seed the roles.")

        has_admin = session.scalars(
            select(User.id).where(User.role_id == admin_role.id).limit(1)
        ).first()
        if has_admin is None:
            session.add(
                User(
                    username=cfg.ADMIN_USERNAME,
                    hashed_password=hash_password(cfg.ADMIN_PASSWORD.get_secret_value()),
                    full_name="Administrateur",
                    role_id=admin_role.id,
                )
            )

        # P5-12b : un document interrompu en cours d'ingestion passe en 'failed'.
        session.execute(
            update(Document)
            .where(
                Document.status.in_(
                    [
                        DocStatus.RECEIVED.value,
                        DocStatus.EXTRACTING.value,
                        DocStatus.CHUNKED.value,
                    ]
                )
            )
            .values(status=DocStatus.FAILED.value, error="interrupted")
        )
        session.commit()


if __name__ == "__main__":
    init_db()
