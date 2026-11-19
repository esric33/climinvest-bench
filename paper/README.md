# Paper data and evaluation

`data/analysis-records.json` contains the 2,640 planned report-level cases for
six model treatments. It retains record identities, metric values, failure
classes, and candidate and reference hashes. The 51 incomplete reports receive
zero credit where applicable. `data/resource-records.json` contains recorded
response accounting used in the figures and tables. Missing cost and tool
observations retain their original missing values.

[The analysis policy](data/analysis-policy.json) defines the individual
metrics, the composite `Q = (S + T + K + C + R + J) / 6`, and the project-level
paired tests with Holm correction. [Provenance](data/provenance.json) records
the checksums of the original ledgers and of the columns selected for release.
`scoring.py` contains the report rescoring implementation. Its counterfactual
tests run with `python -m unittest discover -s paper -p 'test_*.py'`.

`reproduce.py` checks the released ledgers and regenerates the paper's analysis
outputs. This is a score-to-results replay. The shipped R and J values are the
archived semantic judgments. Re-running the historical model and judge
trajectories requires separate source artifacts and access to the historical
model treatments.
