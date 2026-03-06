#!/usr/bin/env python3
"""Extract top 10 configs from aggressive optimizer leaderboard."""

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
LB_PATH = ROOT / "output" / "leaderboard_aggressive.json"
OUTPUT_PATH = ROOT / "output" / "aggressive_top10_configs.json"

MIN_AVG_RETURN = 10.0
MAX_WORST_DD = -25.0


def main():
    lb = json.loads(LB_PATH.read_text())
    print(f"Loaded {len(lb)} entries from {LB_PATH.name}")

    filtered = [
        e for e in lb
        if e["summary"]["avg_return"] >= MIN_AVG_RETURN
        and e["summary"]["worst_dd"] >= MAX_WORST_DD
    ]
    print(f"After filter (avg>={MIN_AVG_RETURN}%, DD>={MAX_WORST_DD}%): {len(filtered)}")

    filtered.sort(key=lambda x: x["summary"]["avg_return"], reverse=True)
    top10 = filtered[:10]

    configs = [
        {
            "run_id": e["run_id"],
            "summary": e["summary"],
            "strategy_params": e["strategy_params"],
        }
        for e in top10
    ]

    OUTPUT_PATH.write_text(json.dumps(configs, indent=2))
    print(f"\nTop 10 saved to {OUTPUT_PATH.name}:")
    for i, c in enumerate(configs):
        s = c["summary"]
        print(f"  {i+1:>2}. {c['run_id']}: {s['avg_return']:+.1f}%/yr, "
              f"DD={s['worst_dd']:.1f}%, cons={s['consistency_score']:.0%}")


if __name__ == "__main__":
    main()
