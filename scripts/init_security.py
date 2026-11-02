"""Add a private development MFA encryption key once, preserving existing values."""

import os
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import dotenv_values

path = Path(".env")
if not path.is_file() or path.is_symlink():
    raise SystemExit("Create a regular private .env using init_local.py first.")
if not dotenv_values(path).get("MFA_ENCRYPTION_KEY"):
    # Blank key declarations require operator correction, rather than duplicate bindings.
    if "MFA_ENCRYPTION_KEY" in dotenv_values(path):
        raise SystemExit("Set the blank MFA_ENCRYPTION_KEY securely before continuing.")
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW), "a") as handle:
        handle.write("\nMFA_ENCRYPTION_KEY=" + Fernet.generate_key().decode() + "\n")
    path.chmod(0o600)
    print("Added a private development MFA key. Back it up securely with the database.")
else:
    print("Existing MFA key preserved.")
