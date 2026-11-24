from __future__ import annotations

import os
from typing import Any, Mapping

from benchmarks.benchrunner.providers.profiles import (
    RESPONSES_TEXT_FORMAT,
    OpenRouterPolicy,
    get_openrouter_treatment,
    resolve_provider_profile,
)

from .anthropic_messages import AnthropicMessagesProvider
from ..context_budget import InputTokenCounter
from .base import Provider
from .fixtures import FixtureProvider
from .openai_compatible import OpenAICompatibleProvider
from .openai_responses import OpenAIResponsesProvider, TEXTUAL_JSON


def create_provider(
    provider_id: str,
    *,
    model: str | None = None,
    endpoint: str | None = None,
    api_key: str | None = None,
    max_output_tokens: int = 8000,
    reasoning_effort: str | None = None,
    generation_seed: int | None = None,
    timeout_seconds: float = 180.0,
    profile_id: str | None = None,
    action_protocol: str | None = None,
    action_output_contract: str | None = None,
    openrouter_policy: OpenRouterPolicy | None = None,
    environ: Mapping[str, str] | None = None,
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
) -> Provider:
    """Build a provider adapter around the common semantic tool protocol."""

    if native_tool_policy is not None and provider_id != "openai_responses":
        raise ValueError("native_tool_policy requires the Responses adapter")
    if generation_seed is not None and provider_id != "openai_responses":
        raise ValueError("generation_seed requires a qualified Responses adapter")

    context_options = {
        "context_window_tokens": context_window_tokens,
        "context_safety_margin_tokens": context_safety_margin_tokens,
        "input_token_count_mode": input_token_count_mode,
        "input_token_counter": input_token_counter,
        "input_token_counter_id": input_token_counter_id,
        "context_probe_max_requests": context_probe_max_requests,
        "context_probe_max_cost_usd": context_probe_max_cost_usd,
        "context_probe_budget": context_probe_budget,
        "context_probe_retry_policy": context_probe_retry_policy,
    }
    if provider_id != "openai_responses" and any(value is not None for value in context_options.values()):
        raise ValueError("context budgeting is supported only by openai_responses")
    if provider_id == "fixture":
        return FixtureProvider()
    if not model:
        raise ValueError(f"{provider_id}: model is required")
    if provider_id == "openai_responses":
        source = os.environ if environ is None else environ
        selected_endpoint = endpoint
        selected_key = api_key
        api_key_env = "OPENAI_API_KEY"
        selected_profile = profile_id or "openai"
        structured_output_dialect = RESPONSES_TEXT_FORMAT
        request_headers: tuple[tuple[str, str], ...] = ()
        supports_openrouter_policy = False
        if profile_id is not None:
            profile = resolve_provider_profile(profile_id, source)
            if endpoint is not None and endpoint != profile.responses_endpoint:
                raise ValueError(
                    f"{profile_id}: endpoint override conflicts with the "
                    "resolved provider profile"
                )
            selected_endpoint = profile.responses_endpoint
            api_key_env = profile.api_key_env
            structured_output_dialect = profile.structured_output_dialect
            request_headers = profile.request_headers
            supports_openrouter_policy = profile.supports_openrouter_policy
            if selected_key is None:
                selected_key = source.get(api_key_env, "")
        if supports_openrouter_policy:
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
        elif openrouter_policy is not None:
            raise ValueError(
                "openrouter_policy is supported only by the openrouter profile"
            )
        return OpenAIResponsesProvider(
            model=model,
            endpoint=(
                selected_endpoint
                or "https://api.openai.com/v1/responses"
            ),
            api_key=selected_key,
            api_key_env=api_key_env,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            generation_seed=generation_seed,
            timeout_seconds=timeout_seconds,
            profile_id=selected_profile,
            structured_output_dialect=structured_output_dialect,
            request_headers=request_headers,
            openrouter_policy=openrouter_policy,
            final_turn_tool_choice_policy=final_turn_tool_choice_policy,
            native_tool_policy=native_tool_policy,
            diagnostic_content_scope=diagnostic_content_scope,
            # Responses runs use the provider-independent textual protocol by
            # default.  Native functions remain an explicit secondary arm.
            action_protocol=action_protocol or TEXTUAL_JSON,
            action_output_contract=action_output_contract,
            **context_options,
        )
    if profile_id is not None:
        raise ValueError(
            "provider profiles are supported only by openai_responses"
        )
    if action_protocol is not None:
        raise ValueError(
            "action_protocol is supported only by openai_responses"
        )
    if action_output_contract is not None:
        raise ValueError(
            "action_output_contract is supported only by openai_responses"
        )
    if openrouter_policy is not None:
        raise ValueError(
            "openrouter_policy is supported only by openai_responses"
        )
    if provider_id == "anthropic_messages":
        return AnthropicMessagesProvider(
            model=model,
            endpoint=endpoint or "https://api.anthropic.com/v1/messages",
            api_key=api_key,
            max_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
            final_turn_tool_choice_policy=final_turn_tool_choice_policy,
        )
    if provider_id == "openai_compatible":
        if not endpoint:
            raise ValueError("openai_compatible: endpoint is required")
        return OpenAICompatibleProvider(
            model=model,
            endpoint=endpoint,
            api_key=api_key,
            max_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
            final_turn_tool_choice_policy=final_turn_tool_choice_policy,
        )
    raise ValueError(f"unknown provider {provider_id!r}")
