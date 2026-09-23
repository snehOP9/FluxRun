"""Generate local-only configuration. Existing configuration is never replaced."""
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    print("Using existing .env")
else:
    from cryptography.fernet import Fernet
    values = {
        "POSTGRES_PASSWORD": secrets.token_hex(24),
        "MINIO_ROOT_PASSWORD": secrets.token_hex(24),
        "LOCAL_ADMIN_PASSWORD": secrets.token_urlsafe(24),
        "ENCRYPTION_KEY": Fernet.generate_key().decode(),
    }
    lines = []
    for line in (root / ".env.example").read_text().splitlines():
        key = line.split("=", 1)[0]
        lines.append(f"{key}={values[key]}" if key in values else line)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Created .env with generated local secrets. Read LOCAL_ADMIN_PASSWORD there to sign in.")
