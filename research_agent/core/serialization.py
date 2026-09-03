"""Canonical JSON for internal fingerprints, not raw corpus file checksums."""
import hashlib
import json


def _check_mapping_keys(value: object) -> None:
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("Canonical JSON requires string mapping keys")
        for child in value.values():
            _check_mapping_keys(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _check_mapping_keys(child)


def canonical_bytes(value: object) -> bytes:
    """Serialize sorted compact UTF-8; reject NaN/Inf and coerced map keys."""
    # Encoder first: reject unsupported types and cycles before walking keys.
    text = json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )
    _check_mapping_keys(value)
    return text.encode("utf-8")


def digest(value: object) -> str:
    """Return lowercase SHA-256 over canonical JSON bytes."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
