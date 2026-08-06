import hashlib
import hmac
import json
import re
from typing import Any, Iterable, Mapping
import unicodedata


PROTOCOL = "codex-router/v1"
MARKER_PREFIX = "[CODEX_ROUTER_V1]\n"
STAGES = ("local_sol", "web_sol", "luna")
RUN_PROTOCOL = "codex-router/run-state/v1"
PACKET_PROTOCOL = "codex-router/stage-packet/v1"
WEB_RESPONSE_PREFIX = "[CODEX_ROUTER_RESPONSE_V1]"
_PACKET_KEYS = {
    "protocol",
    "driver_context_id",
    "run_id",
    "packet_id",
    "target_stage",
    "source_revision",
    "payload",
    "packet_digest",
}
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


class ProtocolError(ValueError):
    pass


def normalize_content(value: str) -> str:
    if not isinstance(value, str):
        raise ProtocolError("content must be text")
    normalized = unicodedata.normalize(
        "NFC", value.replace("\r\n", "\n").replace("\r", "\n")
    )
    try:
        normalized.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ProtocolError("content must be valid UTF-8 text") from error
    return normalized


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", errors="strict")


def digest_json(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def build_stage_packet(
    *,
    driver_context_id: str,
    run_id: str,
    packet_id: str,
    target_stage: str,
    source_revision: int,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if target_stage not in STAGES:
        raise ProtocolError(f"unknown stage: {target_stage}")
    for name, value in (
        ("driver_context_id", driver_context_id),
        ("run_id", run_id),
        ("packet_id", packet_id),
    ):
        if not isinstance(value, str) or not value:
            raise ProtocolError(f"{name} is required")
    if not isinstance(source_revision, int) or isinstance(source_revision, bool):
        raise ProtocolError("source_revision must be an integer")
    if source_revision < 0:
        raise ProtocolError("source_revision must not be negative")
    if not isinstance(payload, Mapping):
        raise ProtocolError("payload must be an object")
    packet = {
        "protocol": PACKET_PROTOCOL,
        "driver_context_id": driver_context_id,
        "run_id": run_id,
        "packet_id": packet_id,
        "target_stage": target_stage,
        "source_revision": source_revision,
        "payload": dict(payload),
    }
    return {**packet, "packet_digest": digest_json(packet)}


def validate_stage_packet(
    packet: Mapping[str, Any],
    *,
    expected_driver_context_id: str | None = None,
    expected_run_id: str | None = None,
    expected_target_stage: str | None = None,
    expected_source_revision: int | None = None,
) -> None:
    if not isinstance(packet, Mapping) or set(packet) != _PACKET_KEYS:
        raise ProtocolError("stage packet schema is invalid")
    if packet.get("protocol") != PACKET_PROTOCOL:
        raise ProtocolError("stage packet protocol is invalid")
    for name in ("driver_context_id", "run_id", "packet_id"):
        if not isinstance(packet.get(name), str) or not packet[name]:
            raise ProtocolError("stage packet identity is invalid")
    if packet.get("target_stage") not in STAGES:
        raise ProtocolError("stage packet target is invalid")
    source_revision = packet.get("source_revision")
    if (
        not isinstance(source_revision, int)
        or isinstance(source_revision, bool)
        or source_revision < 0
    ):
        raise ProtocolError("stage packet revision is invalid")
    if not isinstance(packet.get("payload"), Mapping):
        raise ProtocolError("stage packet payload is invalid")
    stored_digest = packet.get("packet_digest")
    if not isinstance(stored_digest, str) or _SHA256_PATTERN.fullmatch(stored_digest) is None:
        raise ProtocolError("stage packet digest is malformed")
    unsigned = {key: value for key, value in packet.items() if key != "packet_digest"}
    try:
        recomputed = digest_json(unsigned)
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise ProtocolError("stage packet is not canonical JSON") from error
    if not hmac.compare_digest(stored_digest, recomputed):
        raise ProtocolError("stage packet digest does not match its content")
    expected = {
        "driver_context_id": expected_driver_context_id,
        "run_id": expected_run_id,
        "target_stage": expected_target_stage,
        "source_revision": expected_source_revision,
    }
    for name, expected_value in expected.items():
        if expected_value is not None and packet.get(name) != expected_value:
            raise ProtocolError("stage packet does not match canonical state")


def submission_digest(
    driver_context_id: str,
    run_id: str,
    stage: str,
    packet_digest: str,
    content: str,
    stable_execution_metadata: Mapping[str, Any],
) -> str:
    return digest_json(
        {
            "driver_context_id": driver_context_id,
            "run_id": run_id,
            "stage": stage,
            "packet_digest": packet_digest,
            "normalized_content": normalize_content(content),
            "stable_execution_metadata": dict(stable_execution_metadata),
        }
    )


def failure_digest(
    driver_context_id: str,
    run_id: str,
    stage: str,
    packet_digest: str,
    failure: Mapping[str, Any],
    stable_execution_metadata: Mapping[str, Any],
) -> str:
    return digest_json(
        {
            "driver_context_id": driver_context_id,
            "run_id": run_id,
            "stage": stage,
            "packet_digest": packet_digest,
            "failure": dict(failure),
            "stable_execution_metadata": dict(stable_execution_metadata),
        }
    )


def web_response_marker(packet: Mapping[str, Any]) -> str:
    required = {
        "driver_context_id": packet.get("driver_context_id"),
        "run_id": packet.get("run_id"),
        "stage": packet.get("target_stage"),
        "revision": packet.get("source_revision"),
        "packet_id": packet.get("packet_id"),
        "packet_digest": packet.get("packet_digest"),
    }
    if packet.get("protocol") != PACKET_PROTOCOL:
        raise ProtocolError("invalid stage packet protocol")
    if required["stage"] != "web_sol":
        raise ProtocolError("Web response marker requires a web_sol packet")
    if any(value is None or value == "" for value in required.values()):
        raise ProtocolError("stage packet is missing marker identity")
    return (
        f"{WEB_RESPONSE_PREFIX} "
        f"driver_context_id={required['driver_context_id']} "
        f"run_id={required['run_id']} "
        f"stage={required['stage']} "
        f"revision={required['revision']} "
        f"packet_id={required['packet_id']} "
        f"packet_digest={required['packet_digest']}"
    )


def validate_web_response(content: str, packet: Mapping[str, Any]) -> None:
    normalized = normalize_content(content)
    marker = web_response_marker(packet)
    nonempty_lines = [line for line in normalized.split("\n") if line.strip()]
    if not nonempty_lines or nonempty_lines[0] != marker:
        raise ProtocolError("Web response marker must be the first non-empty line")
    if normalized.count(marker) != 1:
        raise ProtocolError("Web response marker must occur exactly once")


def make_handoff(run_id: str, stage: str, content: str) -> dict[str, str]:
    if stage not in STAGES:
        raise ProtocolError(f"unknown stage: {stage}")
    if not run_id:
        raise ProtocolError("run_id is required")
    return {
        "router_protocol": PROTOCOL,
        "run_id": run_id,
        "stage": stage,
        "content": content,
    }


def serialize_handoff_item(envelope: Mapping[str, str]) -> dict[str, Any]:
    payload = json.dumps(dict(envelope), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": MARKER_PREFIX + payload}],
    }


def find_router_handoff(
    records: Iterable[Mapping[str, Any]], run_id: str, stage: str
) -> dict[str, str]:
    matches: list[dict[str, str]] = []
    for record in records:
        if record.get("type") != "response_item":
            continue
        item = record.get("payload")
        if not isinstance(item, Mapping):
            continue
        if item.get("type") != "message" or item.get("role") != "assistant":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, Mapping) or part.get("type") != "output_text":
                continue
            value = part.get("text")
            if not isinstance(value, str) or not value.startswith(MARKER_PREFIX):
                continue
            try:
                envelope = json.loads(value[len(MARKER_PREFIX) :])
            except json.JSONDecodeError as exc:
                raise ProtocolError("invalid router envelope JSON") from exc
            if not isinstance(envelope, dict):
                continue
            if (
                envelope.get("router_protocol") == PROTOCOL
                and envelope.get("run_id") == run_id
                and envelope.get("stage") == stage
                and isinstance(envelope.get("content"), str)
            ):
                matches.append(envelope)
    if not matches:
        raise ProtocolError(f"router handoff not found for {run_id}/{stage}")
    if len(matches) != 1:
        raise ProtocolError(f"duplicate router handoff for {run_id}/{stage}")
    return matches[0]
