#!/usr/bin/env python3
"""Export revised paper scores and retained response accounting, entirely offline.

The caller supplies revised joined records. This module never scores reports,
calls models, modifies source evidence, or writes manuscript results prose.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import mean

COHORTS = ("luna", "muse", "glm", "mimo25", "minimax", "mistral-small4")
NAMES = {"luna": "GPT-5.6 Luna", "muse": "Muse Spark 1.3", "glm": "GLM 5.3 Flash",
         "mimo25": "MiMo V2.5", "minimax": "MiniMax M3", "mistral-small4": "Mistral Small 4"}
SHORT = {"luna": "Luna", "muse": "Muse", "glm": "GLM", "mimo25": "MiMo",
         "minimax": "MiniMax", "mistral-small4": "Mistral Small 4"}
SCOPES = ("section", "report")
METRICS = {"complete": tuple("STKCRJ"), "missingness": tuple("STKCRJM"), "update": tuple("STKCRJAP")}
TITLES = {"complete": "Baseline generation", "missingness": "Missing evidence", "update": "Report maintenance"}
TABLE_NAMES = {"complete": "rq1a", "missingness": "rq1b", "update": "rq1c"}
COUNTS = {"complete": 20, "missingness": 100, "update": 100}
PAIR_FIELDS = ("project_id", "task", "condition_id", "category", "replicate")
IDENTITY_FIELDS = ("template_id", "expected_gold_sha256", "contract_sha256", "canonical_t0_sha256")
RESOURCE_RELATIVE = Path("paper/data/resource-records.json")
TOLERANCE = 1e-12


def known(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def csvsave(path, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v) if isinstance(v, (list, dict, tuple)) else v
                             for k, v in row.items()})


def project_macro(rows, field):
    """Mean within project, then equal weight over projects; no silent exclusions."""
    projects = defaultdict(list)
    for row in rows:
        if not known(row.get(field)):
            raise ValueError(f"Missing {field}: {row.get('record_key')}")
        projects[row["project_id"]].append(row[field])
    return mean(mean(values) for values in projects.values()) if projects else None


def case_key(row):
    return tuple(row.get(field) for field in PAIR_FIELDS)


def paired_projects(rows, metric):
    """Pair conditions before calculating project means; reject unmatched cases."""
    sides = {scope: {} for scope in SCOPES}
    for row in rows:
        key = case_key(row)
        if key in sides[row["scope"]]:
            raise ValueError(f"Duplicate paired case: {key}, {row['scope']}")
        sides[row["scope"]][key] = row
    if set(sides["section"]) != set(sides["report"]):
        raise ValueError("Strategy populations do not match")
    projects = defaultdict(list)
    for key in sorted(sides["section"], key=str):
        section, report = (sides[scope][key] for scope in SCOPES)
        for field in IDENTITY_FIELDS:
            # Failed submissions can lack runtime hashes; compare every
            # identity field available on both sides while retaining failures.
            if section.get(field) is not None and report.get(field) is not None and section[field] != report[field]:
                raise ValueError(f"Mismatched {field}: {key}")
        if not all(known(row.get(metric)) for row in (section, report)):
            raise ValueError(f"Unmeasured paired metric {metric}: {key}")
        projects[section["project_id"]].append((section, report))
    result = []
    for project, pairs in sorted(projects.items()):
        sm, rm = (mean(pair[i][metric] for pair in pairs) for i in (0, 1))
        result.append({"project_id": project, "matched_report_pairs": len(pairs),
                       "section": sm, "report": rm, "difference": sm - rm,
                       "record_pairs": [[s["record_key"], r["record_key"]] for s, r in pairs]})
    return result


def sign_flip(differences):
    """Exact two-sided absolute-mean sign-flip test; zero signs collapse."""
    import numpy as np
    differences = np.asarray(differences, dtype=float)
    if not len(differences):
        return None, 0, 0
    differences = np.where(np.abs(differences) <= TOLERANCE, 0.0, differences)
    nonzero = differences[differences != 0]
    sums = np.zeros(1)
    for value in nonzero:
        sums = np.concatenate((sums + value, sums - value))
    observed = abs(float(differences.sum()))
    pvalue = float(np.count_nonzero(np.abs(sums) >= observed - TOLERANCE) / len(sums))
    return pvalue, len(nonzero), len(sums)


def holm(values):
    """Retain untestable planned slots at p=1."""
    pvalues = [1.0 if value is None else value for value in values]
    adjusted = [None] * len(pvalues)
    running = 0.0
    for rank, index in enumerate(sorted(range(len(pvalues)), key=lambda i: (pvalues[i], i))):
        running = max(running, (len(pvalues) - rank) * pvalues[index])
        adjusted[index] = min(1.0, running)
    return adjusted


def adjust_families(tests):
    summaries = []
    for task, metrics in METRICS.items():
        family = [row for row in tests if row["task"] == task]
        if {(r["cohort_id"], r["metric"]) for r in family} != {(m, k) for m in COHORTS for k in metrics}:
            raise ValueError(f"Incomplete planned family: {task}")
        for row, adjusted in zip(family, holm([r["p_raw"] if r["eligible"] else None for r in family])):
            row.update(p_holm=adjusted, significant=bool(row["eligible"] and adjusted < .05),
                       family_id=task, family_size=len(family))
        summaries.append({"task": task, "models": len(COHORTS), "metrics": list(metrics),
                          "family_size": len(family), "eligible_tests": sum(r["eligible"] for r in family),
                          "significant": sum(r["significant"] for r in family), "alpha": .05})
    return summaries


def aggregate_resources(rows, resources):
    """Recorded response accounting; never turn missing prices/tools into zero."""
    selected = [resources[row["record_key"]] for row in rows]
    joined = []
    for row, resource in zip(rows, selected):
        for field in ("cohort_id", "scope", "project_id", "task"):
            if row[field] != resource[field]:
                raise ValueError(f"Resource identity mismatch: {row['record_key']}, {field}")
        joined.append({**resource, "Q": row["Q"]})
    result = {"cases": len(rows), "projects": len({r["project_id"] for r in rows}),
              "Q": project_macro(joined, "Q"), "Q_100": 100 * project_macro(joined, "Q"),
              "accepted": sum(bool(r["terminal"]) for r in rows),
              "record_keys": [r["record_key"] for r in rows]}
    for field in ("latency_seconds", "input_tokens", "output_tokens", "total_tokens", "response_turns"):
        result[field] = project_macro(joined, field)
        result[field + "_n"] = len(joined)
    # The disclosed tool metric is the mean over available native report cases.
    tools = [r["executed_tool_calls"] for r in selected if known(r.get("executed_tool_calls"))]
    result["executed_tool_calls"] = mean(tools) if tools else None
    result["executed_tool_calls_n"] = len(tools)
    costs = [r["reported_usd_subtotal"] for r in selected
             if r.get("reported_usd_subtotal") is not None and r["usd_unreported_turns"] == 0]
    result["reported_usd_known_cases"] = len(costs)
    result["recorded_response_usd"] = (str(sum((Decimal(c) for c in costs), Decimal(0)) / len(rows))
                                        if len(costs) == len(rows) and rows else None)
    result["native_summary_cases"] = sum(bool(r["native_summary_available"]) for r in selected)
    result["receipt_reconstructed_cases"] = len(rows) - result["native_summary_cases"]
    return result


def tex_number(value, decimals=1):
    return "---" if value is None else f"{float(value):.{decimals}f}"


def table_text(caption, label, columns, header, lines, footnote="", wide=True):
    environment = "table*" if wide else "table"
    text = [rf"\begin{{{environment}}}[t]", r"\centering\small", r"\setlength{\tabcolsep}{4pt}",
            rf"\caption{{{caption}}}", rf"\label{{{label}}}", rf"\begin{{tabular}}{{{columns}}}",
            r"\toprule", header + r" \\", r"\midrule", *lines, r"\bottomrule", r"\end{tabular}"]
    if footnote:
        text += [r"\par\vspace{3pt}", r"\begin{minipage}{0.98\linewidth}\footnotesize", footnote, r"\end{minipage}"]
    text += [rf"\end{{{environment}}}", ""]
    return "\n".join(text)


def make_quality_tables(output, means, tests):
    lookup = {(r["cohort_id"], r["task"], r["scope"], r["metric"]): r["mean"] for r in means}
    comparisons = {(r["cohort_id"], r["task"], r["metric"]): r for r in tests}
    for task, metrics in METRICS.items():
        lines, csvrows = [], []
        for cohort in COHORTS:
            for scope in SCOPES:
                values, csvrow = [], {"model": NAMES[cohort], "cohort_id": cohort, "scope": scope}
                for metric in metrics:
                    value = lookup[cohort, task, scope, metric]
                    other = lookup[cohort, task, "report" if scope == "section" else "section", metric]
                    rendered = tex_number(100 * value)
                    if value > other + TOLERANCE:
                        rendered = r"\textbf{" + rendered + "}"
                    test = comparisons[cohort, task, metric]
                    if test["significant"] and test["higher_paired_scope"] == scope:
                        rendered += r"\textsuperscript{*}"
                    values.append(rendered)
                    csvrow[metric] = value
                    csvrow[metric + "_100"] = 100 * value
                lines.append(" & ".join([NAMES[cohort], scope.title(), *values]) + r" \\")
                csvrows.append(csvrow)
            lines.append(r"\addlinespace[2pt]")
        notes = (r"$S$: structure; $T$: tables; $K$: calculated-result correctness; $C$: citation obligations; "
                 r"$R$: prose requirement coverage; $J$: supported required citation groups. ")
        if task == "missingness":
            notes += r"$M$: missingness. "
        if task == "update":
            notes += r"$A$: affected-section change rate; $P$: unaffected-section preservation. $A$ measures edits, not their correctness. "
        notes += (r"All 20 projects contribute equally. All planned cases remain included; incomplete reports receive zero on applicable measures. "
                  r"Existing semantic measurement-failure assignments are retained. "
                  rf"$^{{*}}p_{{\mathrm{{Holm}}}}<.05$: exact two-sided project-paired sign-flip tests, "
                  rf"with {6 * len(metrics)} planned comparisons in this task's Holm family.")
        text = table_text(TITLES[task] + ". Scores on a 0--100 scale. Bold marks the higher unrounded mean within each model.",
                          "tab:" + TABLE_NAMES[task], "ll" + "r" * len(metrics),
                          "Model & Strategy & " + " & ".join("$" + m + "$" for m in metrics), lines, notes)
        (output / "tables" / (TABLE_NAMES[task] + ".tex")).write_text(text)
        csvsave(output / "data" / (TABLE_NAMES[task] + ".csv"), csvrows)


def make_supplement(output, rows, overall, families):
    completion, resource_lines, quality_lines = [], [], []
    completion_rows = []
    for point in overall:
        cohort, scope = point["cohort_id"], point["scope"]
        selected = [r for r in rows if r["cohort_id"] == cohort and r["scope"] == scope]
        cells = []
        item = {"cohort_id": cohort, "model": NAMES[cohort], "scope": scope}
        for task in METRICS:
            cases = [r for r in selected if r["task"] == task]
            accepted = sum(bool(r["terminal"]) for r in cases)
            item[task + "_accepted"], item[task + "_planned"] = accepted, len(cases)
            cells.append(f"{accepted}/{len(cases)}")
        item.update(accepted=point["accepted"], planned=point["cases"])
        completion_rows.append(item)
        completion.append(" & ".join([NAMES[cohort], scope.title(), *cells, f"{point['accepted']}/{point['cases']}",
                                     tex_number(100 * point["accepted"] / point["cases"], 2)]) + r" \\")
        resource_lines.append(" & ".join([NAMES[cohort], scope.title(), tex_number(point["input_tokens"] / 1000),
                              tex_number(point["output_tokens"] / 1000), tex_number(point["response_turns"]),
                              tex_number(point["executed_tool_calls"]), str(point["executed_tool_calls_n"]),
                              tex_number(point["recorded_response_usd"], 4)]) + r" \\")
        quality_lines.append(" & ".join([NAMES[cohort], scope.title(), tex_number(point["Q_100"]),
                                        tex_number(point["latency_seconds"]), str(point["cases"])]) + r" \\")
    completion_tex = table_text("Accepted report cases / planned cases.", "tab:supp-completion", "llrrrrr",
                                "Model & Strategy & Baseline & Missing & Update & All & All (\\%)", completion,
                                "Completion requires an accepted whole report or all 15 required sections; it does not imply correctness.")
    resource_tex = table_text("Recorded generation resources per planned report case. Tokens are in thousands.",
                              "tab:supp-resources", "llrrrrrr",
                              r"Model & Strategy & Input k & Output k & Turns & Tools & $n_{\rm tool}$ & USD/case", resource_lines,
                              r"Each model--strategy pair contributes 220 cases (baseline:missing:update = 1:5:5), including unsuccessful cases. "
                              r"Turns count returned responses. Tools use the available native execution summaries; $n_{\rm tool}$ reports that denominator. "
                              r"A dash indicates unavailable charges, not zero. Charges exclude semantic judging and operational overhead.")
    quality_tex = table_text("Quality and recorded response time over the complete 1:5:5 task mix.",
                             "tab:rq2-overall", "llrrr", r"Model & Strategy & $Q$ (0--100) & Time (s) & Cases", quality_lines,
                             r"$Q=(S+T+K+C+R+J)/6$. Conditions are averaged within project and the 20 projects receive equal weight. "
                             r"Time sums recorded model-response durations across all trajectories; it is not elapsed report-production time.")
    pair_lines = [" & ".join([TITLES[f["task"]], str(COUNTS[f["task"]]), "20",
                               f"{f['eligible_tests']}/{f['family_size']}"]) + r" \\" for f in families]
    pairs_tex = table_text("Paired coverage. Case and project pairs are per model; eligible tests span all six models.",
                           "tab:supp-pairs", "lrrr", "Task & Case pairs & Projects & Eligible tests", pair_lines,
                           "Five matched intervention conditions are averaged within each project before testing.", wide=False)
    for filename, content in (("completion.tex", completion_tex), ("resources.tex", resource_tex),
                              ("paired-coverage.tex", pairs_tex), ("rq2-overall.tex", quality_tex)):
        (output / "tables" / filename).write_text(content)
    appendix = (r"\section{Completion, recorded resources, and paired coverage}" + "\n" +
                r"\label{app:reporting-supplement}" + "\n\n" + completion_tex + "\n" + resource_tex + "\n" + pairs_tex)
    (output / "appendix-reporting.tex").write_text(appendix)
    csvsave(output / "data" / "completion.csv", completion_rows)


def make_figures(output, panels, overall):
    os.environ.setdefault("MPLCONFIGDIR", str(output / "matplotlib-cache"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    colors = dict(zip(COHORTS, ["#235BA8", "#008B8D", "#D56A24", "#8549A7", "#667085", "#BC3C52"]))
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.titlesize": 9,
                         "axes.labelsize": 8, "xtick.labelsize": 7, "ytick.labelsize": 7,
                         "legend.fontsize": 7, "pdf.fonttype": 42, "ps.fonttype": 42,
                         "axes.spines.top": False, "axes.spines.right": False})
    def panel(ax, points, title):
        for cohort in COHORTS:
            pair = [p for p in points if p["cohort_id"] == cohort]
            ax.plot([p["latency_seconds"] for p in pair], [p["Q_100"] for p in pair],
                    color=colors[cohort], lw=.8, alpha=.35, zorder=1)
        for point in points:
            ax.scatter(point["latency_seconds"], point["Q_100"], s=30,
                       c=colors[point["cohort_id"]], marker="o" if point["scope"] == "section" else "s",
                       edgecolors="white", linewidths=.4, zorder=3)
        ax.set_title(title, pad=8)
        ax.set_ylim(0, 100)
        ax.set_xlim(left=0)
        ax.grid(color="#dde2e7", lw=.5, zorder=0)
        ax.set_axisbelow(True)
    models = [Line2D([], [], marker="o", ls="", color=colors[m], label=SHORT[m], markersize=5) for m in COHORTS]
    scopes = [Line2D([], [], marker=symbol, ls="", color="#333333", label=scope.title(), markersize=5)
              for scope, symbol in (("section", "o"), ("report", "s"))]
    fig, axes = plt.subplots(1, 3, figsize=(7.05, 3.08))
    for ax, task in zip(axes, METRICS):
        panel(ax, panels[task], TITLES[task])
    axes[0].set_ylabel("Report quality Q (0–100)")
    fig.supxlabel("Summed recorded model-response time (s)", fontsize=8, y=.115)
    fig.legend(handles=models, loc="upper center", bbox_to_anchor=(.5, 1.005), ncol=6,
               frameon=False, columnspacing=.85, handletextpad=.35)
    fig.legend(handles=scopes, loc="lower center", bbox_to_anchor=(.5, -.005), ncol=2, frameon=False)
    fig.subplots_adjust(left=.085, right=.99, bottom=.24, top=.76, wspace=.30)
    fig.savefig(output / "figures/rq2-quality-time.pdf")
    fig.savefig(output / "figures/rq2-quality-time.png", dpi=240)
    plt.close(fig)
    for task, filename in (("complete", "baseline"), ("missingness", "missingness"), ("update", "updates"), ("all", "overall")):
        fig, ax = plt.subplots(figsize=(5.4, 3.8))
        panel(ax, overall if task == "all" else panels[task], "All conditions (1:5:5 task mix)" if task == "all" else TITLES[task])
        ax.set_xlabel("Summed recorded model-response time (s)")
        ax.set_ylabel("Report quality Q (0–100)")
        fig.legend(handles=models, loc="upper center", bbox_to_anchor=(.5, 1), ncol=3, frameon=False)
        fig.legend(handles=scopes, loc="lower center", bbox_to_anchor=(.5, .005), ncol=2, frameon=False)
        fig.subplots_adjust(left=.13, right=.97, bottom=.20, top=.72)
        fig.savefig(output / f"figures/rq2-{filename}.pdf")
        fig.savefig(output / f"figures/rq2-{filename}.png", dpi=220)
        plt.close(fig)


def export(records_path, output, root):
    records_path, output, root = map(Path, (records_path, output, root))
    payload = read(records_path)
    rows = payload["records"] if isinstance(payload, dict) else payload
    resource_path = root / RESOURCE_RELATIVE
    resource_rows = read(resource_path)
    resources = {r["record_key"]: r for r in resource_rows}
    assert len(rows) == len(resources) == len(resource_rows) == 2640
    assert len({r["record_key"] for r in rows}) == 2640
    assert {r["record_key"] for r in rows} == set(resources)
    assert sum(bool(r["terminal"]) for r in rows) == 2589
    assert all(r["finished"] for r in rows)
    for row in rows:
        for metric in METRICS[row["task"]]:
            assert known(row[metric]) and 0 <= row[metric] <= 1, (row["record_key"], metric)
            if not row["terminal"]:
                assert row[metric] == 0
        assert known(row["Q"]) and abs(row["Q"] - mean(row[k] for k in "STKCRJ")) < TOLERANCE
    for directory in ("data", "tables", "figures"):
        (output / directory).mkdir(parents=True, exist_ok=True)
    means, tests, differences, coverage = [], [], [], []
    panels = {task: [] for task in METRICS}
    overall = []
    for cohort in COHORTS:
        for task, metrics in METRICS.items():
            selected = [r for r in rows if r["cohort_id"] == cohort and r["task"] == task]
            for scope in SCOPES:
                group = [r for r in selected if r["scope"] == scope]
                assert len(group) == COUNTS[task] and len({r["project_id"] for r in group}) == 20
                assert set(Counter(r["project_id"] for r in group).values()) == {1 if task == "complete" else 5}
                coverage.append({"cohort_id": cohort, "task": task, "scope": scope, "planned": len(group),
                                 "accepted": sum(bool(r["terminal"]) for r in group), "projects": 20,
                                 "metric_report_counts": {m: len(group) for m in metrics}})
                for metric in metrics:
                    value = project_macro(group, metric)
                    means.append({"cohort_id": cohort, "model": NAMES[cohort], "task": task, "scope": scope,
                                  "metric": metric, "mean": value, "mean_100": 100 * value,
                                  "reports": len(group), "projects": 20})
                panels[task].append({"cohort_id": cohort, "model": NAMES[cohort], "scope": scope,
                                     "task": task, **aggregate_resources(group, resources)})
            for metric in metrics:
                project_rows = paired_projects(selected, metric)
                assert len(project_rows) == 20
                for p in project_rows:
                    differences.append({"cohort_id": cohort, "task": task, "metric": metric, **p})
                values = [p["difference"] for p in project_rows]
                pvalue, nonzero, permutations = sign_flip(values)
                effect = mean(values)
                tests.append({"cohort_id": cohort, "model": NAMES[cohort], "task": task, "metric": metric,
                              "eligible": True, "paired_reports": COUNTS[task], "paired_projects": 20,
                              "paired_section_mean": mean(p["section"] for p in project_rows),
                              "paired_report_mean": mean(p["report"] for p in project_rows),
                              "paired_difference": effect, "p_raw": pvalue, "nonzero_projects": nonzero,
                              "sign_assignments": permutations, "project_differences": values,
                              "project_ids": [p["project_id"] for p in project_rows],
                              "higher_paired_scope": "section" if effect > TOLERANCE else "report" if effect < -TOLERANCE else None})
        for scope in SCOPES:
            group = [r for r in rows if r["cohort_id"] == cohort and r["scope"] == scope]
            assert len(group) == 220 and set(Counter(r["project_id"] for r in group).values()) == {11}
            overall.append({"cohort_id": cohort, "model": NAMES[cohort], "scope": scope,
                            "task": "all", **aggregate_resources(group, resources)})
    families = adjust_families(tests)
    assert len(means) == 252 and len(tests) == 126 and len(differences) == 2520
    make_quality_tables(output, means, tests)
    make_supplement(output, rows, overall, families)
    make_figures(output, panels, overall)
    for name, values in (("table-means", means), ("paired-project-differences", differences),
                         ("coverage", coverage), ("family-summary", families), ("rq2-overall", overall),
                         ("rq2-task-points", [p for task in METRICS for p in panels[task]])):
        save(output / "data" / (name + ".json"), values)
        csvsave(output / "data" / (name + ".csv"), values)
    save(output / "data/significance-126.json", {"method": "exact two-sided project sign-flip",
                                                "families": families, "tests": tests})
    csvsave(output / "data/significance-126.csv", tests)
    for task in METRICS:
        csvsave(output / "data" / ("significance-" + task + ".csv"), [t for t in tests if t["task"] == task])
    lookup = {(m["cohort_id"], m["task"], m["metric"], m["scope"]): m["mean_100"] for m in means}
    csvsave(output / "data/table-results.csv", [{**t,
             "section_mean_100": lookup[t["cohort_id"], t["task"], t["metric"], "section"],
             "report_mean_100": lookup[t["cohort_id"], t["task"], t["metric"], "report"]} for t in tests])
    caption = (r"Report quality and summed recorded model-response time. Each task panel uses all planned cases across 20 projects. "
               r"$Q=(S+T+K+C+R+J)/6$; incomplete reports receive zero quality. "
               r"Time sums returned generation-response durations across all trajectories, including unsuccessful generations. "
               r"It excludes failed-response overhead, counting probes, scheduling and backoff, and is not elapsed production time." + "\n")
    (output / "figures/caption.tex").write_text(caption)
    summary = {"records": len(rows), "accepted": 2589, "table_means": len(means), "paired_tests": len(tests),
               "paired_project_differences": len(differences), "families": families,
               "task_points": 36, "overall_points": 12, "quality_formula": "(S+T+K+C+R+J)/6",
               "records_sha256": hashlib.sha256(records_path.read_bytes()).hexdigest(),
               "resource_source": RESOURCE_RELATIVE.as_posix(), "resource_sha256": hashlib.sha256(resource_path.read_bytes()).hexdigest(),
               "provider_calls": 0}
    save(output / "data/export-summary.json", summary)
    return summary


def verify_exports(output: Path, paper_root: Path) -> None:
    """Compare statistical outputs and rendered tables with the archived results."""
    for expected in sorted((paper_root / "expected").glob("*.json")):
        generated = output / "data" / expected.name
        if read(generated) != read(expected):
            raise ValueError(f"Reproduced statistics differ for {expected.name}")
    for expected in sorted((paper_root / "tables").glob("*.tex")):
        generated = output / "tables" / expected.name
        if generated.read_bytes() != expected.read_bytes():
            raise ValueError(f"Reproduced table differs for {expected.name}")


if __name__ == "__main__":
    paper_root = Path(__file__).resolve().parent
    root = paper_root.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and (not args.output.is_dir() or any(args.output.iterdir())):
        parser.error("--output must be a new or empty directory")

    records_path = paper_root / "data/analysis-records.json"
    resource_path = root / RESOURCE_RELATIVE
    provenance = read(paper_root / "data/provenance.json")
    for path, field in (
        (records_path, "score_rows_sha256"),
        (resource_path, "resource_rows_sha256"),
    ):
        if hashlib.sha256(path.read_bytes()).hexdigest() != provenance[field]:
            raise ValueError(f"Input checksum differs for {path.name}")
    summary = export(records_path, args.output, root)
    verify_exports(args.output, paper_root)
    print(json.dumps({**summary, "archive_comparison": "passed"}, indent=2))
