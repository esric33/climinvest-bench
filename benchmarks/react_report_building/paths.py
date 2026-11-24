from __future__ import annotations

import os
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[1]
DATA_ROOT = PACKAGE_ROOT / "data"
RAW_CLIMATEFUND_PATH = Path(
    os.environ.get(
        "CLIMATEFUND_DATA_PATH",
        DATA_ROOT / "raw" / "climatefund.json",
    )
).expanduser()
CLIMATEFUND_SOURCE_PATH = "external/ClimateFund@d7a57b8/climatefund.json"
NORMALIZED_ROOT = DATA_ROOT / "normalized" / "projects"
SELECTION_ROOT = DATA_ROOT / "selections" / "kpis"
REFERENCE_ROOT = DATA_ROOT / "references"
CATALOGUE_ROOT = DATA_ROOT / "catalogues"
CONDITION_ROOT = DATA_ROOT / "conditions"
GOLD_ROOT = DATA_ROOT / "gold"
RUNS_ROOT = PACKAGE_ROOT / "runs"
SCHEMA_ROOT = PACKAGE_ROOT / "schemas"
PROMPT_ROOT = PACKAGE_ROOT / "prompts"
TEMPLATE_ROOT = PACKAGE_ROOT / "templates"
CONFIG_ROOT = PACKAGE_ROOT / "config"
