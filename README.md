# ClimInvestBench

ClimInvestBench evaluates evidence-grounded investment report generation and
maintenance. It compares whole-report and section-by-section generation on
20 fixed ClimateFund projects. The three tasks cover baseline generation,
generation with missing evidence, and report updates after evidence changes.
Each model has 440 report-level records across the two generation strategies.

This release accompanies *ClimInvestBench: Evaluating Agentic Investment Report
Generation and Maintenance* by Edward Richards, Javier Sanz-Cruzado, and
Richard McCreadie. It uses the frozen September 2026 runtime, evidence,
conditions, and executable gold. See [citation metadata](CITATION.cff) and
[third-party notices](THIRD_PARTY_NOTICES.md).

## Install and run the offline benchmark

Use Python 3.11 or newer, Node.js 22, and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked --extra paper
uv run --locked --extra paper climinvest-benchmark validate
node benchmarks/react_report_building/v2/compile_contract.js --check
uv run --locked --extra paper benchrun run \
  --config experiments/v2-readiness.yaml --run-dir runs/offline-fixture --no-progress
```

The fixture exercises 22 report-level records on FP083 and 176 simulated
episodes. It needs no account, credentials, or external model calls. Use a
fresh run directory for a separate run. The runtime supports the four tools
used by the paper: `get_data`, `calculate`, `create_report`, and
`create_section`.

## Reproduce the paper tables and plots

```sh
uv run --locked --extra paper python paper/reproduce.py --output runs/paper-replay
```

This command checks the included input hashes, then regenerates the tables,
plots, and statistics from the 2,640 report-level score and resource rows.
It compares all 252 means, 126 paired tests, 2,520 paired project differences,
resource summaries, and rendered tables with the archived outputs. See
[paper data and evaluation](paper/README.md) for the metric policy and replay
scope.

The package includes the normalized inputs used for the benchmark. For source
rebuilding, the upstream revision and byte checksum are in
[`sources/climatefund.json`](sources/climatefund.json).

## Licensing

- The benchmark code, paper replay scripts, and software documentation use the
  [MIT license](LICENSE).
- The original paper results in `paper/data/`, `paper/expected/`, and
  `paper/tables/` use [CC BY 4.0](LICENSES/CC-BY-4.0.txt).
  See the [results attribution](paper/README.md#results-license).
- The ClimateFund-derived benchmark material retains
  [MPL-2.0](LICENSES/MPL-2.0.txt) and its upstream attribution.
  The vendored TraceMark compiler carries its original MIT notice.
  See [third-party notices](THIRD_PARTY_NOTICES.md).
