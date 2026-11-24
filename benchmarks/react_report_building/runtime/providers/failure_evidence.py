"""Bounded, versioned diagnostics without raw scientific request material."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any


SCHEMA_VERSION = "react_report.provider_failure_evidence/v1"
MAX_BODY_BYTES = 256 * 1024
MAX_MESSAGE_CHARS = 1024
MAX_SYNTHETIC_BODY_CHARS = 8192
_PRIVATE_KEY = re.compile(r"authorization|cookie|api[_-]?key|password|secret|credential|access[_-]?token|refresh[_-]?token", re.I)
_SECRET = re.compile(r"\b(?:Bearer|Basic)\s+[^\s\"'<>]+|\bsk-[A-Za-z0-9_-]{8,}|\b(?:api[_-]?key|password|secret|access[_-]?token|refresh[_-]?token)\s*[=:]\s*[^\s\"'<>]+", re.I)
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.\[\]-]{1,160}\Z")


def failure_evidence(
    body: bytes, *, http_status: int, request_payload: bytes = b"",
    credentials: tuple[str, ...] = (), content_scope: str = "scientific",
    body_complete: bool = True,
) -> dict[str, Any]:
    """Hash observed bytes and retain only sanitized bounded diagnostic text.

    A body exceeding the read bound is explicitly a prefix: its hash and byte
    count never pretend to describe unread bytes. Scientific diagnostics retain
    only error code/type/param and a capped message. Request words and quoted
    fragments are removed from that message to suppress evidence echoes.
    """
    if content_scope not in {"scientific", "synthetic"}:
        raise ValueError("invalid diagnostic content scope")
    if len(body) > MAX_BODY_BYTES:
        body, body_complete = body[:MAX_BODY_BYTES + 1], False
    redacted = False
    private_words: set[str] = set()
    if content_scope == "scientific":
        try:
            request_value = json.loads(request_payload)
        except (ValueError, UnicodeError):
            request_value = None
        def words(value: Any) -> None:
            if isinstance(value, str):
                private_words.update(word.casefold() for word in re.findall(r"\w+", value))
            elif isinstance(value, dict):
                for item in value.values():
                    words(item)
            elif isinstance(value, list):
                for item in value:
                    words(item)
        words(request_value)

    def clean_text(value: str, *, message: bool = False) -> str:
        nonlocal redacted
        original = value
        for credential in credentials:
            if credential:
                value = value.replace(credential, "[REDACTED]")
        value = _SECRET.sub("[REDACTED]", value)
        value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
        if content_scope == "scientific":
            value = re.sub(r"https?://[^\s\"'<>]+", "[REDACTED]", value)
            if message:
                value = re.sub(r'''"[^"\n]*"|'[^'\n]*'|`[^`\n]*`''', "[REDACTED]", value)
            value = re.sub(r"\w+", lambda match: "[REDACTED]" if match[0].casefold() in private_words else match[0], value)
        redacted |= value != original
        return value

    def clean_object(value: Any, depth: int = 0) -> Any:
        nonlocal redacted
        if depth > 12:
            redacted = True
            return "[REDACTED]"
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if _PRIVATE_KEY.search(str(key)):
                    result[str(key)] = "[REDACTED]"
                    redacted = True
                else:
                    result[clean_text(str(key))] = clean_object(item, depth + 1)
            return result
        if isinstance(value, list):
            return [clean_object(item, depth + 1) for item in value]
        return clean_text(value) if isinstance(value, str) else value

    evidence: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "http_status": http_status,
        "body_bytes": len(body), "body_sha256": sha256(body).hexdigest(),
        "body_complete": body_complete,
        "body_sha256_scope": "full_body" if body_complete else "observed_prefix",
        "content_scope": content_scope,
    }
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError):
        value = None
    error = value.get("error", value) if isinstance(value, dict) else None
    fields: dict[str, Any] = {}
    if isinstance(error, dict):
        for key in ("code", "type", "param"):
            raw = error.get(key)
            if isinstance(raw, str):
                cleaned = clean_text(raw)
                if cleaned == raw and _IDENTIFIER.fullmatch(cleaned):
                    fields[key] = cleaned
                else:
                    fields[key] = "[REDACTED]"
                    redacted = True
        if isinstance(error.get("message"), str):
            message = clean_text(error["message"], message=True)
            fields["message"] = message[:MAX_MESSAGE_CHARS]
            evidence["message_truncated"] = len(message) > MAX_MESSAGE_CHARS
        diagnostic = error.get("diagnostic")
        if error.get("code") == "responses_count_render_failed" and isinstance(diagnostic, dict):
            safe_diagnostic: dict[str, str] = {}
            stage = diagnostic.get("stage")
            if isinstance(stage, str) and stage in {"responses_make_request", "extract_prompt_len"}:
                safe_diagnostic["stage"] = stage
            for key in ("exception_class", "exception_module"):
                raw = diagnostic.get(key)
                if isinstance(raw, str) and clean_text(raw) == raw and _IDENTIFIER.fullmatch(raw):
                    safe_diagnostic[key] = raw
            if safe_diagnostic:
                fields["diagnostic"] = safe_diagnostic
    evidence["provider_error"] = fields
    if content_scope == "synthetic":
        # Synthetic probes contain no scientific evidence, but credentials and
        # credential-bearing fields are still removed before this extra audit.
        sanitized = json.dumps(clean_object(value), ensure_ascii=False) if value is not None else clean_text(body.decode("utf-8", errors="replace"))
        evidence["sanitized_body"] = sanitized[:MAX_SYNTHETIC_BODY_CHARS]
        evidence["sanitized_body_truncated"] = len(sanitized) > MAX_SYNTHETIC_BODY_CHARS
    else:
        evidence["raw_body_omitted"] = True
    evidence["redacted"] = redacted
    return evidence


def read_failure_evidence(stream: Any, **kwargs: Any) -> dict[str, Any]:
    """Read at most the bound plus one byte; failures still have a receipt."""
    try:
        body = stream.read(MAX_BODY_BYTES + 1)
        if not isinstance(body, bytes):
            raise ValueError("invalid error body stream")
    except Exception:
        return {**failure_evidence(b"", body_complete=False, **kwargs), "body_read_failed": True}
    return failure_evidence(body, body_complete=len(body) <= MAX_BODY_BYTES, **kwargs)
