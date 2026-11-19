from __future__ import annotations

import re
from typing import Any


FAMILY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "land_nature_outcome",
        re.compile(
            r"(?:\b(?:hectares?|ha)\b.{0,100}\b(?:land|forests?|conserv(?:ed|ation)|"
            r"restor(?:ed|ation)|plant(?:ed|ation)|managed|production systems?)\b|"
            r"\b(?:land|forests?|conserv(?:ed|ation)|restor(?:ed|ation)|"
            r"plant(?:ed|ation)|managed|production systems?)\b.{0,100}"
            r"\b(?:hectares?|ha)\b|\bsustainably produced wood products?\b)",
            re.I,
        ),
    ),
    (
        "climate_impact",
        re.compile(
            r"(?:\b(?:tonnes?|tons?)\s+of\s+(?:carbon dioxide equivalent|co2(?:e|eq)?)\b|"
            r"\bt\s*co2(?:e|eq)?\b|"
            r"\b(?:ghg|greenhouse gas|co2|carbon dioxide equivalent|emissions?)"
            r"(?:\s+emissions?)?\s+(?:reduc(?:ed|tion|tions)|avoid(?:ed|ance)|"
            r"remov(?:ed|als?)|sequester(?:ed|ation))\b|"
            r"\bemission\s+reduction\b)",
            re.I,
        ),
    ),
    (
        "climate_resilience",
        re.compile(
            r"\bphysical assets?\b.{0,100}\b(?:resilien|climate variability)\w*\b",
            re.I,
        ),
    ),
    (
        "low_emission_capacity",
        re.compile(
            r"(?:\b(?:mw|mws|mwh|gwh|tj)\b|"
            r"\b(?:energy|power)\s+(?:intensity|savings?|generated|produced|"
            r"consumption)\b|"
            r"\bproportion of low[- ]?emission power supply\b|"
            r"\b(?:low[- ]?emission|renewable|solar|wind|pv|storage|generation)"
            r"\b.{0,80}\b(?:capacity\s+(?:installed|generated|rehabilitated|built|"
            r"awarded)|energy\s+(?:generated|produced|saved)|installed|"
            r"commissioned|dispatchable)\b|"
            r"\bbattery energy storage system procured\b|"
            r"\bgrids? (?:are )?upgraded\b|"
            r"\bgrid connected solar pv farms?\b|"
            r"\b(?:saidi|saifi)\b)",
            re.I,
        ),
    ),
    (
        "beneficiaries_access",
        re.compile(
            r"(?:\bbeneficiar(?:y|ies)\b|"
            r"\b(?:households?|individuals?|people|population|localities|ngos?)\b"
            r".{0,90}\b(?:(?:with)?improved access|accessing|connected|connections?|"
            r"benefit(?:ed|ing)?|reached|improved livelihoods?)\b|"
            r"\b(?:(?:with)?improved access|accessing|connections?|improved livelihoods?)\b"
            r".{0,90}\b(?:households?|individuals?|people|population|localities|ngos?)\b|"
            r"\bincreased household income\b|"
            r"\b(?:health facilities|schools|service hubs|service centers)\b"
            r".{0,80}\bpowered\b)",
            re.I,
        ),
    ),
    (
        "employment_gender",
        re.compile(r"\b(jobs?|employment|women|female|gender)\b", re.I),
    ),
    (
        "institutional_capacity",
        re.compile(
            r"\b(capacity build(?:ing|t)|train(?:ed|ing|ings)|institution(?:al|s)?|"
            r"staff(?:ed|ing)?|officer|"
            r"knowledge and experience|(?:enhanced|strengthened|technical|financing)"
            r"\s+capacity)\b",
            re.I,
        ),
    ),
    (
        "policy_governance",
        re.compile(
            r"\b(policy|policies|regulat(?:ion|ions|ory|or|ors|ed)?|governance|"
            r"frameworks?|roadmaps?|plans?|strateg(?:y|ies)|act|"
            r"enabling environment)\b",
            re.I,
        ),
    ),
    (
        "finance_investment",
        re.compile(
            r"(?:\bvolume of (?:public and private )?(?:finance|financing|funds?)\b|"
            r"\b(?:finance|financing|capital|funds?)\s+(?:leveraged|mobilized|"
            r"cataly[sz]ed|approved|disbursed)\b|"
            r"\b(?:amount|value|usd volume|total value) of (?:loans?|finance|"
            r"financing|funding|disbursement|debt)\b|"
            r"\b(?:total|volume|value)\b.{0,40}\binvestments?\b|"
            r"\bnumber of loans?\b(?!\s+officers?)|\bfunding leverage factor\b|"
            r"\b(?:finance|financing|investment|capital|funding|loans?|disbursement)"
            r"\s*\(?usd\b)",
            re.I,
        ),
    ),
]

FAMILY_ORDER = [
    "climate_impact",
    "climate_resilience",
    "land_nature_outcome",
    "low_emission_capacity",
    "beneficiaries_access",
    "policy_governance",
    "institutional_capacity",
    "finance_investment",
    "employment_gender",
    "other",
]

EXCLUDED_DUPLICATE_PATTERN = re.compile(
    r"(?:\bghg\b|\bgreenhouse gas\b|\bemission reduction\b|"
    r"\bcarbon\s+dioxide\s+equivalent\b|\bt\s*co2(?:e|eq)?\b|"
    r"\bcost\s+per\s+t\s*co2)",
    re.I,
)

COST_INTENSITY_INDICATOR_PATTERN = re.compile(
    r"\bcost\s+per\s+(?:(?:metric\s+)?tonnes?\s+(?:of\s+)?|t\s*)"
    r"(?:co2|carbon dioxide)(?:[- ]?equivalent|e|eq)?\b",
    re.I,
)

DIRECT_EMPLOYMENT_PATTERN = re.compile(r"\b(?:jobs?|employment)\b", re.I)

PLACEHOLDER_INDICATOR_NAMES = frozenset(
    {
        "",
        "-",
        "n a",
        "na",
        "nil",
        "none",
        "not applicable",
        "not available",
        "null",
        "tbc",
        "tbd",
    }
)


def classify_kpi(name: str) -> str:
    # Measurement-bearing phrases outrank incidental context. For example,
    # ``USD volume ... final beneficiaries`` is a finance indicator, while
    # ``energy-efficiency jobs`` is an employment indicator. This ordering is
    # deterministic and intentionally does not infer from project prose.
    if COST_INTENSITY_INDICATOR_PATTERN.search(name):
        return "other"
    patterns = {family: pattern for family, pattern in FAMILY_PATTERNS}
    for family in ("land_nature_outcome", "climate_impact", "climate_resilience"):
        if patterns[family].search(name):
            return family
    if DIRECT_EMPLOYMENT_PATTERN.search(name):
        return "employment_gender"
    for family in (
        "finance_investment",
        "low_emission_capacity",
        "beneficiaries_access",
        "employment_gender",
        "institutional_capacity",
        "policy_governance",
    ):
        if patterns[family].search(name):
            return family
    return "other"


def flatten_kpis(project: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for outcome_index, outcome in enumerate(project.get("outcomes") or []):
        for kpi_index, kpi in enumerate(outcome.get("kpis") or []):
            output.append(
                {
                    **kpi,
                    "_path": f"outcomes.{outcome_index}.kpis.{kpi_index}",
                    "_outcome_id": str(outcome.get("code") or f"outcome.{outcome_index}"),
                    "_source_order": len(output),
                }
            )
    return output


def canonical_indicator_name(value: Any) -> str:
    """Return a conservative key used only for exact-ish KPI deduplication."""

    collapsed = " ".join(str(value or "").split()).casefold()
    return re.sub(r"[^\w]+", " ", collapsed, flags=re.UNICODE).strip()


def clean_kpis(
    project: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return the complete usable KPI pool and a record-by-record audit.

    The source order is retained. Only blank/placeholder indicator names and
    exact-ish duplicate names are excluded, with an explicit audit trail. A
    source KPI is not dropped merely because a benchmark calculation addresses
    a similar construct: its target, verification and assumptions remain source
    evidence. No ranking or synthetic priority is introduced at normalization
    time.
    """

    candidates: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    first_path_by_name: dict[str, str] = {}
    for kpi in flatten_kpis(project):
        name = " ".join(str(kpi.get("name") or "").split())
        canonical_name = canonical_indicator_name(name)
        family = classify_kpi(name)
        duplicate_of = first_path_by_name.get(canonical_name)
        if canonical_name in PLACEHOLDER_INDICATOR_NAMES:
            eligible = False
            reason = "placeholder indicator name"
        elif duplicate_of is not None:
            eligible = False
            reason = "duplicate indicator name"
        else:
            eligible = True
            reason = "eligible"
            first_path_by_name[canonical_name] = kpi["_path"]
        audit.append(
            {
                "path": kpi["_path"],
                "name": name,
                "canonical_name": canonical_name,
                "family": family,
                "source_order": kpi["_source_order"] + 1,
                "eligible": eligible,
                "reason": reason,
                "duplicate_of": duplicate_of,
                "legacy_selection_eligible": (
                    eligible and not bool(EXCLUDED_DUPLICATE_PATTERN.search(name))
                ),
            }
        )
        if eligible:
            candidates.append(
                {
                    **kpi,
                    "name": name,
                    "_canonical_name": canonical_name,
                    "_family": family,
                }
            )
    return candidates, audit


def select_kpis_from_candidates(
    candidates: list[dict[str, Any]],
    *,
    count: int = 5,
    project_code: str = "project",
) -> list[dict[str, Any]]:
    """Retain the legacy five-row diversity sample for compatibility only."""

    # The legacy five-row table intentionally avoided GHG/cost-intensity KPIs
    # because those values were already rendered elsewhere.  The complete
    # dt.kpis register does not apply this presentation-only exclusion.
    selection_candidates = [
        candidate
        for candidate in candidates
        if not EXCLUDED_DUPLICATE_PATTERN.search(str(candidate.get("name") or ""))
    ]
    selected: list[dict[str, Any]] = []
    used_paths: set[str] = set()
    for family in FAMILY_ORDER:
        for candidate in selection_candidates:
            if candidate["_family"] != family or candidate["_path"] in used_paths:
                continue
            selected.append(candidate)
            used_paths.add(candidate["_path"])
            break
        if len(selected) == count:
            break
    if len(selected) < count:
        for candidate in selection_candidates:
            if candidate["_path"] in used_paths:
                continue
            selected.append(candidate)
            used_paths.add(candidate["_path"])
            if len(selected) == count:
                break
    if len(selected) != count:
        raise ValueError(
            f"{project_code}: only {len(selected)} eligible KPIs for a {count}-row report"
        )
    return selected


def select_kpis(
    project: dict[str, Any], count: int = 5
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates, audit = clean_kpis(project)
    selected = select_kpis_from_candidates(
        candidates,
        count=count,
        project_code=str(project.get("code") or "project"),
    )
    return selected, audit
