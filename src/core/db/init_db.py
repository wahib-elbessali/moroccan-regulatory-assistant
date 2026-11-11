import logging
from uuid import uuid4

from src.core.db.session import engine, SessionLocal, Base
from src.core.db.models import Role, User, Document
from src.core.contracts.enums import RoleName, DocStatus
from src.core.security import get_password_hash
from src.core.config import cfg

logger = logging.getLogger(__name__)


def init_database() -> None:
    """Crée les tables et initialise les données système indispensables."""
    logger.info("Création des tables PostgreSQL...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        existing_roles = {r.name: r for r in db.query(Role).all()}
        role_definitions = [
            (
                RoleName.ADMIN.value,
                "Administrateur système (gestion des comptes, rôles, audit)",
                True,
            ),
            (
                RoleName.EDITEUR.value,
                "Juriste (gestion du corpus, accès aux textes internes et publics)",
                True,
            ),
            (
                RoleName.LECTEUR.value,
                "Citoyen / Lecteur (accès aux documents publics et uploads privés)",
                True,
            ),
        ]

        for name, desc, web_active in role_definitions:
            if name not in existing_roles:
                new_role = Role(name=name, description=desc, web_enabled=web_active)
                db.add(new_role)
                logger.info("Rôle créé : %s", name)
        db.commit()

        admin_role = db.query(Role).filter_by(name=RoleName.ADMIN.value).first()
        admin_user = db.query(User).filter_by(role_id=admin_role.id).first()

        if not admin_user:
            admin_username = cfg.admin.username or "admin"
            admin_password = cfg.admin.password or "AdminPassword123!"
            root_admin = User(
                id=uuid4(),
                username=admin_username,
                hashed_password=get_password_hash(admin_password),
                full_name="System Administrator",
                is_active=True,
                role_id=admin_role.id,
            )
            db.add(root_admin)
            db.commit()
            logger.info("Administrateur racine initialisé avec succès : %s", admin_username)

        interrupted_count = (
            db.query(Document)
            .filter(
                Document.status.in_(
                    [DocStatus.RECEIVED.value, DocStatus.EXTRACTING.value, DocStatus.CHUNKED.value]
                )
            )
            .update(
                {Document.status: DocStatus.FAILED.value, Document.error: "interrupted"},
                synchronize_session=False,
            )
        )
        if interrupted_count > 0:
            db.commit()
            logger.warning(
                "%d document(s) interrompu(s) réinitialisé(s) à l'état 'failed'.", interrupted_count
            )

    except Exception as exc:
        db.rollback()
        logger.error("Erreur critique lors de l'initialisation de la base : %s", exc)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    init_database()
