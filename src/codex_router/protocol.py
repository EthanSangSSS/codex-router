import json
from typing import Any, Iterable, Mapping


PROTOCOL = "codex-router/v1"
MARKER_PREFIX = "[CODEX_ROUTER_V1]\n"
STAGES = ("local_sol", "web_sol", "luna")


class ProtocolError(ValueError):
    pass


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
