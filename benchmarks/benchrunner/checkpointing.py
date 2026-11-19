"""Crash-safe provider-turn replay for ReAct work items."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any

from benchmarks.react_report_building.runtime.providers.base import (
    Provider,
    ProviderToolCall,
    ProviderTurn,
)
from benchmarks.react_report_building.runtime.provider_cost import (
    normalize_provider_cost,
)
from benchmarks.react_report_building.util import sha256_json

from .checkpoints import CheckpointSink


CHECKPOINT_SCHEMA_VERSION = "benchrunner.provider_turn_checkpoint/v1"


class CheckpointMismatchError(RuntimeError):
    """Raised when saved paid work no longer matches the reconstructed request."""


class CheckpointingProvider:
    """Persist every completed provider turn before tool execution continues.

    Scheduler retries reconstruct an episode from its immutable work identity.
    Matching turns are replayed locally, so a later failed turn can be retried
    without paying for earlier successful turns again.  The small unavoidable
    failure window is the interval between the HTTP response arriving and the
    run-store checkpoint transaction completing.
    """

    def __init__(
        self,
        provider: Provider,
        checkpoints: CheckpointSink,
        *,
        work_identity: dict[str, Any],
        turn_index_offset: int = 0,
    ) -> None:
        self.provider = provider
        self.checkpoints = checkpoints
        self.work_identity = work_identity
        if type(turn_index_offset) is not int or turn_index_offset < 0:
            raise ValueError("turn_index_offset must be a non-negative integer")
        self.turn_index_offset = turn_index_offset
        self.name = str(getattr(provider, "name", "unknown"))
        self.model = str(getattr(provider, "model", "unknown"))
        self.transport = str(
            getattr(provider, "transport", self.name)
        )
        self.action_protocol = str(
            getattr(provider, "action_protocol", "textual_json")
        )
        self.action_interface_version = getattr(
            provider, "action_interface_version", None
        )
        self.action_output_contract = getattr(
            provider, "action_output_contract", None
        )
        self.action_output_schema_version = getattr(
            provider, "action_output_schema_version", None
        )
        self.profile_id = getattr(provider, "profile_id", None)
        raw_provider_routing = getattr(
            provider, "provider_routing_provenance", None
        )
        self.provider_routing_provenance = (
            deepcopy(raw_provider_routing)
            if isinstance(raw_provider_routing, dict)
            else None
        )

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        episode: Any,
    ) -> ProviderTurn:
        turn_index = len(getattr(episode, "turns", ()))
        name = f"provider-turn-{self.turn_index_offset + turn_index:03d}"
        fingerprint = self._request_fingerprint(messages, episode)
        saved = self.checkpoints.load(name)
        if saved is not None:
            if (
                not isinstance(saved, dict)
                or saved.get("schema_version") != CHECKPOINT_SCHEMA_VERSION
                or saved.get("request_sha256") != fingerprint
            ):
                raise CheckpointMismatchError(
                    f"saved checkpoint {name!r} does not match the rebuilt request"
                )
            return _decode_turn(saved.get("provider_turn"))

        turn = self.provider.complete(messages, episode=episode)
        self.checkpoints.save(
            name,
            {
                "schema_version": CHECKPOINT_SCHEMA_VERSION,
                "request_sha256": fingerprint,
                "provider_turn": _encode_turn(turn),
            },
        )
        return turn

    def _request_fingerprint(
        self,
        messages: list[dict[str, str]],
        episode: Any,
    ) -> str:
        provider_identity = {
            "name": self.name,
            "model": self.model,
            "transport": self.transport,
            "profile_id": self.profile_id,
            "action_protocol": self.action_protocol,
        }
        if self.action_interface_version:
            provider_identity["action_interface_version"] = str(
                self.action_interface_version
            )
        if self.action_output_contract:
            provider_identity["action_output_contract"] = str(
                self.action_output_contract
            )
        if self.action_output_schema_version:
            provider_identity["action_output_schema_version"] = str(
                self.action_output_schema_version
            )
        if self.provider_routing_provenance is not None:
            provider_identity["provider_routing"] = deepcopy(
                self.provider_routing_provenance
            )
        for field_name in ("final_turn_tool_choice_provenance", "context_budget_provenance", "generation_seed"):
            value = getattr(self.provider, field_name, None)
            if value is not None:
                provider_identity[field_name] = deepcopy(value)
        return sha256_json(
            {
                "work_identity": self.work_identity,
                "provider": provider_identity,
                "episode": {
                    "episode_id": getattr(episode, "episode_id", None),
                    "episode_kind": getattr(episode, "episode_kind", None),
                    "project_id": getattr(episode, "project_id", None),
                    "section_id": getattr(episode, "section_id", None),
                    "allowed_tools": sorted(
                        getattr(episode, "allowed_tools", ())
                    ),
                    "turn_policy": getattr(
                        episode, "turn_policy", "unrestricted"
                    ),
                    **({"terminal_protocol_version": episode.terminal_protocol_version}
                       if getattr(episode, "terminal_protocol_version", "react_report.terminal_protocol/v1")
                       != "react_report.terminal_protocol/v1" else {}),
                    "messages": messages,
                    "turns": getattr(episode, "turns", ()),
                },
            }
        )


def _encode_turn(turn: ProviderTurn) -> dict[str, Any]:
    if not isinstance(turn, ProviderTurn):
        raise TypeError("provider returned a non-ProviderTurn value")
    return {
        "text": turn.text,
        "tool_calls": (
            [asdict(call) for call in turn.tool_calls]
            if turn.tool_calls is not None
            else None
        ),
        "protocol_error": turn.protocol_error,
        "raw_response": turn.raw_response,
        "usage": turn.usage,
        "latency_seconds": turn.latency_seconds,
        "provider_request_id": turn.provider_request_id,
        "transport": turn.transport,
        "action_protocol": turn.action_protocol,
        "normalizations": turn.normalizations,
        "request_context": turn.request_context,
        "provider_cost": normalize_provider_cost(turn.provider_cost),
    }


def _decode_turn(value: Any) -> ProviderTurn:
    if not isinstance(value, dict):
        raise CheckpointMismatchError("saved provider turn is not an object")
    raw_calls = value.get("tool_calls")
    if raw_calls is not None and not isinstance(raw_calls, list):
        raise CheckpointMismatchError("saved provider tool calls are not a list")
    raw_normalizations = value.get("normalizations") or []
    if not isinstance(raw_normalizations, list) or any(
        not isinstance(item, dict) for item in raw_normalizations
    ):
        raise CheckpointMismatchError(
            "saved provider normalizations are not a list of objects"
        )
    raw_request_context = value.get("request_context") or {}
    if not isinstance(raw_request_context, dict):
        raise CheckpointMismatchError(
            "saved provider request context is not an object"
        )
    try:
        calls = (
            [ProviderToolCall(**item) for item in raw_calls]
            if raw_calls is not None
            else None
        )
        return ProviderTurn(
            text=str(value.get("text") or ""),
            tool_calls=calls,
            protocol_error=value.get("protocol_error"),
            raw_response=value.get("raw_response"),
            usage=dict(value.get("usage") or {}),
            latency_seconds=float(value.get("latency_seconds") or 0.0),
            provider_request_id=value.get("provider_request_id"),
            transport=value.get("transport"),
            action_protocol=value.get("action_protocol"),
            normalizations=[dict(item) for item in raw_normalizations],
            request_context=dict(raw_request_context),
            provider_cost=normalize_provider_cost(value.get("provider_cost")),
        )
    except (TypeError, ValueError) as exc:
        raise CheckpointMismatchError("saved provider turn is malformed") from exc
