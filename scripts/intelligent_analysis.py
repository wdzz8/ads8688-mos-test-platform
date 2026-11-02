"""Build an exploratory TinyML and adaptive-sampling report from real experiment data.

The model is deliberately small and deterministic. It is a planning aid only:
it never changes the accepted measurement rows or replaces hardware limits.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "demo" / "data" / "experiment_analysis.json"
DEFAULT_OUTPUT = ROOT / "demo" / "data" / "intelligent_analysis.json"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def fit_tiny_mlp(x: np.ndarray, y: np.ndarray, *, seed: int, steps: int = 1800):
    """Fit a small 2-8-1 tanh network with deterministic gradient descent."""
    mean_x = x.mean(axis=0)
    scale_x = x.std(axis=0)
    scale_x[scale_x == 0] = 1.0
    mean_y = float(y.mean())
    scale_y = float(y.std()) or 1.0
    xn = (x - mean_x) / scale_x
    yn = (y - mean_y) / scale_y

    rng = np.random.default_rng(seed)
    w1 = rng.normal(0.0, 0.30, (x.shape[1], 8))
    b1 = np.zeros(8)
    w2 = rng.normal(0.0, 0.30, (8, 1))
    b2 = 0.0
    rate = 0.01
    regularization = 1e-3
    for _ in range(steps):
        hidden = np.tanh(xn @ w1 + b1)
        prediction = (hidden @ w2).ravel() + b2
        error = prediction - yn
        grad_output = 2.0 * error / len(xn)
        grad_w2 = hidden.T @ grad_output[:, None] + regularization * w2
        grad_b2 = float(grad_output.sum())
        grad_hidden = (grad_output[:, None] @ w2.T) * (1.0 - hidden * hidden)
        grad_w1 = xn.T @ grad_hidden + regularization * w1
        grad_b1 = grad_hidden.sum(axis=0)
        w1 -= rate * grad_w1
        b1 -= rate * grad_b1
        w2 -= rate * grad_w2
        b2 -= rate * grad_b2
    return {
        "mean_x": mean_x,
        "scale_x": scale_x,
        "mean_y": mean_y,
        "scale_y": scale_y,
        "w1": w1,
        "b1": b1,
        "w2": w2,
        "b2": b2,
    }


def predict(model, x: np.ndarray) -> np.ndarray:
    xn = (x - model["mean_x"]) / model["scale_x"]
    hidden = np.tanh(xn @ model["w1"] + model["b1"])
    return (hidden @ model["w2"] + model["b2"]).ravel() * model["scale_y"] + model["mean_y"]


def collect_static(data):
    rows = []
    for curve in data["static"]["curves"]:
        for point in curve["points"]:
            rows.append(
                {
                    "VGS_V": float(curve["VGS_V"]),
                    "VDS_V": float(point["VDS_V"]),
                    "ID_mA": float(point["ID_mA"]),
                    "repeat_SD_mA": float(point["repeat_SD_mA"]),
                    "held_out_prediction_mA": float(point["held_out_prediction_mA"]),
                }
            )
    return rows


def tiny_mlp_report(rows):
    x = np.array([[r["VGS_V"], r["VDS_V"]] for r in rows], dtype=float)
    y = np.array([r["ID_mA"] for r in rows], dtype=float)
    full = fit_tiny_mlp(x, y, seed=20261103)
    train_prediction = predict(full, x)
    loo_prediction = []
    for index in range(len(rows)):
        keep = np.arange(len(rows)) != index
        fold = fit_tiny_mlp(x[keep], y[keep], seed=20261103 + index, steps=1500)
        loo_prediction.append(float(predict(fold, x[index : index + 1])[0]))
    loo_prediction = np.array(loo_prediction)
    details = []
    for row, prediction in zip(rows, loo_prediction):
        details.append(
            {
                "VGS_V": row["VGS_V"],
                "VDS_V": row["VDS_V"],
                "ID_mA": row["ID_mA"],
                "tiny_mlp_loo_prediction_mA": float(prediction),
                "tiny_mlp_loo_abs_error_mA": float(abs(prediction - row["ID_mA"])),
            }
        )
    return {
        "method": "2-8-1 tanh TinyMLP, deterministic NumPy gradient descent",
        "training_rows": len(rows),
        "train_RMSE_mA": float(np.sqrt(np.mean((train_prediction - y) ** 2))),
        "leave_one_out_RMSE_mA": float(np.sqrt(np.mean((loo_prediction - y) ** 2))),
        "used_for_measurement_acceptance": False,
        "scope": "Exploratory regression and next-point planning; accepted rows still use hardware and rule-based gates.",
        "points": details,
    }


def adaptive_plan(data, rows):
    """Recommend two extra VDS points per curve using residual and slope change."""
    plans = []
    for curve in data["static"]["curves"]:
        points = sorted(curve["points"], key=lambda p: p["VDS_V"])
        if len(points) < 3:
            continue
        vds = np.array([p["VDS_V"] for p in points], dtype=float)
        ids = np.array([p["ID_mA"] for p in points], dtype=float)
        residual = np.abs(ids - np.array([p["held_out_prediction_mA"] for p in points]))
        residual_scale = float(np.median(residual) + 1e-6)
        slopes = np.diff(ids) / np.maximum(np.diff(vds), 1e-6)
        candidates = []
        for i in range(len(vds) - 1):
            midpoint = float((vds[i] + vds[i + 1]) / 2.0)
            curvature = abs(float(slopes[i + 1] - slopes[i])) if i + 1 < len(slopes) else abs(float(slopes[i]))
            local_residual = float((residual[i] + residual[i + 1]) / (2.0 * residual_scale))
            score = curvature + local_residual
            candidates.append(
                {
                    "VGS_V": float(curve["VGS_V"]),
                    "recommended_VDS_V": midpoint,
                    "priority_score": float(score),
                    "reason": "局部斜率变化 + 留一残差较大",
                }
            )
        candidates.sort(key=lambda item: item["priority_score"], reverse=True)
        chosen = []
        for candidate in candidates:
            if all(abs(candidate["recommended_VDS_V"] - item["recommended_VDS_V"]) > 0.15 for item in chosen):
                chosen.append(candidate)
            if len(chosen) == 2:
                break
        plans.extend(chosen)
    return {
        "strategy": "coarse-to-fine residual-guided VDS planning",
        "current_points_per_curve": 7,
        "recommended_extra_points": plans,
        "hardware_run_completed": False,
        "scope": "Planning suggestions only; they must be verified by a new real acquisition before being reported as measurements.",
    }


def build_report(data):
    rows = collect_static(data)
    mlp = tiny_mlp_report(rows)
    return {
        "source": "Real PCB1 experiment_analysis.json; no synthetic measurement rows",
        "quality_summary": {
            "static_valid_rows": int(data["static"]["valid_rows"]),
            "dynamic_valid_rows": int(sum(item["metrics"]["valid_rows"] for item in data["dynamic"]["results"])),
            "transfer_points": int(len(data.get("transfer", {}).get("points", []))),
        },
        "device_profile": {
            "VGS_at_1mA_V": data.get("transfer", {}).get("VGS_at_1mA_V"),
            "max_gm_mS": data.get("transfer", {}).get("max_gm_mS"),
            "profile_type": "single measured 2N7000 run; nominal current scale",
        },
        "tiny_mlp": mlp,
        "adaptive_plan": adaptive_plan(data, rows),
        "boundary": "The intelligence layer assists analysis and test planning. It does not replace FPGA quality gates, DPS readback, calibration, or safety protection.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    data = read_json(args.source)
    report = build_report(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "tiny_mlp_train_RMSE_mA": report["tiny_mlp"]["train_RMSE_mA"],
        "tiny_mlp_loo_RMSE_mA": report["tiny_mlp"]["leave_one_out_RMSE_mA"],
        "recommended_extra_points": len(report["adaptive_plan"]["recommended_extra_points"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
