"""Single-use account challenges; raw credentials exist only in private delivery."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models import Record


class PasswordResetToken(Record, db.Model):
    __tablename__ = "password_reset_tokens"
    token_digest: Mapped[str] = mapped_column(db.String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)


class EmailVerificationToken(Record, db.Model):
    __tablename__ = "email_verification_tokens"
    token_digest: Mapped[str] = mapped_column(db.String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
