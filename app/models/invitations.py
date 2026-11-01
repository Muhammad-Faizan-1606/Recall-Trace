import uuid
from datetime import datetime

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models import Owned


class Invitation(Owned, db.Model):
    __tablename__ = "invitations"
    email: Mapped[str] = mapped_column(db.String(254))
    token_digest: Mapped[str] = mapped_column(db.String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    invited_by_id: Mapped[uuid.UUID]
    role_id: Mapped[uuid.UUID]
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "invited_by_id"], ["memberships.organization_id", "memberships.id"]
        ),
        ForeignKeyConstraint(["organization_id", "role_id"], ["roles.organization_id", "roles.id"]),
    )
