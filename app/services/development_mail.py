"""Private local account delivery or explicitly configured production HTTPS mail.

The historical function names remain for callers; no raw token is saved to an
outbox or logged. Production never writes the development mailbox.
"""

import hashlib
import json
import os
import secrets
from pathlib import Path

from flask import current_app


def _directory():
    configured = current_app.config.get("ACCOUNT_MAIL_DIR")
    if not configured or current_app.config.get("APP_ENV") == "production":
        return None
    instance = Path(current_app.instance_path).resolve()
    directory = Path(configured)
    if not directory.is_absolute():
        directory = instance / directory
    directory = directory.resolve()
    if directory == instance or not directory.is_relative_to(instance):
        return None
    return directory


def development_mail_configured():
    if current_app.config.get("APP_ENV") == "production":
        return bool(
            current_app.config.get("MAIL_MODE") == "resend"
            and current_app.config.get("MAIL_API_KEY")
            and current_app.config.get("MAIL_FROM")
        )
    return _directory() is not None


def deliver_development_message(recipient, subject, body):
    """Return transport acceptance, never a guarantee that a recipient read mail.

    Challenge issuance commits before this call. Production sends synchronously
    through verified TLS. Failed/ambiguous delivery returns False; a fresh request
    creates a new challenge, rather than storing raw account tokens in job payloads.
    """
    if current_app.config.get("APP_ENV") == "production":
        if not development_mail_configured():
            return False
        from app.services.notices import send_message

        fingerprint = hashlib.sha256(
            json.dumps([recipient, subject, body], ensure_ascii=False).encode()
        ).hexdigest()
        outcome, _reference, _error = send_message(
            recipient, subject, body, "account-" + fingerprint
        )
        if outcome != "sent":
            current_app.logger.warning("Production account mail was not confirmed accepted.")
        return outcome == "sent"
    directory = _directory()
    if directory is None:
        return False
    message_path = None
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        message_path = directory / f"{secrets.token_hex(16)}.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        descriptor = os.open(message_path, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"recipient": recipient, "subject": subject, "body": body}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        return True
    except OSError:
        if message_path is not None:
            message_path.unlink(missing_ok=True)
        current_app.logger.warning("Private development account delivery failed.")
        return False
