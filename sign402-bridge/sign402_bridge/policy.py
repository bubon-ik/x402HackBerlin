import hashlib
import json
from typing import Any


def canonicalize_policy(policy: dict[str, Any]) -> str:
    return json.dumps(
        policy,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def hash_policy(policy: dict[str, Any]) -> str:
    canonical = canonicalize_policy(policy).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()

