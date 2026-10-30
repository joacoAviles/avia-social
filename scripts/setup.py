#!/usr/bin/env python3
"""Generate local secrets without overwriting an existing installation."""

import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / ".env"
if path.exists():
    raise SystemExit(".env already exists; preserved")
password = secrets.token_hex(24)
text = (root / ".env.example").read_text()
text = text.replace("SECRET_KEY=REPLACE_USING_SETUP", "SECRET_KEY=" + secrets.token_hex(48))
text = text.replace("ENCRYPTION_KEY_SALT=REPLACE_USING_SETUP", "ENCRYPTION_KEY_SALT=" + secrets.token_hex(32))
text = text.replace("REPLACE_USING_SETUP", password)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as file:
    file.write(text)
(root / "secrets").mkdir(mode=0o700, exist_ok=True)
print("Generated .env and empty secrets/. No accounts or external integrations enabled.")
