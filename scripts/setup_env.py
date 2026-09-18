"""Create a local .env without printing credentials or overwriting existing values."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
path = root / ".env"
if path.exists():
    print("Existing .env preserved.")
else:
    text = (root / ".env.example").read_text()
    text = text.replace("PAN_HASH_SECRET=\n", "PAN_HASH_SECRET=" + secrets.token_hex(32) + "\n")
    text = text.replace("BOOTSTRAP_ADMIN_PASSWORD=\n", "BOOTSTRAP_ADMIN_PASSWORD=" + secrets.token_urlsafe(24) + "\n")
    (root / "data" / "certs").mkdir(parents=True, exist_ok=True)
    (root / "data" / "assets").mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print("Created ignored .env. Read BOOTSTRAP_ADMIN_PASSWORD there to sign in.")
