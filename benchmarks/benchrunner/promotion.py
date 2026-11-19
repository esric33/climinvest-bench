"""Offline, fail-closed promotion of one exact native-tool treatment.

Policies are frozen before smoke generation. Evidence bundles seal real output
files after collection. Neither operation makes requests or declares a model
qualified merely because its configuration parses. The launch owner supplies
observed serving provenance; hashes establish integrity, not remote attestation.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from benchmarks.react_report_building.util import sha256_json, sha256_text
from benchmarks.react_report_building.runtime.final_turn_policy import final_turn_policy_provenance
from benchmarks.react_report_building.runtime.native_tool_policy import native_tool_policy_provenance
from .artifacts import atomic_write_json
from .config import load_study_config, parse_study_config, sanitized_config
from .plan import _adapter_implementation_hash, build_study_plan
from .providers import native_smoke, profiles
from .work import WorkGraph, WorkSpec

POLICY_SCHEMA = "benchrunner.smoke_promotion_policy/v1"
BUNDLE_SCHEMA = "benchrunner.smoke_evidence_bundle/v1"
OBSERVED_SCHEMA = "benchrunner.observed_serving/v1"
PROBE_FIELDS = ("context_probe_max_requests", "context_probe_max_cost_usd")
CASE_PAIRS = (("FP102", "complete", None),
              ("FP083", "missingness", "value_with_dependents.single_section"),
              ("FP019", "update", "collection_with_dependents.cross_section"))


class PromotionError(ValueError):
    """Evidence is missing, inconsistent, stale or did not pass."""


def require(ok: Any, message: str) -> None:
    if not ok:
        raise PromotionError(message)


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (OSError, ValueError) as exc:
        raise PromotionError(f"cannot read valid JSON: {path}") from exc


def _file(root: Path, relative: str) -> Path:
    require(isinstance(relative, str) and bool(relative), "artifact path is missing")
    path = (root / relative).resolve()
    require(not Path(relative).is_absolute() and path.is_relative_to(root.resolve()), "artifact path escapes evidence directory")
    require(path.is_file(), f"required evidence is missing: {relative}")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> list[dict]:
    try:
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except (OSError, ValueError) as exc:
        raise PromotionError(f"invalid JSONL evidence: {path}") from exc
    require(all(isinstance(row, dict) for row in rows), "JSONL records must be objects")
    return rows


def _policy(policy: dict) -> None:
    require(policy.get("schema_version") == POLICY_SCHEMA and policy.get("status") == "prepared_not_qualified"
            and policy.get("policy_sha256") == sha256_json({k: v for k, v in policy.items() if k != "policy_sha256"}), "promotion policy digest/schema mismatch")
    require(policy.get("source_binding") == source_binding(), "current runtime/source differs from reviewed policy; prepare a new policy")


def _clean(config: dict) -> dict:
    return sanitized_config(parse_study_config({k: v for k, v in config.items() if k != "inferential"}))


def treatment(config: dict, *, omit_probe_limits: bool = False) -> dict:
    result = {k: deepcopy(v) for k, v in _clean(config).items()
              if k not in {"study_id", "mode", "inferential", "selection"}}
    if omit_probe_limits:
        for model in result["models"]:
            for field in PROBE_FIELDS:
                model.pop(field, None)
    return result


def source_binding() -> dict:
    benchmark = Path(__file__).resolve().parents[1] / "react_report_building"
    # Plans bind prepared inputs, but gold files also need an explicit binding:
    # a hand-edited resolved oracle must not inherit an earlier smoke approval.
    # data/raw is an unused local download/cache, not a runtime input. Its
    # descriptor, normalized evidence, corrections and gold remain hash-bound.
    inputs = {str(path.relative_to(benchmark)): _sha(path)
              for folder in (benchmark / "data", benchmark / "v2/data", benchmark / "v2/compiled", benchmark / "prompts")
              for path in sorted(folder.rglob("*"))
              if path.is_file() and path.suffix in {".json", ".yaml", ".yml", ".md"}
              and not path.is_relative_to(benchmark / "data/raw")}
    return {
        "adapter_implementation_sha256": _adapter_implementation_hash(),
        "runtime_source_sha256": native_smoke._runtime_source_hash(),
        "provider_profile_implementation_sha256": sha256_text(Path(profiles.__file__).read_text()),
        "smoke_implementation_sha256": sha256_text(Path(native_smoke.__file__).read_text()),
        "probe_budget_implementation_sha256": sha256_text(Path(__file__).with_name("probe_budget.py").read_text()),
        "vllm_count_implementation_sha256": sha256_text(Path(profiles.__file__).with_name("vllm_input_tokens.py").read_text()),
        "promotion_implementation_sha256": sha256_text(Path(__file__).read_text()),
        "benchmark_artifacts_sha256": sha256_json(inputs),
        "gold_implementation_sha256": _sha(benchmark / "v2/oracle.py"),
    }


def _endpoint(value: str, local: bool) -> str:
    parsed = urlsplit(value)
    require(parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username
            and not parsed.password and not parsed.query and not parsed.fragment, "invalid serving endpoint")
    if local:
        require(parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                and parsed.port is not None and 1024 <= parsed.port <= 65535,
                "local serving endpoint must be an explicit allocation-local port")
        return "http://allocation-local" + parsed.path
    require(parsed.scheme == "https", "hosted endpoint must use HTTPS")
    return urlunsplit(parsed)


def serving_identity(identity: dict) -> dict:
    """Normalize only an allocation-local TCP port, never model/server fields."""
    result = deepcopy(identity)
    require(result.get("kind") in {"vllm", "hosted"}, "serving identity needs vllm or hosted kind")
    local = result["kind"] == "vllm"
    for key in ("model_id", "source_revision"):
        require(isinstance(result.get(key), str) and bool(result[key]), f"serving identity lacks {key}")
    require(re.fullmatch(r"[0-9a-f]{40}", result["source_revision"]), "source revision must be pinned")
    result["resolved_endpoint"] = _endpoint(result.get("resolved_endpoint", ""), local)
    if local:
        if "minimum_kv_cache_tokens" in result:
            require(type(result["minimum_kv_cache_tokens"]) is int
                    and result["minimum_kv_cache_tokens"] > 0,
                    "minimum_kv_cache_tokens must be a positive integer")
        for key in ("model_revision", "tokenizer_revision"):
            require(re.fullmatch(r"[0-9a-f]{40}", str(result.get(key, ""))), f"serving identity lacks pinned {key}")
        require(re.fullmatch(r".+@sha256:[0-9a-f]{64}", str(result.get("image_digest", ""))), "server image must be digest-pinned")
        require(isinstance(result.get("hardware"), dict) and result["hardware"].get("gpu_model")
                and type(result["hardware"].get("gpu_count")) is int and result["hardware"]["gpu_count"] > 0,
                "actual GPU model/count are required")
        args = result.get("serve_argv")
        require(isinstance(args, list) and args and all(isinstance(x, str) for x in args), "actual serving argv is required")
        require(args.count("--port") == 1, "serving argv must have one allocation port")
        port_index = args.index("--port") + 1
        require(port_index < len(args) and args[port_index] == str(urlsplit(identity["resolved_endpoint"]).port), "serving argv port differs from endpoint")
        args[port_index] = "<allocation-port>"
        hashes = result.get("artifact_sha256")
        require(isinstance(hashes, dict), "serving artifact hashes must be declared, including an explicit empty map")
        for path, digest in hashes.items():
            require(isinstance(path, str) and re.fullmatch(r"[0-9a-f]{64}", str(digest)), "invalid serving artifact hash")
        for flag in ("--tool-parser-plugin", "--reasoning-parser-plugin", "--chat-template"):
            if flag in args:
                pos = args.index(flag) + 1
                require(pos < len(args) and args[pos] in hashes, f"{flag} file is not hash-bound")
    else:
        require("routing" in result, "hosted routing must be explicit, including null for a direct provider")
    return result


def _profile_payload(profile_id: str) -> dict:
    profile = profiles.resolve_provider_profile(profile_id)
    return {"profile_id": profile.profile_id, "protocol": profile.protocol,
            "base_url": profile.base_url, "responses_endpoint": profile.responses_endpoint,
            "api_key_env": profile.api_key_env, "allow_insecure_http": profile.allow_insecure_http,
            "structured_output_dialect": profile.structured_output_dialect,
            "request_headers": [list(x) for x in profile.request_headers],
            "supports_openrouter_policy": profile.supports_openrouter_policy}


def _profile_shape(payload: dict, local: bool) -> dict:
    result = deepcopy(payload)
    for key in ("base_url", "responses_endpoint"):
        result[key] = _endpoint(result[key], local)
    return result


def _plan_digest(plan: dict) -> str:
    """Bind every input/implementation identity; endpoint profiles are checked separately."""
    rows = []
    for work in plan["graph"]["work"]:
        identity = {k: v for k, v in work["identity"].items()
                    if k not in {"study_id", "study_mode", "inferential", "provider_profile_sha256"}}
        rows.append({"kind": work["kind"], "provider": work["provider"], "model": work["model"], "identity": identity})
    # Record identities do not contain dependency IDs; explicit membership is
    # bound separately and checked when loading the graph/record specifications.
    return sha256_json(sorted(rows, key=sha256_json))


def _verify_plan(plan: dict, profile_hash: str) -> None:
    graph = WorkGraph(WorkSpec.from_dict(work) for work in plan["graph"]["work"])
    require(graph.graph_id == plan["graph_id"] == plan["graph"]["graph_id"], "plan graph hash is invalid")
    episodes = {work.work_id: work for work in graph if work.kind == "react_episode"}
    reducers = {work.work_id: work for work in graph if work.kind == "react_record"}
    require(len(episodes) == plan["episode_count"] and len(reducers) == plan["record_count"] == len(plan["records"]), "plan counts do not match work graph")
    require(all(work.identity.get("provider_profile_sha256") == profile_hash for work in graph), "plan provider profile differs from observed route")
    covered = []
    for record in plan["records"]:
        reducer = reducers.get(record["work_id"])
        require(reducer is not None, "record reducer is absent")
        require(set(record["episode_work_ids"]) == set(reducer.dependencies), "record episode membership differs from graph")
        require(all(k in episodes and episodes[k].identity["record_key"] == record["record_key"] for k in reducer.dependencies), "record contains wrong episode")
        require(all(record.get(k) == v for k, v in reducer.identity.items()), "record specification differs from graph identity")
        covered.extend(reducer.dependencies)
    require(len(covered) == len(set(covered)) == len(episodes), "episode coverage is missing or duplicated")


def prepare_policy(full_path: Path, smoke_path: Path, intended_serving: dict,
                   *, allow_probe_limit_scaling: bool = False) -> dict:
    full, smoke = load_study_config(full_path), load_study_config(smoke_path)
    require(full.inferential and smoke.mode == "smoke", "need a canonical full study and explicit task smoke")
    a, b = sanitized_config(full), sanitized_config(smoke)
    require(len(full.models) == len(smoke.models) == 1, "promotion is per model treatment")
    require(treatment(a, omit_probe_limits=allow_probe_limit_scaling) == treatment(b, omit_probe_limits=allow_probe_limit_scaling), "full and task-smoke treatment differ")
    contract = (full.models[0].native_tool_policy, full.models[0].final_turn_tool_choice_policy)
    require(contract in {("strict_required_v1", "required"), ("strict_auto_v1", "auto")},
            "promotion requires strict/required or an explicit strict/auto treatment")
    require(full.generation.max_turns == 8 and full.generation.terminal_protocol_version == "react_report.terminal_protocol/v2", "promotion requires the corrected eight-turn protocol")
    wanted = {(project, task, category, scope) for project, task, category in CASE_PAIRS for scope in ("report", "section")}
    selected = {(c.project_id, c.task, c.category, c.scope) for c in smoke.selection.cases}
    require(selected == wanted and len(smoke.selection.cases) == 6 and not any(c.section_ids for c in smoke.selection.cases), "task smoke must contain the fixed six full-composition cases")
    require(full.replicates == smoke.replicates == 1, "smoke promotion requires one replicate")
    normalized_serving = serving_identity(intended_serving)
    require(normalized_serving["model_id"] == full.models[0].model, "serving identity names a different model")
    local = normalized_serving["kind"] == "vllm"
    require(local == (full.models[0].provider == "ida"), "serving kind differs from provider")
    if not local:
        require(normalized_serving["routing"] == a["models"][0].get("openrouter"), "serving routing differs from study")
    profile = _profile_payload(full.models[0].provider)
    require(_endpoint(profile["responses_endpoint"], local) == normalized_serving["resolved_endpoint"], "configured endpoint differs from intended serving")
    full_plan = build_study_plan(full, enforce_condition_readiness=False).to_dict()
    smoke_plan = build_study_plan(smoke).to_dict()
    require((smoke_plan["record_count"], smoke_plan["episode_count"]) == (6, 48), "task smoke did not expand to six records/48 episodes")
    require((full_plan["record_count"], full_plan["episode_count"]) == (440, 3520), "full study coverage is not canonical")
    policy = {
        "schema_version": POLICY_SCHEMA, "status": "prepared_not_qualified",
        "full_config": a, "task_smoke_config": b,
        "source_binding": source_binding(), "serving_identity": normalized_serving,
        "provider_profile_shape": _profile_shape(profile, local),
        "full_plan_inputs_sha256": _plan_digest(full_plan),
        "task_smoke_plan_inputs_sha256": _plan_digest(smoke_plan),
        "allow_probe_limit_scaling": allow_probe_limit_scaling,
        "stage_a": {"long_form": True, "probe_max_output_tokens": 2048, "long_form_max_output_tokens": 8192,
                    "required_case_ids": [x[0] for x in (*native_smoke.CASE_SPECS, native_smoke.LONG_FORM_CASE_SPEC)]},
        "stage_b": {"records": 6, "episodes": 48, "require_all_accepted_terminals": True,
                    "deterministic_quality_threshold": None, "partials_allowed": False},
        "provider_calls": 0,
    }
    if contract == ("strict_auto_v1", "auto"):
        # This is a separate, request-bound treatment, never an implicit
        # compatibility fallback from an unsuccessful required-tool smoke.
        policy["stage_a"]["native_tool_policy"] = "strict_auto_v1"
        policy["stage_a"]["tool_choice_policy"] = "auto"
    policy["policy_sha256"] = sha256_json(policy)
    return policy


def _observed(path: Path, policy: dict, files: dict[str, str] | None = None) -> dict:
    value = _json(path)
    require(value.get("schema_version") == OBSERVED_SCHEMA, "observed serving capture schema is missing")
    require(value.get("observation_method") in {"launcher_runtime_capture", "provider_endpoint_capture"}, "actual runtime/endpoint capture is required")
    try:
        require(datetime.fromisoformat(value["captured_at"].replace("Z", "+00:00")).tzinfo is not None, "capture time needs a timezone")
    except (KeyError, TypeError, ValueError) as exc:
        raise PromotionError("observed serving capture time is invalid") from exc
    identity = value.get("identity", {})
    require(serving_identity(identity) == policy["serving_identity"], "observed serving identity differs from reviewed treatment")
    profile = value.get("provider_profile", {})
    local = identity["kind"] == "vllm"
    require(_profile_shape(profile, local) == policy["provider_profile_shape"], "observed provider profile differs")
    require(profile["responses_endpoint"] == identity["resolved_endpoint"], "observed endpoint and profile disagree")
    evidence = value.get("evidence_artifacts", [])
    roles = {item.get("role") for item in evidence}
    required = {"runtime_provenance", "serving_model", "launch_spec"} if local else {"runtime_provenance", "endpoint_metadata"}
    minimum_kv_tokens = identity.get("minimum_kv_cache_tokens") if local else None
    if minimum_kv_tokens is not None:
        required.add("kv_headroom")
    require(required.issubset(roles), "observed serving capture lacks supporting runtime/endpoint evidence")
    for item in evidence:
        artifact = _file(path.parent, item["path"])
        require(_sha(artifact) == item.get("sha256"), "observed serving evidence hash mismatch")
        if files is not None:
            require(files.get(item["path"]) == item["sha256"], "serving evidence is not in sealed bundle")
        if item["role"] == "runtime_provenance":
            runtime = _json(artifact)
            require(runtime.get("source_revision") == identity["source_revision"]
                    and runtime.get("adapter_implementation_sha256") == policy["source_binding"]["adapter_implementation_sha256"]
                    and runtime.get("runtime_source_sha256") == policy["source_binding"]["runtime_source_sha256"]
                    and runtime.get("serving_identity_sha256") == sha256_json(identity), "runtime provenance does not bind source and observed serving identity")
        if item["role"] == "serving_model":
            model_receipt = _json(artifact)
            require(model_receipt.get("matched") is True and model_receipt.get("expected_model") == identity["model_id"]
                    and identity["model_id"] in model_receipt.get("listed_models", []), "actual served model receipt is invalid")
        if item["role"] == "kv_headroom" and minimum_kv_tokens is not None:
            headroom = _json(artifact)
            capacities = headroom.get("observed_token_capacities")
            require(headroom.get("schema_version") == "climinvest.vllm_kv_headroom/v1"
                    and headroom.get("passed") is True
                    and headroom.get("error_code") is None
                    and type(headroom.get("required_tokens")) is int
                    and headroom["required_tokens"] == minimum_kv_tokens
                    and type(headroom.get("minimum_observed_tokens")) is int
                    and headroom["minimum_observed_tokens"] >= minimum_kv_tokens
                    and isinstance(capacities, list) and bool(capacities)
                    and all(type(count) is int and count > 0 for count in capacities)
                    and min(capacities) == headroom["minimum_observed_tokens"]
                    and re.fullmatch(r"[0-9a-f]{64}", str(headroom.get("log_sha256", ""))),
                    "KV headroom receipt does not meet the reviewed minimum")
    return value


def seal_evidence(policy: dict, root: Path, stage: str) -> dict:
    """Hash collected artifacts, then validate them; never manufacture success."""
    _policy(policy)
    require(stage in {"stage_a", "stage_b"}, "unknown evidence stage")
    root = root.resolve()
    observed = _observed(root / "observed-serving.json", policy)
    paths = {"observed-serving.json", *(x["path"] for x in observed["evidence_artifacts"])}
    if stage == "stage_a":
        paths.add("native-smoke.json")
        receipt = _json(root / "native-smoke.json")
        paths.update(x["path"] for model in receipt.get("models", []) for case in model.get("cases", []) for x in case.get("audit_artifacts", []))
    else:
        paths.update({"plan.json", "manifest.json", "resolved-config.json", "exports/summary.json", "exports/records.jsonl", "exports/failures.jsonl"})
        for record in _rows(root / "exports/records.jsonl"):
            paths.update(record.get("episode_artifacts", []))
            for key in ("candidate_artifact", "record_artifact"):
                if record.get(key):
                    paths.add(record[key])
    bundle = {"schema_version": BUNDLE_SCHEMA, "stage": stage, "policy_sha256": policy["policy_sha256"],
              "files": {p: _sha(_file(root, p)) for p in sorted(paths)}}
    bundle["bundle_sha256"] = sha256_json(bundle)
    validate_evidence(policy, root, bundle)
    return bundle


def validate_evidence(policy: dict, root: Path, bundle: dict) -> dict:
    _policy(policy)
    require(bundle.get("schema_version") == BUNDLE_SCHEMA and bundle.get("policy_sha256") == policy["policy_sha256"], "evidence bundle belongs to another policy")
    require(bundle.get("bundle_sha256") == sha256_json({k: v for k, v in bundle.items() if k != "bundle_sha256"}), "evidence bundle digest mismatch")
    files = bundle.get("files", {})
    require(isinstance(files, dict) and "observed-serving.json" in files, "observed serving evidence is unsealed")
    for relative, digest in files.items():
        require(_sha(_file(root, relative)) == digest, f"evidence file hash mismatch: {relative}")
    observed = _observed(root / "observed-serving.json", policy, files)
    if bundle.get("stage") == "stage_a":
        _validate_a(policy, root, files, observed)
    elif bundle.get("stage") == "stage_b":
        _validate_b(policy, root, files, observed)
    else:
        raise PromotionError("unknown evidence stage")
    return {"stage": bundle["stage"], "status": "passed", "bundle_sha256": bundle["bundle_sha256"]}


def _validate_a(policy: dict, root: Path, files: dict, observed: dict) -> None:
    require("native-smoke.json" in files, "native smoke receipt is unsealed")
    receipt = _json(root / "native-smoke.json")
    require(receipt.get("schema_version") == native_smoke.LONG_FORM_SCHEMA_VERSION and receipt.get("status") == "passed", "Stage A did not pass the long-form native gate")
    require(receipt.get("study_sha256") == sha256_json(receipt.get("study")), "Stage A study digest mismatch")
    require(receipt["study"] in [policy["full_config"], policy["task_smoke_config"]], "Stage A used another configuration")
    for key in ("runtime_source_sha256", "provider_profile_implementation_sha256", "smoke_implementation_sha256",
                "probe_budget_implementation_sha256", "vllm_count_implementation_sha256"):
        require(receipt.get(key) == policy["source_binding"][key], f"Stage A source mismatch: {key}")
    require(receipt.get("probe_requested_max_output_tokens") == 2048 and receipt.get("request_budget_per_model") == 8
            and receipt.get("retry_attempts") == 0, "Stage A limits differ from the preregistered gate")
    cap = receipt["study"]["generation"]["max_output_tokens"]
    configured_model = receipt["study"]["models"][0]
    explicit_auto = configured_model.get("native_tool_policy") == "strict_auto_v1"
    final_choice = configured_model["final_turn_tool_choice_policy"]
    expected_long = native_smoke._long_form_constraints(8192, min(cap, 8192), tool_choice=final_choice)
    require(receipt.get("long_form") == expected_long, "Stage A long-form constraints differ")
    constraints = {"schema_version": native_smoke.LONG_FORM_SCHEMA_VERSION,
                   "probe_requested_max_output_tokens": 2048, "probe_effective_max_output_tokens": min(cap, 2048),
                   "request_budget_per_model": 8, "conditional_count_probe_request_ceiling_per_model": 1,
                   "conditional_count_max_observed_output_tokens": native_smoke.OPENROUTER_PROBE_MAX_OBSERVED_OUTPUT_TOKENS,
                   "long_form": expected_long}
    require(receipt.get("qualification_constraints_sha256") == sha256_json(constraints), "Stage A constraint hash mismatch")
    require(len(receipt.get("models", [])) == 1, "Stage A model count differs")
    model = receipt["models"][0]
    require(model.get("model") == receipt["study"]["models"][0] and model.get("status") == "passed", "Stage A model treatment mismatch/failure")
    require(model.get("treatment_sha256") == sha256_json({"model": model["model"], "generation": receipt["study"]["generation"]}), "Stage A treatment hash mismatch")
    require(model.get("resolved_endpoint_sha256") == sha256_text(observed["identity"]["resolved_endpoint"]), "Stage A ran on another endpoint")
    cases = model.get("cases", [])
    require([x.get("case_id") for x in cases] == policy["stage_a"]["required_case_ids"], "Stage A cases are missing, duplicated or changed")
    total_requests = 0
    specs = (*native_smoke.CASE_SPECS, native_smoke.LONG_FORM_CASE_SPEC)
    for case, spec in zip(cases, specs):
        require(case.get("status") == "passed" and all(case.get(key) is True for key in
                ("native_conformance_raw", "native_conformance_normalized", "terminal_accepted", "terminal_schema_valid")), f"Stage A case failed: {spec[0]}")
        require(case.get("failure") is None and case.get("replayed_provider_history_turns_at_start") == 0, "Stage A failure or fabricated prior history")
        if explicit_auto:
            expected_final = final_turn_policy_provenance("auto")
            expected_native = native_tool_policy_provenance("strict_auto_v1")
            require(policy["stage_a"].get("native_tool_policy") == "strict_auto_v1"
                    and policy["stage_a"].get("tool_choice_policy") == "auto"
                    and final_choice == "auto" and model.get("final_turn_policy") == expected_final
                    and case.get("final_turn_policy") == expected_final,
                    "Stage A auto treatment attribution differs")
            contexts = case.get("request_contexts", [])
            require(len(contexts) == case.get("generation_request_count") and bool(contexts)
                    and all(context.get("effective_tool_choice") == "auto"
                            and context.get("native_tool_policy") == expected_native
                            and context.get("final_turn_tool_choice_policy") == expected_final for context in contexts),
                    "Stage A did not use strict auto on every request")
        episode, expected_tool, _ = native_smoke._long_form_episode(8) if spec == native_smoke.LONG_FORM_CASE_SPEC else native_smoke._episode(spec, 8)
        require(case.get("prompt_sha256") == sha256_json(episode.messages) and case.get("terminal_tool") == expected_tool, "Stage A prompt/terminal treatment differs")
        artifacts, schemas = case.get("audit_artifacts", []), case.get("offered_production_schemas", [])
        require(len(artifacts) == len(schemas) == case.get("generation_request_count") and 1 <= len(artifacts) <= spec[2], "Stage A request/raw-evidence count mismatch")
        total_requests += len(artifacts)
        raws = []
        for artifact, offered in zip(artifacts, schemas):
            require(artifact.get("status") == "saved" and artifact.get("redacted") is False, "raw qualification response is absent or redacted")
            require(files.get(artifact.get("path")) == artifact.get("artifact_sha256"), "raw qualification response is unsealed")
            raw = _json(_file(root, artifact["path"]))
            require(sha256_text(json.dumps(raw, ensure_ascii=False, sort_keys=True)) == artifact.get("raw_sha256"), "native raw response canonical hash mismatch")
            require(offered.get("sha256") == sha256_json(offered.get("definitions")), "offered schema hash mismatch")
            require(native_smoke._raw_conformance(raw, offered["definitions"])["valid"], "raw response does not conform to native schema")
            raws.append(raw)
        require(all(x.get("matched") is True for x in case.get("input_count_consistency", [])), "Stage A exact count/usage mismatch")
        if model["model"].get("input_token_count_mode") == "vllm_responses":
            require(len(case.get("input_count_consistency", [])) == len(raws), "Stage A renderer was not qualified on every response")
        if spec[0] == "tool_continuation":
            require(case.get("continuation_valid") is True, "native continuation did not pass")
        if spec == native_smoke.LONG_FORM_CASE_SPEC:
            if explicit_auto:
                require({key: case.get("long_form", {}).get(key) for key in expected_long} == expected_long,
                        "long-form auto request constraints differ")
            terminal = next(x for x in raws[-1]["output"] if x.get("type") == "function_call")
            require(native_smoke._long_form_conformance({"terminal": json.loads(terminal["arguments"])})["valid"], "long-form raw payload is too small or missing escaping characters")
    require(total_requests == model.get("generation_request_count") and total_requests <= 8, "Stage A exceeded action budget")
    counts = model.get("counting_cases", [])
    if model["model"].get("input_token_count_mode") == native_smoke.OPENROUTER_CONDITIONAL_COUNT_MODE:
        require(len(counts) == 1 and counts[0].get("status") == "passed" and counts[0].get("actions_executed") == 0
                and counts[0].get("context_count_request_count") == 1, "conditional counting was not qualified")
    else:
        require(not counts, "unexpected Stage A counting treatment")


def _validate_b(policy: dict, root: Path, files: dict, observed: dict) -> None:
    required = {"plan.json", "resolved-config.json", "manifest.json", "exports/summary.json", "exports/records.jsonl", "exports/failures.jsonl"}
    require(required.issubset(files), "Stage B core evidence is unsealed")
    config, plan = _json(root / "resolved-config.json"), _json(root / "plan.json")
    require(config == policy["task_smoke_config"] == plan.get("config"), "Stage B used another configuration")
    _verify_plan(plan, sha256_json(observed["provider_profile"]))
    require(_plan_digest(plan) == policy["task_smoke_plan_inputs_sha256"], "Stage B prompt/input/source bindings differ")
    manifest, summary = _json(root / "manifest.json"), _json(root / "exports/summary.json")
    require(manifest.get("schema_version") == "benchrunner.run_manifest/v1"
            and manifest.get("record_count") == 6 and manifest.get("episode_count") == 48
            and manifest.get("graph_id") == plan["graph_id"] and manifest.get("plan_id") == "plan-" + sha256_json({k: v for k, v in plan.items() if k != "graph"}), "Stage B manifest/plan identity mismatch")
    require(summary.get("schema_version") == "benchrunner.run_export/v2" and summary.get("collection_complete") is True
            and summary.get("planned_records") == summary.get("scientific_records") == 6, "Stage B collection is incomplete")
    require(not _rows(root / "exports/failures.jsonl") and summary.get("infrastructure_failures") == 0, "Stage B has failed/blocked scheduler work")
    records = _rows(root / "exports/records.jsonl")
    expected = {x["record_key"]: x for x in plan["records"]}
    require(len(records) == 6 and {x.get("record_key") for x in records} == set(expected), "Stage B records are missing or duplicated")
    episodes_seen = set()
    for record in records:
        spec = expected[record["record_key"]]
        require(record.get("schema_version") == "react_report.run_record/v2", "unsupported native run record schema")
        require(all(record.get(k) == v for k, v in spec.items() if k not in {"work_id", "schema_version", "episode_work_ids"}), "Stage B record identity differs from bound plan")
        # WorkSpec canonicalizes dependency order; report specs preserve section
        # order. Both must identify the same complete, duplicate-free set.
        recorded_ids = record.get("episode_work_ids", [])
        require(isinstance(recorded_ids, list) and len(recorded_ids) == len(spec["episode_work_ids"])
                and set(recorded_ids) == set(spec["episode_work_ids"]), "Stage B episode membership differs from bound plan")
        # Task-smoke records are diagnostic by design. Analysis eligibility
        # belongs to the canonical full study and cannot qualify a smoke.
        require(record.get("status") == "completed" and record.get("analysis_eligible") is False
                and record.get("diagnostic_only") is True and record.get("study_mode") == "smoke"
                and record.get("inferential") is False
                and record.get("partial_smoke") is False and isinstance(record.get("score"), dict), "Stage B did not produce a complete scored report unit")
        require(record.get("outcomes", {}).get("report_reached_terminal") is True, "Stage B report did not reach all accepted terminals")
        count = 15 if record["scope"] == "section" else 1
        require(len(record.get("episode_artifacts", [])) == len(record.get("episode_work_ids", [])) == count, "Stage B contains a partial composition")
        require(record.get("record_artifact") in files and _json(_file(root, record["record_artifact"])) == record, "record export differs from saved record artifact")
        candidate = record.get("candidate_artifact")
        require(candidate in files and _sha(_file(root, candidate)) == record.get("candidate_markdown_sha256"), "Stage B candidate is missing or changed")
        for relative in record["episode_artifacts"]:
            require(relative in files, "Stage B episode is unsealed")
            episode = _json(_file(root, relative))
            work_id = episode.get("runner_work_id")
            require(work_id in spec["episode_work_ids"] and work_id not in episodes_seen, "Stage B episode is wrong or duplicated")
            episodes_seen.add(work_id)
            require(episode.get("record_key") == record["record_key"] and episode.get("status") == "completed"
                    and episode.get("terminal", {}).get("status") == "accepted", "Stage B episode did not reach an accepted terminal")
            require(bool(episode.get("turns")) and isinstance(episode.get("accounting"), dict), "Stage B episode is missing actual turns/accounting")
    require(len(episodes_seen) == 48, "Stage B episode coverage is incomplete")


def validate_promotion(policy: dict, config_path: Path, observed_path: Path, phase: str,
                       *, stage_a: tuple[Path, dict] | None = None,
                       stage_b: tuple[Path, dict] | None = None) -> dict:
    _policy(policy)
    require(phase in {"stage_a", "stage_b", "full"}, "invalid promotion phase")
    current = load_study_config(config_path)
    expected = policy["task_smoke_config"] if phase == "stage_b" else policy["full_config"]
    require(sanitized_config(current) == expected, "launch configuration differs from reviewed stage")
    observed = _observed(observed_path, policy)
    require(_profile_payload(current.models[0].provider) == observed["provider_profile"], "launch environment differs from observed serving profile")
    if phase != "stage_a":
        plan = build_study_plan(current, enforce_condition_readiness=False).to_dict()
        require(_plan_digest(plan) == policy["task_smoke_plan_inputs_sha256" if phase == "stage_b" else "full_plan_inputs_sha256"], "current benchmark plan inputs differ from reviewed policy")
    results = []
    if phase in {"stage_b", "full"}:
        require(stage_a is not None, "real passed Stage A evidence is required")
        results.append(validate_evidence(policy, *stage_a))
        require(results[-1]["stage"] == "stage_a", "wrong evidence supplied for Stage A")
    if phase == "full":
        require(stage_b is not None, "real passed Stage B evidence is required")
        results.append(validate_evidence(policy, *stage_b))
        require(results[-1]["stage"] == "stage_b", "wrong evidence supplied for Stage B")
    return {"schema_version": "benchrunner.smoke_promotion_result/v1", "phase": phase,
            "status": "ready_for_stage_a" if phase == "stage_a" else "passed",
            "policy_sha256": policy["policy_sha256"], "evidence": results, "provider_calls": 0}
