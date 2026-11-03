"""Build a small offline browser bundle from the revalidated experiment JSON."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "demo/data/experiment_analysis.json"
INTELLIGENCE = ROOT / "demo/data/intelligent_analysis.json"
ENGINEERING = ROOT / "demo/data/engineering_report.json"
TARGET = ROOT / "demo/demo_data.js"

def decimate(values, limit=900):
    if len(values) <= limit:
        return values
    step = (len(values) - 1) / (limit - 1)
    return [values[round(i * step)] for i in range(limit)]

def main():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    intelligence = json.loads(INTELLIGENCE.read_text(encoding="utf-8")) if INTELLIGENCE.exists() else None
    engineering = json.loads(ENGINEERING.read_text(encoding="utf-8")) if ENGINEERING.exists() else None
    compact = {
        "source": source["source"],
        "scaling": source["scaling"],
        "static": source["static"],
        "transfer": source.get("transfer"),
        "intelligent": intelligence,
        "engineering": engineering,
        "dynamic": {
            "row_period_s": source["dynamic"]["row_period_s"],
            "channel_interval_s": source["dynamic"]["channel_interval_s"],
            "CH0_to_CH7_skew_s": source["dynamic"]["CH0_to_CH7_skew_s"],
            "results": [],
        },
    }
    for result in source["dynamic"]["results"]:
        trace = result["trace"]
        compact["dynamic"]["results"].append({
            "metrics": result["metrics"],
            "trace": {key: decimate(values) for key, values in trace.items()},
        })
    payload = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    TARGET.write_text("window.EXPERIMENT_DATA=" + payload + ";\n", encoding="utf-8")
    print(TARGET, len(payload), "bytes")

if __name__ == "__main__":
    main()
