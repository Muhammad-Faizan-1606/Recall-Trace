"""Company-scoped facilities, partner directory, catalog taxonomy and lot identity."""

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models import Owned


def tenant_fk(field, table):
    return ForeignKeyConstraint(
        ["organization_id", field], [f"{table}.organization_id", f"{table}.id"]
    )


def identity(*unique):
    return (UniqueConstraint("organization_id", "id"), UniqueConstraint("organization_id", *unique))


class Site(Owned, db.Model):
    __tablename__ = "sites"
    code: Mapped[str] = mapped_column(db.String(40))
    name: Mapped[str] = mapped_column(db.String(120))
    address_text: Mapped[str] = mapped_column(db.Text)
    country_code: Mapped[str] = mapped_column(db.String(2))
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        *identity("code"),
        CheckConstraint("length(country_code) = 2", name="country_code"),
    )


class Partner(Owned, db.Model):
    __tablename__ = "partners"
    code: Mapped[str] = mapped_column(db.String(40))
    name: Mapped[str] = mapped_column(db.String(160))
    status: Mapped[str] = mapped_column(db.String(20), default="active", server_default="active")
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        *identity("code"),
        CheckConstraint("status IN ('active', 'inactive')", name="status"),
    )


class PartnerRoleAssignment(Owned, db.Model):
    __tablename__ = "partner_role_assignments"
    role_code: Mapped[str] = mapped_column(db.String(20))
    partner_id: Mapped[uuid.UUID] = mapped_column()
    __table_args__ = (
        *identity("partner_id", "role_code"),
        tenant_fk("partner_id", "partners"),
        CheckConstraint("role_code IN ('supplier', 'customer', 'distributor')", name="role_code"),
    )


class PartnerContact(Owned, db.Model):
    __tablename__ = "partner_contacts"
    name: Mapped[str] = mapped_column(db.String(120))
    email: Mapped[str | None] = mapped_column(db.String(254))
    phone: Mapped[str | None] = mapped_column(db.String(40))
    purpose: Mapped[str] = mapped_column(db.String(80))
    partner_id: Mapped[uuid.UUID] = mapped_column()
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        tenant_fk("partner_id", "partners"),
        CheckConstraint(
            "coalesce(length(trim(email)), 0) > 0 OR coalesce(length(trim(phone)), 0) > 0",
            name="contact_channel",
        ),
    )


class PartnerAddress(Owned, db.Model):
    __tablename__ = "partner_addresses"
    label: Mapped[str] = mapped_column(db.String(80))
    address_text: Mapped[str] = mapped_column(db.Text)
    country_code: Mapped[str] = mapped_column(db.String(2))
    partner_id: Mapped[uuid.UUID] = mapped_column()
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        tenant_fk("partner_id", "partners"),
        CheckConstraint("length(country_code) = 2", name="country_code"),
    )


class ItemCategory(Owned, db.Model):
    __tablename__ = "item_categories"
    code: Mapped[str] = mapped_column(db.String(40))
    name: Mapped[str] = mapped_column(db.String(100))
    parent_id: Mapped[uuid.UUID | None] = mapped_column()
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        *identity("code"),
        tenant_fk("parent_id", "item_categories"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_self_parent"),
    )


class ItemCategoryAssignment(Owned, db.Model):
    __tablename__ = "item_category_assignments"
    item_id: Mapped[uuid.UUID] = mapped_column()
    category_id: Mapped[uuid.UUID] = mapped_column()
    __table_args__ = (
        *identity("item_id", "category_id"),
        tenant_fk("item_id", "items"),
        tenant_fk("category_id", "item_categories"),
    )


class SupplierItem(Owned, db.Model):
    __tablename__ = "supplier_items"
    supplier_sku: Mapped[str] = mapped_column(db.String(80))
    lead_time_days: Mapped[int | None] = mapped_column()
    partner_id: Mapped[uuid.UUID] = mapped_column()
    variant_id: Mapped[uuid.UUID] = mapped_column()
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        *identity("partner_id", "variant_id"),
        tenant_fk("partner_id", "partners"),
        tenant_fk("variant_id", "item_variants"),
        CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="lead_time_days"),
    )


class Warehouse(Owned, db.Model):
    __tablename__ = "warehouses"
    code: Mapped[str] = mapped_column(db.String(40))
    name: Mapped[str] = mapped_column(db.String(120))
    site_id: Mapped[uuid.UUID] = mapped_column()
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (*identity("code"), tenant_fk("site_id", "sites"))


class StorageLocation(Owned, db.Model):
    __tablename__ = "storage_locations"
    code: Mapped[str] = mapped_column(db.String(40))
    name: Mapped[str] = mapped_column(db.String(100))
    kind: Mapped[str] = mapped_column(db.String(20), default="storage", server_default="storage")
    warehouse_id: Mapped[uuid.UUID] = mapped_column()
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        *identity("warehouse_id", "code"),
        tenant_fk("warehouse_id", "warehouses"),
        CheckConstraint("kind IN ('storage', 'quarantine', 'dispatch', 'production')", name="kind"),
    )


class Lot(Owned, db.Model):
    __tablename__ = "lots"
    lot_code: Mapped[str] = mapped_column(db.String(80))
    supplier_lot_code: Mapped[str | None] = mapped_column(db.String(100))
    manufactured_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    expires_on: Mapped[date | None] = mapped_column(db.Date)
    variant_id: Mapped[uuid.UUID] = mapped_column()
    supplier_id: Mapped[uuid.UUID | None] = mapped_column()
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        *identity("lot_code"),
        tenant_fk("variant_id", "item_variants"),
        tenant_fk("supplier_id", "partners"),
        CheckConstraint(
            "manufactured_at IS NULL OR expires_on IS NULL OR expires_on >= manufactured_at::date",
            name="date_order",
        ),
    )


class Carrier(Owned, db.Model):
    __tablename__ = "carriers"
    code: Mapped[str] = mapped_column(db.String(40))
    name: Mapped[str] = mapped_column(db.String(120))
    tracking_url_template: Mapped[str | None] = mapped_column(db.Text)
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = identity("code")
