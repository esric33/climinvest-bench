"""Strict, credential-free study configuration for reusable benchmark runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from benchmarks.react_report_building.runtime.structured_output import (
    ACTION_OUTPUT_CONTRACTS,
    HARMONY_REASONING_ACTION_JSON,
    REASONING_THEN_ACTION_JSON,
    is_gpt_oss_model,
)
from benchmarks.react_report_building.runtime.episode import (
    LEGACY_TERMINAL_PROTOCOL,
    SPLIT_TERMINAL_PROTOCOL,
    RESERVE_FINAL_TURN,
    TURN_POLICIES,
    UNRESTRICTED_TURNS,
)

from .providers.profiles import (
    OpenRouterMaxPrice,
    OpenRouterPolicy,
    OpenRouterProviderPolicy,
    ProviderProfileError,
    get_openrouter_treatment,
)

from .scheduler import MAX_CONCURRENCY
from benchmarks.react_report_building.runtime.context_budget import ContextBudget, OPENROUTER_PROBE_ON_CLAMP
from benchmarks.react_report_building.runtime.native_tool_policy import validate_native_tool_policy


SCHEMA_VERSION = "benchrunner.study/v2"
LEGACY_SCHEMA_VERSIONS = frozenset({"benchrunner.study/v1"})
SUPPORTED_ADAPTERS = frozenset({"react_report_v2"})
SUPPORTED_PROVIDERS = frozenset({"openai", "openrouter", "ida", "fixture"})
SUPPORTED_TASKS = frozenset({"complete", "missingness", "update"})
SUPPORTED_SCOPES = frozenset({"report", "section"})
SUPPORTED_REASONING = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)
SUPPORTED_ACTION_PROTOCOLS = frozenset({"native_tools", "textual_json"})


class StudyConfigError(ValueError):
    """Raised when a study file is unsafe, ambiguous, or unsupported."""


@dataclass(frozen=True, slots=True)
class ModelSpec:
    alias: str
    provider: str
    model: str
    reasoning_effort: str | None = None
    action_output_contract: str | None = None
    openrouter: OpenRouterPolicy | None = None
    final_turn_tool_choice_policy: str | None = None
    context_window_tokens: int | None = None
    context_safety_margin_tokens: int | None = None
    input_token_count_mode: str | None = None
    context_probe_max_requests: int | None = None
    context_probe_max_cost_usd: str | None = None
    native_tool_policy: str | None = None
    generation_seed: int | None = None


@dataclass(frozen=True, slots=True)
class CaseSpec:
    project_id: str
    task: str
    scope: str
    category: str | None = None
    section_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SelectionSpec:
    cases: tuple[CaseSpec, ...] = ()
    projects: tuple[str, ...] = ()
    tasks: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    categories: tuple[str, ...] | str = "all"

    @property
    def is_explicit(self) -> bool:
        return bool(self.cases)


@dataclass(frozen=True, slots=True)
class GenerationSpec:
    action_protocol: str = "textual_json"
    max_turns: int = 4
    max_output_tokens: int = 16_000
    timeout_seconds: float = 180.0
    turn_policy: str = UNRESTRICTED_TURNS
    terminal_protocol_version: str = LEGACY_TERMINAL_PROTOCOL
    # A fresh attempt of only the failed episode, never a quality-score retry.
    episode_retry_limit: int = 0


@dataclass(frozen=True, slots=True)
class SchedulerSpec:
    concurrency: int = 10
    provider_limits: Mapping[str, int] = field(default_factory=dict)
    model_limits: Mapping[str, int] = field(default_factory=dict)
    lease_seconds: float = 600.0


@dataclass(frozen=True, slots=True)
class RetrySpec:
    max_attempts: int = 4
    base_delay_seconds: float = 2.0
    max_delay_seconds: float = 60.0
    max_total_delay_seconds: float = 180.0


@dataclass(frozen=True, slots=True)
class StudyConfig:
    study_id: str
    mode: str
    adapter: str
    models: tuple[ModelSpec, ...]
    selection: SelectionSpec
    generation: GenerationSpec
    scheduler: SchedulerSpec
    retry: RetrySpec
    schema_version: str = SCHEMA_VERSION
    replicates: int = 1
    analysis_seed: int = 7
    source_path: Path | None = None

    @property
    def inferential(self) -> bool:
        selection = self.selection
        return bool(
            self.mode == "full"
            and not selection.is_explicit
            and len(selection.projects) == 20
            and set(selection.tasks) == SUPPORTED_TASKS
            and set(selection.scopes) == SUPPORTED_SCOPES
            and selection.categories == "all"
        )


def load_study_config(path: Path) -> StudyConfig:
    source_path = Path(path).resolve()
    try:
        payload = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise StudyConfigError(f"cannot read study config: {source_path}") from exc
    except yaml.YAMLError as exc:
        raise StudyConfigError("study config is not valid YAML") from exc
    return parse_study_config(payload, source_path=source_path)


def parse_study_config(
    payload: Any,
    *,
    source_path: Path | None = None,
) -> StudyConfig:
    root = _mapping(payload, "study config")
    _keys(
        root,
        {
            "schema_version",
            "study_id",
            "mode",
            "adapter",
            "analysis_seed",
            "replicates",
            "models",
            "selection",
            "generation",
            "scheduler",
            "retry",
        },
        "study config",
    )
    schema_version = str(root.get("schema_version") or "")
    if (
        schema_version != SCHEMA_VERSION
        and schema_version not in LEGACY_SCHEMA_VERSIONS
    ):
        raise StudyConfigError(
            f"schema_version must be one of "
            f"{sorted({SCHEMA_VERSION, *LEGACY_SCHEMA_VERSIONS})}"
        )
    study_id = _slug(root.get("study_id"), "study_id")
    mode = str(root.get("mode") or "").strip().lower()
    if mode not in {"smoke", "full"}:
        raise StudyConfigError("mode must be 'smoke' or 'full'")
    adapter = str(root.get("adapter") or "").strip()
    if adapter not in SUPPORTED_ADAPTERS:
        raise StudyConfigError(
            f"adapter must be one of {sorted(SUPPORTED_ADAPTERS)}"
        )
    analysis_seed = _positive_int(
        root.get("analysis_seed", 7), "analysis_seed", allow_zero=True
    )
    replicates = _positive_int(root.get("replicates", 1), "replicates")
    generation = _generation(root.get("generation", {}))
    models = _models(
        root.get("models"),
        schema_version=schema_version,
        action_protocol=generation.action_protocol,
    )
    if generation.terminal_protocol_version == SPLIT_TERMINAL_PROTOCOL:
        for model in models:
            if model.provider != "fixture" and (
                generation.action_protocol != "native_tools"
                or model.final_turn_tool_choice_policy is None
            ):
                raise StudyConfigError(
                    "split terminal protocol requires native_tools and an explicit "
                    "models[].final_turn_tool_choice_policy"
                )
    selection = _selection(root.get("selection"), mode=mode)
    scheduler = _scheduler(root.get("scheduler", {}), models=models)
    retry = _retry(root.get("retry", {}))
    return StudyConfig(
        schema_version=schema_version,
        study_id=study_id,
        mode=mode,
        adapter=adapter,
        analysis_seed=analysis_seed,
        replicates=replicates,
        models=models,
        selection=selection,
        generation=generation,
        scheduler=scheduler,
        retry=retry,
        source_path=source_path,
    )


def sanitized_config(config: StudyConfig) -> dict[str, Any]:
    """Return a stable JSON-ready config containing no credential values."""

    selection: dict[str, Any]
    if config.selection.is_explicit:
        selection = {
            "cases": [
                {
                    "project_id": case.project_id,
                    "task": case.task,
                    "scope": case.scope,
                    **({"category": case.category} if case.category else {}),
                    **(
                        {"section_ids": list(case.section_ids)}
                        if case.section_ids
                        else {}
                    ),
                }
                for case in config.selection.cases
            ]
        }
    else:
        selection = {
            "projects": list(config.selection.projects),
            "tasks": list(config.selection.tasks),
            "scopes": list(config.selection.scopes),
            "categories": (
                config.selection.categories
                if isinstance(config.selection.categories, str)
                else list(config.selection.categories)
            ),
        }
    return {
        "schema_version": config.schema_version,
        "study_id": config.study_id,
        "mode": config.mode,
        "inferential": config.inferential,
        "adapter": config.adapter,
        # This seed is reserved for downstream resampling/statistical analysis.
        # It is deliberately not presented as a provider generation seed.
        "analysis_seed": config.analysis_seed,
        "replicates": config.replicates,
        "models": [
            {
                "alias": item.alias,
                "provider": item.provider,
                "model": item.model,
                **(
                    {"reasoning_effort": item.reasoning_effort}
                    if item.reasoning_effort is not None
                    else {}
                ),
                **(
                    {"action_output_contract": item.action_output_contract}
                    if item.action_output_contract is not None
                    else {}
                ),
                **(
                    {"openrouter": item.openrouter.as_config()}
                    if item.openrouter is not None
                    else {}
                ),
                **(
                    {"final_turn_tool_choice_policy": item.final_turn_tool_choice_policy}
                    if item.final_turn_tool_choice_policy is not None
                    else {}
                ),
                **({"native_tool_policy": item.native_tool_policy}
                   if item.native_tool_policy is not None else {}),
                **({"generation_seed": item.generation_seed}
                   if item.generation_seed is not None else {}),
                **(
                    {
                        "context_window_tokens": item.context_window_tokens,
                        "context_safety_margin_tokens": item.context_safety_margin_tokens,
                        "input_token_count_mode": item.input_token_count_mode,
                    }
                    if item.context_window_tokens is not None else {}
                ),
                **({"context_probe_max_requests": item.context_probe_max_requests,
                    "context_probe_max_cost_usd": item.context_probe_max_cost_usd}
                   if item.context_probe_max_requests is not None else {}),
            }
            for item in config.models
        ],
        "selection": selection,
        "generation": {
            "action_protocol": config.generation.action_protocol,
            "max_turns": config.generation.max_turns,
            "turn_policy": config.generation.turn_policy,
            "max_output_tokens": config.generation.max_output_tokens,
            "timeout_seconds": config.generation.timeout_seconds,
            **({"episode_retry_limit": config.generation.episode_retry_limit}
               if config.generation.episode_retry_limit else {}),
            **(
                {"terminal_protocol_version": config.generation.terminal_protocol_version}
                if config.generation.terminal_protocol_version != LEGACY_TERMINAL_PROTOCOL
                else {}
            ),
        },
        "scheduler": {
            "concurrency": config.scheduler.concurrency,
            "provider_limits": dict(sorted(config.scheduler.provider_limits.items())),
            "model_limits": dict(sorted(config.scheduler.model_limits.items())),
            "lease_seconds": config.scheduler.lease_seconds,
        },
        "retry": {
            "max_attempts": config.retry.max_attempts,
            "base_delay_seconds": config.retry.base_delay_seconds,
            "max_delay_seconds": config.retry.max_delay_seconds,
            "max_total_delay_seconds": config.retry.max_total_delay_seconds,
        },
    }


def _models(
    value: Any,
    *,
    schema_version: str,
    action_protocol: str,
) -> tuple[ModelSpec, ...]:
    if not isinstance(value, list) or not value:
        raise StudyConfigError("models must be a non-empty list")
    output: list[ModelSpec] = []
    for index, raw in enumerate(value):
        item = _mapping(raw, f"models[{index}]")
        _keys(
            item,
            {
                "alias",
                "provider",
                "model",
                "reasoning_effort",
                "action_output_contract",
                "openrouter",
                "final_turn_tool_choice_policy",
                "native_tool_policy",
                "generation_seed",
                "context_window_tokens",
                "context_safety_margin_tokens",
                "input_token_count_mode",
                "context_probe_max_requests",
                "context_probe_max_cost_usd",
            },
            f"models[{index}]",
        )
        alias = _slug(item.get("alias"), f"models[{index}].alias")
        provider = str(item.get("provider") or "").strip().lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise StudyConfigError(
                f"models[{index}].provider must be one of "
                f"{sorted(SUPPORTED_PROVIDERS)}"
            )
        model = str(item.get("model") or "").strip()
        if not model:
            raise StudyConfigError(f"models[{index}].model is required")
        reasoning = item.get("reasoning_effort")
        generation_seed = item.get("generation_seed")
        if generation_seed is not None:
            if (type(generation_seed) is not int
                    or not 0 <= generation_seed <= 2_147_483_646):
                raise StudyConfigError("generation_seed must be an integer between 0 and 2147483646")
            if provider not in {"ida", "openrouter"}:
                raise StudyConfigError("generation_seed requires a qualified ida/OpenRouter endpoint; direct OpenAI Responses has no seed parameter")
        final_turn_policy = item.get("final_turn_tool_choice_policy")
        if final_turn_policy is not None:
            if not isinstance(final_turn_policy, str) or final_turn_policy not in {"auto", "required", "named"}:
                raise StudyConfigError(
                    f"models[{index}].final_turn_tool_choice_policy must be auto, required, or named"
                )
            if action_protocol != "native_tools":
                raise StudyConfigError("final-turn tool choice requires native_tools")
        native_policy = item.get("native_tool_policy")
        if native_policy is not None:
            try:
                validate_native_tool_policy(native_policy, action_protocol=action_protocol,
                                            final_turn_tool_choice_policy=final_turn_policy)
            except ValueError as exc:
                raise StudyConfigError(str(exc)) from exc
            if provider == "fixture":
                raise StudyConfigError("strict native tool policy requires a qualified native_tools endpoint")
        context_fields = {"context_window_tokens", "context_safety_margin_tokens", "input_token_count_mode"}
        supplied_context_fields = context_fields & item.keys()
        context_window = context_margin = count_mode = None
        probe_requests = item.get("context_probe_max_requests")
        probe_cost = item.get("context_probe_max_cost_usd")
        if supplied_context_fields:
            if provider == "fixture":
                raise StudyConfigError("fixture providers do not execute context budgeting")
            if supplied_context_fields != context_fields:
                raise StudyConfigError("context budgeting requires window, safety margin, and count mode together")
            context_window = _positive_int(item["context_window_tokens"], "context_window_tokens")
            context_margin = _positive_int(item["context_safety_margin_tokens"], "context_safety_margin_tokens")
            count_mode = item["input_token_count_mode"]
            if not isinstance(count_mode, str) or count_mode not in {"openai_responses", "conservative_bytes", "responses_probe", "vllm_responses", OPENROUTER_PROBE_ON_CLAMP}:
                raise StudyConfigError("unsupported input_token_count_mode")
            if count_mode == "openai_responses" and provider != "openai":
                raise StudyConfigError("exact OpenAI counting requires the direct OpenAI provider")
            if count_mode in {"responses_probe", "vllm_responses"} and provider != "ida":
                raise StudyConfigError("one-token Responses counting is self-hosted only")
            if context_margin < 256 or context_window <= context_margin + 256:
                raise StudyConfigError("context window must leave output room after a safety margin of at least 256 tokens")
        if count_mode == OPENROUTER_PROBE_ON_CLAMP:
            if provider != "openrouter":
                raise StudyConfigError("conditional paid counting requires an explicit OpenRouter treatment")
            try:
                budget = ContextBudget(context_window, context_margin, count_mode,
                                       context_probe_max_requests=probe_requests,
                                       context_probe_max_cost_usd=probe_cost)
                probe_cost = budget.context_probe_max_cost_usd
            except (TypeError, ValueError) as exc:
                raise StudyConfigError(str(exc)) from None
        elif {"context_probe_max_requests", "context_probe_max_cost_usd"} & item.keys():
            raise StudyConfigError("probe limits require openrouter_probe_on_clamp")
        if reasoning is not None:
            reasoning = str(reasoning).strip().lower()
            if reasoning not in SUPPORTED_REASONING:
                raise StudyConfigError(
                    f"models[{index}].reasoning_effort is unsupported"
                )
        raw_action_output_contract = item.get("action_output_contract")
        if schema_version in LEGACY_SCHEMA_VERSIONS:
            if raw_action_output_contract is not None:
                raise StudyConfigError(
                    f"models[{index}].action_output_contract requires "
                    f"{SCHEMA_VERSION}"
                )
            action_output_contract = None
        elif provider == "fixture":
            if action_protocol == "native_tools":
                raise StudyConfigError(
                    "generation.action_protocol='native_tools' is unsupported "
                    "for fixture providers"
                )
            if raw_action_output_contract is not None:
                raise StudyConfigError(
                    f"models[{index}].action_output_contract is unsupported "
                    "for fixture providers"
                )
            action_output_contract = None
        elif action_protocol == "native_tools":
            if raw_action_output_contract is not None:
                raise StudyConfigError(
                    f"models[{index}].action_output_contract must be omitted "
                    "when generation.action_protocol='native_tools'"
                )
            action_output_contract = None
        elif raw_action_output_contract is None:
            raise StudyConfigError(
                f"models[{index}].action_output_contract is required by "
                f"{SCHEMA_VERSION}"
            )
        else:
            action_output_contract = str(raw_action_output_contract).strip()
        if (
            action_output_contract is not None
            and action_output_contract not in ACTION_OUTPUT_CONTRACTS
        ):
            raise StudyConfigError(
                f"models[{index}].action_output_contract must be one of "
                f"{sorted(ACTION_OUTPUT_CONTRACTS)}"
            )
        if (
            action_output_contract
            in {HARMONY_REASONING_ACTION_JSON, REASONING_THEN_ACTION_JSON}
            and provider != "ida"
        ):
            raise StudyConfigError(
                f"{action_output_contract} is supported only by the ida "
                "vLLM-compatible profile"
            )
        if (
            action_output_contract == HARMONY_REASONING_ACTION_JSON
            and not is_gpt_oss_model(model)
        ):
            raise StudyConfigError(
                "harmony_reasoning_action_json requires a GPT-OSS model"
            )
        raw_openrouter = item.get("openrouter")
        if provider == "openrouter":
            if schema_version in LEGACY_SCHEMA_VERSIONS:
                raise StudyConfigError(
                    f"models[{index}].openrouter requires {SCHEMA_VERSION}"
                )
            if raw_openrouter is None:
                raise StudyConfigError(
                    f"models[{index}].openrouter is required for OpenRouter models"
                )
            openrouter = _openrouter_policy(
                raw_openrouter,
                label=f"models[{index}].openrouter",
            )
            try:
                treatment = get_openrouter_treatment(model)
            except ProviderProfileError as exc:
                raise StudyConfigError(str(exc)) from exc
            if reasoning != treatment.reasoning_effort:
                raise StudyConfigError(
                    f"models[{index}].reasoning_effort must be "
                    f"{treatment.reasoning_effort!r} for {model}"
                )
            if openrouter != treatment.policy:
                raise StudyConfigError(
                    f"models[{index}].openrouter must exactly match the approved "
                    f"routing, privacy, compression, price, and tool-call policy "
                    f"for {model}"
                )
        else:
            if raw_openrouter is not None:
                raise StudyConfigError(
                    f"models[{index}].openrouter is supported only by the "
                    "openrouter provider"
                )
            openrouter = None
        output.append(
            ModelSpec(
                alias,
                provider,
                model,
                reasoning,
                action_output_contract,
                openrouter,
                final_turn_policy,
                context_window,
                context_margin,
                count_mode,
                probe_requests,
                probe_cost,
                native_policy,
                generation_seed,
            )
        )
    aliases = [item.alias for item in output]
    if len(set(aliases)) != len(aliases):
        raise StudyConfigError("model aliases must be unique")
    treatments = [
        (
            item.provider,
            item.model,
            item.reasoning_effort,
            item.action_output_contract,
            item.final_turn_tool_choice_policy,
            item.context_window_tokens,
            item.context_safety_margin_tokens,
            item.input_token_count_mode,
            item.context_probe_max_requests,
            item.context_probe_max_cost_usd,
            item.native_tool_policy,
            item.generation_seed,
        )
        for item in output
    ]
    if len(set(treatments)) != len(treatments):
        raise StudyConfigError(
            "provider/model/reasoning treatments must be unique; aliases are labels, "
            "not replicates"
        )
    return tuple(output)


def _openrouter_policy(value: Any, *, label: str) -> OpenRouterPolicy:
    item = _mapping(value, label)
    _keys(
        item,
        {"provider", "context_compression", "parallel_tool_calls"},
        label,
    )
    if "provider" not in item or "context_compression" not in item:
        raise StudyConfigError(
            f"{label} requires provider and context_compression"
        )
    provider_label = f"{label}.provider"
    provider = _mapping(item.get("provider"), provider_label)
    _keys(
        provider,
        {
            "only",
            "allow_fallbacks",
            "require_parameters",
            "data_collection",
            "zdr",
            "max_price",
        },
        provider_label,
    )
    required_provider_fields = {
        "only",
        "allow_fallbacks",
        "require_parameters",
        "data_collection",
        "zdr",
        "max_price",
    }
    missing = sorted(required_provider_fields - set(provider))
    if missing:
        raise StudyConfigError(
            f"{provider_label} is missing required fields: {', '.join(missing)}"
        )
    only = _string_tuple(provider.get("only"), f"{provider_label}.only")
    if not only:
        raise StudyConfigError(f"{provider_label}.only must not be empty")
    data_collection = str(provider.get("data_collection") or "").strip().lower()
    if data_collection not in {"allow", "deny"}:
        raise StudyConfigError(
            f"{provider_label}.data_collection must be 'allow' or 'deny'"
        )
    max_price_label = f"{provider_label}.max_price"
    max_price = _mapping(provider.get("max_price"), max_price_label)
    _keys(max_price, {"prompt", "completion"}, max_price_label)
    if set(max_price) != {"prompt", "completion"}:
        raise StudyConfigError(
            f"{max_price_label} requires prompt and completion"
        )
    return OpenRouterPolicy(
        provider=OpenRouterProviderPolicy(
            only=only,
            allow_fallbacks=_boolean(
                provider.get("allow_fallbacks"),
                f"{provider_label}.allow_fallbacks",
            ),
            require_parameters=_boolean(
                provider.get("require_parameters"),
                f"{provider_label}.require_parameters",
            ),
            data_collection=data_collection,
            zdr=_boolean(provider.get("zdr"), f"{provider_label}.zdr"),
            max_price=OpenRouterMaxPrice(
                prompt=_positive_float(
                    max_price.get("prompt"),
                    f"{max_price_label}.prompt",
                ),
                completion=_positive_float(
                    max_price.get("completion"),
                    f"{max_price_label}.completion",
                ),
            ),
        ),
        context_compression=_boolean(
            item.get("context_compression"),
            f"{label}.context_compression",
        ),
        parallel_tool_calls=(
            _boolean(
                item.get("parallel_tool_calls"),
                f"{label}.parallel_tool_calls",
            )
            if "parallel_tool_calls" in item
            else None
        ),
    )


def _selection(value: Any, *, mode: str) -> SelectionSpec:
    item = _mapping(value, "selection")
    _keys(
        item,
        {"cases", "projects", "tasks", "scopes", "categories"},
        "selection",
    )
    if "cases" in item:
        if any(key in item for key in ("projects", "tasks", "scopes", "categories")):
            raise StudyConfigError(
                "selection.cases cannot be combined with matrix fields"
            )
        raw_cases = item.get("cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            raise StudyConfigError("selection.cases must be a non-empty list")
        cases = tuple(
            _case(raw, index=index, mode=mode)
            for index, raw in enumerate(raw_cases)
        )
        identities = [
            (
                case.project_id,
                case.task,
                case.scope,
                case.category,
                case.section_ids,
            )
            for case in cases
        ]
        if len(set(identities)) != len(identities):
            raise StudyConfigError("selection.cases contains duplicates")
        return SelectionSpec(cases=cases)

    projects = _string_tuple(item.get("projects"), "selection.projects", upper=True)
    tasks = _string_tuple(item.get("tasks"), "selection.tasks")
    scopes = _string_tuple(item.get("scopes"), "selection.scopes")
    if not projects or not tasks or not scopes:
        raise StudyConfigError(
            "matrix selection requires projects, tasks, and scopes"
        )
    unknown_tasks = sorted(set(tasks) - SUPPORTED_TASKS)
    unknown_scopes = sorted(set(scopes) - SUPPORTED_SCOPES)
    if unknown_tasks:
        raise StudyConfigError(f"unknown tasks: {', '.join(unknown_tasks)}")
    if unknown_scopes:
        raise StudyConfigError(f"unknown scopes: {', '.join(unknown_scopes)}")
    raw_categories = item.get("categories", "all")
    categories: tuple[str, ...] | str
    if raw_categories == "all":
        categories = "all"
    else:
        categories = _string_tuple(raw_categories, "selection.categories")
        if not categories:
            raise StudyConfigError("selection.categories must not be empty")
    if mode == "full" and (
        len(projects) != 20
        or set(tasks) != SUPPORTED_TASKS
        or set(scopes) != SUPPORTED_SCOPES
        or categories != "all"
    ):
        raise StudyConfigError(
            "full mode requires exactly 20 projects, all three tasks, both "
            "scopes, and categories='all'"
        )
    return SelectionSpec(
        projects=projects,
        tasks=tasks,
        scopes=scopes,
        categories=categories,
    )


def _case(value: Any, *, index: int, mode: str) -> CaseSpec:
    label = f"selection.cases[{index}]"
    item = _mapping(value, label)
    _keys(
        item,
        {"project_id", "task", "scope", "category", "section_ids"},
        label,
    )
    project_id = str(item.get("project_id") or "").strip().upper()
    task = str(item.get("task") or "").strip().lower()
    scope = str(item.get("scope") or "").strip().lower()
    if not project_id:
        raise StudyConfigError(f"{label}.project_id is required")
    if task not in SUPPORTED_TASKS:
        raise StudyConfigError(f"{label}.task is unsupported")
    if scope not in SUPPORTED_SCOPES:
        raise StudyConfigError(f"{label}.scope is unsupported")
    category = item.get("category")
    category = str(category).strip() if category is not None else None
    if task == "complete" and category is not None:
        raise StudyConfigError(f"{label}: complete must not have a category")
    if task != "complete" and not category:
        raise StudyConfigError(f"{label}: {task} requires a category")
    section_ids = _string_tuple(
        item.get("section_ids", []), f"{label}.section_ids"
    )
    if scope == "report" and section_ids:
        raise StudyConfigError(f"{label}: report scope cannot select sections")
    if mode == "full" and section_ids:
        raise StudyConfigError(
            f"{label}: partial section selection is smoke-only"
        )
    return CaseSpec(project_id, task, scope, category, section_ids)


def _generation(value: Any) -> GenerationSpec:
    item = _mapping(value, "generation")
    _keys(
        item,
        {
            "action_protocol",
            "max_turns",
            "turn_policy",
            "max_output_tokens",
            "timeout_seconds",
            "terminal_protocol_version",
            "episode_retry_limit",
        },
        "generation",
    )
    action_protocol = str(
        item.get("action_protocol", "textual_json")
    ).strip()
    if action_protocol not in SUPPORTED_ACTION_PROTOCOLS:
        raise StudyConfigError(
            "generation.action_protocol must be one of "
            f"{sorted(SUPPORTED_ACTION_PROTOCOLS)}"
        )
    max_turns = _positive_int(
        item.get("max_turns", 4), "generation.max_turns"
    )
    turn_policy = str(
        item.get("turn_policy", UNRESTRICTED_TURNS)
    ).strip()
    if turn_policy not in TURN_POLICIES:
        raise StudyConfigError(
            "generation.turn_policy must be one of "
            f"{sorted(TURN_POLICIES)}"
        )
    if turn_policy == RESERVE_FINAL_TURN and max_turns < 2:
        raise StudyConfigError(
            "generation.turn_policy='reserve_final_turn' requires "
            "generation.max_turns >= 2"
        )
    terminal_protocol_version = item.get(
        "terminal_protocol_version", LEGACY_TERMINAL_PROTOCOL
    )
    if terminal_protocol_version not in {LEGACY_TERMINAL_PROTOCOL, SPLIT_TERMINAL_PROTOCOL}:
        raise StudyConfigError("unsupported generation.terminal_protocol_version")
    episode_retry_limit = item.get("episode_retry_limit", 0)
    if type(episode_retry_limit) is not int or episode_retry_limit not in {0, 1}:
        raise StudyConfigError("generation.episode_retry_limit must be 0 or 1")
    return GenerationSpec(
        action_protocol=action_protocol,
        max_turns=max_turns,
        turn_policy=turn_policy,
        terminal_protocol_version=terminal_protocol_version,
        episode_retry_limit=episode_retry_limit,
        max_output_tokens=_positive_int(
            item.get("max_output_tokens", 16_000),
            "generation.max_output_tokens",
        ),
        timeout_seconds=_positive_float(
            item.get("timeout_seconds", 180.0),
            "generation.timeout_seconds",
        ),
    )


def _scheduler(value: Any, *, models: tuple[ModelSpec, ...]) -> SchedulerSpec:
    item = _mapping(value, "scheduler")
    _keys(
        item,
        {"concurrency", "provider_limits", "model_limits", "lease_seconds"},
        "scheduler",
    )
    concurrency = _positive_int(
        item.get("concurrency", 10), "scheduler.concurrency"
    )
    if concurrency > MAX_CONCURRENCY:
        raise StudyConfigError(
            f"scheduler.concurrency cannot exceed {MAX_CONCURRENCY}"
        )
    provider_limits = _limit_mapping(
        item.get("provider_limits", {}), "scheduler.provider_limits"
    )
    model_limits = _limit_mapping(
        item.get("model_limits", {}), "scheduler.model_limits"
    )
    unknown_providers = sorted(set(provider_limits) - SUPPORTED_PROVIDERS)
    unknown_models = sorted(set(model_limits) - {model.alias for model in models})
    if unknown_providers:
        raise StudyConfigError(
            "scheduler.provider_limits contains unknown providers: "
            + ", ".join(unknown_providers)
        )
    if unknown_models:
        raise StudyConfigError(
            "scheduler.model_limits contains unknown aliases: "
            + ", ".join(unknown_models)
        )
    if model_limits:
        required_aliases = {
            model.alias for model in models if model.provider != "fixture"
        }
        missing_aliases = sorted(required_aliases - set(model_limits))
        if missing_aliases:
            raise StudyConfigError(
                "scheduler.model_limits must cover every non-fixture model alias; "
                "missing: " + ", ".join(missing_aliases)
            )
    resource_limits: dict[tuple[str, str], tuple[int, str]] = {}
    models_by_alias = {model.alias: model for model in models}
    for alias in sorted(model_limits):
        model = models_by_alias[alias]
        resource = (model.provider, model.model)
        limit = model_limits[alias]
        previous = resource_limits.get(resource)
        if previous is not None and previous[0] != limit:
            previous_limit, previous_alias = previous
            raise StudyConfigError(
                "scheduler.model_limits assigns conflicting limits to aliases "
                f"{previous_alias!r} ({previous_limit}) and {alias!r} ({limit}) "
                f"for backend model {resource[0]}/{resource[1]}"
            )
        resource_limits[resource] = (limit, alias)
    if any(limit > concurrency for limit in (*provider_limits.values(), *model_limits.values())):
        raise StudyConfigError("scheduler sub-limits cannot exceed concurrency")
    return SchedulerSpec(
        concurrency=concurrency,
        provider_limits=provider_limits,
        model_limits=model_limits,
        lease_seconds=_positive_float(
            item.get("lease_seconds", 600.0), "scheduler.lease_seconds"
        ),
    )


def _retry(value: Any) -> RetrySpec:
    item = _mapping(value, "retry")
    _keys(
        item,
        {
            "max_attempts",
            "base_delay_seconds",
            "max_delay_seconds",
            "max_total_delay_seconds",
        },
        "retry",
    )
    result = RetrySpec(
        max_attempts=_positive_int(
            item.get("max_attempts", 4), "retry.max_attempts"
        ),
        base_delay_seconds=_positive_float(
            item.get("base_delay_seconds", 2.0), "retry.base_delay_seconds"
        ),
        max_delay_seconds=_positive_float(
            item.get("max_delay_seconds", 60.0), "retry.max_delay_seconds"
        ),
        max_total_delay_seconds=_positive_float(
            item.get("max_total_delay_seconds", 180.0),
            "retry.max_total_delay_seconds",
        ),
    )
    if result.base_delay_seconds > result.max_delay_seconds:
        raise StudyConfigError("retry base delay cannot exceed maximum delay")
    return result


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StudyConfigError(f"{label} must be an object")
    return value


def _keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise StudyConfigError(
            f"{label} contains unknown fields: {', '.join(unknown)}"
        )


def _slug(value: Any, label: str) -> str:
    rendered = str(value or "").strip()
    if not rendered or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for character in rendered
    ):
        raise StudyConfigError(
            f"{label} must contain only letters, digits, '-' and '_'"
        )
    return rendered


def _positive_int(value: Any, label: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StudyConfigError(f"{label} must be an integer")
    minimum = 0 if allow_zero else 1
    if value < minimum:
        raise StudyConfigError(f"{label} must be at least {minimum}")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise StudyConfigError(f"{label} must be a boolean")
    return value


def _positive_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StudyConfigError(f"{label} must be numeric")
    rendered = float(value)
    if rendered <= 0:
        raise StudyConfigError(f"{label} must be positive")
    return rendered


def _string_tuple(value: Any, label: str, *, upper: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise StudyConfigError(f"{label} must be a list")
    output = tuple(
        (str(item).strip().upper() if upper else str(item).strip())
        for item in value
        if str(item).strip()
    )
    if len(set(output)) != len(output):
        raise StudyConfigError(f"{label} contains duplicates")
    return output


def _limit_mapping(value: Any, label: str) -> Mapping[str, int]:
    item = _mapping(value, label)
    return {
        str(key): _positive_int(raw, f"{label}.{key}")
        for key, raw in item.items()
    }
