"""TOTP per RFC 6238 with encrypted secrets, replay denial and atomic recovery."""

import base64
import hashlib
import hmac
import re
import secrets
import struct
import time
from datetime import timedelta
from urllib.parse import quote

from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken
from flask import abort, current_app, session
from flask_login import current_user, logout_user
from sqlalchemy import select, update

from app.extensions import db
from app.models import AuthSession, User, now
from app.models.security import MfaFactor
from app.policies import membership_for
from app.services.auth import digest, hasher


class MfaError(ValueError):
    pass


def cipher():
    key = current_app.config.get("MFA_ENCRYPTION_KEY")
    if not key:
        raise MfaError("MFA encryption is not configured by the operator.")
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise MfaError("MFA encryption configuration is invalid.") from exc


def secret_for(factor):
    if factor.key_version != current_app.config.get("MFA_KEY_VERSION", "v1"):
        raise MfaError("MFA key version is unavailable; contact the operator.")
    try:
        return cipher().decrypt(factor.secret_ciphertext.encode()).decode()
    except (InvalidToken, UnicodeError) as exc:
        raise MfaError("MFA key cannot decrypt this factor; contact the operator.") from exc


def totp(secret, step=None):
    """Six-digit SHA-1 TOTP, 30-second steps; no secrets logged."""
    step = int(time.time() // 30) if step is None else step
    raw = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8))
    mac = hmac.new(raw, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1000000:06d}"


def factor_for_user(user_id, lock=False):
    query = select(MfaFactor).where(MfaFactor.user_id == user_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.session.scalar(query)


def _lock_user():
    if not current_user.is_authenticated:
        abort(401)
    user = db.session.scalar(
        select(User)
        .where(User.id == current_user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not user or not user.is_active:
        abort(401)
    return user


def _password(user, password):
    try:
        valid = hasher.verify(user.password_hash, password)
    except (VerificationError, InvalidHashError, TypeError):
        valid = False
    if not valid:
        raise MfaError("Password confirmation failed.")


def _auth(lock=False):
    token = session.get("auth_ref")
    if not current_user.is_authenticated or not token:
        abort(401)
    query = select(AuthSession).where(
        AuthSession.user_id == current_user.id,
        AuthSession.token_digest == digest(token),
        AuthSession.revoked_at.is_(None),
        AuthSession.expires_at > now(),
        AuthSession.auth_version == current_user.auth_version,
        AuthSession.last_seen_at > now() - timedelta(minutes=30),
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    auth = db.session.scalar(query)
    if auth is None:
        abort(401)
    return auth


def begin_enrollment(password):
    try:
        user = _lock_user()
        _password(user, password)
        factor = factor_for_user(user.id, lock=True)
        if factor and factor.verified_at:
            raise MfaError("A factor is already enrolled. Use your existing authenticator.")
        if factor:
            db.session.delete(factor)
            db.session.flush()
        secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        factor = MfaFactor(
            user_id=user.id,
            secret_ciphertext=cipher().encrypt(secret.encode()).decode(),
            key_version=current_app.config.get("MFA_KEY_VERSION", "v1"),
            recovery_code_hashes=[],
        )
        db.session.add(factor)
        db.session.commit()
        # Shown once on the CSRF-protected enrollment response; never in a URL.
        return secret
    except Exception:
        db.session.rollback()
        raise


def provisioning_uri(secret):
    return (
        f"otpauth://totp/{quote('RecallTrace:' + current_user.email, safe='')}"
        f"?secret={secret}&issuer=RecallTrace&algorithm=SHA1&digits=6&period=30"
    )


def _consume(factor, code, allow_recovery=True):
    code = (code or "").strip()
    if re.fullmatch(r"[0-9]{6}", code):
        secret = secret_for(factor)
        current_step = int(time.time() // 30)
        for step in (current_step, current_step - 1, current_step + 1):
            if hmac.compare_digest(totp(secret, step), code):
                if factor.last_used_step is not None and step <= factor.last_used_step:
                    raise MfaError(
                        "This authenticator code was already used. Wait for the next code."
                    )
                factor.last_used_step = step
                return "totp"
    if allow_recovery and re.fullmatch(r"[A-Za-z0-9_-]{20,64}", code):
        matched = digest(code)
        hashes = list(factor.recovery_code_hashes)
        for value in hashes:
            if hmac.compare_digest(value, matched):
                hashes.remove(value)
                factor.recovery_code_hashes = hashes
                return "recovery"
    raise MfaError("Invalid authenticator or recovery code.")


def _revoke_others(user_id, auth_id):
    db.session.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.id != auth_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now())
    )


def confirm_enrollment(code):
    try:
        user = _lock_user()
        factor = factor_for_user(user.id, lock=True)
        if not factor or factor.verified_at:
            raise MfaError("Begin a new enrollment first.")
        _consume(factor, code, allow_recovery=False)
        codes = [secrets.token_urlsafe(18) for _ in range(10)]
        factor.recovery_code_hashes = [digest(code) for code in codes]
        factor.verified_at = now()
        auth = _auth(lock=True)
        auth.last_mfa_at = now()
        _revoke_others(user.id, auth.id)
        db.session.commit()
        return codes
    except Exception:
        db.session.rollback()
        raise


def verify(code):
    try:
        user = _lock_user()
        factor = factor_for_user(user.id, lock=True)
        if not factor or not factor.verified_at:
            raise MfaError("Enroll an authenticator first.")
        method = _consume(factor, code)
        auth = _auth(lock=True)
        auth.last_mfa_at = now()
        if method == "recovery":
            _revoke_others(user.id, auth.id)
        db.session.commit()
        return method
    except Exception:
        db.session.rollback()
        raise


def disable(password, code):
    try:
        user = _lock_user()
        _password(user, password)
        factor = factor_for_user(user.id, lock=True)
        if not factor or not factor.verified_at:
            raise MfaError("No verified factor is enrolled.")
        _consume(factor, code)
        db.session.delete(factor)
        user.auth_version += 1
        db.session.execute(
            update(AuthSession).where(AuthSession.user_id == user.id).values(revoked_at=now())
        )
        db.session.commit()
        logout_user()
        session.clear()
    except Exception:
        db.session.rollback()
        raise


def login_verified():
    """An enrolled user must satisfy MFA at least once in every fresh login session."""
    factor = factor_for_user(current_user.id)
    return not factor or not factor.verified_at or _auth().last_mfa_at is not None


def require_recent_mfa(company_id):
    membership_for(company_id)
    factor = factor_for_user(current_user.id)
    auth = _auth()
    if (
        not factor
        or not factor.verified_at
        or not auth.last_mfa_at
        or auth.last_mfa_at < now() - timedelta(minutes=10)
    ):
        abort(
            403, description="Verify your authenticator within the last 10 minutes before approval."
        )
