"""Secondary, citation-support LLM-as-judge evaluation for V2 reports.

The deterministic benchmark evaluator remains authoritative.  This module reads
completed report artifacts, binds them to frozen executable gold and a frozen
question bank, and writes a separate, explicitly uncalibrated judgment bundle.
It never edits a run record or its primary score.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib import request
from urllib.parse import urlsplit, urlunsplit

from benchmarks.benchrunner.artifacts import atomic_write_json, atomic_write_text
from benchmarks.benchrunner.work import WorkGraph, WorkGraphError

from ..util import sha256_json, sha256_text
from .contract_registry import DEFAULT_CONTRACT_REGISTRY, normalize_project_id
from .oracle import validate_executable_gold


V2_ROOT = Path(__file__).resolve().parent
PACKAGE_ROOT = V2_ROOT.parent
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
DEFAULT_QUESTION_BANK_PATH = (
    V2_ROOT / "data" / "judge" / "full_report_questions.qwen3-8b.v1.json"
)
DEFAULT_PROMPT_PATH = PACKAGE_ROOT / "prompts" / "v2_citation_judge.md"
GOLD_PROJECT_ROOT = V2_ROOT / "data" / "gold" / "projects"

PLAN_SCHEMA_VERSION = "climinvest.v2_citation_judge_plan/v1"
MANIFEST_SCHEMA_VERSION = "climinvest.v2_citation_judge_manifest/v1"
JOB_RESULT_SCHEMA_VERSION = "climinvest.v2_citation_judge_job/v1"
RECORDS_SCHEMA_VERSION = "climinvest.v2_citation_judgments/v1"
SUMMARY_SCHEMA_VERSION = "climinvest.v2_citation_judge_summary/v1"
QUESTION_BANK_SCHEMA_VERSION = "climinvest.v2_citation_question_bank/v1"
CALIBRATION_STATUS = "uncalibrated_secondary"

QUESTION_VALUES = ("F", "P", "N", "X", "U")
CITATION_VALUES = ("S", "P", "N", "M", "U")
ANSWER_SCORES = {"F": 1.0, "P": 0.5, "N": 0.0, "X": 0.0, "U": 0.0}
CITATION_SCORES = {"S": 1.0, "P": 0.5, "N": 0.0, "M": 0.0, "U": 0.0}
EXPECTED_CONTEXTS = {
    (family, task)
    for family in ("asset_delivery", "financing_facility", "land_use_nature")
    for task in ("missingness", "update")
}

LINK_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\n]+)\)")
BARE_CITATION_RE = re.compile(
    r"\[((?:missing\.)?(?:dt|calc|req|reference)\.[A-Za-z0-9_.-]+)\]"
)
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

JudgeTransport = Callable[[str, dict[str, Any], float, str | None], dict[str, Any]]


class CitationJudgeError(ValueError):
    """Raised before judge use when immutable inputs do not bind."""


@dataclass(frozen=True, slots=True)
class CitationJudgeConfig:
    run_dir: Path
    output_dir: Path
    endpoint: str
    judge_model: str
    judge_model_revision: str | None = None
    question_bank_path: Path = DEFAULT_QUESTION_BANK_PATH
    prompt_path: Path = DEFAULT_PROMPT_PATH
    candidate_model_aliases: tuple[str, ...] = ()
    concurrency: int = 8
    components_per_job: int = 8
    seed: int = 7
    max_attempts: int = 3
    timeout_seconds: float = 900.0
    api_key_env: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_dir", Path(self.run_dir).resolve())
        object.__setattr__(self, "output_dir", Path(self.output_dir).resolve())
        object.__setattr__(
            self, "question_bank_path", Path(self.question_bank_path).resolve()
        )
        object.__setattr__(self, "prompt_path", Path(self.prompt_path).resolve())
        object.__setattr__(
            self,
            "candidate_model_aliases",
            tuple(dict.fromkeys(str(item).strip() for item in self.candidate_model_aliases)),
        )
        if not str(self.judge_model).strip():
            raise CitationJudgeError("judge_model must be non-empty")
        if self.judge_model_revision is not None and not str(
            self.judge_model_revision
        ).strip():
            raise CitationJudgeError("judge_model_revision must be non-empty when set")
        if self.concurrency < 1:
            raise CitationJudgeError("concurrency must be at least one")
        if not 1 <= self.components_per_job <= 15:
            raise CitationJudgeError("components_per_job must be between 1 and 15")
        if self.max_attempts < 1:
            raise CitationJudgeError("max_attempts must be at least one")
        if self.timeout_seconds <= 0:
            raise CitationJudgeError("timeout_seconds must be positive")
        if any(not item for item in self.candidate_model_aliases):
            raise CitationJudgeError("candidate model aliases must be non-empty")
        if self.api_key_env and not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", self.api_key_env
        ):
            raise CitationJudgeError("api_key_env is not a valid environment name")
        _chat_completions_endpoint(self.endpoint)
        if (
            self.output_dir == self.run_dir
            or self.run_dir in self.output_dir.parents
            or self.output_dir in self.run_dir.parents
        ):
            raise CitationJudgeError(
                "judge output_dir and run_dir must be separate, non-overlapping trees"
            )


@dataclass(slots=True)
class PreparedCitationJudge:
    config: CitationJudgeConfig
    identity: dict[str, Any]
    judge_id: str
    plan: dict[str, Any]
    records: list[dict[str, Any]]
    jobs: list[dict[str, Any]]
    system_prompt: str


def plan_citation_judge(config: CitationJudgeConfig) -> dict[str, Any]:
    """Validate and expand a judge run without performing or caching any call."""

    return prepare_citation_judge(config).plan


def prepare_citation_judge(config: CitationJudgeConfig) -> PreparedCitationJudge:
    run, planned_records = _load_run_binding(config.run_dir)
    bank = load_question_bank(config.question_bank_path)
    system_prompt = config.prompt_path.read_text(encoding="utf-8").strip()
    if not system_prompt:
        raise CitationJudgeError(f"judge prompt is empty: {config.prompt_path}")
    prompt_sha256 = sha256_text(system_prompt)
    prototypes = {
        (str(item["family"]), str(item["task"])): item
        for item in bank["contexts"]
    }

    records, skipped, source_identities = _build_records(
        config,
        prototypes=prototypes,
        planned_records=planned_records,
    )
    jobs = _build_jobs(
        records,
        components_per_job=config.components_per_job,
        prompt_sha256=prompt_sha256,
    )
    if not jobs:
        raise CitationJudgeError("no judge calls are required by the selected records")

    endpoint = _chat_completions_endpoint(config.endpoint)
    identity = {
        "schema_version": "climinvest.v2_citation_judge_identity/v1",
        "calibration_status": CALIBRATION_STATUS,
        "score_effect": "secondary_only",
        "run": run,
        "candidate_records": source_identities,
        "question_bank": {
            "path": _display_path(config.question_bank_path),
            "bank_sha256": bank["bank_sha256"],
            "schema_version": bank["schema_version"],
        },
        "prompt": {
            "path": _display_path(config.prompt_path),
            "sha256": prompt_sha256,
        },
        "judge": {
            "endpoint": endpoint,
            "model": config.judge_model,
            "model_revision": config.judge_model_revision,
            "seed": config.seed,
            "max_attempts": config.max_attempts,
            "timeout_seconds": config.timeout_seconds,
            "components_per_job": config.components_per_job,
            "api_key_env": config.api_key_env,
            "structured_output": "fixed_cardinality_json_schema",
        },
    }
    judge_id = f"judge-{sha256_json(identity)}"
    for job in jobs:
        job["judge_id"] = judge_id

    question_count = sum(job["question_count"] for job in jobs)
    citation_count = sum(job["citation_count"] for job in jobs)
    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "status": "planned",
        "provider_calls": 0,
        "calibration_status": CALIBRATION_STATUS,
        "score_effect": "secondary_only",
        "judge_id": judge_id,
        "run_dir": str(config.run_dir),
        "output_dir": str(config.output_dir),
        "record_count": len(records),
        "skipped_record_count": skipped,
        "job_count": len(jobs),
        "question_count": question_count,
        "citation_count": citation_count,
        "coverage_gap_component_count": sum(
            bool(component["coverage_gap"])
            for record in records
            for component in record["components"]
        ),
        "candidate_model_aliases": sorted(
            {str(record["model_alias"]) for record in records}
        ),
        "question_bank_sha256": bank["bank_sha256"],
        "prompt_sha256": prompt_sha256,
        "jobs": [
            {
                "job_id": job["job_id"],
                "record_key": job["record_key"],
                "question_count": job["question_count"],
                "citation_count": job["citation_count"],
                "job_input_sha256": job["job_input_sha256"],
                "response_schema_sha256": job["response_schema_sha256"],
            }
            for job in jobs
        ],
    }
    return PreparedCitationJudge(
        config=config,
        identity=identity,
        judge_id=judge_id,
        plan=plan,
        records=records,
        jobs=jobs,
        system_prompt=system_prompt,
    )


def execute_citation_judge(
    config: CitationJudgeConfig,
    *,
    transport: JudgeTransport | None = None,
) -> dict[str, Any]:
    """Execute or resume a secondary judge run in its own output directory."""

    prepared = prepare_citation_judge(config)
    output_root = config.output_dir
    _initialize_output(prepared)

    api_key: str | None = None
    if config.api_key_env:
        api_key = os.environ.get(config.api_key_env)
        if not api_key:
            raise CitationJudgeError(
                f"{config.api_key_env} is required for judge execution"
            )
    call = transport or _post_json
    cached: dict[str, dict[str, Any]] = {}
    pending: list[dict[str, Any]] = []
    for job in prepared.jobs:
        path = output_root / "jobs" / f"{job['job_id']}.json"
        if not path.is_file():
            pending.append(job)
            continue
        prior = _read_object(path)
        _validate_cached_output(prepared, job, prior, path=path)
        if prior.get("status") == "completed":
            cached[job["job_id"]] = prior
        else:
            pending.append(job)

    fresh: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=config.concurrency
    ) as pool:
        future_to_job = {
            pool.submit(_call_job, prepared, job, call, api_key): job
            for job in pending
        }
        for future in concurrent.futures.as_completed(future_to_job):
            job = future_to_job[future]
            result = future.result()
            fresh[job["job_id"]] = result
            atomic_write_json(
                output_root / "jobs" / f"{job['job_id']}.json",
                result,
            )

    outputs = [
        cached.get(job["job_id"]) or fresh[job["job_id"]]
        for job in prepared.jobs
    ]
    attach_results(prepared.records, prepared.jobs, outputs)
    summary = _summary(prepared, outputs, cached_count=len(cached))
    records_payload = {
        "schema_version": RECORDS_SCHEMA_VERSION,
        "judge_id": prepared.judge_id,
        "calibration_status": CALIBRATION_STATUS,
        "score_effect": "secondary_only",
        "records": prepared.records,
    }
    atomic_write_json(output_root / "records.json", records_payload)
    atomic_write_json(output_root / "summary.json", summary)
    atomic_write_text(
        output_root / "review.md",
        render_review(prepared, summary, outputs) + "\n",
    )
    _finish_manifest(prepared, summary)
    return summary


def load_question_bank(path: Path = DEFAULT_QUESTION_BANK_PATH) -> dict[str, Any]:
    source_path = Path(path).resolve()
    payload = _read_object(source_path)
    if payload.get("schema_version") != QUESTION_BANK_SCHEMA_VERSION:
        raise CitationJudgeError("unexpected citation question-bank schema")
    claimed_hash = payload.get("bank_sha256")
    unhashed = {key: value for key, value in payload.items() if key != "bank_sha256"}
    if claimed_hash != sha256_json(unhashed):
        raise CitationJudgeError("citation question-bank hash differs")
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        raise CitationJudgeError("citation question bank lacks source provenance")
    source_document = provenance.get("source_document")
    source_sha256 = provenance.get("source_document_sha256")
    if not isinstance(source_document, str) or not isinstance(source_sha256, str):
        raise CitationJudgeError("citation question-bank provenance is incomplete")
    review_path = _safe_relative_path(source_path.parent, source_document)
    if not review_path.is_file():
        raise CitationJudgeError(f"question-bank source document is missing: {review_path}")
    if _sha256_file(review_path) != source_sha256:
        raise CitationJudgeError("question-bank source document hash differs")

    contexts = payload.get("contexts")
    if not isinstance(contexts, list):
        raise CitationJudgeError("citation question-bank contexts must be a list")
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for context in contexts:
        if not isinstance(context, dict):
            raise CitationJudgeError("citation question-bank context must be an object")
        key = (str(context.get("family") or ""), str(context.get("task") or ""))
        if key in by_key:
            raise CitationJudgeError(f"duplicate citation question-bank context: {key}")
        by_key[key] = context
        components = context.get("components")
        if not isinstance(components, list) or len(components) != 15:
            raise CitationJudgeError(f"{key}: expected exactly 15 components")
        component_ids: set[str] = set()
        for component in components:
            component_id = str(component.get("component_id") or "")
            if not component_id or component_id in component_ids:
                raise CitationJudgeError(f"{key}: invalid or duplicate component id")
            component_ids.add(component_id)
            questions = component.get("questions")
            if not isinstance(questions, list):
                raise CitationJudgeError(f"{key}:{component_id}: questions must be a list")
            for question in questions:
                slots = question.get("answer_slots")
                if (
                    question.get("aggregator") != "AND"
                    or not isinstance(question.get("question"), str)
                    or not isinstance(slots, list)
                    or not slots
                    or any(not isinstance(slot, str) or not slot for slot in slots)
                ):
                    raise CitationJudgeError(
                        f"{key}:{component_id}: invalid fixed question"
                    )
    if set(by_key) != EXPECTED_CONTEXTS:
        raise CitationJudgeError(
            f"citation question-bank contexts differ: {set(by_key) ^ EXPECTED_CONTEXTS}"
        )
    return payload


def response_schema(job: dict[str, Any]) -> dict[str, Any]:
    """Return the strict, fixed-cardinality schema for one immutable job."""

    q_count = int(job["question_count"])
    c_count = int(job["citation_count"])
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["question_verdicts", "citation_verdicts"],
        "properties": {
            "question_verdicts": {
                "type": "array",
                "minItems": q_count,
                "maxItems": q_count,
                "items": {"type": "string", "enum": list(QUESTION_VALUES)},
            },
            "citation_verdicts": {
                "type": "array",
                "minItems": c_count,
                "maxItems": c_count,
                "items": {"type": "string", "enum": list(CITATION_VALUES)},
            },
        },
    }


def attach_results(
    records: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
) -> None:
    """Attach judge verdicts, with missing/unresolved decisions kept deterministic."""

    output_index = {str(output["job_id"]): output for output in outputs}
    for job in jobs:
        output = output_index[job["job_id"]]
        question_verdicts = iter(output["question_verdicts"])
        citation_verdicts = iter(output["citation_verdicts"])
        for question in ordered_questions(job):
            verdict = next(question_verdicts)
            if any(
                evidence["reference_status"] == "unresolved"
                for evidence in question["answer_evidence"]
            ):
                verdict = "U"
            question["answer_verdict"] = verdict
            for evidence in question["answer_evidence"]:
                raw_citation_verdict = next(citation_verdicts)
                if evidence["reference_status"] == "unresolved":
                    citation_verdict = "U"
                elif not evidence["claim_excerpts"]:
                    citation_verdict = "M"
                else:
                    citation_verdict = raw_citation_verdict
                evidence["citation_verdict"] = citation_verdict
        if output.get("status") != "completed":
            for component in job["components"]:
                component["judge_error"] = output.get("error") or "judge call failed"
    for record in records:
        record["secondary_metrics"] = calculate_metrics(record)


def calculate_metrics(record: dict[str, Any]) -> dict[str, Any]:
    questions = [
        question
        for component in record["components"]
        for question in component["questions"]
    ]
    citations = [
        evidence for question in questions for evidence in question["answer_evidence"]
    ]
    assessable_questions = [q for q in questions if q["answer_verdict"] != "U"]
    assessable_citations = [c for c in citations if c["citation_verdict"] != "U"]
    answer = _weighted_value(assessable_questions, "answer_verdict", ANSWER_SCORES)
    citation_support = _weighted_value(
        assessable_citations, "citation_verdict", CITATION_SCORES
    )
    presence = (
        sum(bool(citation["claim_excerpts"]) for citation in citations) / len(citations)
        if citations
        else 0.0
    )
    harmonic = (
        2 * answer * citation_support / (answer + citation_support)
        if answer + citation_support
        else 0.0
    )
    return {
        "calibration_status": CALIBRATION_STATUS,
        "score_effect": "secondary_only",
        "questions": len(questions),
        "assessable_questions": len(assessable_questions),
        "citation_slots": len(citations),
        "assessable_citation_slots": len(assessable_citations),
        "coverage_gap_components": sum(
            bool(component.get("coverage_gap")) for component in record["components"]
        ),
        "answer_coverage": answer,
        "citation_presence": presence,
        "citation_support_coverage": citation_support,
        "harmonic_f1": harmonic,
        "answer_verdicts": dict(sorted(Counter(q["answer_verdict"] for q in questions).items())),
        "citation_verdicts": dict(
            sorted(Counter(c["citation_verdict"] for c in citations).items())
        ),
    }


def ordered_questions(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        question
        for component in job["components"]
        for question in component["questions"]
    ]


def ordered_citations(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        evidence
        for question in ordered_questions(job)
        for evidence in question["answer_evidence"]
    ]


def render_review(
    prepared: PreparedCitationJudge,
    summary: dict[str, Any],
    outputs: list[dict[str, Any]],
) -> str:
    overall = summary["secondary_metrics"]
    lines = [
        "# V2 citation-support LLM judgment",
        "",
        "> **Status:** Uncalibrated secondary analysis. These values do not alter "
        "the deterministic primary benchmark score and must not be used as a "
        "leaderboard score without human calibration and judge-sensitivity checks.",
        "",
        "## Scope",
        "",
        f"- Judge ID: `{prepared.judge_id}`",
        f"- Judge model: `{prepared.config.judge_model}`",
        f"- Candidate reports: {summary['record_count']}",
        f"- Judge calls: {summary['job_count']}",
        f"- Failed calls: {summary['failed_job_count']}",
        f"- Reused calls: {summary['reused_job_count']}",
        f"- Questions: {overall['questions']}",
        f"- Citation slots: {overall['citation_slots']}",
        f"- Question-bank coverage-gap components: {overall['coverage_gap_components']}",
        "",
        "## Overall secondary metrics",
        "",
        "| Answer coverage | Citation presence | Citation support | Harmonic F1 |",
        "|---:|---:|---:|---:|",
        (
            f"| {_pct(overall['answer_coverage'])} | "
            f"{_pct(overall['citation_presence'])} | "
            f"{_pct(overall['citation_support_coverage'])} | "
            f"{_pct(overall['harmonic_f1'])} |"
        ),
        "",
        "## Candidate model × family × task",
        "",
        (
            "| Candidate | Family | Task | Reports | Questions | Citation slots | "
            "Answer | Presence | Support | F1 |"
        ),
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in prepared.records:
        groups[(record["model_alias"], record["family"], record["task"])].append(record)
    for (model, family, task), records in sorted(groups.items()):
        metrics = weighted_summary(records)
        lines.append(
            f"| `{model}` | `{family}` | `{task}` | {metrics['records']} | "
            f"{metrics['questions']} | {metrics['citation_slots']} | "
            f"{_pct(metrics['answer_coverage'])} | "
            f"{_pct(metrics['citation_presence'])} | "
            f"{_pct(metrics['citation_support_coverage'])} | "
            f"{_pct(metrics['harmonic_f1'])} |"
        )
    lines.extend(
        [
            "",
            "## Record results",
            "",
            "| Candidate | Project | Task | Condition | Answer | Presence | Support | F1 |",
            "|---|---|---|---|---:|---:|---:|---:|",
        ]
    )
    for record in sorted(
        prepared.records,
        key=lambda item: (
            item["model_alias"],
            item["project_id"],
            item["task"],
            str(item["condition_id"]),
            item["record_key"],
        ),
    ):
        metrics = record["secondary_metrics"]
        lines.append(
            f"| `{record['model_alias']}` | `{record['project_id']}` | "
            f"`{record['task']}` | `{record['condition_id'] or 'complete'}` | "
            f"{_pct(metrics['answer_coverage'])} | "
            f"{_pct(metrics['citation_presence'])} | "
            f"{_pct(metrics['citation_support_coverage'])} | "
            f"{_pct(metrics['harmonic_f1'])} |"
        )
    failures = [output for output in outputs if output.get("status") != "completed"]
    if failures:
        lines.extend(["", "## Judge-call failures", ""])
        for output in failures:
            lines.append(f"- `{output['job_id']}`: {output.get('error', 'unknown error')}")
    lines.extend(
        [
            "",
            "## Calibration warning",
            "",
            "The compact judge emits no free-text rationale. Calibrate stratified "
            "samples of every answer and citation verdict, missingness cases, "
            "complete-set questions, and counterfactual citation swaps. The frozen "
            "question bank was generated by Qwen3-8B, so use another judge family "
            "for sensitivity analysis when Qwen3-8B is the judge.",
        ]
    )
    return "\n".join(lines)


def weighted_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    question_count = sum(r["secondary_metrics"]["questions"] for r in records)
    assessable_questions = sum(
        r["secondary_metrics"]["assessable_questions"] for r in records
    )
    citation_count = sum(r["secondary_metrics"]["citation_slots"] for r in records)
    assessable_citations = sum(
        r["secondary_metrics"]["assessable_citation_slots"] for r in records
    )
    coverage_gaps = sum(
        r["secondary_metrics"]["coverage_gap_components"] for r in records
    )
    answer = _weighted_metric(records, "answer_coverage", "assessable_questions")
    support = _weighted_metric(
        records, "citation_support_coverage", "assessable_citation_slots"
    )
    presence = _weighted_metric(records, "citation_presence", "citation_slots")
    return {
        "records": len(records),
        "questions": question_count,
        "assessable_questions": assessable_questions,
        "citation_slots": citation_count,
        "assessable_citation_slots": assessable_citations,
        "coverage_gap_components": coverage_gaps,
        "answer_coverage": answer,
        "citation_presence": presence,
        "citation_support_coverage": support,
        "harmonic_f1": (
            2 * answer * support / (answer + support) if answer + support else 0.0
        ),
    }


def _load_run_binding(
    run_dir: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if not run_dir.is_dir():
        raise CitationJudgeError(f"run directory does not exist: {run_dir}")
    manifest_path = run_dir / "manifest.json"
    plan_path = run_dir / "plan.json"
    manifest = _read_object(manifest_path)
    plan = _read_object(plan_path)
    if manifest.get("schema_version") != "benchrunner.run_manifest/v1":
        raise CitationJudgeError("unexpected benchmark run-manifest schema")
    if plan.get("schema_version") != "benchrunner.study_plan/v1":
        raise CitationJudgeError("unexpected benchmark study-plan schema")
    graph_payload = plan.get("graph")
    if not isinstance(graph_payload, dict):
        raise CitationJudgeError("run plan work graph must be an object")
    try:
        graph = WorkGraph.from_dict(graph_payload)
    except (TypeError, ValueError, WorkGraphError) as exc:
        raise CitationJudgeError(f"run plan contains an invalid work graph: {exc}") from exc
    if graph.graph_id != plan.get("graph_id"):
        raise CitationJudgeError("plan graph_id differs from its canonical contents")
    plan_without_graph = {key: value for key, value in plan.items() if key != "graph"}
    expected_plan_id = f"plan-{sha256_json(plan_without_graph)}"
    if manifest.get("plan_id") != expected_plan_id:
        raise CitationJudgeError("run manifest plan_id differs from plan.json")
    if manifest.get("graph_id") != plan.get("graph_id"):
        raise CitationJudgeError("run manifest graph_id differs from plan.json")
    plan_config = plan.get("config")
    if not isinstance(plan_config, dict) or plan_config.get("adapter") != "react_report_v2":
        raise CitationJudgeError("judge requires a react_report_v2 run")
    if manifest.get("study_id") != plan_config.get("study_id"):
        raise CitationJudgeError("run manifest study_id differs from plan.json")
    if manifest.get("adapter") not in (None, plan_config.get("adapter")):
        raise CitationJudgeError("run manifest adapter differs from plan.json")
    if manifest.get("study_mode") not in (None, plan_config.get("mode")):
        raise CitationJudgeError("run manifest study mode differs from plan.json")

    raw_records = plan.get("records")
    if not isinstance(raw_records, list) or any(
        not isinstance(item, dict) for item in raw_records
    ):
        raise CitationJudgeError("run plan records must be a list of objects")
    planned_records: dict[str, dict[str, Any]] = {}
    for item in raw_records:
        record_key = item.get("record_key")
        if not isinstance(record_key, str) or not record_key:
            raise CitationJudgeError("run plan contains a record without a record_key")
        if record_key in planned_records:
            raise CitationJudgeError(f"run plan contains duplicate record_key {record_key!r}")
        planned_records[record_key] = item
        work_id = item.get("work_id")
        if not isinstance(work_id, str) or not work_id:
            raise CitationJudgeError(f"planned record {record_key!r} lacks a work_id")
        try:
            work = graph.get(work_id)
        except WorkGraphError as exc:
            raise CitationJudgeError(
                f"planned record {record_key!r} points outside the work graph"
            ) from exc
        expected_identity = {
            key: value
            for key, value in item.items()
            if key not in {"work_id", "episode_work_ids"}
        }
        if work.kind != "react_record" or dict(work.identity) != expected_identity:
            raise CitationJudgeError(
                f"planned record {record_key!r} differs from its reducer work item"
            )
        episode_work_ids = item.get("episode_work_ids")
        if (
            not isinstance(episode_work_ids, list)
            or any(not isinstance(value, str) for value in episode_work_ids)
            or len(episode_work_ids) != len(set(episode_work_ids))
            or tuple(sorted(episode_work_ids)) != work.dependencies
        ):
            raise CitationJudgeError(
                f"planned record {record_key!r} dependencies differ from its work item"
            )
    episode_count = sum(item.kind == "react_episode" for item in graph)
    if plan.get("record_count") != len(planned_records):
        raise CitationJudgeError("run plan record_count differs from its records")
    if plan.get("episode_count") != episode_count:
        raise CitationJudgeError("run plan episode_count differs from its work graph")
    if manifest.get("record_count") != len(planned_records):
        raise CitationJudgeError("run manifest record_count differs from plan.json")
    if manifest.get("episode_count") != episode_count:
        raise CitationJudgeError("run manifest episode_count differs from plan.json")

    resolved_path = run_dir / "resolved-config.json"
    resolved_sha256 = None
    if resolved_path.is_file():
        resolved = _read_object(resolved_path)
        if resolved != plan_config:
            raise CitationJudgeError("resolved-config.json differs from plan.json")
        resolved_sha256 = _sha256_file(resolved_path)
    identity = {
        "study_id": manifest["study_id"],
        "plan_id": manifest["plan_id"],
        "graph_id": manifest["graph_id"],
        "manifest_sha256": _sha256_file(manifest_path),
        "plan_sha256": _sha256_file(plan_path),
        "resolved_config_sha256": resolved_sha256,
    }
    return identity, planned_records


def _build_records(
    config: CitationJudgeConfig,
    *,
    prototypes: dict[tuple[str, str], dict[str, Any]],
    planned_records: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    records_root = config.run_dir / "records"
    if not records_root.is_dir():
        raise CitationJudgeError(f"run has no records directory: {records_root}")
    selected_aliases = set(config.candidate_model_aliases)
    aliases_seen: set[str] = set()
    skipped = 0
    results: list[dict[str, Any]] = []
    identities: list[dict[str, Any]] = []
    for record_path in sorted(records_root.glob("*.json")):
        source = _read_object(record_path)
        record_key = source.get("record_key")
        if not isinstance(record_key, str) or record_key not in planned_records:
            raise CitationJudgeError(
                f"{record_path.name}: record is absent from the immutable study plan"
            )
        planned = planned_records[record_key]
        for key, expected in planned.items():
            if key == "work_id":
                continue
            if key not in source or source[key] != expected:
                raise CitationJudgeError(
                    f"{record_path.name}: record field {key!r} differs from the study plan"
                )
        planned_work_id = planned.get("work_id")
        if isinstance(planned_work_id, str) and planned_work_id:
            expected_record = f"records/{planned_work_id}.json"
            expected_candidate = f"candidates/{planned_work_id}.md"
            if record_path.name != f"{planned_work_id}.json":
                raise CitationJudgeError(
                    f"{record_path.name}: record filename differs from the study plan"
                )
            if source.get("record_artifact") != expected_record:
                raise CitationJudgeError(
                    f"{record_path.name}: record artifact path differs from the study plan"
                )
            if source.get("candidate_artifact") not in (None, expected_candidate):
                raise CitationJudgeError(
                    f"{record_path.name}: candidate artifact path differs from the study plan"
                )
        model_alias = str(source.get("model_alias") or "")
        if model_alias:
            aliases_seen.add(model_alias)
        if selected_aliases and model_alias not in selected_aliases:
            skipped += 1
            continue
        if source.get("scope") != "report" or source.get("status") != "completed":
            skipped += 1
            continue
        target, identity = _build_record(config.run_dir, record_path, source, prototypes)
        results.append(target)
        identities.append(identity)
    missing_aliases = sorted(selected_aliases - aliases_seen)
    if missing_aliases:
        raise CitationJudgeError(
            f"candidate model aliases are absent from the run: {missing_aliases}"
        )
    if not results:
        raise CitationJudgeError("no completed V2 report records matched the selection")
    record_keys = [str(item["record_key"]) for item in results]
    if len(record_keys) != len(set(record_keys)):
        raise CitationJudgeError("completed report selection contains duplicate record keys")
    results.sort(key=lambda item: item["record_key"])
    identities.sort(key=lambda item: item["record_key"])
    return results, skipped, identities


def _build_record(
    run_dir: Path,
    record_path: Path,
    source: dict[str, Any],
    prototypes: dict[tuple[str, str], dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    required = ("record_key", "project_id", "template_id", "task", "candidate_artifact")
    missing = [key for key in required if source.get(key) in (None, "")]
    if missing:
        raise CitationJudgeError(f"{record_path.name}: missing fields {missing}")
    project_id = normalize_project_id(str(source["project_id"]))
    if not SAFE_IDENTIFIER_RE.fullmatch(project_id):
        raise CitationJudgeError(f"unsafe project id: {project_id!r}")
    family = str(source["template_id"])
    task = str(source["task"])
    if task not in {"complete", "missingness", "update"}:
        raise CitationJudgeError(f"{source['record_key']}: unsupported V2 task {task!r}")
    if task == "complete" and source.get("condition_id") is not None:
        raise CitationJudgeError(
            f"{source['record_key']}: complete task unexpectedly has a condition"
        )
    if task != "complete" and source.get("condition_id") is None:
        raise CitationJudgeError(
            f"{source['record_key']}: conditioned task lacks a condition"
        )
    prototype_task = "missingness" if task == "missingness" else "update"
    try:
        prototype = prototypes[(family, prototype_task)]
    except KeyError as exc:
        raise CitationJudgeError(
            f"no frozen question context for {(family, prototype_task)}"
        ) from exc

    candidate_path = _safe_relative_path(run_dir, str(source["candidate_artifact"]))
    if not candidate_path.is_file():
        raise CitationJudgeError(f"candidate artifact is missing: {candidate_path}")
    markdown = candidate_path.read_text(encoding="utf-8")
    candidate_sha256 = sha256_text(markdown)
    declared_candidate_hash = source.get("candidate_markdown_sha256")
    if declared_candidate_hash and declared_candidate_hash != candidate_sha256:
        raise CitationJudgeError(
            f"{source['record_key']}: candidate markdown hash differs"
        )

    gold_path = _gold_path(project_id, source.get("condition_id"))
    gold = _read_object(gold_path)
    gold_errors = validate_executable_gold(gold)
    if gold_errors:
        raise CitationJudgeError(
            f"{source['record_key']}: invalid executable gold: {'; '.join(gold_errors)}"
        )
    if gold.get("project_id") != project_id:
        raise CitationJudgeError(f"{source['record_key']}: executable-gold project differs")
    if gold.get("condition_id") != source.get("condition_id"):
        raise CitationJudgeError(f"{source['record_key']}: executable-gold condition differs")
    if gold.get("template_id") != family:
        raise CitationJudgeError(f"{source['record_key']}: executable-gold family differs")
    gold_sha256 = str(gold["gold_sha256"])
    for label, declared in (
        ("record expected gold", source.get("expected_gold_sha256")),
        ("primary score gold", (source.get("score") or {}).get("gold_sha256")),
    ):
        if declared and declared != gold_sha256:
            raise CitationJudgeError(f"{source['record_key']}: {label} hash differs")

    binding = DEFAULT_CONTRACT_REGISTRY.resolve(
        project_id=project_id,
        contract_id=family,
    )
    contract = binding.load()
    contract_sha256 = sha256_json(contract)
    if gold.get("contract_sha256") != contract_sha256:
        raise CitationJudgeError(f"{source['record_key']}: gold contract hash differs")
    if source.get("contract_sha256") and source["contract_sha256"] != contract_sha256:
        raise CitationJudgeError(f"{source['record_key']}: record contract hash differs")

    states = _state_index(gold)
    title_state = states.get("dt.project.title") or {}
    project_title = str(title_state.get("value") or project_id)
    target: dict[str, Any] = {
        "record_key": str(source["record_key"]),
        "record_file": record_path.name,
        "record_sha256": _sha256_file(record_path),
        "model_alias": str(source.get("model_alias") or "unknown"),
        "model_id": str(source.get("model_id") or "unknown"),
        "provider_profile": str(source.get("provider_profile") or "unknown"),
        "project_id": project_id,
        "project_title": project_title,
        "condition_id": source.get("condition_id"),
        "task": task,
        "family": family,
        "candidate_artifact": str(source["candidate_artifact"]),
        "candidate_markdown_sha256": candidate_sha256,
        "gold_path": _display_path(gold_path),
        "gold_sha256": gold_sha256,
        "contract_sha256": contract_sha256,
        "primary_score_sha256": (
            sha256_json(source["score"])
            if isinstance(source.get("score"), dict)
            else None
        ),
        "components": [],
    }
    prototype_components = {
        str(item["component_id"]): item for item in prototype["components"]
    }
    titles = _subsection_titles(gold)
    for ordinal, gold_component in enumerate(gold["llm_obligations"], start=1):
        component_id = str(gold_component["component_id"])
        try:
            question_plan = prototype_components[component_id]
        except KeyError as exc:
            raise CitationJudgeError(
                f"{source['record_key']}: question bank lacks {component_id}"
            ) from exc
        expected_slots = Counter(map(str, gold_component.get("context_ids") or []))
        planned_slots = Counter(
            str(slot)
            for question in question_plan["questions"]
            for slot in question["answer_slots"]
        )
        if expected_slots != planned_slots:
            raise CitationJudgeError(
                f"{source['record_key']}:{component_id}: question slots differ from gold"
            )
        subsection_id = str(gold_component["subsection_id"])
        try:
            component_text = _extract_subsection(markdown, titles[subsection_id])
        except KeyError as exc:
            raise CitationJudgeError(
                f"{source['record_key']}: gold lacks subsection {subsection_id}"
            ) from exc
        component_out: dict[str, Any] = {
            "ordinal": ordinal,
            "component_id": component_id,
            "section_id": str(gold_component["section_id"]),
            "title": str(question_plan["title"]),
            "text": component_text,
            "coverage_gap": bool(question_plan.get("coverage_gap")),
            "question_source": {
                "family": family,
                "prototype_task": prototype_task,
                "prototype_project_id": prototype["prototype_project_id"],
                "fallback": bool(question_plan.get("fallback")),
            },
            "questions": [],
        }
        for question_number, planned_question in enumerate(
            question_plan["questions"], start=1
        ):
            answer_evidence = []
            for citation_id in planned_question["answer_slots"]:
                answer = _expected_answer(str(citation_id), gold_component, states)
                answer_evidence.append(
                    {
                        "citation_id": str(citation_id),
                        "reference_status": answer["status"],
                        "authoritative_answer": answer["answer"],
                        "claim_excerpts": _citation_excerpts(
                            component_text, str(citation_id)
                        ),
                    }
                )
            component_out["questions"].append(
                {
                    "question_id": (
                        f"{record_path.stem}:{component_id}:q{question_number}"
                    ),
                    "question": _personalize_question(
                        str(planned_question["question"]),
                        prototype=prototype,
                        project_id=project_id,
                        project_title=project_title,
                    ),
                    "aggregator": "AND",
                    "answer_evidence": answer_evidence,
                }
            )
        target["components"].append(component_out)
    if len(target["components"]) != 15:
        raise CitationJudgeError(f"{source['record_key']}: expected 15 LLM components")
    if set(prototype_components) != {
        component["component_id"] for component in target["components"]
    }:
        raise CitationJudgeError(
            f"{source['record_key']}: gold and question-bank components differ"
        )
    identity = {
        key: target[key]
        for key in (
            "record_key",
            "record_file",
            "record_sha256",
            "model_alias",
            "model_id",
            "provider_profile",
            "project_id",
            "condition_id",
            "task",
            "family",
            "candidate_artifact",
            "candidate_markdown_sha256",
            "gold_sha256",
            "contract_sha256",
            "primary_score_sha256",
        )
    }
    return target, identity


def _build_jobs(
    records: list[dict[str, Any]],
    *,
    components_per_job: int,
    prompt_sha256: str,
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for record in records:
        for start in range(0, len(record["components"]), components_per_job):
            components = record["components"][start : start + components_per_job]
            questions = [q for component in components for q in component["questions"]]
            if not questions:
                continue
            chunk_number = start // components_per_job + 1
            job_id = (
                f"{Path(record['record_file']).stem}-chunk-{chunk_number:02d}"
            )
            if not SAFE_IDENTIFIER_RE.fullmatch(job_id):
                raise CitationJudgeError(f"unsafe generated job id: {job_id}")
            job: dict[str, Any] = {
                "job_id": job_id,
                "record_key": record["record_key"],
                "record_file": record["record_file"],
                "components": components,
            }
            job["question_count"] = len(ordered_questions(job))
            job["citation_count"] = len(ordered_citations(job))
            schema = response_schema(job)
            job["response_schema_sha256"] = sha256_json(schema)
            job["job_input_sha256"] = sha256_json(
                {
                    "prompt_sha256": prompt_sha256,
                    "input": _judge_input(job),
                    "response_schema": schema,
                }
            )
            jobs.append(job)
    return jobs


def _judge_input(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "alignment": {
            "question_count": len(ordered_questions(job)),
            "citation_count": len(ordered_citations(job)),
            "instruction": (
                "Flatten components/questions in order for question_verdicts; then "
                "flatten each question's answer_evidence in order for citation_verdicts."
            ),
        },
        "components": [
            {
                "component_id": component["component_id"],
                "report_text": _compact(component["text"], 7000),
                "questions": [
                    {
                        "question": question["question"],
                        "aggregator": "AND",
                        "answer_evidence": [
                            {
                                "citation_id": evidence["citation_id"],
                                "reference_status": evidence["reference_status"],
                                "authoritative_answer": _compact(
                                    evidence["authoritative_answer"], 900
                                ),
                                "cited_claim_excerpts": [
                                    _compact(excerpt, 450)
                                    for excerpt in evidence["claim_excerpts"][:2]
                                ],
                            }
                            for evidence in question["answer_evidence"]
                        ],
                    }
                    for question in component["questions"]
                ],
            }
            for component in job["components"]
            if component["questions"]
        ],
    }


def _call_job(
    prepared: PreparedCitationJudge,
    job: dict[str, Any],
    transport: JudgeTransport,
    api_key: str | None,
) -> dict[str, Any]:
    config = prepared.config
    schema = response_schema(job)
    payload_base = {
        "model": config.judge_model,
        "temperature": 0,
        "max_tokens": max(
            192,
            min(1000, 64 + 12 * (job["question_count"] + job["citation_count"])),
        ),
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {"role": "system", "content": prepared.system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    _judge_input(job),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "judge_" + hashlib.sha256(job["job_id"].encode()).hexdigest()[:16],
                "strict": True,
                "schema": schema,
            },
        },
    }
    seeds_tried: list[int] = []
    last_error: Exception | None = None
    for attempt in range(config.max_attempts):
        seed = config.seed + attempt
        seeds_tried.append(seed)
        try:
            body = transport(
                _chat_completions_endpoint(config.endpoint),
                {**payload_base, "seed": seed},
                config.timeout_seconds,
                api_key,
            )
            message = body["choices"][0]["message"]["content"]
            if not isinstance(message, str):
                raise ValueError("judge message content must be a JSON string")
            parsed = json.loads(message)
            question_verdicts, citation_verdicts = _validate_verdicts(job, parsed)
            return {
                "schema_version": JOB_RESULT_SCHEMA_VERSION,
                "status": "completed",
                "judge_id": prepared.judge_id,
                "job_id": job["job_id"],
                "job_input_sha256": job["job_input_sha256"],
                "response_schema_sha256": job["response_schema_sha256"],
                "judge_model": config.judge_model,
                "judge_model_revision": config.judge_model_revision,
                "question_verdicts": question_verdicts,
                "citation_verdicts": citation_verdicts,
                "usage": body.get("usage") or {},
                "provider_request_id": body.get("id"),
                "attempts": attempt + 1,
                "seeds_tried": seeds_tried,
            }
        except Exception as exc:  # transport and malformed-output failures are retryable
            last_error = exc
    return {
        "schema_version": JOB_RESULT_SCHEMA_VERSION,
        "status": "failed",
        "judge_id": prepared.judge_id,
        "job_id": job["job_id"],
        "job_input_sha256": job["job_input_sha256"],
        "response_schema_sha256": job["response_schema_sha256"],
        "judge_model": config.judge_model,
        "judge_model_revision": config.judge_model_revision,
        "question_verdicts": ["U"] * job["question_count"],
        "citation_verdicts": ["U"] * job["citation_count"],
        "usage": {},
        "error": f"{type(last_error).__name__}: {last_error}",
        "attempts": config.max_attempts,
        "seeds_tried": seeds_tried,
    }


def _validate_verdicts(
    job: dict[str, Any], parsed: Any
) -> tuple[list[str], list[str]]:
    if not isinstance(parsed, dict) or set(parsed) != {
        "question_verdicts",
        "citation_verdicts",
    }:
        raise ValueError("judge output must contain exactly the two verdict arrays")
    questions = parsed["question_verdicts"]
    citations = parsed["citation_verdicts"]
    if (
        not isinstance(questions, list)
        or len(questions) != job["question_count"]
        or any(item not in QUESTION_VALUES for item in questions)
    ):
        raise ValueError("question verdicts violate fixed cardinality or enum")
    if (
        not isinstance(citations, list)
        or len(citations) != job["citation_count"]
        or any(item not in CITATION_VALUES for item in citations)
    ):
        raise ValueError("citation verdicts violate fixed cardinality or enum")
    return list(questions), list(citations)


def _post_json(
    endpoint: str,
    payload: dict[str, Any],
    timeout_seconds: float,
    api_key: str | None,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    http_request = request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with request.urlopen(http_request, timeout=timeout_seconds) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict):
        raise ValueError("judge response must be a JSON object")
    return body


def _initialize_output(prepared: PreparedCitationJudge) -> None:
    root = prepared.config.output_dir
    if root.exists() and not root.is_dir():
        raise CitationJudgeError(f"judge output path is not a directory: {root}")
    manifest_path = root / "manifest.json"
    if root.is_dir() and any(root.iterdir()) and not manifest_path.is_file():
        raise CitationJudgeError(
            "non-empty judge output directory lacks an identity manifest"
        )
    root.mkdir(parents=True, exist_ok=True)
    (root / "jobs").mkdir(exist_ok=True)
    now = _utc_now()
    if manifest_path.is_file():
        existing = _read_object(manifest_path)
        if (
            existing.get("schema_version") != MANIFEST_SCHEMA_VERSION
            or existing.get("judge_id") != prepared.judge_id
            or existing.get("identity") != prepared.identity
        ):
            raise CitationJudgeError(
                "judge output directory belongs to a different immutable identity"
            )
    else:
        atomic_write_json(
            manifest_path,
            {
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "status": "in_progress",
                "created_at": now,
                "updated_at": now,
                "judge_id": prepared.judge_id,
                "calibration_status": CALIBRATION_STATUS,
                "score_effect": "secondary_only",
                "identity": prepared.identity,
            },
        )
    _write_or_verify_json(root / "plan.json", prepared.plan)


def _finish_manifest(
    prepared: PreparedCitationJudge, summary: dict[str, Any]
) -> None:
    path = prepared.config.output_dir / "manifest.json"
    manifest = _read_object(path)
    manifest.update(
        status=summary["status"],
        updated_at=_utc_now(),
        record_count=summary["record_count"],
        job_count=summary["job_count"],
        failed_job_count=summary["failed_job_count"],
        reused_job_count=summary["reused_job_count"],
        fresh_job_count=summary["fresh_job_count"],
    )
    atomic_write_json(path, manifest)


def _validate_cached_output(
    prepared: PreparedCitationJudge,
    job: dict[str, Any],
    value: dict[str, Any],
    *,
    path: Path,
) -> None:
    expected = {
        "schema_version": JOB_RESULT_SCHEMA_VERSION,
        "judge_id": prepared.judge_id,
        "job_id": job["job_id"],
        "job_input_sha256": job["job_input_sha256"],
        "response_schema_sha256": job["response_schema_sha256"],
        "judge_model": prepared.config.judge_model,
        "judge_model_revision": prepared.config.judge_model_revision,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise CitationJudgeError(f"cached judge output identity differs: {path}")
    if value.get("status") not in {"completed", "failed"}:
        raise CitationJudgeError(f"cached judge output has invalid status: {path}")
    _validate_verdicts(
        job,
        {
            "question_verdicts": value.get("question_verdicts"),
            "citation_verdicts": value.get("citation_verdicts"),
        },
    )


def _summary(
    prepared: PreparedCitationJudge,
    outputs: list[dict[str, Any]],
    *,
    cached_count: int,
) -> dict[str, Any]:
    failures = [output for output in outputs if output.get("status") != "completed"]
    usage: Counter[str] = Counter()
    for output in outputs:
        for key, value in (output.get("usage") or {}).items():
            if isinstance(value, (int, float)):
                usage[key] += value
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "status": "completed" if not failures else "completed_with_judge_failures",
        "calibration_status": CALIBRATION_STATUS,
        "score_effect": "secondary_only",
        "judge_id": prepared.judge_id,
        "record_count": len(prepared.records),
        "job_count": len(prepared.jobs),
        "failed_job_count": len(failures),
        "reused_job_count": cached_count,
        "fresh_job_count": len(outputs) - cached_count,
        "question_count": sum(job["question_count"] for job in prepared.jobs),
        "citation_count": sum(job["citation_count"] for job in prepared.jobs),
        "usage": dict(sorted(usage.items())),
        "secondary_metrics": weighted_summary(prepared.records),
        "artifacts": {
            "manifest": "manifest.json",
            "plan": "plan.json",
            "records": "records.json",
            "summary": "summary.json",
            "review": "review.md",
            "jobs": "jobs/",
        },
    }


def _state_index(value: Any) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            item_id = item.get("id")
            if (
                isinstance(item_id, str)
                and "status" in item
                and ("value" in item or item.get("status") != "available")
            ):
                prior = output.get(item_id)
                if prior is None or ("value" not in prior and "value" in item):
                    output[item_id] = item
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return output


def _expected_answer(
    slot: str,
    component_gold: dict[str, Any],
    states: dict[str, dict[str, Any]],
) -> dict[str, str]:
    for obligation in component_gold.get("obligations") or []:
        if obligation.get("node_id") == slot or slot in (
            obligation.get("allowed_citation_ids") or []
        ):
            labels = obligation.get("expected_labels") or []
            if labels:
                return {"status": "resolved", "answer": "; ".join(map(str, labels))}
    state = states.get(slot)
    if state is None:
        return {
            "status": "unresolved",
            "answer": "No exact resolved state found.",
        }
    status = str(state.get("status") or "unknown")
    answer = _compact_value(state.get("value")) if "value" in state else status
    unit = state.get("unit")
    if unit and answer not in {"null", status}:
        answer = f"{answer} {unit}"
    return {"status": "resolved", "answer": answer}


def _subsection_titles(gold: dict[str, Any]) -> dict[str, str]:
    return {
        str(subsection["id"]): str(subsection["title"])
        for section in gold["structure"]["sections"]
        for subsection in section.get("subsections") or []
    }


def _extract_subsection(markdown: str, title: str) -> str:
    pattern = re.compile(
        rf"^###\s+{re.escape(title)}\s*$\n(.*?)(?=^##[#]?\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(markdown)
    if not match:
        raise CitationJudgeError(f"candidate subsection not found: {title}")
    return match.group(1).strip()


def _citation_excerpts(text: str, target: str) -> list[str]:
    accepted_targets = {target, f"missing.{target}"}
    excerpts: list[str] = []
    occupied: list[tuple[int, int]] = []
    for match in LINK_RE.finditer(text):
        occupied.append((match.start(), match.end()))
        if match.group(2).strip() in accepted_targets:
            excerpts.append(_sentence_excerpt(text, match.start(), match.end()))
    for match in BARE_CITATION_RE.finditer(text):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        if match.group(1) in accepted_targets:
            excerpts.append(_sentence_excerpt(text, match.start(), match.end()))
    return list(dict.fromkeys(excerpts))[:3]


def _sentence_excerpt(text: str, start: int, end: int, limit: int = 600) -> str:
    left = max(text.rfind(". ", 0, start), text.rfind("\n", 0, start))
    right_candidates = [
        position
        for position in (text.find(". ", end), text.find("\n", end))
        if position >= 0
    ]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    return _compact(text[left + 1 : right].strip(), limit)


def _personalize_question(
    value: str,
    *,
    prototype: dict[str, Any],
    project_id: str,
    project_title: str,
) -> str:
    text = value.replace(str(prototype["prototype_project_title"]), project_title)
    return text.replace(str(prototype["prototype_project_id"]), project_id)


def _compact_value(value: Any, limit: int = 2400) -> str:
    if isinstance(value, list):
        text = "; ".join(_preferred_record_label(item) for item in value)
    elif isinstance(value, dict):
        text = (
            _preferred_record_label(value)
            if "fields" in value
            else json.dumps(value, ensure_ascii=False, sort_keys=True)
        )
    elif value is None:
        text = "null"
    else:
        text = str(value)
    return _compact(text, limit)


def _preferred_record_label(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value)
    fields = value.get("fields") or {}
    for key in ("name", "indicator", "title", "type", "description"):
        field = fields.get(key)
        if isinstance(field, dict) and field.get("value") not in (None, ""):
            return str(field["value"]).strip()
    if value.get("value") not in (None, ""):
        return str(value["value"])
    return str(value.get("id") or "record")


def _gold_path(project_id: str, condition_id: Any) -> Path:
    project_root = GOLD_PROJECT_ROOT / project_id.lower()
    if condition_id is None:
        path = project_root / "baseline.json"
    else:
        condition = str(condition_id)
        if not SAFE_IDENTIFIER_RE.fullmatch(condition):
            raise CitationJudgeError(f"unsafe condition id: {condition!r}")
        path = project_root / "conditions" / f"{condition}.json"
    if not path.is_file():
        raise CitationJudgeError(f"executable gold is missing: {path}")
    return path


def _safe_relative_path(root: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute():
        raise CitationJudgeError(f"path must be relative: {value!r}")
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise CitationJudgeError(f"path escapes its artifact root: {value!r}") from exc
    return resolved


def _chat_completions_endpoint(value: str) -> str:
    parsed = urlsplit(str(value).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CitationJudgeError("judge endpoint must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CitationJudgeError(
            "judge endpoint must not contain credentials, a query, or a fragment"
        )
    path = parsed.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path += "/chat/completions" if path.endswith("/v1") else "/v1/chat/completions"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _validate_json_value(value: Any) -> None:
    json.dumps(value, ensure_ascii=False, allow_nan=False)


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CitationJudgeError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CitationJudgeError(f"JSON object required: {path}")
    _validate_json_value(value)
    return value


def _write_or_verify_json(path: Path, value: Any) -> None:
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != value:
            raise CitationJudgeError(f"immutable judge artifact differs: {path.name}")
        return
    atomic_write_json(path, value)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPOSITORY_ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _compact(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _weighted_value(
    values: list[dict[str, Any]], key: str, scores: dict[str, float]
) -> float:
    return (
        sum(scores[str(item[key])] for item in values) / len(values)
        if values
        else 0.0
    )


def _weighted_metric(
    records: list[dict[str, Any]], metric: str, denominator: str
) -> float:
    total = sum(record["secondary_metrics"][denominator] for record in records)
    return (
        sum(
            record["secondary_metrics"][metric]
            * record["secondary_metrics"][denominator]
            for record in records
        )
        / total
        if total
        else 0.0
    )


def _pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "CALIBRATION_STATUS",
    "CitationJudgeConfig",
    "CitationJudgeError",
    "DEFAULT_PROMPT_PATH",
    "DEFAULT_QUESTION_BANK_PATH",
    "attach_results",
    "calculate_metrics",
    "execute_citation_judge",
    "load_question_bank",
    "plan_citation_judge",
    "prepare_citation_judge",
    "response_schema",
    "weighted_summary",
]
