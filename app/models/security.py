"""Encrypted MFA factors and immutable, company-scoped audit metadata."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, UniqueConstraint, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models import Owned, Record


class MfaFactor(Record, db.Model):
    __tablename__ = "mfa_factors"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    kind: Mapped[str] = mapped_column(db.String(20), default="totp", server_default="totp")
    secret_ciphertext: Mapped[str] = mapped_column(db.Text)
    key_version: Mapped[str] = mapped_column(db.String(20))
    recovery_code_hashes: Mapped[list] = mapped_column(JSONB, default=list)
    last_used_step: Mapped[int | None] = mapped_column(db.BigInteger)
    verified_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (CheckConstraint("kind = 'totp'", name="kind"),)


class AuditEvent(Owned, db.Model):
    __tablename__ = "audit_events"
    action: Mapped[str] = mapped_column(db.String(100))
    entity_kind: Mapped[str] = mapped_column(db.String(60))
    entity_id: Mapped[uuid.UUID | None] = mapped_column()
    safe_details: Mapped[dict] = mapped_column(JSONB, default=dict)
    correlation_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column()
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["memberships.organization_id", "memberships.id"]
        ),
    )


@event.listens_for(AuditEvent, "before_update")
@event.listens_for(AuditEvent, "before_delete")
def immutable_audit(mapper, connection, target):
    raise ValueError("Audit history cannot be edited or deleted.")
