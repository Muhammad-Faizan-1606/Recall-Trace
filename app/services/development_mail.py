"""Opt-in local-only delivery. No network mail integration is configured."""

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
    return _directory() is not None


def deliver_development_message(recipient, subject, body):
    """Write a private mailbox message, returning False without disclosing its contents.

    The caller owns the database transaction. A development spool file is not proof
    of external delivery, and this adapter must not be used for production mail.
    """
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
