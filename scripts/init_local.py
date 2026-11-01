"""Create private local configuration once; never overwrite existing configuration."""

import os
import secrets
from pathlib import Path

path = Path(".env")
if path.exists():
    print(".env already exists; preserved unchanged.")
else:
    password = secrets.token_hex(24)
    content = (
        "APP_ENV=development\n"
        f"SECRET_KEY={secrets.token_hex(32)}\n"
        f"POSTGRES_PASSWORD={password}\n"
        f"DATABASE_URL=postgresql+psycopg://recalltrace:{password}@127.0.0.1:5432/recalltrace\n"
        "SESSION_REDIS_URL=redis://127.0.0.1:6379/0\n"
        "RATELIMIT_STORAGE_URI=redis://127.0.0.1:6379/1\n"
    )
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
        handle.write(content)
    print("Created private .env with generated local credentials; values not printed.")
