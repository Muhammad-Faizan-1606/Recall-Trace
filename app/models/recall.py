"""Recorded trace snapshots and controlled recall investigation history."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models import Owned, now
from app.models.quality import owned, tenant_fk


class RecallCase(Owned, db.Model):
    __tablename__ = "recall_cases"
    reference: Mapped[str] = mapped_column(db.String(80))
    title: Mapped[str] = mapped_column(db.String(160))
    reason: Mapped[str] = mapped_column(db.Text)
    severity: Mapped[str] = mapped_column(db.String(20))
    status: Mapped[str] = mapped_column(db.String(20), default="draft")
    approved_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    owner_id: Mapped[uuid.UUID]
    approver_id: Mapped[uuid.UUID | None]
    submitted_by_id: Mapped[uuid.UUID | None]
    __table_args__ = owned(
        UniqueConstraint("organization_id", "reference"),
        tenant_fk("owner_id", "memberships"),
        tenant_fk("approver_id", "memberships"),
        tenant_fk("submitted_by_id", "memberships"),
        CheckConstraint(
            "approver_id IS NULL OR approver_id <> submitted_by_id", name="independent_approval"
        ),
        CheckConstraint("severity IN ('low','medium','high','critical')", name="case_severity"),
        CheckConstraint(
            "status IN ('draft','submitted','approved','active','pending_closure','closed','rejected','cancelled')",
            name="case_status",
        ),
    )


class CaseSource(Owned, db.Model):
    __tablename__ = "case_sources"
    source_note: Mapped[str] = mapped_column(db.Text)
    case_id: Mapped[uuid.UUID]
    lot_id: Mapped[uuid.UUID]
    nonconformance_id: Mapped[uuid.UUID | None]
    __table_args__ = owned(
        tenant_fk("case_id", "recall_cases"),
        tenant_fk("lot_id", "lots"),
        tenant_fk("nonconformance_id", "nonconformances"),
        UniqueConstraint("case_id", "lot_id"),
    )


class TraceRun(Owned, db.Model):
    __tablename__ = "trace_runs"
    direction: Mapped[str] = mapped_column(db.String(20))
    status: Mapped[str] = mapped_column(db.String(20))
    trace_revision: Mapped[int] = mapped_column(db.BigInteger)
    algorithm_version: Mapped[str] = mapped_column(db.String(30), default="core-1")
    limits: Mapped[dict] = mapped_column(JSONB, default=dict)
    completed_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    is_complete: Mapped[bool] = mapped_column(default=False)
    case_id: Mapped[uuid.UUID]
    requested_by_id: Mapped[uuid.UUID]
    __table_args__ = owned(
        tenant_fk("case_id", "recall_cases"),
        tenant_fk("requested_by_id", "memberships"),
        CheckConstraint("direction IN ('downstream','upstream')", name="trace_direction"),
        CheckConstraint("trace_revision >= 0", name="trace_revision"),
    )


class TraceResult(Owned, db.Model):
    __tablename__ = "trace_results"
    depth: Mapped[int]
    evidence_path: Mapped[list] = mapped_column(JSONB)
    scope_basis: Mapped[str] = mapped_column(db.String(30), default="conservative")
    trace_run_id: Mapped[uuid.UUID]
    lot_id: Mapped[uuid.UUID]
    __table_args__ = owned(
        tenant_fk("trace_run_id", "trace_runs"),
        tenant_fk("lot_id", "lots"),
        UniqueConstraint("trace_run_id", "lot_id"),
        CheckConstraint("depth >= 0", name="trace_depth"),
    )


class CaseAffectedShipment(Owned, db.Model):
    __tablename__ = "case_affected_shipments"
    quantity_dispatched: Mapped[Decimal] = mapped_column(db.Numeric(20, 6))
    quantity_recovered: Mapped[Decimal] = mapped_column(db.Numeric(20, 6), default=0)
    quantity_resolved: Mapped[Decimal] = mapped_column(db.Numeric(20, 6), default=0)
    case_id: Mapped[uuid.UUID]
    trace_run_id: Mapped[uuid.UUID]
    shipment_line_id: Mapped[uuid.UUID]
    __table_args__ = owned(
        tenant_fk("case_id", "recall_cases"),
        tenant_fk("trace_run_id", "trace_runs"),
        tenant_fk("shipment_line_id", "shipment_lines"),
        UniqueConstraint("case_id", "trace_run_id", "shipment_line_id"),
        CheckConstraint(
            "quantity_recovered >= 0 AND quantity_recovered <= quantity_resolved AND quantity_resolved <= quantity_dispatched",
            name="exposure_quantities",
        ),
    )


class CaseTask(Owned, db.Model):
    __tablename__ = "case_tasks"
    title: Mapped[str] = mapped_column(db.String(160))
    description: Mapped[str | None] = mapped_column(db.Text)
    status: Mapped[str] = mapped_column(db.String(20), default="open")
    mandatory: Mapped[bool] = mapped_column(default=True)
    due_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    case_id: Mapped[uuid.UUID]
    assignee_id: Mapped[uuid.UUID]
    verifier_id: Mapped[uuid.UUID | None]
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = owned(
        tenant_fk("case_id", "recall_cases"),
        tenant_fk("assignee_id", "memberships"),
        tenant_fk("verifier_id", "memberships"),
        CheckConstraint("status IN ('open','completed','verified')", name="task_status"),
    )


class CaseComment(Owned, db.Model):
    __tablename__ = "case_comments"
    body: Mapped[str] = mapped_column(db.Text)
    case_id: Mapped[uuid.UUID]
    author_id: Mapped[uuid.UUID]
    __table_args__ = owned(
        tenant_fk("case_id", "recall_cases"), tenant_fk("author_id", "memberships")
    )


class CaseDocument(Owned, db.Model):
    __tablename__ = "case_documents"
    case_id: Mapped[uuid.UUID]
    document_id: Mapped[uuid.UUID]
    __table_args__ = owned(
        tenant_fk("case_id", "recall_cases"),
        tenant_fk("document_id", "documents"),
        UniqueConstraint("case_id", "document_id"),
    )


class RecoveryRecord(Owned, db.Model):
    __tablename__ = "recovery_records"
    evidence_reference: Mapped[str] = mapped_column(db.String(100))
    quantity: Mapped[Decimal] = mapped_column(db.Numeric(20, 6))
    disposition: Mapped[str] = mapped_column(db.String(30))
    verified_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=now)
    evidence_note: Mapped[str] = mapped_column(db.Text)
    case_id: Mapped[uuid.UUID]
    shipment_line_id: Mapped[uuid.UUID]
    verified_by_id: Mapped[uuid.UUID]
    notice_id: Mapped[uuid.UUID | None]
    customer_return_line_id: Mapped[uuid.UUID | None]
    __table_args__ = owned(
        tenant_fk("case_id", "recall_cases"),
        tenant_fk("shipment_line_id", "shipment_lines"),
        tenant_fk("verified_by_id", "memberships"),
        tenant_fk("notice_id", "recall_notices"),
        UniqueConstraint("organization_id", "evidence_reference"),
        CheckConstraint("quantity > 0", name="positive_recovery"),
        CheckConstraint(
            "disposition IN ('returned','destroyed','other_resolved')", name="recovery_disposition"
        ),
    )
