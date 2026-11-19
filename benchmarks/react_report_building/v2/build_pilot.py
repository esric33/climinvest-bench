from __future__ import annotations

import json

from .perturbations import PILOT_PATH, write_pilot


def main() -> None:
    payload = write_pilot()
    print(
        json.dumps(
            {
                "path": str(PILOT_PATH),
                "mask_count": len(payload["masks"]),
                "mutation_count": len(payload["mutations"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
