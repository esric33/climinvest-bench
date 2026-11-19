from __future__ import annotations

import json
import os
from copy import deepcopy
from hashlib import sha256
from time import monotonic
from typing import Any
from urllib import error, request
from urllib.parse import urlsplit

from benchmarks.benchrunner.providers.profiles import (
    RESPONSES_TEXT_FORMAT,
    STRUCTURED_OUTPUT_DIALECTS,
    VLLM_STRUCTURED_OUTPUTS,
    OpenRouterMetadataError,
    OpenRouterPolicy,
    get_openrouter_treatment,
    sanitize_openrouter_metadata,
    validate_openrouter_metadata,
)
from benchmarks.benchrunner.retry import RETRYABLE_FAILED_RESPONSE_CODES, RetryPolicy, retry_call

from ..provider_cost import provider_cost_from_usage
from ..context_budget import (
    ContextBudgetError,
    InputTokenCounter,
    configured_context_budget,
    serialize_request_payload,
    OPENROUTER_PROBE_ON_CLAMP,
    OPENROUTER_PROBE_MAX_OUTPUT_TOKENS,
    OPENROUTER_PROBE_MAX_OBSERVED_OUTPUT_TOKENS,
)
from ..episode import SPLIT_TERMINAL_PROTOCOL
from ..final_turn_policy import final_turn_policy_provenance, final_turn_tool_choice
from ..protocol import (
    parse_textual_tool_turn,
    render_tool_observations,
)
from ..structured_output import (
    ACTION_JSON_SCHEMA,
    ACTION_JSON_SCHEMA_VERSION,
    ACTION_OUTPUT_CONTRACTS,
    HARMONY_ACTION_OUTPUT_TOOL_NAME,
    HARMONY_REASONING_ACTION_JSON,
    REASONING_THEN_ACTION_JSON,
    action_json_schema,
    harmony_action_output_tool,
    harmony_reasoning_action_structural_tag,
    is_gpt_oss_model,
    reasoning_boundary_event,
    reasoning_then_action_regex,
    split_reasoning_action,
    validate_action_json,
)
from ..native_tool_policy import validate_native_tool_policy
from ..tool_schemas import (
    openai_responses_tools,
    uses_compact_calculation_actions,
)
from .failure_evidence import failure_evidence, read_failure_evidence
from .base import (
    ProviderConnectionError,
    ProviderHTTPError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderToolCall,
    ProviderTurn,
    messages_for_current_turn,
)


NATIVE_TOOLS = "native_tools"
TEXTUAL_JSON = "textual_json"
ACTION_PROTOCOLS = frozenset({NATIVE_TOOLS, TEXTUAL_JSON})
NATIVE_TOOL_CHOICE = "auto"
NATIVE_ACTION_INTERFACE_VERSION = "react_report.native_tool_interface/v3"
SPLIT_NATIVE_ACTION_INTERFACE_VERSION = "react_report.native_tool_interface/v4"
TEXTUAL_ACTION_INTERFACE_VERSION = "react_report.textual_action_interface/v4"
STRUCTURED_ACTION_INTERFACE_VERSION = "react_report.textual_action_interface/v6"
GPT_OSS_VLLM_CHANNEL_SUFFIX = "<|channel|>commentary"
NATIVE_ACTION_NORMALIZATION_POLICY = {
    "schema_version": "react_report.action_normalization_policy/v4",
    "policy_id": "native_tool_calls/v4",
    "batch_semantics": "ordered_provider_batch",
    "normalization_scope": "none",
    "raw_response_preserved": True,
    "tool_names_and_arguments": "unchanged_for_all_models",
    "malformed_batch_disposition": "atomic_rejection",
    "call_identity": "provider_call_id",
    "single_observation_boundary_per_response": True,
    "terminal_must_be_sole_semantic_action": True,
}
TEXTUAL_ACTION_NORMALIZATION_POLICY = {
    "schema_version": "react_report.action_normalization_policy/v5",
    "policy_id": "contract_aware_textual_action/v6",
    "batch_semantics": "ordered_open_loop",
    "legacy_accepts_multiple_action_envelopes": True,
    "structured_requires_single_action_envelope": True,
    "structured_validation_before_carrier_normalization": True,
    "single_observation_boundary_per_response": True,
    "terminal_must_be_sole_semantic_action": True,
    "recognized_phases": ["commentary", "final_answer"],
    "phase_metadata_required": False,
    "requires_canonical_semantic_equality": True,
    "canonical_exact_duplicate_calls_execute_once": True,
    "duplicate_retention": "first_emitted",
    "normalization_scope": "complete_provider_response",
    "normalized_replay": "synthetic_assistant_semantic_text",
    "distinct_actions_execute_in_emitted_order": True,
}
DEFAULT_API_KEY_ENVS = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ida": "IDA_LLM_API_KEY",
}
FAILED_RESPONSE_COST_DETAIL_KEYS = frozenset(
    {
        "upstream_inference_cost",
        "upstream_inference_input_cost",
        "upstream_inference_output_cost",
    }
)

# Official Responses input_tokens schema, checked 2026-09-05. Generation-only
# fields (max_output_tokens/store/include) do not enter the count request.
# https://developers.openai.com/api/reference/typescript/resources/responses/subresources/input_tokens/methods/count
RESPONSES_INPUT_TOKEN_COUNT_FIELDS = frozenset({
    "model", "input", "instructions", "tools", "tool_choice", "parallel_tool_calls",
    "reasoning", "text", "truncation", "conversation", "previous_response_id", "personality",
})


class ProviderContextBudgetError(ProviderRequestError):
    def __init__(self, failure: ContextBudgetError) -> None:
        super().__init__(str(failure), transport="openai_responses", retryable=False)
        self.code = failure.code
        self.request_context = {"context_budget": deepcopy(failure.receipt)}


class OpenAIResponsesProvider:
    name = "openai_responses"
    transport = "openai_responses"

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        endpoint: str = "https://api.openai.com/v1/responses",
        timeout_seconds: float = 180.0,
        max_output_tokens: int = 8000,
        reasoning_effort: str | None = None,
        generation_seed: int | None = None,
        action_protocol: str = NATIVE_TOOLS,
        action_output_contract: str | None = None,
        profile_id: str = "openai",
        api_key_env: str | None = None,
        structured_output_dialect: str | None = None,
        request_headers: (
            dict[str, str] | tuple[tuple[str, str], ...] | None
        ) = None,
        openrouter_policy: OpenRouterPolicy | None = None,
        final_turn_tool_choice_policy: str | None = None,
        native_tool_policy: str | None = None,
        context_window_tokens: int | None = None,
        context_safety_margin_tokens: int | None = None,
        input_token_count_mode: str | None = None,
        input_token_counter: InputTokenCounter | None = None,
        input_token_counter_id: str | None = None,
        context_probe_max_requests: int | None = None,
        context_probe_max_cost_usd: str | None = None,
        context_probe_budget: Any = None,
        context_probe_retry_policy: Any = None,
        diagnostic_content_scope: str = "scientific",
    ) -> None:
        if diagnostic_content_scope not in {"scientific", "synthetic"}:
            raise ValueError("invalid diagnostic content scope")
        self.diagnostic_content_scope = diagnostic_content_scope
        if action_protocol not in ACTION_PROTOCOLS:
            choices = ", ".join(sorted(ACTION_PROTOCOLS))
            raise ValueError(
                f"unknown Responses action protocol {action_protocol!r}; "
                f"choose from {choices}"
            )
        self.profile_id = str(profile_id).strip().lower() or "openai"
        if generation_seed is not None:
            if type(generation_seed) is not int or not 0 <= generation_seed <= 2_147_483_647:
                raise ValueError("generation_seed must be an integer between 0 and 2147483647")
            if self.profile_id not in {"ida", "openrouter"}:
                raise ValueError("direct OpenAI Responses does not support a generation seed")
        self.generation_seed = generation_seed
        self.structured_output_dialect = structured_output_dialect or (
            VLLM_STRUCTURED_OUTPUTS
            if self.profile_id == "ida"
            else RESPONSES_TEXT_FORMAT
        )
        if self.structured_output_dialect not in STRUCTURED_OUTPUT_DIALECTS:
            raise ValueError("unsupported Responses structured-output dialect")
        normalized_request_headers = _normalize_request_headers(request_headers)
        if (
            action_output_contract is not None
            and action_output_contract not in ACTION_OUTPUT_CONTRACTS
        ):
            choices = ", ".join(sorted(ACTION_OUTPUT_CONTRACTS))
            raise ValueError(
                f"unknown action output contract {action_output_contract!r}; "
                f"choose from {choices}"
            )
        if action_output_contract is not None and action_protocol != TEXTUAL_JSON:
            raise ValueError(
                "structured action output is supported only with textual_json"
            )
        if (
            action_output_contract
            in {HARMONY_REASONING_ACTION_JSON, REASONING_THEN_ACTION_JSON}
            and self.structured_output_dialect != VLLM_STRUCTURED_OUTPUTS
        ):
            raise ValueError(
                f"{action_output_contract} requires the vLLM "
                "structured_outputs extension"
            )
        if (
            action_output_contract == HARMONY_REASONING_ACTION_JSON
            and not is_gpt_oss_model(model)
        ):
            raise ValueError(
                "harmony_reasoning_action_json requires a GPT-OSS model"
            )
        if self.profile_id == "openrouter":
            if openrouter_policy is None:
                raise ValueError(
                    "openrouter: an explicit routing/privacy policy is required"
                )
            treatment = get_openrouter_treatment(model)
            if openrouter_policy != treatment.policy:
                raise ValueError(
                    f"openrouter: policy does not match the approved treatment for {model}"
                )
            if reasoning_effort != treatment.reasoning_effort:
                raise ValueError(
                    "openrouter: reasoning effort does not match the approved "
                    f"treatment for {model}"
                )
            normalized_headers = {
                name.casefold(): value.casefold()
                for name, value in normalized_request_headers.items()
            }
            if (
                self.structured_output_dialect != RESPONSES_TEXT_FORMAT
                or normalized_headers.get("x-openrouter-metadata") != "enabled"
                or normalized_headers.get("x-openrouter-cache") != "false"
            ):
                raise ValueError(
                    "openrouter: standard Responses output, router metadata, "
                    "and explicit cache bypass are required"
                )
        elif openrouter_policy is not None:
            raise ValueError(
                "openrouter_policy is supported only by the openrouter profile"
            )
        self.model = model
        self.api_key_env = api_key_env or DEFAULT_API_KEY_ENVS.get(
            self.profile_id,
            "OPENAI_API_KEY",
        )
        self.api_key = (
            api_key
            if api_key is not None
            else os.environ.get(self.api_key_env, "")
        )
        self.endpoint = endpoint
        self.context_budget = configured_context_budget(
            context_window_tokens=context_window_tokens,
            context_safety_margin_tokens=context_safety_margin_tokens,
            input_token_count_mode=input_token_count_mode,
            input_token_counter_id=input_token_counter_id,
            context_probe_max_requests=context_probe_max_requests,
            context_probe_max_cost_usd=context_probe_max_cost_usd,
        )
        if input_token_count_mode == "openai_responses" and (
            self.profile_id != "openai"
            or endpoint.rstrip("/") != "https://api.openai.com/v1/responses"
        ):
            raise ValueError("openai_responses token counting requires the direct official OpenAI endpoint")
        if input_token_count_mode == "responses_probe":
            raise ValueError("generation-backed self-hosted counting is retired; use vllm_responses")
        if input_token_count_mode == "vllm_responses" and (
            self.profile_id != "ida"
            or (urlsplit(endpoint).hostname or "").lower() in {"api.openai.com", "openrouter.ai"}
        ):
            raise ValueError("vllm_responses token counting requires a self-hosted ida endpoint")
        if (
            input_token_count_mode == "injected" and not callable(input_token_counter)
        ) or (
            input_token_count_mode != "injected" and input_token_counter is not None
        ):
            raise ValueError("injected mode requires an input_token_counter; other modes prohibit it")
        self.input_token_counter = input_token_counter
        self.context_probe_budget = context_probe_budget
        self.context_probe_retry_policy = context_probe_retry_policy or RetryPolicy(max_attempts=1)
        if input_token_count_mode == OPENROUTER_PROBE_ON_CLAMP:
            if (self.profile_id != "openrouter"
                    or endpoint.rstrip("/") != "https://openrouter.ai/api/v1/responses"):
                raise ValueError("conditional paid counting requires an explicit treatment on the official OpenRouter endpoint")
            if context_probe_budget is None or not all(callable(getattr(context_probe_budget, name, None)) for name in ("reserve", "settle", "snapshot")):
                raise ValueError("conditional paid counting requires a durable context probe budget")
            limits = context_probe_budget.snapshot()
            from decimal import Decimal
            if (limits["max_requests"] > context_probe_max_requests
                    or Decimal(limits["max_cost_usd"]) > Decimal(self.context_budget.context_probe_max_cost_usd)):
                raise ValueError("probe ledger cannot exceed the declared treatment limits")
        elif context_probe_budget is not None:
            raise ValueError("a paid context probe budget requires openrouter_probe_on_clamp")
        self.context_budget_provenance = self.context_budget.provenance() if self.context_budget else None
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self.reasoning_effort = reasoning_effort
        self.native_tool_policy = native_tool_policy
        self.native_tool_policy_provenance = validate_native_tool_policy(
            native_tool_policy, action_protocol=action_protocol,
            final_turn_tool_choice_policy=final_turn_tool_choice_policy)
        self.final_turn_tool_choice_policy = final_turn_tool_choice_policy
        self.final_turn_tool_choice_provenance = final_turn_policy_provenance(final_turn_tool_choice_policy)
        self.request_headers = normalized_request_headers
        self.openrouter_policy = openrouter_policy
        self.provider_routing_provenance = (
            {
                "schema_version": "benchrunner.openrouter_routing/v1",
                **openrouter_policy.as_config(),
                "router_metadata_requested": (
                    any(
                        name.casefold() == "x-openrouter-metadata"
                        and value.casefold() == "enabled"
                        for name, value in self.request_headers.items()
                    )
                ),
            }
            if openrouter_policy is not None
            else None
        )
        self.action_protocol = action_protocol
        self.action_output_contract = action_output_contract
        self.action_output_schema_version = (
            ACTION_JSON_SCHEMA_VERSION
            if action_output_contract is not None
            else None
        )
        self.action_interface_version = (
            NATIVE_ACTION_INTERFACE_VERSION
            if action_protocol == NATIVE_TOOLS
            else (
                STRUCTURED_ACTION_INTERFACE_VERSION
                if action_output_contract is not None
                else TEXTUAL_ACTION_INTERFACE_VERSION
            )
        )

    def complete(self, messages: list[dict[str, str]], *, episode: Any) -> ProviderTurn:
        request_context: dict[str, Any] = {}
        try:
            return self._complete(messages, episode=episode, request_context_out=request_context)
        except ProviderRequestError as exc:
            # A generation failure must not erase completed preflight work.
            if request_context.get("context_budget"):
                exc.request_context = deepcopy(request_context)
            raise

    def _build_request(
        self,
        messages: list[dict[str, str]],
        *,
        episode: Any,
    ) -> tuple[dict[str, Any], dict[str, Any], Any, bool]:
        if not self.api_key:
            raise RuntimeError(f"{self.api_key_env} is not configured")
        if self.action_protocol == NATIVE_TOOLS:
            messages = messages_for_current_turn(messages, episode)
            self.action_interface_version = (
                SPLIT_NATIVE_ACTION_INTERFACE_VERSION
                if getattr(episode, "terminal_protocol_version", None) == SPLIT_TERMINAL_PROTOCOL
                else NATIVE_ACTION_INTERFACE_VERSION
            )
        if getattr(episode, "terminal_protocol_version", None) == SPLIT_TERMINAL_PROTOCOL:
            if self.action_protocol != NATIVE_TOOLS:
                raise ValueError("the corrected terminal protocol requires native_tools")
        native_tools = (
            openai_responses_tools(episode, strict=self.native_tool_policy is not None)
            if self.action_protocol == NATIVE_TOOLS
            else []
        )
        action_instruction = None
        if self.action_protocol == TEXTUAL_JSON:
            action_instruction = (
                structured_json_action_instruction(
                    episode,
                    reasoning_prefixed=(
                        self.action_output_contract == REASONING_THEN_ACTION_JSON
                    ),
                    harmony_carrier=(
                        self.action_output_contract == HARMONY_REASONING_ACTION_JSON
                    ),
                )
                if self.action_output_contract is not None
                else textual_json_action_instruction(episode)
            )
        constraint_payload, constraint_context = self._output_constraint(episode)
        wire_tools = list(native_tools)
        harmony_carrier = (
            self.action_output_contract == HARMONY_REASONING_ACTION_JSON
        )
        if harmony_carrier:
            wire_tools = [harmony_action_output_tool(episode)]
        responses_input = (
            build_responses_input(
                messages,
                episode.turns,
                tools=native_tools,
            )
            if self.action_protocol == NATIVE_TOOLS
            else build_textual_responses_input(
                messages,
                episode,
                action_instruction=action_instruction,
            )
        )
        top_level_instructions = None
        initial_item_count = min(2, len(messages))
        uses_vllm_gpt_oss_compatibility = (
            self.action_protocol == NATIVE_TOOLS
            and self.profile_id == "ida"
            and is_gpt_oss_model(self.model)
        )
        if uses_vllm_gpt_oss_compatibility:
            top_level_instructions, responses_input = (
                promote_initial_system_to_responses_instructions(responses_input)
            )
            if top_level_instructions is not None:
                initial_item_count = max(0, initial_item_count - 1)
        request_context = responses_input_attribution(
            responses_input,
            initial_item_count=initial_item_count,
            replayed_turn_count=len(getattr(episode, "turns", ())),
            action_protocol=self.action_protocol,
            protocol_instruction_characters=len(action_instruction or ""),
            tools=wire_tools,
            action_output_contract=self.action_output_contract,
            structured_constraint=constraint_context,
            top_level_instructions=top_level_instructions,
        )
        if self.provider_routing_provenance is not None:
            request_context["provider_routing"] = deepcopy(
                self.provider_routing_provenance
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "input": responses_input,
            "max_output_tokens": self.max_output_tokens,
            # Each request carries its complete benchmark transcript.  Avoid
            # provider-side conversation state so OpenAI and IDA see the same
            # inputs and resumable checkpoints remain self-contained.
            "store": False,
        }
        if top_level_instructions is not None:
            # vLLM's GPT-OSS Responses renderer treats an input role=system
            # item as the Harmony model identity. Ordinary benchmark system
            # instructions belong in the developer message, which vLLM
            # constructs from this top-level Responses field.
            payload["instructions"] = top_level_instructions
        if self.profile_id == "openai":
            # OpenAI returns encrypted reasoning state for stateless replay
            # only when it is requested explicitly.  IDA is not asked for this
            # OpenAI-specific include so the shared textual protocol stays
            # usable on its compatibility layer.
            payload["include"] = ["reasoning.encrypted_content"]
        if native_tools:
            payload.update(
                tools=native_tools,
                tool_choice=final_turn_tool_choice(
                    episode, self.final_turn_tool_choice_policy,
                    transport=self.transport,
                    ordinary_choice=(self.native_tool_policy_provenance["ordinary_tool_choice"]
                                     if self.native_tool_policy_provenance is not None else NATIVE_TOOL_CHOICE),
                ),
            )
            # OpenRouter parallel-tool behavior is treatment-specific and is
            # added below by the hash-bound route policy only for endpoints
            # that advertise the parameter.  Sending it generically would
            # filter out otherwise tool-capable pinned endpoints when
            # require_parameters routing is enabled.
            if self.openrouter_policy is None:
                payload["parallel_tool_calls"] = True
        elif harmony_carrier:
            # vLLM's Responses/Harmony path supports only automatic tool
            # choice. The whole-token-stream structural tag below makes this
            # sole synthetic carrier mandatory despite that API spelling.
            payload.update(
                tools=wire_tools,
                tool_choice="auto",
                parallel_tool_calls=False,
            )
        payload.update(constraint_payload)
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        if self.generation_seed is not None:
            payload["seed"] = self.generation_seed
            request_context["generation_seed"] = self.generation_seed
        if self.openrouter_policy is not None:
            payload.update(self.openrouter_policy.request_fields())
        if native_tools and self.native_tool_policy_provenance is not None:
            request_context["native_tool_policy"] = deepcopy(self.native_tool_policy_provenance)
        if native_tools and self.final_turn_tool_choice_provenance is not None:
            request_context["final_turn_tool_choice_policy"] = deepcopy(self.final_turn_tool_choice_provenance)
            request_context["effective_tool_choice"] = deepcopy(payload["tool_choice"])
            # Preserve ordinary parallel retrieval. An explicit final policy
            # narrows the palette and disables parallel terminal emission where
            # the route already supports the parallel parameter.
            if getattr(episode, "turn_phase", None) == "finalization" and "parallel_tool_calls" in payload:
                payload["parallel_tool_calls"] = False
        return payload, request_context, native_tools, uses_vllm_gpt_oss_compatibility

    def prepare_context(self, messages: list[dict[str, str]], *, episode: Any) -> dict[str, Any]:
        """Qualify counting using the production request without an action request."""
        payload, context, _, _ = self._build_request(messages, episode=episode)
        _, context, _ = self._prepare_request(payload, context)
        return context

    def probe_count_transport(self, messages: list[dict[str, str]], *, episode: Any) -> dict[str, Any]:
        """Exercise the production counter on a short request, without padding."""
        payload, context, _, _ = self._build_request(messages, episode=episode)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", **self.request_headers}
        preflight = {}
        budget = {**self.context_budget.provenance(), "probe_triggered": True,
                  "count_kind": "estimate", "input_tokens": None, "preflight": preflight}
        context["context_budget"] = budget
        try:
            count = self._openrouter_probe_input_tokens(payload, headers, preflight)
        except Exception as exc:
            failure = ProviderContextBudgetError(ContextBudgetError("input_token_count_failed", budget))
            failure.request_context = deepcopy(context)
            raise failure from None
        budget.update(input_tokens=count, count_kind="exact")
        return context

    def _prepare_request(self, payload: dict[str, Any], request_context: dict[str, Any]):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.request_headers,
        }
        if self.context_budget is not None:
            exact_counter = self.input_token_counter
            preflight_receipt: dict[str, Any] = {}
            if self.context_budget.input_token_count_mode == "openai_responses":
                exact_counter = lambda candidate: self._count_input_tokens(candidate, headers, preflight_receipt)
            elif self.context_budget.input_token_count_mode == "vllm_responses":
                exact_counter = lambda candidate: self._count_vllm_input_tokens(candidate, headers, preflight_receipt)
            elif self.context_budget.input_token_count_mode == OPENROUTER_PROBE_ON_CLAMP:
                exact_counter = lambda candidate: self._openrouter_probe_input_tokens(candidate, headers, preflight_receipt)
            try:
                payload, budget_receipt = self.context_budget.prepare(payload, exact_counter=exact_counter)
            except ContextBudgetError as exc:
                if preflight_receipt:
                    exc.receipt["preflight"] = deepcopy(preflight_receipt)
                failure = ProviderContextBudgetError(exc)
                failure.request_context = {
                    **deepcopy(request_context),
                    "context_budget": deepcopy(exc.receipt),
                }
                raise failure from None
            if preflight_receipt:
                budget_receipt["preflight"] = preflight_receipt
            request_context["context_budget"] = budget_receipt
        body = serialize_request_payload(payload)
        request_context["request_payload_sha256"] = sha256(body).hexdigest()
        return payload, request_context, headers

    def _complete(self, messages: list[dict[str, str]], *, episode: Any,
                  request_context_out: dict[str, Any]) -> ProviderTurn:
        payload, request_context, native_tools, uses_vllm_gpt_oss_compatibility = self._build_request(messages, episode=episode)
        payload, request_context, headers = self._prepare_request(payload, request_context)
        request_context_out.update(deepcopy(request_context))
        body = serialize_request_payload(payload)
        call = request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers=headers,
        )
        started = monotonic()
        try:
            with request.urlopen(call, timeout=self.timeout_seconds) as response:
                raw_value = response.read()
        except error.HTTPError as exc:
            failure = ProviderHTTPError(
                transport=self.transport,
                status_code=int(exc.code),
                provider_request_id=_header_value(
                    exc.headers,
                    "x-request-id",
                    "request-id",
                    "x-generation-id",
                ),
                retry_after_seconds=_retry_after_seconds(exc.headers),
            )
            failure.failure_evidence = read_failure_evidence(
                exc, http_status=int(exc.code), request_payload=body,
                credentials=(str(self.api_key or ""),), content_scope=self.diagnostic_content_scope)
            # Close the HTTPError stream after preserving bounded sanitized facts.
            try:
                exc.close()
            except (OSError, ValueError):
                # Cleanup must not replace the stable, sanitized failure with
                # an implementation-specific stream-finalization exception.
                pass
            raise failure from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise ProviderConnectionError(transport=self.transport) from exc
        try:
            decoded_value = raw_value.decode("utf-8")
            value = json.loads(decoded_value)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderResponseError(
                transport=self.transport,
                code="invalid_json",
            ) from exc
        if not isinstance(value, dict):
            raise ProviderResponseError(
                transport=self.transport,
                code="non_object_envelope",
            )
        try:
            _raise_for_retryable_native_response_failure(
                value,
                action_protocol=self.action_protocol,
                transport=self.transport,
                decoded_value=decoded_value,
                latency_seconds=monotonic() - started,
            )
        except ProviderResponseError as exc:
            exc.failure_evidence = failure_evidence(raw_value, http_status=200,
                request_payload=body, credentials=(str(self.api_key or ""),),
                content_scope=self.diagnostic_content_scope)
            raise
        tool_calls, text, normalizations = _extract_native_turn_details(
            value,
            action_protocol=self.action_protocol,
            action_output_contract=self.action_output_contract,
            episode=episode,
        )
        raw_usage = value.get("usage")
        try:
            # Decode a cost-only view with JSON decimals retained as their
            # source strings. The ordinary response stays conventionally
            # decoded for parsers and raw-response compatibility.
            precise_value = json.loads(decoded_value, parse_float=str)
            precise_usage = (
                precise_value.get("usage")
                if isinstance(precise_value, dict)
                else None
            )
            provider_cost = (
                provider_cost_from_usage(precise_usage)
                if isinstance(precise_usage, dict)
                else {}
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderResponseError(
                transport=self.transport,
                code="invalid_provider_cost",
            ) from exc
        usage = normalize_usage(raw_usage)
        if self.openrouter_policy is not None:
            try:
                routing_metadata = validate_openrouter_metadata(
                    value.get("openrouter_metadata"),
                    expected_model=self.model,
                    expected_provider=self.openrouter_policy.provider.only[0],
                )
            except OpenRouterMetadataError as exc:
                raise ProviderResponseError(
                    transport=self.transport,
                    code=exc.code,
                ) from None
        else:
            routing_metadata = sanitize_openrouter_metadata(
                value.get("openrouter_metadata")
            )
        if routing_metadata is not None:
            request_context["openrouter_metadata"] = routing_metadata
        if self.action_protocol == TEXTUAL_JSON:
            protocol_error = None
            if tool_calls:
                protocol_error = (
                    "textual Responses transport unexpectedly returned native "
                    "function_call items"
                )
            elif self.action_output_contract == REASONING_THEN_ACTION_JSON and (
                sum(
                    item.get("kind") == "reasoning_prefixed_textual_action"
                    for item in normalizations
                )
                != 1
                or any(
                    item.get("kind") == "reasoning_boundary_rejected"
                    for item in normalizations
                )
            ):
                protocol_error = (
                    "reasoning-prefixed action did not contain exactly one "
                    "valid </think> boundary"
                )
            elif self.action_output_contract is not None:
                try:
                    validate_action_json(text, episode)
                except ValueError as exc:
                    protocol_error = str(exc)
            normalized_calls = None
        else:
            protocol_error = _native_response_protocol_error(
                value,
                tool_calls,
                tools_requested=bool(native_tools),
            )
            normalized_calls = tool_calls if protocol_error is None else None
        return ProviderTurn(
            text=text,
            tool_calls=normalized_calls,
            protocol_error=protocol_error,
            raw_response=value,
            usage=usage,
            latency_seconds=monotonic() - started,
            provider_request_id=value.get("id"),
            transport=self.transport,
            action_protocol=self.action_protocol,
            normalizations=normalizations,
            request_context=request_context,
            provider_cost=provider_cost,
        )

    def _count_input_tokens(self, payload, headers, receipt):
        return self._retry_count(lambda single: self._count_input_tokens_once(payload, headers, single), receipt)

    def _count_input_tokens_once(
        self,
        payload: dict[str, Any],
        headers: dict[str, str],
        receipt: dict[str, Any],
    ) -> int:
        count_payload = {
            field: value for field, value in payload.items()
            if field in RESPONSES_INPUT_TOKEN_COUNT_FIELDS
        }
        call = request.Request(
            self.endpoint.rstrip("/") + "/input_tokens",
            data=serialize_request_payload(count_payload),
            method="POST",
            headers=headers,
        )
        receipt.update(kind="openai_input_tokens", generation_requested=False)
        value = self._read_count_response(call, receipt)
        if not isinstance(value, dict) or value.get("object") != "response.input_tokens":
            raise ValueError("invalid input token count envelope")
        return value.get("input_tokens")

    def _count_vllm_input_tokens(self, payload, headers, receipt):
        from benchmarks.benchrunner.providers.vllm_input_tokens import SCHEMA_VERSION, SUPPORTED_VERSIONS
        body = serialize_request_payload(payload)
        receipt.update(kind="self_hosted_responses_count", generation_requested=False,
                       actions_executed=0, input_payload_altered=False, input_token_delta=0)
        call = request.Request(self.endpoint.rstrip("/") + "/input_tokens", data=body,
                               method="POST", headers=headers)
        value = self._read_count_response(call, receipt)
        if not isinstance(value, dict) or value.get("object") != "response.input_tokens":
            raise ValueError("invalid vLLM count envelope")
        details = value.get("counting")
        expected = {"schema_version": SCHEMA_VERSION, "method": "vllm_responses_renderer",
                    "model": self.model, "request_payload_sha256": sha256(body).hexdigest(),
                    "generation_requested": False, "actions_executed": 0,
                    "input_payload_altered": False, "input_token_delta": 0,
                    "render_only_overrides": {"max_output_tokens": 1}}
        if (not isinstance(details, dict)
            or any(type(details.get(k)) is not type(v) or details[k] != v for k, v in expected.items())
            or type(details["render_only_overrides"].get("max_output_tokens")) is not int):
            raise ValueError("vLLM count did not bind the unchanged production input")
        version = details.get("vllm_version")
        digest = details.get("renderer_source_sha256")
        if not isinstance(version, str) or version.split("+", 1)[0] not in SUPPORTED_VERSIONS:
            raise ValueError("unqualified vLLM count renderer version")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("vLLM count renderer digest is missing")
        receipt["counting"] = {**expected, "vllm_version": version, "renderer_source_sha256": digest}
        return value.get("input_tokens")

    @staticmethod
    def _validate_probe_response(value: Any, receipt: dict[str, Any], *, max_observed_output_tokens: int = OPENROUTER_PROBE_MAX_OUTPUT_TOKENS) -> int:
        if not isinstance(value, dict):
            raise ValueError("invalid input token probe envelope")
        usage = value.get("usage")
        if not isinstance(usage, dict) or not {"input_tokens", "output_tokens"}.issubset(usage):
            raise ValueError("input token probe requires measured usage")
        for key in ("input_tokens", "output_tokens"):
            if isinstance(usage[key], bool) or not isinstance(usage[key], int) or usage[key] < 0:
                raise ValueError("invalid input token probe usage")
        normalized_usage = {key: usage[key] for key in ("input_tokens", "output_tokens")}
        for details_key, count_key, output_key in (
            ("output_tokens_details", "reasoning_tokens", "reasoning_tokens"),
            ("input_tokens_details", "cached_tokens", "cached_input_tokens"),
        ):
            details = usage.get(details_key)
            detail = details.get(count_key) if isinstance(details, dict) else None
            if detail is not None and (isinstance(detail, bool) or not isinstance(detail, int) or detail < 0):
                raise ValueError("invalid input token probe usage details")
            # Missing telemetry remains unavailable, not measured zero.
            normalized_usage[output_key] = detail
        receipt["usage"] = normalized_usage
        receipt["actions_executed"] = 0
        receipt.update(requested_output_tokens=OPENROUTER_PROBE_MAX_OUTPUT_TOKENS, observed_output_tokens=usage["output_tokens"],
                       max_observed_output_tokens=max_observed_output_tokens, output_cap_overrun=usage["output_tokens"] > OPENROUTER_PROBE_MAX_OUTPUT_TOKENS)
        if usage["output_tokens"] > max_observed_output_tokens:
            raise ValueError("input token probe exceeded its accepted observed output limit")
        if value.get("status") not in {"completed", "incomplete"} or value.get("error"):
            raise ValueError("failed input token probe")
        return usage["input_tokens"]

    def _openrouter_probe_input_tokens(self, payload: dict[str, Any], headers: dict[str, str],
                                      receipt: dict[str, Any]) -> int:
        return self._retry_count(lambda single: self._openrouter_probe_input_tokens_once(payload, headers, single), receipt)

    def _retry_count(self, count_operation, receipt):
        attempts = []
        def operation():
            single = {}
            try:
                return count_operation(single)
            finally:
                attempts.append(single)
                receipt.clear()
                receipt.update(deepcopy(single))
                receipt["attempts"] = deepcopy(attempts)
                receipt["request_count"] = sum(a.get("request_count", 0) for a in attempts)
                receipt["latency_seconds"] = sum(a.get("latency_seconds", 0) for a in attempts)
                receipt["retry_wait_seconds"] = sum(a.get("retry", {}).get("delay_seconds", 0) for a in attempts)
        def failed(exc, attempt, decision):
            attempts[-1]["retry"] = {"attempt": attempt, "will_retry": decision.retry,
                                    "delay_seconds": decision.delay_seconds, "reason": decision.reason}
            receipt["attempts"] = deepcopy(attempts)
            receipt["retry_wait_seconds"] = sum(a.get("retry", {}).get("delay_seconds", 0) for a in attempts)
        return retry_call(operation, self.context_probe_retry_policy, on_failure=failed)

    def _openrouter_probe_input_tokens_once(self, payload: dict[str, Any], headers: dict[str, str],
                                           receipt: dict[str, Any]) -> int:
        """One separately budgeted inference; its output is never an action."""
        from decimal import Decimal
        from benchmarks.benchrunner.probe_budget import ProbeBudgetError, worst_case_probe_cost

        probe = deepcopy(payload)
        probe["max_output_tokens"] = OPENROUTER_PROBE_MAX_OUTPUT_TOKENS
        body = serialize_request_payload(probe)
        receipt.update(kind="openrouter_responses_probe", generation_requested=True,
                       max_output_tokens=OPENROUTER_PROBE_MAX_OUTPUT_TOKENS, actions_executed=0, request_count=0,
                       latency_seconds=0.0, request_payload_sha256=sha256(body).hexdigest())
        price = self.openrouter_policy.provider.max_price
        worst = worst_case_probe_cost(self.context_budget.context_window_tokens,
                                     price.prompt, price.completion,
                                     max_observed_output_tokens=OPENROUTER_PROBE_MAX_OBSERVED_OUTPUT_TOKENS)
        try:
            reservation = self.context_probe_budget.reserve(
                worst_case_cost_usd=worst, request_payload_sha256=receipt["request_payload_sha256"])
        except ProbeBudgetError as exc:
            receipt["failure_code"] = exc.code
            raise
        valid = False
        observed_cost = None
        try:
            call = request.Request(self.endpoint, data=body, method="POST", headers=headers)
            value = self._read_count_response(call, receipt, precise_cost=True)
            if isinstance(value, dict) and isinstance(value.get("usage"), dict):
                receipt["provider_cost"] = provider_cost_from_usage(value["usage"])
                observed_cost = receipt["provider_cost"].get("total")
            count = self._validate_probe_response(value, receipt, max_observed_output_tokens=OPENROUTER_PROBE_MAX_OBSERVED_OUTPUT_TOKENS)
            if receipt["output_cap_overrun"] and observed_cost is None:
                raise ValueError("probe output overrun requires measured cost settlement")
            reasoning = receipt["usage"].get("reasoning_tokens")
            if reasoning is not None and reasoning > receipt["usage"]["output_tokens"]:
                # This breakdown does not determine the input count. Preserve
                # the provider's numbers without making up corrected usage.
                receipt["usage_warnings"] = ["reasoning_tokens_exceed_output_tokens"]
            cached = receipt["usage"].get("cached_input_tokens")
            if cached is not None and cached > count:
                raise ValueError("probe cached input exceeded its total input count")
            receipt["openrouter_metadata"] = validate_openrouter_metadata(
                value.get("openrouter_metadata"), expected_model=self.model,
                expected_provider=self.openrouter_policy.provider.only[0])
            if count > self.context_budget.context_window_tokens:
                raise ValueError("probe input count exceeded the bound route context window")
            valid = True
            return count
        except Exception:
            receipt["failure_code"] = "openrouter_count_probe_failed"
            raise
        finally:
            # Failed, missing-cost and interrupted probes retain their reserved
            # liability. A reported overrun is charged even on an invalid reply.
            settle_cost = observed_cost if valid or (observed_cost is not None and Decimal(observed_cost) > worst) else None
            try:
                receipt["budget_reservation"] = self.context_probe_budget.settle(
                    reservation, observed_cost_usd=settle_cost,
                    receipt={"status": "completed" if valid else "failed",
                             "request_payload_sha256": receipt["request_payload_sha256"],
                             "latency_seconds": receipt["latency_seconds"],
                             **({"usage_warnings": receipt["usage_warnings"]} if "usage_warnings" in receipt else {}),
                             **receipt.get("usage", {})})
            except ProbeBudgetError as exc:
                receipt["failure_code"] = exc.code
                try:
                    snapshot = self.context_probe_budget.snapshot()
                    reservations = snapshot.pop("reservations", {})
                    if reservation in reservations:
                        receipt["budget_reservation"] = {
                            "reservation_id": reservation,
                            "reservation": reservations[reservation],
                            "budget": snapshot,
                        }
                except ProbeBudgetError:
                    pass
                # The ledger has already retained the liability/overrun. Never
                # issue the main request if settlement cannot be confirmed.
                raise

    def _read_count_response(self, call: request.Request, receipt: dict[str, Any], *, precise_cost: bool = False) -> Any:
        receipt.update(request_count=1, request_payload_sha256=sha256(call.data or b"").hexdigest())
        started = monotonic()
        try:
            with request.urlopen(call, timeout=self.timeout_seconds) as response:
                body = response.read(2_000_001)
                if len(body) > 2_000_000:
                    raise ValueError("count probe response exceeded the audit limit")
                value = json.loads(body.decode("utf-8"), **({"parse_float": str} if precise_cost else {}))
                status = getattr(response, "status", 200)
                receipt["http_status"] = status if isinstance(status, int) else 200
                if isinstance(value, dict) and (value.get("error") or value.get("status") == "failed"):
                    receipt["failure_evidence"] = failure_evidence(body, http_status=receipt["http_status"],
                        request_payload=call.data or b"", credentials=(str(self.api_key or ""),),
                        content_scope=self.diagnostic_content_scope)
                return value
        except error.HTTPError as exc:
            receipt["http_status"] = int(exc.code)
            receipt["failure_evidence"] = read_failure_evidence(exc, http_status=int(exc.code),
                request_payload=call.data or b"", credentials=(str(self.api_key or ""),),
                content_scope=self.diagnostic_content_scope)
            try:
                exc.close()
            except (OSError, ValueError):
                pass
            failure = ProviderHTTPError(status_code=int(exc.code), transport=self.transport,
                                        retry_after_seconds=_retry_after_seconds(exc.headers))
            failure.failure_evidence = receipt["failure_evidence"]
            raise failure from None
        except (error.URLError, TimeoutError, ConnectionError):
            raise ProviderConnectionError(transport=self.transport) from None
        finally:
            receipt["latency_seconds"] = monotonic() - started

    def _output_constraint(
        self,
        episode: Any,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        if self.action_output_contract is None:
            return {}, None
        if self.action_output_contract == ACTION_JSON_SCHEMA:
            schema = action_json_schema(episode)
            if self.structured_output_dialect == RESPONSES_TEXT_FORMAT:
                field = "responses.text.format"
                payload = {
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": "react_report_action",
                            "schema": schema,
                            "strict": True,
                        }
                    }
                }
            else:
                field = "vllm.structured_outputs.json"
                payload = {"structured_outputs": {"json": schema}}
            constraint = schema
            kind = "json_schema"
        elif self.action_output_contract == HARMONY_REASONING_ACTION_JSON:
            field = "vllm.structured_outputs.structural_tag"
            constraint = harmony_reasoning_action_structural_tag(episode)
            payload = {
                "structured_outputs": {
                    "structural_tag": compact_output(constraint)
                }
            }
            kind = "structural_tag"
        elif self.action_output_contract == REASONING_THEN_ACTION_JSON:
            field = "vllm.structured_outputs.regex"
            constraint = reasoning_then_action_regex(episode)
            payload = {"structured_outputs": {"regex": constraint}}
            kind = "regex"
        else:  # pragma: no cover - constructor validation owns this branch.
            raise AssertionError(self.action_output_contract)
        encoded = compact_output(constraint)
        return payload, {
            "contract": self.action_output_contract,
            "schema_version": ACTION_JSON_SCHEMA_VERSION,
            "kind": kind,
            "request_field": field,
            "sha256": sha256(encoded.encode("utf-8")).hexdigest(),
            "serialized_characters": len(encoded),
        }


def extract_native_turn(
    value: dict[str, Any],
    *,
    action_protocol: str = NATIVE_TOOLS,
    action_output_contract: str | None = None,
) -> tuple[list[ProviderToolCall], str]:
    calls, text, _ = _extract_native_turn_details(
        value,
        action_protocol=action_protocol,
        action_output_contract=action_output_contract,
        episode=None,
    )
    return calls, text


def _raise_for_retryable_native_response_failure(
    value: dict[str, Any],
    *,
    action_protocol: str,
    transport: str,
    decoded_value: str,
    latency_seconds: float,
) -> None:
    """Promote an allowlisted failed Responses envelope to a retryable error.

    Responses-compatible gateways can encode a transient upstream failure in
    an otherwise successful HTTP response.  Classify only stable machine
    codes: the provider-controlled message and output may contain request
    content and must never reach a checkpoint or scheduler error artifact.
    Other non-completed envelopes continue through protocol validation.
    """

    if action_protocol != NATIVE_TOOLS or value.get("status") != "failed":
        return
    error_value = value.get("error")
    if not isinstance(error_value, dict):
        return
    raw_message = error_value.get("message")
    if not isinstance(raw_message, str) or not raw_message.strip():
        return
    raw_code = error_value.get("code")
    if not isinstance(raw_code, str):
        return
    code = raw_code.strip().casefold()
    if code not in RETRYABLE_FAILED_RESPONSE_CODES:
        return
    usage, provider_cost = _failed_response_accounting(
        value,
        decoded_value=decoded_value,
    )
    raise ProviderResponseError(
        transport=transport,
        code=code,
        retryable=True,
        usage=usage,
        provider_cost=provider_cost,
        latency_seconds=latency_seconds,
    )


def _failed_response_accounting(
    value: dict[str, Any],
    *,
    decoded_value: str,
) -> tuple[dict[str, int] | None, dict[str, Any]]:
    """Extract only bounded numeric accounting from a failed envelope."""

    raw_usage = value.get("usage")
    usage = _strict_failed_response_usage(raw_usage)
    try:
        precise_value = json.loads(decoded_value, parse_float=str)
        precise_usage = (
            precise_value.get("usage")
            if isinstance(precise_value, dict)
            else None
        )
        provider_cost = (
            _failed_response_cost_from_usage(precise_usage)
            if isinstance(precise_usage, dict)
            else {}
        )
    except (json.JSONDecodeError, TypeError, ValueError, OverflowError):
        provider_cost = {}
    return usage, provider_cost


def _strict_failed_response_usage(value: Any) -> dict[str, int] | None:
    """Keep complete non-negative integer usage; map malformed usage to unknown."""

    if not isinstance(value, dict) or not {
        "input_tokens",
        "output_tokens",
    }.issubset(value):
        return None
    input_details = value.get("input_tokens_details")
    output_details = value.get("output_tokens_details")
    if input_details is None:
        input_details = {}
    if output_details is None:
        output_details = {}
    if not isinstance(input_details, dict) or not isinstance(
        output_details, dict
    ):
        return None
    normalized = {
        "input_tokens": value["input_tokens"],
        "output_tokens": value["output_tokens"],
        "reasoning_tokens": output_details.get("reasoning_tokens", 0),
        "cached_input_tokens": input_details.get("cached_tokens", 0),
    }
    if any(
        isinstance(count, bool)
        or not isinstance(count, int)
        or count < 0
        for count in normalized.values()
    ):
        return None
    return normalized


def _failed_response_cost_from_usage(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize cost after allowlisting failed-response numeric fields."""

    sanitized_usage: dict[str, Any] = {}
    if "cost" in value:
        sanitized_usage["cost"] = value["cost"]
    raw_details = value.get("cost_details")
    if isinstance(raw_details, dict):
        details = {
            key: raw_details[key]
            for key in FAILED_RESPONSE_COST_DETAIL_KEYS
            if key in raw_details
        }
        if details:
            sanitized_usage["cost_details"] = details
    if not sanitized_usage:
        return {}
    return provider_cost_from_usage(sanitized_usage)


def _extract_native_turn_details(
    value: dict[str, Any],
    *,
    action_protocol: str,
    action_output_contract: str | None = None,
    episode: Any | None = None,
) -> tuple[list[ProviderToolCall], str, list[dict[str, Any]]]:
    if (
        action_output_contract is not None
        and (
            value.get("status") != "completed"
            or value.get("error") is not None
        )
    ):
        # A parseable prefix from a token-limited or otherwise incomplete
        # response is not a completed constrained action.
        return [], "", []
    if action_output_contract == HARMONY_REASONING_ACTION_JSON:
        # XGrammar admits exactly one canonical Harmony function carrier. Its
        # arguments are the textual controller action. Preserve those bytes
        # unless the provider-neutral duplicate-call policy deliberately
        # derives a de-duplicated semantic action; the untouched carrier stays
        # in raw_response either way.
        carrier = _harmony_action_output_carrier(value)
        if carrier is None:
            return [], "", []
        output_index, raw_arguments, phase = carrier
        if episode is None:
            return [], raw_arguments, []
        try:
            validate_action_json(raw_arguments, episode)
        except ValueError:
            # Preserve an invalid carrier untouched so the ordinary protocol
            # verifier reports it.  De-duplication is semantic normalization,
            # never a way to repair malformed output.
            return [], raw_arguments, []
        semantic_text, normalization = _response_text(
            [
                {
                    "output_index": output_index,
                    "phase": phase,
                    "text": raw_arguments,
                }
            ],
            action_protocol=action_protocol,
        )
        if normalization is None:
            return [], raw_arguments, []
        return [], semantic_text, [normalization]

    if action_output_contract is not None:
        output = value.get("output") or []
        if (
            not isinstance(output, list)
            or any(
                not isinstance(item, dict)
                or item.get("type") not in {"reasoning", "message"}
                for item in output
            )
        ):
            return [], "", []

    calls: list[ProviderToolCall] = []
    message_actions: list[dict[str, Any]] = []
    for output_index, item in enumerate(value.get("output") or []):
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "function_call":
            raw_arguments = item.get("arguments")
            arguments, argument_error = parse_arguments(raw_arguments)
            calls.append(
                ProviderToolCall(
                    call_id=str(item.get("call_id") or ""),
                    tool=str(item.get("name") or ""),
                    arguments=arguments,
                    error=argument_error,
                )
            )
        if action_protocol == TEXTUAL_JSON and item_type == "mcp_call":
            # Some Responses-compatible Harmony servers serialize an
            # assistant's textual JSON action as a completed ``mcp_call``
            # even when no native tools were attached.  Its ``arguments`` are
            # the complete textual action envelope, not native call arguments.
            # Treat only the successful output-only shape as text; the
            # controller still applies the ordinary textual protocol parser.
            message_text = _textual_mcp_call_arguments(item)
            if message_text:
                message_actions.append(
                    {
                        "output_index": output_index,
                        "phase": item.get("phase"),
                        "text": message_text,
                    }
                )
            continue
        if item_type != "message":
            continue
        if (
            action_output_contract is not None
            and item.get("status") not in (None, "completed")
        ):
            return [], "", []
        content_parts: list[str] = []
        for content in item.get("content") or []:
            if (
                action_output_contract is not None
                and isinstance(content, dict)
                and content.get("type") == "refusal"
            ):
                return [], "", []
            text = content.get("text") if isinstance(content, dict) else None
            if isinstance(text, str):
                content_parts.append(text)
        # Responses may split one message across multiple content chunks.  A
        # message item is the meaningful phase boundary; chunks within it are
        # therefore joined before any textual-action normalization.
        joined_text = "".join(content_parts)
        message_text = (
            joined_text
            if action_output_contract is not None
            else joined_text.strip()
        )
        if message_text:
            message_actions.append(
                {
                    "output_index": output_index,
                    "phase": item.get("phase"),
                    "text": message_text,
                }
            )
    if action_output_contract is not None and len(message_actions) != 1:
        return calls, "", []
    boundary_events: list[dict[str, Any]] = []
    if action_output_contract == REASONING_THEN_ACTION_JSON:
        for message in message_actions:
            try:
                parsed = split_reasoning_action(str(message["text"]))
            except ValueError:
                boundary_events.append(
                    {
                        "schema_version": "react_report.reasoning_boundary/v1",
                        "kind": "reasoning_boundary_rejected",
                        "output_index": int(message["output_index"]),
                        "raw_response_preserved": True,
                    }
                )
                continue
            message["text"] = parsed.action
            boundary_events.append(
                reasoning_boundary_event(
                    parsed,
                    output_index=int(message["output_index"]),
                )
            )
    normalize = action_output_contract is None
    if action_output_contract is not None and episode is not None:
        # Every constrained carrier must already be independently schema-valid
        # before exact duplicates may be collapsed across the response.
        # Otherwise normalization could turn malformed output into an accepted
        # action.  The final verifier still requires one semantic envelope.
        normalize = True
        for message in message_actions:
            try:
                validate_action_json(str(message["text"]), episode)
            except ValueError:
                # Return the exact rejected carrier.  Passing it through
                # `_response_text` would strip outer bytes on its legacy path
                # and could turn decoder-invalid output into valid JSON.
                return calls, str(message_actions[0]["text"]), boundary_events
    text, normalization = _response_text(
        message_actions,
        action_protocol=action_protocol,
        normalize=normalize,
    )
    normalizations = list(boundary_events)
    if normalization is not None:
        normalizations.append(normalization)
    return calls, text, normalizations


def _native_response_protocol_error(
    value: dict[str, Any],
    calls: list[ProviderToolCall],
    *,
    tools_requested: bool,
) -> str | None:
    """Reject native batches that cannot be replayed without invention."""

    if value.get("status") != "completed":
        return "native Responses envelope was not completed"
    if value.get("error") is not None:
        return "native Responses envelope contained an error"
    output = value.get("output")
    if not isinstance(output, list):
        return "native Responses envelope did not contain an output list"
    raw_calls = [
        item
        for item in output
        if isinstance(item, dict) and item.get("type") == "function_call"
    ]
    if tools_requested and not raw_calls:
        return "OpenAI response contained no native function_call items"
    if len(raw_calls) != len(calls):
        return "native Responses function_call extraction was incomplete"

    call_ids: list[str] = []
    for item in raw_calls:
        if "status" not in item or item["status"] not in {None, "completed"}:
            return "native Responses function_call item was not completed"
        call_id = item.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            return "native Responses function_call item had no call_id"
        name = item.get("name")
        if not isinstance(name, str) or not name:
            return "native Responses function_call item had no name"
        call_ids.append(call_id)
    if len(call_ids) != len(set(call_ids)):
        return "native Responses function_call items repeated a call_id"
    return None


def _harmony_action_output_carrier(
    value: dict[str, Any],
) -> tuple[int, str, Any] | None:
    if value.get("status") != "completed":
        return None
    output = value.get("output") or []
    if (
        not isinstance(output, list)
        or len(output) != 2
        or not all(isinstance(item, dict) for item in output)
        or output[0].get("type") != "reasoning"
        or output[1].get("type") != "function_call"
    ):
        return None
    output_index, carrier = 1, output[1]
    if carrier.get("status") not in (None, "completed"):
        return None
    if carrier.get("name") != HARMONY_ACTION_OUTPUT_TOOL_NAME:
        return None
    call_id = carrier.get("call_id")
    arguments = carrier.get("arguments")
    if not isinstance(call_id, str) or not call_id:
        return None
    if not isinstance(arguments, str) or not arguments:
        return None
    return output_index, arguments, carrier.get("phase")


def _textual_mcp_call_arguments(item: dict[str, Any]) -> str | None:
    """Return a successful MCP-shaped textual action carrier's contents."""

    if (
        item.get("status") != "completed"
        or item.get("error") is not None
        or item.get("output") is not None
        or item.get("approval_request_id") not in (None, "")
    ):
        return None
    arguments = item.get("arguments")
    if not isinstance(arguments, str):
        return None
    return arguments.strip() or None


def _response_text(
    message_actions: list[dict[str, Any]],
    *,
    action_protocol: str,
    normalize: bool = True,
) -> tuple[str, dict[str, Any] | None]:
    """Return first-occurrence call semantics for one raw provider response.

    Canonical-exact calls are idempotent at the benchmark boundary. Providers
    can emit one combined action and then repeat its calls in separate response
    phases; executing those copies only duplicates observations and context.
    Raw emissions remain untouched in the provider trace and emitted counts,
    while the controller receives each exact call once in original order.
    """

    message_texts = [str(item["text"]) for item in message_actions]
    combined = "\n".join(message_texts).strip()
    if action_protocol != TEXTUAL_JSON or not message_actions or not normalize:
        return "".join(message_texts).strip(), None

    parsed_messages: list[tuple[dict[str, Any], Any]] = []
    for message, text in zip(message_actions, message_texts, strict=True):
        try:
            parsed = parse_textual_tool_turn(text)
        except (TypeError, ValueError):
            # Leave malformed output untouched so the controller reports the
            # actual protocol error.  Normalizing only a parseable subset would
            # make the batch non-atomic and erase model behavior.
            return combined, None
        parsed_messages.append((message, parsed))

    seen: set[str] = set()
    retained_raw: list[str] = []
    retained_output_indexes: list[int] = []
    duplicate_output_indexes: list[int] = []
    original_envelope_count = 0
    original_call_count = 0
    normalized_envelope_count = 0
    normalized_call_count = 0
    duplicate_call_count = 0
    for message, parsed in parsed_messages:
        output_index = int(message["output_index"])
        message_retained = False
        message_duplicated = False
        original_envelope_count += len(parsed.envelopes)
        original_call_count += len(parsed.calls)
        for envelope in parsed.envelopes:
            retained_calls: list[dict[str, Any]] = []
            for call in envelope["calls"]:
                canonical = json.dumps(
                    call,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if canonical in seen:
                    duplicate_call_count += 1
                    message_duplicated = True
                    continue
                seen.add(canonical)
                retained_calls.append(call)
            if not retained_calls:
                continue
            if len(retained_calls) == len(envelope["calls"]):
                retained_raw.append(str(envelope["raw"]).strip())
            else:
                retained_raw.append(
                    json.dumps(
                        {
                            "action": envelope["action"],
                            "calls": retained_calls,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
            normalized_envelope_count += 1
            normalized_call_count += len(retained_calls)
            message_retained = True
        if message_retained:
            retained_output_indexes.append(output_index)
        if message_duplicated:
            duplicate_output_indexes.append(output_index)

    if duplicate_call_count:
        phases = [item.get("phase") for item in message_actions]
        return "\n".join(retained_raw).strip(), {
            "schema_version": "react_report.action_normalization/v3",
            "kind": "identical_textual_calls",
            "policy_id": TEXTUAL_ACTION_NORMALIZATION_POLICY["policy_id"],
            "phases": phases,
            "source_output_indexes": [
                int(item["output_index"]) for item in message_actions
            ],
            "retained_output_indexes": retained_output_indexes,
            "duplicate_output_indexes": duplicate_output_indexes,
            "original_action_message_count": len(message_actions),
            "normalized_action_message_count": len(retained_output_indexes),
            "original_action_envelope_count": original_envelope_count,
            "normalized_action_envelope_count": normalized_envelope_count,
            "duplicate_action_envelope_count": (
                original_envelope_count - normalized_envelope_count
            ),
            "original_call_count": original_call_count,
            "normalized_call_count": normalized_call_count,
            "duplicate_call_count": duplicate_call_count,
            "replay": "synthetic_assistant_semantic_text",
        }
    return combined, None


def parse_arguments(value: Any) -> tuple[dict[str, Any] | None, str | None]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as exc:
        return None, f"native tool arguments are invalid JSON: {exc.msg}"
    if not isinstance(parsed, dict):
        return None, "native tool arguments must decode to an object"
    return parsed, None


def promote_initial_system_to_responses_instructions(
    items: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Put ordinary GPT-OSS instructions in Harmony's developer message.

    vLLM's GPT-OSS Responses renderer reserves an input ``system`` item for
    model identity metadata. The top-level Responses ``instructions`` field
    is rendered as the developer message and is therefore the correct carrier
    for this benchmark's system prompt.
    """

    converted = [deepcopy(item) for item in items]
    if not converted or converted[0].get("role") != "system":
        return None, converted
    content = converted[0].get("content")
    if not isinstance(content, str):
        return None, converted
    return content, converted[1:]


def build_responses_input(
    messages: list[dict[str, str]],
    turns: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = [
        deepcopy(item) for item in messages[:2]
    ]
    for turn in turns:
        raw_response = turn.get("raw_response")
        if isinstance(raw_response, dict):
            items.extend(
                _native_replay_output(
                    raw_response.get("output") or [],
                    turn,
                    tools=tools or [],
                )
            )
        calls = turn.get("calls") or []
        observations = turn.get("observations") or []
        if calls:
            for index, call in enumerate(calls):
                call_id = call.get("provider_call_id")
                if not call_id:
                    continue
                observation = (
                    observations[index]
                    if index < len(observations)
                    else {
                        "status": "protocol_error",
                        "message": "tool call produced no observation",
                    }
                )
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": compact_output(observation),
                    }
                )
        elif turn.get("status") == "protocol_error":
            items.append(
                {
                    "role": "user",
                    "content": (
                        "Protocol error: "
                        + str(turn.get("error") or "call a native tool")
                    ),
                }
            )
    return items


def _native_replay_output(
    output: Any,
    turn: dict[str, Any],
    *,
    tools: list[dict[str, Any]],
) -> list[Any]:
    """Replay the retained envelope with only recorded name repairs applied."""

    if not isinstance(output, list):
        return []
    replay = deepcopy(output)
    recorded_offered_tools = turn.get("offered_tools")
    offered_names = (
        {
            str(name)
            for name in recorded_offered_tools
            if isinstance(name, str)
        }
        if isinstance(recorded_offered_tools, list)
        else {
            str(tool.get("name"))
            for tool in tools
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        }
    )
    normalized_calls = {
        str(call.get("provider_call_id")): str(call.get("tool"))
        for call in (turn.get("calls") or [])
        if isinstance(call, dict)
        and isinstance(call.get("provider_call_id"), str)
        and isinstance(call.get("tool"), str)
    }
    replacements: dict[tuple[str, str], str] = {}
    for event in turn.get("normalizations") or []:
        if (
            not isinstance(event, dict)
            or event.get("kind")
            != "vllm_gpt_oss_channel_suffix_tool_name"
            or event.get("policy_id")
            != NATIVE_ACTION_NORMALIZATION_POLICY["policy_id"]
        ):
            continue
        for replacement in event.get("replacements") or []:
            if not isinstance(replacement, dict):
                continue
            call_id = replacement.get("provider_call_id")
            original_name = replacement.get("original_name")
            normalized_name = replacement.get("normalized_name")
            if not all(
                isinstance(value, str)
                for value in (call_id, original_name, normalized_name)
            ):
                continue
            if (
                original_name.removesuffix(GPT_OSS_VLLM_CHANNEL_SUFFIX)
                != normalized_name
                or normalized_name not in offered_names
                or normalized_calls.get(call_id) != normalized_name
            ):
                continue
            replacements[(call_id, original_name)] = normalized_name
    if not replacements:
        return replay
    for item in replay:
        if not isinstance(item, dict) or item.get("type") != "function_call":
            continue
        call_id = item.get("call_id")
        name = item.get("name")
        if isinstance(call_id, str) and isinstance(name, str):
            normalized_name = replacements.get((call_id, name))
            if normalized_name is not None:
                item["name"] = normalized_name
    return replay


def build_textual_responses_input(
    messages: list[dict[str, str]],
    episode: Any,
    *,
    action_instruction: str | None = None,
) -> list[dict[str, Any]]:
    """Build one stateless Responses transcript for textual ReAct.

    Each earlier turn's executed action view is replayed before its user
    observation.  Provider reasoning items are retained, while a normalized
    action response is replayed as one synthetic assistant message containing
    exactly the semantics the controller executed.  This avoids relying on
    ``previous_response_id`` or provider-side storage; the untouched provider
    output remains in the trace for audit.
    """

    converted: list[dict[str, Any]] = [
        deepcopy(item) for item in messages[:2]
    ]
    if not openai_responses_tools(episode):
        return [deepcopy(item) for item in messages]
    _append_textual_instruction(
        converted,
        action_instruction or textual_json_action_instruction(episode),
    )
    for turn in getattr(episode, "turns", ()):
        raw_response = turn.get("raw_response")
        output = (
            raw_response.get("output")
            if isinstance(raw_response, dict)
            else None
        )
        if isinstance(output, list) and output:
            converted.extend(_textual_replay_output(output, turn))
        elif turn.get("raw_text"):
            converted.append(
                {
                    "role": "assistant",
                    "content": str(turn["raw_text"]),
                }
            )
        observations = turn.get("observations") or []
        terminal_accepted = any(
            isinstance(item, dict)
            and item.get("terminal") is True
            and item.get("status") == "accepted"
            for item in observations
        )
        if observations and not terminal_accepted:
            converted.append(
                {
                    "role": "user",
                    "content": render_tool_observations(observations),
                }
            )
        elif turn.get("status") == "protocol_error":
            converted.append(
                {
                    "role": "user",
                    "content": render_tool_observations(
                        [
                            {
                                "status": "protocol_error",
                                "message": str(
                                    turn.get("error")
                                    or "emit a valid textual JSON action batch"
                                ),
                            }
                        ]
                    ),
                }
            )
    return converted


def _textual_replay_output(
    output: list[Any],
    turn: dict[str, Any],
) -> list[Any]:
    """Replay the executed action view while leaving raw trace data untouched."""

    has_mcp_call = any(
        isinstance(item, dict) and item.get("type") == "mcp_call"
        for item in output
    )
    harmony_carrier = (
        turn.get("action_output_contract") == HARMONY_REASONING_ACTION_JSON
    )
    normalized = any(
        isinstance(event, dict)
        and event.get("kind") in {
            "identical_textual_calls",
            "identical_textual_action_envelopes",
            # Resume compatibility for v2 traces created before envelope-wide
            # normalization replaced the narrow cross-phase rule.
            "identical_cross_phase_textual_action",
        }
        for event in turn.get("normalizations") or []
    )
    if not normalized and not has_mcp_call and not harmony_carrier:
        return [deepcopy(item) for item in output]

    semantic_text = str(turn.get("raw_text") or "").strip()
    if not semantic_text:
        if has_mcp_call or harmony_carrier:
            # ``mcp_call`` is an output-only compatibility shape and is not a
            # valid Responses input item on the affected servers.  Drop an
            # unsuccessful carrier; the following user protocol observation
            # tells the model that its action was rejected, while raw_response
            # retains the untouched item for audit.
            return [
                deepcopy(item)
                for item in output
                if not (
                    isinstance(item, dict)
                    and (
                        item.get("type") == "mcp_call"
                        or (
                            harmony_carrier
                            and item.get("type") == "function_call"
                        )
                    )
                )
            ]
        # A normalization event without its executed semantic transcript is
        # incomplete.  Preserve the raw replay rather than silently deleting
        # every assistant action message.
        return [deepcopy(item) for item in output]
    replaced_item_types = {"message"}
    if has_mcp_call:
        replaced_item_types.add("mcp_call")
    if harmony_carrier:
        replaced_item_types.add("function_call")
    # Preserve every opaque provider item (especially encrypted reasoning) in
    # its original relative order.  Raw action carriers cannot be replayed
    # when they contain normalized calls or use the output-only MCP shape, so
    # replay one synthetic message *after* the opaque state with exactly the
    # semantic action text seen by the controller.
    replay = [
        deepcopy(item)
        for item in output
        if not (
            isinstance(item, dict)
            and item.get("type") in replaced_item_types
        )
    ]
    replay.append({"role": "assistant", "content": semantic_text})
    return replay


def _append_textual_instruction(
    items: list[dict[str, Any]],
    instruction: str,
) -> None:
    for item in items:
        if item.get("role") == "system":
            item["content"] = f"{item.get('content', '').rstrip()}\n\n{instruction}"
            return
    items.insert(0, {"role": "system", "content": instruction})


def textual_json_action_instruction(episode: Any) -> str:
    """Return the provider-independent textual action envelope instruction."""

    definitions = openai_responses_tools(episode)
    available = ", ".join(item["name"] for item in definitions)
    terminal = [
        item["name"]
        for item in definitions
        if item["name"] in {"create_report", "create_section"}
    ]
    terminal_text = terminal[0] if len(terminal) == 1 else "the terminal tool"
    calculation_instruction = (
        "For v2 calculate actions, use only exact canonical result IDs, for "
        "example {\"action\":\"tool_calls\",\"calls\":[{\"tool\":"
        "\"calculate\",\"arguments\":{\"ids\":[\"calc.country_count\"]}}]}. "
        "The controller resolves registered dependencies automatically. "
        if uses_compact_calculation_actions(episode)
        else ""
    )
    keep_instruction = ""
    if terminal == ["create_section"]:
        terminal_markdown_action = "create_section mode create or replace"
        section_id = str(getattr(episode, "section_id", "exact.section_id"))
        section_create = getattr(episode, "episode_kind", None) in {
            "section_create",
            "oracle_section",
        }
        terminal_mode = "create" if section_create else "replace"
        if not section_create:
            keep_header = json.dumps(
                {
                    "action": "tool_calls",
                    "calls": [
                        {
                            "tool": "create_section",
                            "arguments": {
                                "section_id": section_id,
                                "mode": "keep",
                            },
                        }
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            keep_instruction = (
                " To retain an unchanged section, emit this JSON-only "
                "terminal action with no Markdown body or markdown argument:\n\n"
                f"{keep_header}\n\n"
            )
        terminal_header = json.dumps(
            {
                "action": "tool_calls",
                "calls": [
                    {
                        "tool": "create_section",
                        "arguments": {
                            "section_id": section_id,
                            "mode": terminal_mode,
                        },
                    }
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        terminal_body_example = (
            "## Exact required section heading\n\n"
            'Final section Markdown with ordinary "quotes" and newlines.'
        )
    else:
        terminal_markdown_action = "create_report"
        terminal_header = (
            '{"action":"tool_calls","calls":['
            '{"tool":"create_report","arguments":{}}]}'
        )
        terminal_body_example = (
            "# Complete report heading\n\n"
            'Final report Markdown with ordinary "quotes" and newlines.'
        )
    terminal_example = f"{terminal_header}\n\n{terminal_body_example}"
    if getattr(episode, "turn_phase", None) == "finalization":
        return (
            "PROVIDER ACTION INTERFACE — TEXTUAL JSON — FINALIZATION TURN\n\n"
            "This is the last provider call. Continue your ordinary reasoning "
            "before choosing the action; reasoning is not disabled or "
            "shortened. The only available semantic action is "
            f"{terminal_text}, and you must emit exactly one such call. Do not "
            "request evidence or calculations. The terminal call must be the "
            "sole semantic action. For "
            f"{terminal_markdown_action}, omit the semantic markdown argument "
            "from the JSON header and put the unescaped Markdown after the "
            "one-line header and one blank line, exactly as shown. Do not use "
            "a Markdown fence, add an end marker, or expect an observation or "
            f"repair turn:\n\n{terminal_example}\n\n"
            f"{keep_instruction}"
            "Stop immediately after the terminal submission."
        )
    turn_instruction_factory = getattr(episode, "turn_instruction", None)
    turn_instruction = (
        turn_instruction_factory()
        if callable(turn_instruction_factory)
        else None
    )
    turn_instruction_prefix = (
        f"{turn_instruction}\n\n" if turn_instruction else ""
    )
    return (
        "PROVIDER ACTION INTERFACE — TEXTUAL JSON\n\n"
        f"{turn_instruction_prefix}"
        "This provider-specific interface replaces any instruction above to "
        "use native function calls or to avoid printing action JSON. The tool "
        "catalogue in the task describes tool semantics; this interface alone "
        "defines their wire encoding. No native tools are attached to this "
        "request. On a nonterminal turn, output exactly one top-level JSON "
        "action object and no Markdown fence, prose, or other JSON value. Put "
        "every independent nonterminal call for this turn in that object's "
        "calls array:\n\n"
        '{"action":"tool_calls","calls":['
        '{"tool":"get_data","arguments":{"ids":["exact.id"]}}]}\n\n'
        f"{calculation_instruction}"
        "Use only these tools: "
        f"{available}. Calls execute once in array order as one open-loop "
        "batch. You receive no observations within the batch, so do not make "
        "a later call depend on an unseen result or simulate a result. "
        f"{terminal_text} is terminal and must be the sole semantic action: "
        "emit exactly one object containing exactly that one call, never mixed "
        "with a nonterminal call or another terminal call. For "
        f"{terminal_markdown_action}, the semantic markdown argument "
        "shown in the tool catalogue MUST be omitted from JSON. Put the "
        "unescaped Markdown body after the one-line JSON header and one blank "
        "line, as shown here. The provider response boundary ends the Markdown; "
        "do not add an end marker or wrap either part in a Markdown code "
        f"fence:\n\n{terminal_example}\n\n"
        f"{keep_instruction}"
        "After emitting the batch, stop and "
        "wait for the next user message, which will contain one combined set "
        "of real tool observations."
    )


def structured_json_action_instruction(
    episode: Any,
    *,
    reasoning_prefixed: bool,
    harmony_carrier: bool = False,
) -> str:
    """Describe the semantic choices left inside the constrained wire form."""

    definitions = openai_responses_tools(episode)
    available = ", ".join(item["name"] for item in definitions)
    terminal = [
        item["name"]
        for item in definitions
        if item["name"] in {"create_report", "create_section"}
    ]
    terminal_text = terminal[0] if len(terminal) == 1 else "the terminal tool"
    reasoning = (
        "The pinned chat template has already opened a <think> block at the "
        "end of the prompt. Continue the model's ordinary reasoning without "
        "repeating that opening tag. When the action is decided, emit exactly "
        "one </think> close tag and then the JSON action object. The decoder "
        "leaves the reasoning text unconstrained and applies the action "
        "constraint only after that boundary. "
        if reasoning_prefixed
        else (
            "Use the model's ordinary native Harmony analysis channel before "
            "submitting the action through the synthetic action_output wire "
            "carrier. The carrier is transport scaffolding, not a benchmark "
            "tool choice. "
            if harmony_carrier
            else "Provider-native reasoning, when available, remains separate "
            "from the constrained action output. "
        )
    )
    calculation = (
        "Use get_data only with complete dt.*, reference.*, or req.* evidence "
        "IDs. Use calculate only with complete canonical calc.* result IDs; "
        "the controller resolves registered dependencies automatically. "
        if uses_compact_calculation_actions(episode)
        else ""
    )
    terminal_arguments = (
        "For create_report, put the complete final Markdown in "
        "calls[0].arguments.markdown. "
        if terminal == ["create_report"]
        else (
            "For create_section mode create or replace, put the complete final "
            "Markdown in calls[0].arguments.markdown. For mode keep, omit the "
            "markdown property. "
        )
    )
    if getattr(episode, "turn_phase", None) == "finalization":
        return (
            "PROVIDER ACTION INTERFACE — STRUCTURED ACTION JSON — "
            "FINALIZATION TURN\n\n"
            "This is the last provider call. The supplied structured-output "
            "constraint exposes only the scope-appropriate terminal action. "
            f"{reasoning}You must submit exactly one {terminal_text} call and "
            "no evidence retrieval or calculation action. "
            f"{terminal_arguments}"
            "The decoder guarantees JSON syntax, not factual correctness: "
            "choose the mode and Markdown content from the task evidence. No "
            "observation or repair turn follows."
        )
    turn_instruction_factory = getattr(episode, "turn_instruction", None)
    turn_instruction = (
        turn_instruction_factory()
        if callable(turn_instruction_factory)
        else None
    )
    turn_instruction_prefix = (
        f"{turn_instruction}\n\n" if turn_instruction else ""
    )
    return (
        "PROVIDER ACTION INTERFACE — STRUCTURED ACTION JSON\n\n"
        f"{turn_instruction_prefix}"
        "This interface replaces instructions to use semantic native function "
        "calls or to print Markdown outside the action object. "
        + (
            "One synthetic action_output function carries the constrained JSON; "
            if harmony_carrier
            else "No native tools are attached. "
        )
        + "The tool catalogue describes tool semantics; the supplied "
        "structured-output constraint defines the wire encoding. "
        f"{reasoning}"
        "On each turn choose exactly one top-level action object with "
        'action="tool_calls" and a non-empty calls array. Use only these tools: '
        f"{available}. Put every independent nonterminal call needed at this "
        "observation boundary in that array. Calls execute once, in array "
        "order, as one open-loop batch; do not make a later call depend on an "
        "unseen result. "
        f"{calculation}"
        f"{terminal_text} is terminal and must be the only call in its turn. "
        f"{terminal_arguments}"
        "The decoder guarantees JSON syntax, not factual correctness: choose "
        "tool names, IDs, modes, and Markdown content from the task evidence. "
        "After the action object, stop and wait for the combined real tool "
        "observations."
    )


def responses_input_attribution(
    items: list[dict[str, Any]],
    *,
    initial_item_count: int,
    replayed_turn_count: int,
    action_protocol: str,
    protocol_instruction_characters: int = 0,
    tools: list[dict[str, Any]] | None = None,
    action_output_contract: str | None = None,
    structured_constraint: dict[str, Any] | None = None,
    top_level_instructions: str | None = None,
) -> dict[str, Any]:
    """Describe request-context growth without retaining additional content.

    Provider usage is the authoritative token count.  These deterministic
    serialized-character counts attribute *where* that context came from and
    deliberately avoid pretending that characters map exactly to tokens.
    """

    categories: dict[str, dict[str, int]] = {}
    for index, item in enumerate(items):
        category = _responses_input_category(
            item,
            is_initial=index < initial_item_count,
        )
        bucket = categories.setdefault(
            category,
            {"items": 0, "serialized_characters": 0},
        )
        bucket["items"] += 1
        bucket["serialized_characters"] += len(compact_output(item))
    if top_level_instructions is not None:
        categories["initial_instructions"] = {
            "items": 1,
            "serialized_characters": len(
                compact_output({"instructions": top_level_instructions})
            ),
        }
    tool_characters = len(compact_output(tools)) if tools else 0
    result = {
        "schema_version": (
            "react_report.request_context/v3"
            if top_level_instructions is not None
            else (
                "react_report.request_context/v2"
                if action_output_contract is not None
                else "react_report.request_context/v1"
            )
        ),
        "measurement": "serialized_characters_not_tokens",
        "action_protocol": action_protocol,
        "replayed_turn_count": max(0, int(replayed_turn_count)),
        "input_item_count": len(items),
        "serialized_input_characters": len(compact_output(items)),
        "tool_definition_characters": tool_characters,
        "protocol_instruction_characters": max(
            0, int(protocol_instruction_characters)
        ),
        "categories": dict(sorted(categories.items())),
    }
    if action_output_contract is not None:
        result["action_output_contract"] = action_output_contract
    if structured_constraint is not None:
        result["structured_constraint"] = deepcopy(structured_constraint)
    if top_level_instructions is not None:
        result["top_level_instruction_characters"] = len(
            top_level_instructions
        )
        result["instructions_transport"] = "responses.instructions"
    return result


def _responses_input_category(
    item: dict[str, Any],
    *,
    is_initial: bool,
) -> str:
    role = item.get("role")
    item_type = item.get("type")
    if is_initial:
        if role == "system":
            return "initial_system"
        if role == "user":
            return "initial_user"
        return "initial_other"
    if item_type == "reasoning":
        return "replayed_reasoning"
    if item_type in {"message", "function_call"} or role == "assistant":
        return "replayed_assistant"
    if item_type == "function_call_output":
        return "replayed_tool_observations"
    if role == "user":
        content = item.get("content")
        if isinstance(content, str):
            try:
                decoded = json.loads(content)
            except json.JSONDecodeError:
                decoded = None
            if (
                isinstance(decoded, dict)
                and decoded.get("role") == "tool_observations"
            ):
                return "replayed_tool_observations"
        return "replayed_protocol_feedback"
    return "replayed_other"


def compact_output(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def normalize_usage(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    details = value.get("output_tokens_details")
    details = details if isinstance(details, dict) else {}
    return {
        "input_tokens": int(value.get("input_tokens") or 0),
        "output_tokens": int(value.get("output_tokens") or 0),
        "reasoning_tokens": int(details.get("reasoning_tokens") or 0),
        "cached_input_tokens": int(
            (value.get("input_tokens_details") or {}).get("cached_tokens") or 0
        ),
    }


def _normalize_request_headers(
    value: dict[str, str] | tuple[tuple[str, str], ...] | None,
) -> dict[str, str]:
    if value is None:
        return {}
    items = value.items() if isinstance(value, dict) else value
    output: dict[str, str] = {}
    seen: set[str] = set()
    for raw_name, raw_value in items:
        name = str(raw_name).strip()
        header_value = str(raw_value).strip()
        normalized = name.casefold()
        if (
            not name
            or not header_value
            or normalized in {"authorization", "content-type"}
            or normalized in seen
            or "\r" in name
            or "\n" in name
            or "\r" in header_value
            or "\n" in header_value
        ):
            raise ValueError("invalid provider request header")
        seen.add(normalized)
        output[name] = header_value
    return output


def _header_value(headers: Any, *names: str) -> str | None:
    if headers is None:
        return None
    for name in names:
        try:
            value = headers.get(name)
        except (AttributeError, TypeError):
            return None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _retry_after_seconds(headers: Any) -> float | None:
    value = _header_value(headers, "retry-after", "Retry-After")
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        from datetime import datetime, timezone
        from email.utils import parsedate_to_datetime
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            seconds = max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
    from math import isfinite
    return seconds if isfinite(seconds) and seconds >= 0 else None
