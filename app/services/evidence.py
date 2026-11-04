"""Bounded private storage and imports; unscanned evidence is never downloadable."""

import csv
import hashlib
import io
import os
import re
import secrets
import socket
import struct
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, urlparse

import requests
from flask import abort, current_app
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Item, now
from app.models.evidence import Document, ExportJob, ImportJob, Notification, NotificationPreference
from app.policies import membership_for, require
from app.services.audit import record as audit
from app.services.business import DomainError, actor, company_lock, scoped

MAX_BYTES = 10 * 1024 * 1024
KINDS = {"component", "finished", "packaging"}
EVENT_TYPES = {"case", "notice", "quality", "export", "import"}


def max_bytes():
    """A deployment may lower the file limit without raising the hard ceiling."""
    limit = current_app.config.get("EVIDENCE_MAX_BYTES", MAX_BYTES)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_BYTES:
        raise RuntimeError("EVIDENCE_MAX_BYTES must be an integer from 1 byte to 10 MiB.")
    return limit


def max_bytes_label():
    limit = max_bytes()
    for unit, divisor in (("MiB", 1024 * 1024), ("KiB", 1024)):
        if limit % divisor == 0:
            return f"{limit // divisor} {unit}"
    return f"{limit} {'byte' if limit == 1 else 'bytes'}"


def _successful(response):
    """Provider redirects must never forward private bytes or credential headers."""
    response.raise_for_status()
    if not 200 <= response.status_code < 300:
        raise requests.HTTPError("Unexpected private provider response.", response=response)


def _storage_root():
    path = Path(
        current_app.config.get("EVIDENCE_ROOT") or Path(current_app.instance_path) / "evidence"
    ).resolve()
    static = Path(current_app.static_folder).resolve()
    if path == static or path.is_relative_to(static):
        raise DomainError("Evidence storage must be outside public static assets.")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _storage_url(key):
    endpoint = current_app.config.get("SUPABASE_URL", "").rstrip("/")
    bucket = current_app.config.get("SUPABASE_STORAGE_BUCKET", "")
    credential = current_app.config.get("SUPABASE_SERVICE_KEY", "")
    if urlparse(endpoint).scheme != "https" or not bucket or not credential:
        raise DomainError("Private Supabase storage is not configured.")
    headers = {
        "Authorization": f"Bearer {credential}",
        "apikey": credential,
    }
    # Confirm the remote bucket's observed privacy; its name is not a guarantee.
    try:
        response = requests.get(
            f"{endpoint}/storage/v1/bucket/{quote(bucket, safe='')}",
            headers=headers,
            timeout=(5, 15),
            allow_redirects=False,
        )
        _successful(response)
        payload = response.json()
        private = isinstance(payload, dict) and payload.get("public") is False
    except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
        raise DomainError("The private evidence bucket could not be verified.") from exc
    if not private:
        raise DomainError("Evidence bucket must be verified private before use.")
    return f"{endpoint}/storage/v1/object/{quote(bucket, safe='')}/{quote(key, safe='/')}", headers


def _valid_key(key):
    if not re.fullmatch(r"[0-9a-f]{32}/[0-9a-f]{48}", key):
        raise DomainError("Invalid private object key.")


def put_bytes(company_id, data):
    if not 0 < len(data) <= max_bytes():
        raise DomainError(f"File must contain 1 byte to {max_bytes_label()}.")
    key = f"{company_id.hex}/{secrets.token_hex(24)}"
    if current_app.config.get("STORAGE_BACKEND", "filesystem") == "supabase":
        url, headers = _storage_url(key)
        headers["Content-Type"] = "application/octet-stream"
        try:
            response = requests.post(
                url, headers=headers, data=data, timeout=(5, 30), allow_redirects=False
            )
            _successful(response)
        except requests.RequestException as exc:
            raise DomainError("Private storage write failed; no evidence was accepted.") from exc
    else:
        root = _storage_root()
        directory = root / company_id.hex
        directory.mkdir(exist_ok=True, mode=0o700)
        if not directory.resolve().is_relative_to(root):
            raise DomainError("Private storage path is invalid.")
        with os.fdopen(
            os.open(root / key, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), "wb"
        ) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    return key


def read_bytes(document):
    _valid_key(document.object_key)
    limit = max_bytes()
    if document.size_bytes > limit:
        raise DomainError(f"File exceeds the current {max_bytes_label()} file limit.")
    if current_app.config.get("STORAGE_BACKEND", "filesystem") == "supabase":
        url, headers = _storage_url(document.object_key)
        try:
            with requests.get(
                url, headers=headers, timeout=(5, 30), stream=True, allow_redirects=False
            ) as response:
                _successful(response)
                data = response.raw.read(limit + 1)
        except requests.RequestException as exc:
            raise DomainError("Private storage read failed.") from exc
    else:
        root = _storage_root()
        path = root / document.object_key
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise DomainError("Private storage path is invalid.")
        try:
            with path.open("rb") as handle:
                data = handle.read(limit + 1)
        except OSError as exc:
            raise DomainError("Private object is unavailable.") from exc
    if len(data) > limit:
        raise DomainError(f"File exceeds the current {max_bytes_label()} file limit.")
    if len(data) != document.size_bytes or hashlib.sha256(data).hexdigest() != document.sha256:
        raise DomainError("Private object integrity check failed.")
    return data


def _delete_bytes(key):
    _valid_key(key)
    if current_app.config.get("STORAGE_BACKEND", "filesystem") == "supabase":
        url, headers = _storage_url(key)
        try:
            _successful(
                requests.delete(url, headers=headers, timeout=(5, 15), allow_redirects=False)
            )
        except requests.RequestException:
            current_app.logger.warning("Private storage cleanup failed; maintenance required.")
    else:
        path = _storage_root() / key
        if path.resolve().is_relative_to(_storage_root()) and not path.is_symlink():
            path.unlink(missing_ok=True)


def _media(data, filename):
    """Bounded signature/trailer checks; antivirus is a separate mandatory decision."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf" and data.startswith(b"%PDF-") and b"%%EOF" in data[-1024:]:
        return "application/pdf"
    if (
        suffix == ".png"
        and data.startswith(b"\x89PNG\r\n\x1a\n")
        and data[-8:] == b"IEND\xaeB`\x82"
    ):
        return "image/png"
    if (
        suffix in {".jpg", ".jpeg"}
        and data.startswith(b"\xff\xd8\xff")
        and data.endswith(b"\xff\xd9")
    ):
        return "image/jpeg"
    raise DomainError("Upload a PDF, PNG or JPEG with matching file content.")


def scan_bytes(data):
    """ClamAV INSTREAM or an explicitly configured trusted HTTPS scanner.

    No development clean switch exists. Tests inject their own scanner adapter;
    a missing or unavailable scanner always leaves the object quarantined.
    """
    endpoint = current_app.config.get("SCANNER_ENDPOINT")
    if endpoint:
        if urlparse(endpoint).scheme != "https":
            return "unavailable"
        try:
            response = requests.post(
                endpoint,
                data=data,
                headers={"Content-Type": "application/octet-stream"},
                timeout=(3, 30),
                allow_redirects=False,
            )
            _successful(response)
            payload = response.json()
            state = payload.get("status") if isinstance(payload, dict) else None
            return state if state in {"clean", "infected"} else "unavailable"
        except (requests.RequestException, ValueError):
            return "unavailable"
    host = current_app.config.get("CLAMAV_HOST")
    if not host:
        return "unavailable"
    try:
        with socket.create_connection(
            (host, int(current_app.config.get("CLAMAV_PORT", 3310))), timeout=5
        ) as connection:
            connection.settimeout(30)
            connection.sendall(b"zINSTREAM\0")
            for index in range(0, len(data), 65536):
                block = data[index : index + 65536]
                connection.sendall(struct.pack("!I", len(block)) + block)
            connection.sendall(struct.pack("!I", 0))
            result = bytearray()
            while len(result) < 1024:
                chunk = connection.recv(1024 - len(result))
                if not chunk:
                    break
                result.extend(chunk)
                if b"\0" in result:
                    break
            reply = bytes(result).strip(b"\0\r\n")
            if reply.endswith(b": OK"):
                return "clean"
            if reply.endswith(b" FOUND"):
                return "infected"
    except (OSError, ValueError):
        pass
    return "unavailable"


def _filename(name):
    if not isinstance(name, str):
        raise DomainError("Choose a valid filename.")
    name = Path(name.replace("\\", "/")).name.strip()
    if not name or len(name) > 240 or any(ord(c) < 32 for c in name):
        raise DomainError("Choose a filename of at most 240 printable characters.")
    return name


def _discard_unlinked(key):
    try:
        _delete_bytes(key)
    except (DomainError, OSError):
        # The object remains private and unlinked if provider cleanup is unavailable.
        current_app.logger.warning("Private unlinked object cleanup requires maintenance.")


def _document(company_id, member_id, data, name, media_type, state, scan_status, object_key=None):
    name = _filename(name)
    key = object_key or put_bytes(company_id, data)
    _valid_key(key)
    if not key.startswith(company_id.hex + "/"):
        raise DomainError("Private object belongs to another company.")
    record = Document(
        organization_id=company_id,
        uploaded_by_id=member_id,
        object_key=key,
        original_name=name,
        media_type=media_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        scan_status=scan_status,
        state=state,
    )
    db.session.add(record)
    db.session.flush()
    return record


def upload(company_id, filename, stream):
    # Network scanning/storage can be slow. Do not hold the company business guard
    # during I/O; authorize before accepting bytes, then recheck before committing.
    require(company_id, "evidence.upload")
    member_id = membership_for(company_id).id
    db.session.rollback()
    filename = _filename(filename)
    data = stream.read(max_bytes() + 1)
    if not 0 < len(data) <= max_bytes():
        raise DomainError(f"File must contain 1 byte to {max_bytes_label()}.")
    media_type = _media(data, filename)
    status = scan_bytes(data)
    key = put_bytes(company_id, data)
    try:
        member = actor(company_id, "evidence.upload")
        if member.id != member_id:
            raise DomainError("Upload authorization changed; retry with the current membership.")
        record = _document(
            company_id,
            member.id,
            data,
            filename,
            media_type,
            "active" if status == "clean" else "quarantined",
            status,
            object_key=key,
        )
        audit(company_id, "evidence.upload", "document", record.id, {"status": status})
        db.session.commit()
        return record
    except Exception:
        db.session.rollback()
        _discard_unlinked(key)
        raise


def rescan(company_id, document_id):
    require(company_id, "evidence.upload")
    member_id = membership_for(company_id).id
    record = scoped(Document, company_id, document_id)
    db.session.refresh(record)
    if record.archived_at or record.state != "quarantined":
        raise DomainError("Only quarantined evidence can be rescanned.")
    snapshot = SimpleNamespace(
        object_key=record.object_key, size_bytes=record.size_bytes, sha256=record.sha256
    )
    version = record.version
    db.session.rollback()
    status = scan_bytes(read_bytes(snapshot))
    try:
        member = actor(company_id, "evidence.upload")
        if member.id != member_id:
            raise DomainError("Scan authorization changed; retry with the current membership.")
        record = scoped(Document, company_id, document_id, lock=True)
        if (
            record.version != version
            or record.object_key != snapshot.object_key
            or record.sha256 != snapshot.sha256
            or record.size_bytes != snapshot.size_bytes
            or record.state != "quarantined"
            or record.archived_at
        ):
            raise DomainError("Document changed while scanning; reload before retrying.")
        record.scan_status = status
        record.state = "active" if status == "clean" else "quarantined"
        audit(company_id, "evidence.scan", "document", record.id, {"status": status})
        db.session.commit()
        return record
    except Exception:
        db.session.rollback()
        raise


def downloadable(company_id, document_id):
    require(company_id, "evidence.read")
    record = scoped(Document, company_id, document_id)
    if (
        record.archived_at
        or record.scan_status != "clean"
        or record.state not in {"active", "export"}
    ):
        abort(404)
    if record.state == "export":
        require(company_id, "reports.export")
        member = membership_for(company_id)
        job = db.session.scalar(
            select(ExportJob).where(
                ExportJob.organization_id == company_id,
                ExportJob.output_document_id == record.id,
                ExportJob.requested_by_id == member.id,
                ExportJob.status == "completed",
                ExportJob.expires_at > now(),
            )
        )
        if job is None:
            abort(404)
    return record, read_bytes(record)


def remove_document(company_id, document_id, version):
    company_lock(company_id)
    actor(company_id, "evidence.upload")
    record = scoped(Document, company_id, document_id, lock=True)
    if record.version != version:
        raise DomainError("Document changed; reload before removing it.")
    # Retain all bytes and metadata when linked to protected business history.
    from app.models.operations import ReceiptDocument
    from app.models.quality import QualityDocument
    from app.models.recall import CaseDocument

    referenced = any(
        db.session.scalar(
            select(model.id)
            .where(model.organization_id == company_id, model.document_id == record.id)
            .limit(1)
        )
        for model in (ReceiptDocument, QualityDocument, CaseDocument)
    )
    referenced = referenced or db.session.scalar(
        select(ImportJob.id).where(
            ImportJob.organization_id == company_id, ImportJob.source_document_id == record.id
        )
    )
    referenced = referenced or db.session.scalar(
        select(ExportJob.id).where(
            ExportJob.organization_id == company_id, ExportJob.output_document_id == record.id
        )
    )
    if referenced:
        # Evidence links must remain accessible to an investigation; archive is metadata only.
        raise DomainError("Referenced evidence is protected; retain it with its business record.")
    key = record.object_key
    audit(company_id, "evidence.delete_unused", "document", record.id)
    db.session.delete(record)
    db.session.commit()
    _delete_bytes(key)


def parse_items_csv(data):
    if not 0 < len(data) <= max_bytes():
        raise DomainError(f"CSV must contain 1 byte to {max_bytes_label()}.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DomainError("CSV must use UTF-8 encoding.") from exc
    if "\x00" in text:
        raise DomainError("CSV contains an invalid character.")
    rows, codes = [], set()
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if reader.fieldnames != ["code", "name", "kind"]:
            raise DomainError("CSV header must be exactly code,name,kind.")
        for number, row in enumerate(reader, start=2):
            if number > 10001 or None in row or any(value is None for value in row.values()):
                raise DomainError("CSV has too many rows or an incorrect column count.")
            values = {key: value.strip() for key, value in row.items()}
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,39}", values["code"]):
                raise DomainError(
                    f"Row {number}: item code must use letters, digits, dot, dash or underscore."
                )
            if not 1 <= len(values["name"]) <= 160 or any(ord(c) < 32 for c in values["name"]):
                raise DomainError(f"Row {number}: enter a printable name of 1 to 160 characters.")
            if values["kind"] not in KINDS or values["code"] in codes:
                raise DomainError(f"Row {number}: invalid kind or repeated item code.")
            rows.append(values)
            codes.add(values["code"])
    except csv.Error as exc:
        raise DomainError("CSV syntax is invalid.") from exc
    if not rows:
        raise DomainError("CSV must contain at least one item.")
    return rows


def prepare_import(company_id, filename, stream, idempotency_key):
    member = actor(company_id, "catalog.manage")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", idempotency_key):
        raise DomainError("Use the supplied import identifier.")
    data = stream.read(max_bytes() + 1)
    rows = parse_items_csv(data)
    company_lock(company_id)
    previous = db.session.scalar(
        select(ImportJob).where(
            ImportJob.organization_id == company_id, ImportJob.idempotency_key == idempotency_key
        )
    )
    if previous:
        source = scoped(Document, company_id, previous.source_document_id)
        if (
            source.sha256 != hashlib.sha256(data).hexdigest()
            or previous.requested_by_id != member.id
        ):
            raise DomainError("Import identifier was already used with another payload.")
        return previous
    existing = set(
        db.session.scalars(
            select(Item.code).where(
                Item.organization_id == company_id, Item.code.in_([row["code"] for row in rows])
            )
        )
    )
    if existing:
        raise DomainError("One or more item codes already exist. No rows were imported.")
    document = _document(company_id, member.id, data, filename, "text/csv", "source", "clean")
    job = ImportJob(
        organization_id=company_id,
        kind="items",
        requested_by_id=member.id,
        source_document_id=document.id,
        status="validated",
        row_count=len(rows),
        idempotency_key=idempotency_key,
        safe_error_summary={},
    )
    db.session.add(job)
    db.session.flush()
    audit(company_id, "import.validate", "import_job", job.id, {"count": len(rows)})
    db.session.commit()
    return job


def commit_import(company_id, job_id):
    member = actor(company_id, "catalog.manage")
    company_lock(company_id)
    job = scoped(ImportJob, company_id, job_id, lock=True)
    if job.requested_by_id != member.id:
        abort(404)
    if job.status == "committed":
        return job
    if job.status != "validated":
        raise DomainError("Only a validated import can be committed.")
    document = scoped(Document, company_id, job.source_document_id)
    rows = parse_items_csv(read_bytes(document))
    try:
        for values in rows:
            db.session.add(Item(organization_id=company_id, **values))
        job.status = "committed"
        audit(company_id, "import.commit", "import_job", job.id, {"count": len(rows)})
        notify(company_id, member.id, "import", {"message": f"Imported {len(rows)} catalog items."})
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise DomainError("An item code now exists; the entire import was rolled back.") from exc
    return job


def cancel_import(company_id, job_id):
    member = actor(company_id, "catalog.manage")
    job = scoped(ImportJob, company_id, job_id, lock=True)
    if job.requested_by_id != member.id:
        abort(404)
    if job.status != "validated":
        raise DomainError("Only an uncommitted import can be cancelled.")
    job.status = "cancelled"
    audit(company_id, "import.cancel", "import_job", job.id)
    db.session.commit()


def csv_cell(value):
    value = "" if value is None else str(value)
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        value = "'" + value
    return value


def create_export(company_id, kind="items", case_id=None):
    member = actor(company_id, "reports.export")
    company_lock(company_id)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    if kind == "items":
        rows = db.session.scalars(
            select(Item).where(Item.organization_id == company_id).order_by(Item.code).limit(10001)
        ).all()
        fields = [(row.code, row.name, row.kind) for row in rows]
        writer.writerow(["code", "name", "kind"])
    elif kind == "stock":
        from app.models.master import Lot, StorageLocation
        from app.models.operations import StockBalance

        rows = db.session.execute(
            select(StockBalance, Lot, StorageLocation)
            .join(Lot, Lot.id == StockBalance.lot_id)
            .join(StorageLocation, StorageLocation.id == StockBalance.location_id)
            .where(StockBalance.organization_id == company_id)
            .limit(10001)
        ).all()
        fields = [
            (lot.lot_code, location.code, balance.quantity) for balance, lot, location in rows
        ]
        writer.writerow(["lot", "location", "quantity_base_unit"])
    elif kind == "case_exposure":
        require(company_id, "trace.run")
        from app.models.operations import ShipmentLine
        from app.models.recall import CaseAffectedShipment
        from app.services.recall import current_trace

        trace = current_trace(company_id, case_id)
        rows = db.session.execute(
            select(CaseAffectedShipment, ShipmentLine)
            .join(ShipmentLine, ShipmentLine.id == CaseAffectedShipment.shipment_line_id)
            .where(
                CaseAffectedShipment.organization_id == company_id,
                CaseAffectedShipment.trace_run_id == trace.id,
            )
            .limit(10001)
        ).all()
        fields = [
            (
                line.id,
                line.lot_id,
                affected.quantity_dispatched,
                affected.quantity_recovered,
                affected.quantity_resolved,
            )
            for affected, line in rows
        ]
        writer.writerow(["shipment_line", "lot", "dispatched", "recovered", "resolved"])
    else:
        raise DomainError("Unsupported export kind.")
    if len(rows) > 10000:
        raise DomainError("Export exceeds 10,000 rows; narrow the dataset first.")
    writer.writerows([csv_cell(value) for value in row] for row in fields)
    data = output.getvalue().encode("utf-8")
    document = _document(company_id, member.id, data, f"{kind}.csv", "text/csv", "export", "clean")
    job = ExportJob(
        organization_id=company_id,
        kind=kind,
        requested_by_id=member.id,
        output_document_id=document.id,
        status="completed",
        filters={"case_id": str(case_id)} if case_id else {},
        expires_at=now() + timedelta(hours=24),
    )
    db.session.add(job)
    db.session.flush()
    audit(
        company_id,
        "export.create",
        "export_job",
        job.id,
        {"count": len(rows), "document_id": str(document.id)},
    )
    notify(company_id, member.id, "export", {"message": "Private export ready for 24 hours."})
    db.session.commit()
    return job


def notify(company_id, member_id, event_type, payload):
    """Flush-only notification intent, safe fixed message and identifiers only."""
    if event_type not in EVENT_TYPES or set(payload) - {"message", "case_id", "notice_id"}:
        raise DomainError("Unsupported notification payload.")
    preference = db.session.scalar(
        select(NotificationPreference).where(
            NotificationPreference.organization_id == company_id,
            NotificationPreference.membership_id == member_id,
            NotificationPreference.event_type == event_type,
            NotificationPreference.channel == "in_app",
        )
    )
    if preference and not preference.enabled:
        return None
    notification = Notification(
        organization_id=company_id,
        membership_id=member_id,
        event_type=event_type,
        safe_payload=payload,
    )
    db.session.add(notification)
    return notification


def mark_notification(company_id, notification_id):
    member = membership_for(company_id)
    row = scoped(Notification, company_id, notification_id, lock=True)
    if row.membership_id != member.id:
        abort(404)
    row.read_at = now()
    db.session.commit()


def set_preference(company_id, event_type, enabled):
    member = membership_for(company_id)
    if event_type not in EVENT_TYPES or not isinstance(enabled, bool):
        raise DomainError("Choose a supported event and preference.")
    company_lock(company_id)
    row = db.session.scalar(
        select(NotificationPreference).where(
            NotificationPreference.organization_id == company_id,
            NotificationPreference.membership_id == member.id,
            NotificationPreference.event_type == event_type,
            NotificationPreference.channel == "in_app",
        )
    )
    if row is None:
        row = NotificationPreference(
            organization_id=company_id,
            membership_id=member.id,
            event_type=event_type,
            channel="in_app",
        )
        db.session.add(row)
    row.enabled = enabled
    db.session.commit()
    return row
