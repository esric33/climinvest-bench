"""Non-secret configuration for OpenAI Responses-compatible providers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit


class ProviderProfileError(ValueError):
    """Raised when a provider profile cannot be resolved safely."""


class OpenRouterMetadataError(ValueError):
    """Stable, content-free failure from OpenRouter routing verification."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


RESPONSES_TEXT_FORMAT = "responses_text_format"
VLLM_STRUCTURED_OUTPUTS = "vllm_structured_outputs"
STRUCTURED_OUTPUT_DIALECTS = frozenset(
    {RESPONSES_TEXT_FORMAT, VLLM_STRUCTURED_OUTPUTS}
)


@dataclass(frozen=True, slots=True)
class OpenRouterMaxPrice:
    """Fail-closed OpenRouter price ceiling, in USD per million tokens."""

    prompt: float
    completion: float


@dataclass(frozen=True, slots=True)
class OpenRouterProviderPolicy:
    """Exact OpenRouter endpoint, privacy, fallback, and price policy."""

    only: tuple[str, ...]
    allow_fallbacks: bool
    require_parameters: bool
    data_collection: str
    zdr: bool
    max_price: OpenRouterMaxPrice


@dataclass(frozen=True, slots=True)
class OpenRouterPolicy:
    """Request-bound OpenRouter policy recorded in the study treatment."""

    provider: OpenRouterProviderPolicy
    context_compression: bool
    parallel_tool_calls: bool | None = None

    def as_config(self) -> dict[str, Any]:
        """Return the canonical, secret-free study representation."""

        config = {
            "provider": {
                "only": list(self.provider.only),
                "allow_fallbacks": self.provider.allow_fallbacks,
                "require_parameters": self.provider.require_parameters,
                "data_collection": self.provider.data_collection,
                "zdr": self.provider.zdr,
                "max_price": {
                    "prompt": self.provider.max_price.prompt,
                    "completion": self.provider.max_price.completion,
                },
            },
            "context_compression": self.context_compression,
        }
        # Preserve the established identities of treatments whose pinned
        # endpoint does not advertise this parameter.  An explicit opt-in is
        # nevertheless hash-bound for routes, such as Solar's Upstage ZDR
        # endpoint, where parallel native tool calls are part of the contract.
        if self.parallel_tool_calls is not None:
            config["parallel_tool_calls"] = self.parallel_tool_calls
        return config

    def request_fields(self) -> dict[str, Any]:
        """Return the OpenRouter Responses request extensions."""

        fields = {
            "provider": self.as_config()["provider"],
            "plugins": [
                {
                    "id": "context-compression",
                    "enabled": self.context_compression,
                }
            ],
        }
        if self.parallel_tool_calls is not None:
            fields["parallel_tool_calls"] = self.parallel_tool_calls
        return fields


@dataclass(frozen=True, slots=True)
class OpenRouterTreatment:
    """One approved model/reasoning/routing benchmark treatment."""

    model: str
    reasoning_effort: str | None
    policy: OpenRouterPolicy


@dataclass(frozen=True, slots=True)
class ResolvedProviderConfig:
    """Effective provider configuration containing no credential value."""

    profile_id: str
    protocol: str
    base_url: str
    responses_endpoint: str
    api_key_env: str
    credential_present: bool
    allow_insecure_http: bool
    structured_output_dialect: str
    request_headers: tuple[tuple[str, str], ...]
    supports_openrouter_policy: bool


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    """Immutable description of how to resolve one provider safely.

    A profile deliberately stores only the environment-variable *name* for a
    credential. Resolution checks whether that variable is populated but never
    copies or returns its value.
    """

    profile_id: str
    api_key_env: str
    default_base_url: str | None = None
    base_url_env: str | None = None
    allow_insecure_http: bool = False
    protocol: str = "openai_responses"
    structured_output_dialect: str = RESPONSES_TEXT_FORMAT
    request_headers: tuple[tuple[str, str], ...] = ()
    supports_openrouter_policy: bool = False

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ProviderProfileError("provider profile ID must be non-empty")
        if not self.api_key_env.strip():
            raise ProviderProfileError(
                f"{self.profile_id}: credential environment name must be non-empty"
            )
        sources = int(self.default_base_url is not None) + int(
            self.base_url_env is not None
        )
        if sources != 1:
            raise ProviderProfileError(
                f"{self.profile_id}: configure exactly one base URL source"
            )
        if self.base_url_env is not None and not self.base_url_env.strip():
            raise ProviderProfileError(
                f"{self.profile_id}: base URL environment name must be non-empty"
            )
        if self.structured_output_dialect not in STRUCTURED_OUTPUT_DIALECTS:
            raise ProviderProfileError(
                f"{self.profile_id}: unsupported structured-output dialect"
            )
        seen_headers: set[str] = set()
        for name, value in self.request_headers:
            normalized_name = str(name).strip().casefold()
            if (
                not normalized_name
                or normalized_name in {"authorization", "content-type"}
                or normalized_name in seen_headers
                or not str(value).strip()
                or "\n" in str(name)
                or "\r" in str(name)
                or "\n" in str(value)
                or "\r" in str(value)
            ):
                raise ProviderProfileError(
                    f"{self.profile_id}: invalid provider request header"
                )
            seen_headers.add(normalized_name)

    @property
    def name(self) -> str:
        """Provider-facing alias for the stable profile identifier."""

        return self.profile_id

    def has_credentials(self, environ: Mapping[str, str] | None = None) -> bool:
        """Return whether the configured credential variable is populated."""

        source = os.environ if environ is None else environ
        value = source.get(self.api_key_env)
        return isinstance(value, str) and bool(value.strip())

    def resolve(
        self,
        environ: Mapping[str, str] | None = None,
    ) -> ResolvedProviderConfig:
        """Resolve endpoint metadata without reading out a credential value."""

        source = os.environ if environ is None else environ
        if self.base_url_env is None:
            assert self.default_base_url is not None
            raw_base_url = self.default_base_url
        else:
            raw_base_url = source.get(self.base_url_env, "")
            if not isinstance(raw_base_url, str) or not raw_base_url.strip():
                raise ProviderProfileError(
                    f"{self.profile_id}: {self.base_url_env} is not configured"
                )

        base_url, responses_endpoint = normalize_responses_endpoint(
            raw_base_url,
            allow_insecure_http=self.allow_insecure_http,
        )
        return ResolvedProviderConfig(
            profile_id=self.profile_id,
            protocol=self.protocol,
            base_url=base_url,
            responses_endpoint=responses_endpoint,
            api_key_env=self.api_key_env,
            credential_present=self.has_credentials(source),
            allow_insecure_http=self.allow_insecure_http,
            structured_output_dialect=self.structured_output_dialect,
            request_headers=self.request_headers,
            supports_openrouter_policy=self.supports_openrouter_policy,
        )


def normalize_responses_endpoint(
    base_url: str,
    *,
    allow_insecure_http: bool = False,
) -> tuple[str, str]:
    """Validate a base URL and return its normalized Responses endpoint."""

    raw = str(base_url).strip()
    if not raw:
        raise ProviderProfileError("provider base URL must be non-empty")
    if "?" in raw or "#" in raw:
        raise ProviderProfileError(
            "provider base URL must not contain a query or fragment"
        )
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        # Accessing ``port`` validates malformed and out-of-range port values.
        parsed.port
    except ValueError as exc:
        raise ProviderProfileError(f"invalid provider base URL: {exc}") from exc

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ProviderProfileError(
            "provider base URL scheme must be http or https"
        )
    if scheme == "http" and not allow_insecure_http:
        raise ProviderProfileError(
            "insecure HTTP is not permitted by this provider profile"
        )
    if not parsed.netloc or not hostname:
        raise ProviderProfileError("provider base URL must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ProviderProfileError(
            "provider base URL must not contain user information"
        )

    path = parsed.path.rstrip("/")
    normalized_base = urlunsplit((scheme, parsed.netloc, path, "", ""))
    endpoint_path = path if path.endswith("/responses") else f"{path}/responses"
    if not endpoint_path.startswith("/"):
        endpoint_path = f"/{endpoint_path}"
    endpoint = urlunsplit((scheme, parsed.netloc, endpoint_path, "", ""))
    return normalized_base, endpoint


OPENAI_PROFILE = ProviderProfile(
    profile_id="openai",
    api_key_env="OPENAI_API_KEY",
    default_base_url="https://api.openai.com/v1",
)

IDA_PROFILE = ProviderProfile(
    profile_id="ida",
    api_key_env="IDA_LLM_API_KEY",
    base_url_env="IDA_LLM_BASE_URL",
    allow_insecure_http=True,
    structured_output_dialect=VLLM_STRUCTURED_OUTPUTS,
)

OPENROUTER_PROFILE = ProviderProfile(
    profile_id="openrouter",
    api_key_env="OPENROUTER_API_KEY",
    default_base_url="https://openrouter.ai/api/v1",
    structured_output_dialect=RESPONSES_TEXT_FORMAT,
    request_headers=(
        ("X-OpenRouter-Metadata", "enabled"),
        ("X-OpenRouter-Cache", "false"),
    ),
    supports_openrouter_policy=True,
)


def _openrouter_treatment(
    model: str,
    reasoning_effort: str | None,
    provider: str,
    data_collection: str,
    zdr: bool,
    prompt_price: float,
    completion_price: float,
    parallel_tool_calls: bool | None = None,
) -> OpenRouterTreatment:
    return OpenRouterTreatment(
        model=model,
        reasoning_effort=reasoning_effort,
        policy=OpenRouterPolicy(
            provider=OpenRouterProviderPolicy(
                only=(provider,),
                allow_fallbacks=False,
                require_parameters=True,
                data_collection=data_collection,
                zdr=zdr,
                max_price=OpenRouterMaxPrice(
                    prompt=prompt_price,
                    completion=completion_price,
                ),
            ),
            context_compression=False,
            parallel_tool_calls=parallel_tool_calls,
        ),
    )


OPENROUTER_TREATMENTS: Mapping[str, OpenRouterTreatment] = MappingProxyType(
    {
        treatment.model: treatment
        for treatment in (
            # Reviewed hosted candidates. Registration permits qualification;
            # only live Stage A/B evidence permits benchmark promotion.
            _openrouter_treatment(
                "qwen/qwen3.8-27b", "medium", "dekallm", "deny", False, 0.20, 2.50,
            ),
            _openrouter_treatment(
                "google/gemma-4-26b-a4b-it", None, "nextbit/bf16", "deny", False, 0.09, 0.30,
            ),
            _openrouter_treatment(
                "deepseek/deepseek-v4.1-flash", None, "deepseek", "allow", False, 0.30, 1.20,
            ),
            _openrouter_treatment(
                "google/gemini-3.8-flash", "medium", "google-ai-studio", "deny", False, 0.75, 3.75,
            ),
            _openrouter_treatment(
                "inception/mercury-2.5-preview",
                "medium",
                "inception",
                "deny",
                True,
                0.04,
                0.15,
            ),
            _openrouter_treatment(
                "meta/muse-spark-1.3-contributor",
                "medium",
                "meta",
                "allow",
                False,
                0.10,
                0.20,
            ),
            _openrouter_treatment(
                "z-ai/glm-5.3-flash",
                "low",
                "z-ai/fp8",
                "deny",
                False,
                0.15,
                0.50,
            ),
            _openrouter_treatment(
                "minimax/minimax-m3", None, "minimax/fp8", "deny", False, 0.30, 1.20,
            ),
            _openrouter_treatment(
                "upstage/solar-pro4",
                "medium",
                "upstage/zdr",
                "deny",
                True,
                0.30,
                1.20,
                parallel_tool_calls=True,
            ),
        )
    }
)

PROVIDER_PROFILES: Mapping[str, ProviderProfile] = MappingProxyType(
    {
        OPENAI_PROFILE.profile_id: OPENAI_PROFILE,
        IDA_PROFILE.profile_id: IDA_PROFILE,
        OPENROUTER_PROFILE.profile_id: OPENROUTER_PROFILE,
    }
)


def get_openrouter_treatment(model: str) -> OpenRouterTreatment:
    """Return the approved, exactly routed OpenRouter treatment."""

    normalized = str(model).strip()
    try:
        return OPENROUTER_TREATMENTS[normalized]
    except KeyError as exc:
        choices = ", ".join(sorted(OPENROUTER_TREATMENTS))
        raise ProviderProfileError(
            f"unsupported OpenRouter model {model!r}; choose from {choices}"
        ) from exc


def sanitize_openrouter_metadata(value: Any) -> dict[str, Any] | None:
    """Retain bounded routing facts without copying provider-controlled data."""

    if not isinstance(value, Mapping):
        return None
    output: dict[str, Any] = {}
    for name in ("requested", "strategy", "region"):
        raw = value.get(name)
        if isinstance(raw, str) and 0 < len(raw) <= 128:
            output[name] = raw
    attempt = value.get("attempt")
    if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt >= 0:
        output["attempt"] = attempt
    is_byok = value.get("is_byok")
    if isinstance(is_byok, bool):
        output["is_byok"] = is_byok

    endpoints = value.get("endpoints")
    if isinstance(endpoints, Mapping):
        available = _safe_router_records(
            endpoints.get("available"),
            fields=("provider", "model", "selected"),
        )
        if available:
            output["endpoints"] = {"available": available}
    attempts = _safe_router_records(
        value.get("attempts"),
        fields=("provider", "model", "status"),
    )
    if attempts:
        output["attempts"] = attempts
    pipeline = _safe_router_records(
        value.get("pipeline"),
        fields=("type", "name"),
    )
    if pipeline:
        output["pipeline"] = pipeline
    return output or None


def validate_openrouter_metadata(
    value: Any,
    *,
    expected_model: str,
    expected_provider: str,
) -> dict[str, Any]:
    """Verify one cache-bypassed response against its exact routing treatment."""

    if not isinstance(expected_model, str) or not expected_model.strip():
        raise ValueError("expected OpenRouter model must be non-empty")
    if not isinstance(expected_provider, str) or not expected_provider.strip():
        raise ValueError("expected OpenRouter provider must be non-empty")

    metadata = sanitize_openrouter_metadata(value)
    if metadata is None:
        raise OpenRouterMetadataError(
            "openrouter.metadata_missing",
            "OpenRouter routing metadata was absent from a cache-bypassed response.",
        )
    if metadata.get("attempt") != 1:
        raise OpenRouterMetadataError(
            "openrouter.attempt_invalid",
            "OpenRouter did not report exactly one successful routing attempt.",
        )
    available = (metadata.get("endpoints") or {}).get("available") or []
    selected = [
        endpoint
        for endpoint in available
        if isinstance(endpoint, dict) and endpoint.get("selected") is True
    ]
    if len(selected) != 1:
        raise OpenRouterMetadataError(
            "openrouter.endpoint_unselected",
            "OpenRouter metadata did not identify exactly one selected endpoint.",
        )

    expected_provider_name = expected_provider.split("/", 1)[0]
    selected_model = selected[0].get("model")
    if (
        metadata.get("requested") != expected_model
        or _router_identity(selected[0].get("provider"))
        != _router_identity(expected_provider_name)
        or not isinstance(selected_model, str)
        or not selected_model.strip()
    ):
        raise OpenRouterMetadataError(
            "openrouter.endpoint_mismatch",
            "OpenRouter metadata did not match the requested provider and model.",
        )
    raw_pipeline = value.get("pipeline") if isinstance(value, Mapping) else None
    if isinstance(raw_pipeline, list) and any(
        isinstance(stage, Mapping)
        and (
            _router_identity(stage.get("name")) == "contextcompression"
            or _router_identity(stage.get("type")) == "contextcompression"
        )
        for stage in raw_pipeline
    ):
        raise OpenRouterMetadataError(
            "openrouter.context_compression_used",
            "OpenRouter reported a forbidden context-compression stage.",
        )
    return metadata


def _safe_router_records(
    value: Any,
    *,
    fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    output: list[dict[str, Any]] = []
    for raw in value[:32]:
        if not isinstance(raw, Mapping):
            continue
        item: dict[str, Any] = {}
        for name in fields:
            candidate = raw.get(name)
            if isinstance(candidate, bool):
                item[name] = candidate
            elif isinstance(candidate, (str, int)) and not isinstance(
                candidate, bool
            ):
                rendered = str(candidate)
                if len(rendered) <= 128:
                    item[name] = candidate
        if item:
            output.append(item)
    return output


def _router_identity(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(character for character in value.casefold() if character.isalnum())


def get_provider_profile(profile_id: str) -> ProviderProfile:
    """Return a named built-in provider profile."""

    normalized = str(profile_id).strip().lower()
    try:
        return PROVIDER_PROFILES[normalized]
    except KeyError as exc:
        choices = ", ".join(sorted(PROVIDER_PROFILES))
        raise ProviderProfileError(
            f"unknown provider profile {profile_id!r}; choose from {choices}"
        ) from exc


def resolve_provider_profile(
    profile_id: str,
    environ: Mapping[str, str] | None = None,
) -> ResolvedProviderConfig:
    """Resolve one built-in profile to a sanitized effective configuration."""

    return get_provider_profile(profile_id).resolve(environ)
