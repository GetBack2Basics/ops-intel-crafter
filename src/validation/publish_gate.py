"""Pre-upload publish gate for Google Cloud Storage.

Adapted from aura_siting_crafter/src/Ingestion_v2/publish_gate.py.
Blocks any secret, credential file, or dataset without verified redistribution permission.
"""

import os
import re
from pathlib import Path
from typing import Dict, Any, List

FORBIDDEN_NAME_PATTERNS = (
    r"(^|/)\.env($|\.)",
    r"credentials?.*\.json$",
    r"application_default_credentials\.json$",
    r"service[-_]?account.*\.json$",
    r"\.pem$",
    r"\.key$",
    r"id_rsa",
    r"\.ppk$",
)


class PublishBlocked(Exception):
    """Raised when a dataset or file must not be uploaded to a cloud bucket."""


def assert_publishable_dataset(entry: Dict[str, Any]) -> None:
    """Blocks publication unless the dataset entry explicitly verifies redistribution permission."""
    key = entry.get("dataset_key", "<unknown>")
    licence = entry.get("licence") or {}
    if licence.get("redistribution_permitted") is not True:
        raise PublishBlocked(
            f"{key}: licence.redistribution_permitted is {licence.get('redistribution_permitted')!r}; "
            "must be verified as True (with licence name and attribution) before public cloud upload."
        )
    if not licence.get("attribution") and licence.get("name") not in ("public-domain",):
        raise PublishBlocked(f"{key}: licence has no attribution string recorded.")


def assert_safe_object_name(object_name: str) -> None:
    """Blocks credential-like files by name."""
    normalized = object_name.replace(os.sep, "/")
    for pattern in FORBIDDEN_NAME_PATTERNS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            raise PublishBlocked(f"{object_name}: file name matches forbidden pattern ({pattern}).")


def load_env_secret_values(base_dir: Path) -> List[str]:
    """Reads secret values (>= 8 chars) from .env to prevent accidental upload in text artifacts."""
    env_path = base_dir / ".env"
    secrets: List[str] = []
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if len(v) >= 8 and any(tok in k.upper() for tok in ("KEY", "SECRET", "TOKEN", "PASSWORD")):
                    secrets.append(v)
    return secrets

