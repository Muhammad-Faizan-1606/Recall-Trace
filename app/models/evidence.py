"""Private evidence, controlled communication and durable shared operations."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models import Owned, now


def owned_constraints(*references, unique=()):
    return (
        UniqueConstraint("organization_id", "id"),
        *(
            ForeignKeyConstraint(
                ["organization_id", field], [f"{table}.organization_id", f"{table}.id"]
            )
            for field, table in references
        ),
        *(UniqueConstraint("organization_id", *fields) for fields in unique),
    )


class Document(Owned, db.Model):
    __tablename__ = "documents"
    object_key: Mapped[str] = mapped_column(db.String(240))
    original_name: Mapped[str] = mapped_column(db.String(240))
    media_type: Mapped[str] = mapped_column(db.String(120))
    size_bytes: Mapped[int] = mapped_column(db.BigInteger)
    sha256: Mapped[str] = mapped_column(db.String(64))
    scan_status: Mapped[str] = mapped_column(db.String(20), default="pending")
    state: Mapped[str] = mapped_column(db.String(20), default="quarantined")
    uploaded_by_id: Mapped[uuid.UUID]
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = owned_constraints(
        ("uploaded_by_id", "memberships"), unique=(("object_key",),)
    ) + (
        CheckConstraint("size_bytes BETWEEN 1 AND 10485760", name="document_size"),
        CheckConstraint(
            "scan_status IN ('pending','clean','infected','unavailable')", name="document_scan"
        ),
        CheckConstraint(
            "state IN ('quarantined','active','source','export')", name="document_state"
        ),
    )


class Notification(Owned, db.Model):
    __tablename__ = "notifications"
    event_type: Mapped[str] = mapped_column(db.String(60))
    safe_payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    membership_id: Mapped[uuid.UUID]
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = owned_constraints(("membership_id", "memberships"))


class NotificationPreference(Owned, db.Model):
    __tablename__ = "notification_preferences"
    event_type: Mapped[str] = mapped_column(db.String(60))
    channel: Mapped[str] = mapped_column(db.String(20), default="in_app")
    enabled: Mapped[bool] = mapped_column(default=True)
    membership_id: Mapped[uuid.UUID]
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = owned_constraints(
        ("membership_id", "memberships"), unique=(("membership_id", "event_type", "channel"),)
    ) + (CheckConstraint("channel = 'in_app'", name="notification_channel"),)


class JobOutbox(Owned, db.Model):
    __tablename__ = "job_outbox"
    kind: Mapped[str] = mapped_column(db.String(60))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    deduplication_key: Mapped[str] = mapped_column(db.String(140))
    status: Mapped[str] = mapped_column(db.String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    available_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=now)
    claimed_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(db.String(80))
    created_by_id: Mapped[uuid.UUID | None]
    __table_args__ = owned_constraints(
        ("created_by_id", "memberships"), unique=(("deduplication_key",),)
    ) + (
        CheckConstraint("attempts >= 0", name="job_attempts"),
        CheckConstraint(
            "status IN ('pending','processing','completed','failed','ambiguous','cancelled')",
            name="job_status",
        ),
    )


class ImportJob(Owned, db.Model):
    __tablename__ = "import_jobs"
    kind: Mapped[str] = mapped_column(db.String(40), default="items")
    status: Mapped[str] = mapped_column(db.String(20), default="validated")
    idempotency_key: Mapped[str] = mapped_column(db.String(100))
    row_count: Mapped[int | None]
    safe_error_summary: Mapped[dict | None] = mapped_column(JSONB)
    source_document_id: Mapped[uuid.UUID]
    requested_by_id: Mapped[uuid.UUID]
    __table_args__ = owned_constraints(
        ("source_document_id", "documents"),
        ("requested_by_id", "memberships"),
        unique=(("idempotency_key",),),
    ) + (
        CheckConstraint("kind = 'items'", name="import_kind"),
        CheckConstraint("status IN ('validated','committed','cancelled')", name="import_status"),
        CheckConstraint("row_count BETWEEN 1 AND 10000", name="import_rows"),
    )


class ExportJob(Owned, db.Model):
    __tablename__ = "export_jobs"
    kind: Mapped[str] = mapped_column(db.String(40), default="items")
    filters: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(db.String(20), default="completed")
    expires_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    output_document_id: Mapped[uuid.UUID | None]
    requested_by_id: Mapped[uuid.UUID]
    __table_args__ = owned_constraints(
        ("output_document_id", "documents"), ("requested_by_id", "memberships")
    ) + (CheckConstraint("kind IN ('items','stock','case_exposure')", name="export_kind"),)


class RecallNotice(Owned, db.Model):
    __tablename__ = "recall_notices"
    revision: Mapped[int] = mapped_column(default=1)
    subject: Mapped[str] = mapped_column(db.String(160))
    body: Mapped[str] = mapped_column(db.Text)
    recipient_email: Mapped[str] = mapped_column(db.String(254))
    status: Mapped[str] = mapped_column(db.String(20), default="draft")
    approved_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    case_id: Mapped[uuid.UUID]
    contact_id: Mapped[uuid.UUID]
    trace_run_id: Mapped[uuid.UUID]
    trace_revision: Mapped[int] = mapped_column(db.BigInteger)
    approved_by_id: Mapped[uuid.UUID | None]
    created_by_id: Mapped[uuid.UUID]
    __table_args__ = owned_constraints(
        ("case_id", "recall_cases"),
        ("contact_id", "partner_contacts"),
        ("trace_run_id", "trace_runs"),
        ("approved_by_id", "memberships"),
        ("created_by_id", "memberships"),
        unique=(("case_id", "contact_id", "revision"),),
    ) + (
        CheckConstraint("revision > 0", name="notice_revision"),
        CheckConstraint(
            "status IN ('draft','approved','queued','sent','local_written','ambiguous','cancelled')",
            name="notice_status",
        ),
    )


class NoticeDelivery(Owned, db.Model):
    __tablename__ = "notice_deliveries"
    idempotency_key: Mapped[str] = mapped_column(db.String(120))
    attempt: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(db.String(20), default="pending")
    provider_reference: Mapped[str | None] = mapped_column(db.String(160))
    sent_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(db.String(80))
    notice_id: Mapped[uuid.UUID]
    __table_args__ = owned_constraints(
        ("notice_id", "recall_notices"), unique=(("notice_id", "attempt"),)
    ) + (CheckConstraint("attempt > 0", name="delivery_attempt"),)


class NoticeAcknowledgement(Owned, db.Model):
    __tablename__ = "notice_acknowledgements"
    acknowledged_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=now)
    method: Mapped[str] = mapped_column(db.String(30))
    safe_note: Mapped[str | None] = mapped_column(db.Text)
    notice_id: Mapped[uuid.UUID]
    recorded_by_id: Mapped[uuid.UUID]
    __table_args__ = owned_constraints(
        ("notice_id", "recall_notices"), ("recorded_by_id", "memberships"), unique=(("notice_id",),)
    ) + (
        CheckConstraint(
            "method IN ('email','phone','written','portal')", name="acknowledgement_method"
        ),
    )
