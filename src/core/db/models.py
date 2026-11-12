import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from src.core.contracts.enums import (
    AccountRequestStatus,
    DocStatus,
)
from src.core.db.base import Base


def utc_now() -> datetime:
    """Horodatage standard UTC pour toutes les entités"""
    return datetime.now(UTC)


class Role(Base):
    """
    Table: roles
    Définit les rôles du système (admin, editeur, lecteur) et la permission de recherche web.
    """

    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(32), unique=True, nullable=False, index=True)  # ex: RoleName.LECTEUR
    description = Column(Text, nullable=True)
    web_enabled = Column(Boolean, default=True, nullable=False)

    # Relations
    users = relationship("User", back_populates="role")
    document_roles = relationship(
        "DocumentRole", back_populates="role", cascade="all, delete-orphan"
    )


class User(Base):
    """
    Table: users
    Comptes utilisateurs enregistrés.
    Règle métier : l'admin ne supprime jamais un utilisateur, il désactive son compte via is_active.
    """

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(32), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)  # Hash Argon2
    full_name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relations
    role = relationship("Role", back_populates="users")
    uploaded_documents = relationship(
        "Document",
        back_populates="owner",
        foreign_keys="Document.owner_id",
        cascade="all, delete-orphan",
    )
    audit_logs = relationship("AuditLog", back_populates="user")
    conversations = relationship(
        "Conversation",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class AccountRequest(Base):
    """
    Table: account_requests
    Demandes d'inscription soumises sans jeton.
    Validées ou rejetées  exclusivement par l'administrateur.
    """

    __tablename__ = "account_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(32), nullable=False, index=True)
    hashed_password = Column(String(255), nullable=True)
    full_name = Column(String(100), nullable=False)
    status = Column(
        String(20),
        default=AccountRequestStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    decided_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at = Column(DateTime(timezone=True), nullable=True)

    # Relation vers l'administrateur ayant approuvé/rejeté
    decider = relationship("User", foreign_keys=[decided_by])


class Document(Base):
    """
    Table: documents
    Documents du corpus ou uploads privés.
    L'identifiant id est calculé via make_doc_id (SHA-256 de scope + file_bytes).
    """

    __tablename__ = "documents"

    id = Column(String(64), primary_key=True)
    title = Column(String(500), nullable=False)
    source_file = Column(String(255), nullable=False)
    source = Column(String(500), nullable=True)
    date = Column(String(100), nullable=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    status = Column(
        String(20),
        default=DocStatus.RECEIVED.value,
        nullable=False,
        index=True,
    )
    error = Column(String(500), nullable=True)
    file_hash = Column(String(64), nullable=False)
    content_hash = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relations
    owner = relationship("User", back_populates="uploaded_documents", foreign_keys=[owner_id])
    allowed_roles = relationship(
        "DocumentRole",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DocumentRole(Base):
    """
    Table: document_roles
    Association N:M entre un document et les rôles autorisés à le consulter.
    """

    __tablename__ = "document_roles"

    document_id = Column(
        String(64),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id = Column(
        Integer,
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Relations
    document = relationship("Document", back_populates="allowed_roles")
    role = relationship("Role", back_populates="document_roles")


class AuditLog(Base):
    """
    Table: audit_log
    Journalisation immuable des événements de sécurité et requêtes /ask.
    """

    __tablename__ = "audit_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    request_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )  # Nullable : tâches de fond, login inconnu
    action = Column(String(50), nullable=False, index=True)
    details = Column(JSONB, nullable=True)
    query_text = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)  # duree tot de la requ
    timestamp = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    # Relation
    user = relationship("User", back_populates="audit_logs")


class Conversation(Base):
    """
    Table: conversations
    Session de chat appartenant à un utilisateur unique.
    """

    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = Column(String(60), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False, index=True
    )

    # Relations
    user = relationship("User", back_populates="conversations")
    messages = relationship(
        "ConversationMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.position",
    )


class ConversationMessage(Base):
    """
    Table: conversation_messages
    Chaque échange question / réponse sérialisé dans la conversation.
    La disponibilité (available) de la réponse est recalculée à la volée selon l'état des documents cités.
    """

    __tablename__ = "conversation_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position = Column(Integer, nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(JSONB, nullable=False)
    cited_doc_ids = Column(JSONB, default=list, nullable=False)  # Liste distincte des doc_id cités
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("conversation_id", "position", name="uq_conversation_message_pos"),
    )

    # Relation
    conversation = relationship("Conversation", back_populates="messages")
