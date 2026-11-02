"""Core model registry. All tenant references use composite foreign keys."""

import uuid
from datetime import UTC, datetime

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, UniqueConstraint, func
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.extensions import db


def now():
    return datetime.now(UTC)


class Record:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), default=now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), default=now, onupdate=now, server_default=func.now()
    )
    version: Mapped[int] = mapped_column(default=1, server_default="1")

    @declared_attr.directive
    def __mapper_args__(cls):
        return {"version_id_col": cls.version}


class Owned(Record):
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)

    @declared_attr.directive
    def __table_args__(cls):
        return (UniqueConstraint("organization_id", "id"),)


class Organization(Record, db.Model):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(db.String(120))
    slug: Mapped[str] = mapped_column(db.String(80), unique=True)
    status: Mapped[str] = mapped_column(db.String(20), default="active", server_default="active")
    trace_revision: Mapped[int] = mapped_column(db.BigInteger, default=0, server_default="0")
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (CheckConstraint("trace_revision >= 0", name="trace_revision"),)


class User(UserMixin, Record, db.Model):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(db.String(254))
    display_name: Mapped[str] = mapped_column(db.String(120))
    password_hash: Mapped[str] = mapped_column(db.Text)
    active: Mapped[bool] = mapped_column(default=True, server_default=db.true())
    auth_version: Mapped[int] = mapped_column(default=1, server_default="1")
    email_verified_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (db.Index("uq_users_email_lower", func.lower(email), unique=True),)

    @property
    def is_active(self):
        return self.active and self.archived_at is None


class Membership(Owned, db.Model):
    __tablename__ = "memberships"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(db.String(20), default="active", server_default="active")
    joined_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), default=now, server_default=func.now()
    )
    # Partner-restricted memberships are denied internal catalog access.
    partner_id: Mapped[uuid.UUID | None]
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    user: Mapped[User] = relationship()
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "user_id"),
        ForeignKeyConstraint(
            ["organization_id", "partner_id"], ["partners.organization_id", "partners.id"]
        ),
    )


class Role(Owned, db.Model):
    __tablename__ = "roles"
    code: Mapped[str] = mapped_column(db.String(50))
    name: Mapped[str] = mapped_column(db.String(80))
    protected: Mapped[bool] = mapped_column(default=False, server_default=db.false())
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "code"),
    )


class Permission(Record, db.Model):
    __tablename__ = "permissions"
    code: Mapped[str] = mapped_column(db.String(100), unique=True)
    description: Mapped[str] = mapped_column(db.String(240))


class RolePermission(Owned, db.Model):
    __tablename__ = "role_permissions"
    role_id: Mapped[uuid.UUID]
    permission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("permissions.id"))
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("role_id", "permission_id"),
        ForeignKeyConstraint(["organization_id", "role_id"], ["roles.organization_id", "roles.id"]),
    )


class MembershipRole(Owned, db.Model):
    __tablename__ = "membership_roles"
    membership_id: Mapped[uuid.UUID]
    role_id: Mapped[uuid.UUID]
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("membership_id", "role_id"),
        ForeignKeyConstraint(
            ["organization_id", "membership_id"], ["memberships.organization_id", "memberships.id"]
        ),
        ForeignKeyConstraint(["organization_id", "role_id"], ["roles.organization_id", "roles.id"]),
    )


class AuthSession(Record, db.Model):
    __tablename__ = "auth_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_digest: Mapped[str] = mapped_column(db.String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), default=now, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    auth_version: Mapped[int]
    last_mfa_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))


class Item(Owned, db.Model):
    __tablename__ = "items"
    code: Mapped[str] = mapped_column(db.String(40))
    name: Mapped[str] = mapped_column(db.String(160))
    kind: Mapped[str] = mapped_column(db.String(20))
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "code"),
        CheckConstraint("kind IN ('component', 'finished', 'packaging')", name="kind"),
    )


class UnitsOfMeasure(Owned, db.Model):
    __tablename__ = "units_of_measure"
    code: Mapped[str] = mapped_column(db.String(20))
    name: Mapped[str] = mapped_column(db.String(80))
    dimension: Mapped[str] = mapped_column(db.String(30))
    decimal_places: Mapped[int] = mapped_column(db.SmallInteger)
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "code"),
        CheckConstraint("decimal_places BETWEEN 0 AND 6", name="decimal_places"),
    )


class ItemVariant(Owned, db.Model):
    __tablename__ = "item_variants"
    sku: Mapped[str] = mapped_column(db.String(80))
    revision: Mapped[str] = mapped_column(db.String(40))
    description: Mapped[str | None] = mapped_column(db.Text)
    item_id: Mapped[uuid.UUID] = mapped_column()
    base_unit_id: Mapped[uuid.UUID] = mapped_column()
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    item: Mapped[Item] = relationship(foreign_keys=[item_id], viewonly=True)
    base_unit: Mapped[UnitsOfMeasure] = relationship(foreign_keys=[base_unit_id], viewonly=True)
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "sku"),
        ForeignKeyConstraint(["organization_id", "item_id"], ["items.organization_id", "items.id"]),
        ForeignKeyConstraint(
            ["organization_id", "base_unit_id"],
            ["units_of_measure.organization_id", "units_of_measure.id"],
        ),
    )


# Import implemented extensions after the common model base is defined.
from app.models import evidence, master, operations, quality, recall, security  # noqa: E402,F401
from app.models.account_tokens import EmailVerificationToken, PasswordResetToken  # noqa: E402,F401
from app.models.invitations import Invitation  # noqa: E402,F401
