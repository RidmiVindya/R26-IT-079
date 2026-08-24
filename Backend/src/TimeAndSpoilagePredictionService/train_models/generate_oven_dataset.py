"""Generate a physics-based oven-drying dataset for the initial prediction model.

Anchored to a real measured run:

    Balaya, 163 g, 100 C, 30 minutes -> properly dried

That single observation calibrates the model below; everything else is derived
from drying physics, so treat this data as *modelled*, not measured. Replace it
with real logged runs as they become available.

Physics used
------------
Thin-layer hot-air drying. Time to reach the target moisture loss scales with:

  * mass / thickness   - a thicker piece dries slower than a thin one of the
                         same mass, so fish shape matters, not just weight.
  * fat content        - fat impedes moisture diffusion (oily fish dry slower).
  * temperature        - roughly Arrhenius-like: hotter air removes moisture
                         faster, with diminishing returns.
  * ambient humidity   - humid air has less capacity to absorb moisture.

Temperature is chosen per batch (not constant): heavier/fattier/thicker fish
get more heat, capped to the safe operating band.

Outputs datasets/fish_drying_oven_3000.csv with the same columns the training
script expects.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "datasets" / "fish_drying_oven_3000.csv"

RANDOM_SEED = 42
N_ROWS = 3000

# --- Safe operating band (keep in sync with config.MAX_DRYING_TEMPERATURE_C) --
TEMP_MIN_C = 80.0
TEMP_MAX_C = 110.0

# --- Measured anchor ---------------------------------------------------------
ANCHOR_FISH = "balaya"
ANCHOR_WEIGHT_KG = 0.163
ANCHOR_TEMP_C = 100.0
ANCHOR_HOURS = 0.5  # 30 minutes

# --- Per-species drying character -------------------------------------------
# thickness: relative cross-section (thicker = slower moisture escape)
# fat:       relative oil content   (fattier = slower moisture diffusion)
# Values are relative to balaya (the anchor species) at 1.00.
FISH_PROFILES = {
    "sprats":    {"thickness": 0.55, "fat": 0.80},
    "salaya":    {"thickness": 0.70, "fat": 0.95},
    "hurulla":   {"thickness": 0.80, "fat": 0.90},
    "kumbalawa": {"thickness": 0.85, "fat": 0.85},
    "linna":     {"thickness": 0.90, "fat": 0.80},
    "balaya":    {"thickness": 1.00, "fat": 1.00},
    "paraw":     {"thickness": 1.05, "fat": 0.90},
    "mackerel":  {"thickness": 1.10, "fat": 1.20},
    "kelawalla": {"thickness": 1.15, "fat": 1.05},
    "tuna":      {"thickness": 1.20, "fat": 1.15},
    "thalapath": {"thickness": 1.25, "fat": 0.95},
    "mora":      {"thickness": 1.30, "fat": 1.10},
}

# Sampling weights so the mix resembles a real catch (small fish dominate).
FISH_SAMPLE_WEIGHTS = {
    "sprats": 0.16, "salaya": 0.13, "hurulla": 0.10, "mackerel": 0.09,
    "linna": 0.09, "balaya": 0.09, "paraw": 0.08, "tuna": 0.07,
    "kumbalawa": 0.07, "kelawalla": 0.05, "thalapath": 0.05, "mora": 0.02,
}

# Reference conditions the base rate is defined at.
REF_HUMIDITY = 33.0

# Physics coefficients.
MASS_EXPONENT = 0.62        # sub-linear: mass doubles -> time < doubles
THICKNESS_EXPONENT = 0.85   # thickness dominates diffusion path length
FAT_EXPONENT = 0.45
TEMP_REF_C = 100.0
TEMP_SENSITIVITY = 1.35     # how strongly hotter air shortens drying
HUMIDITY_SENSITIVITY = 0.35


def choose_temperature(rng, thickness: float, fat: float, weight_kg: float) -> float:
    """Pick a drying temperature: denser/fattier/heavier fish need more heat."""
    load = (
        0.45 * (thickness - 1.0)
        + 0.30 * (fat - 1.0)
        + 0.90 * (weight_kg - ANCHOR_WEIGHT_KG) / ANCHOR_WEIGHT_KG
    )
    temperature = ANCHOR_TEMP_C + load * 18.0
    temperature += rng.normal(0.0, 2.5)  # operator/session variation
    temperature = float(np.clip(temperature, TEMP_MIN_C, TEMP_MAX_C))
    return round(temperature * 2) / 2  # oven dials move in 0.5 C steps


def drying_hours(
    weight_kg: float,
    thickness: float,
    fat: float,
    temperature_c: float,
    humidity_percent: float,
    base_rate: float,
) -> float:
    """Thin-layer drying time from the calibrated base rate."""
    mass_term = (weight_kg / ANCHOR_WEIGHT_KG) ** MASS_EXPONENT
    thickness_term = thickness ** THICKNESS_EXPONENT
    fat_term = fat ** FAT_EXPONENT
    temp_term = (TEMP_REF_C / temperature_c) ** TEMP_SENSITIVITY
    humidity_term = (humidity_percent / REF_HUMIDITY) ** HUMIDITY_SENSITIVITY
    return base_rate * mass_term * thickness_term * fat_term * temp_term * humidity_term


def calibrate_base_rate() -> float:
    """Solve for the base rate that reproduces the measured anchor run."""
    profile = FISH_PROFILES[ANCHOR_FISH]
    unit = drying_hours(
        ANCHOR_WEIGHT_KG,
        profile["thickness"],
        profile["fat"],
        ANCHOR_TEMP_C,
        REF_HUMIDITY,
        base_rate=1.0,
    )
    return ANCHOR_HOURS / unit


def main() -> None:
    rng = np.random.default_rng(RANDOM_SEED)
    base_rate = calibrate_base_rate()

    species = list(FISH_SAMPLE_WEIGHTS)
    probs = np.array([FISH_SAMPLE_WEIGHTS[s] for s in species], dtype=float)
    probs /= probs.sum()

    rows = []
    for i in range(N_ROWS):
        fish = str(rng.choice(species, p=probs))
        profile = FISH_PROFILES[fish]

        # Oven-scale sample, centred near the anchor weight.
        weight = float(np.clip(rng.normal(0.170, 0.030), 0.090, 0.265))
        humidity = float(np.clip(rng.normal(33.0, 4.4), 18.0, 42.0))
        # MQ-136 is freshness context, not a drying driver; keep it realistic.
        mq136 = int(np.clip(rng.gamma(shape=3.0, scale=75.0), 0, 900))

        temperature = choose_temperature(
            rng, profile["thickness"], profile["fat"], weight
        )
        hours = drying_hours(
            weight, profile["thickness"], profile["fat"],
            temperature, humidity, base_rate,
        )
        # Run-to-run variation (loading, airflow, piece size spread).
        hours *= float(rng.normal(1.0, 0.06))
        hours = float(np.clip(hours, 0.15, 1.25))

        rows.append({
            "batch_id": f"FD-{20250201 + i // 12}-{i % 12 + 1:02d}",
            "fish_type": fish,
            "initial_weight_kg": round(weight, 3),
            "humidity_percent": round(humidity, 1),
            "mq136_value": mq136,
            "recommended_temperature_c": temperature,
            "estimated_total_drying_time_hours": round(hours, 4),
        })

    df = pd.DataFrame(rows)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)

    print(f"Wrote {len(df)} rows -> {OUT_PATH.relative_to(ROOT)}")
    print(f"base_rate calibrated to {base_rate:.5f}")
    print()
    print("temperature_c      :", round(df["recommended_temperature_c"].min(), 1),
          "-", round(df["recommended_temperature_c"].max(), 1),
          f"(unique={df['recommended_temperature_c'].nunique()})")
    print("drying minutes     :",
          round(df["estimated_total_drying_time_hours"].min() * 60, 1), "-",
          round(df["estimated_total_drying_time_hours"].max() * 60, 1),
          f"(mean={df['estimated_total_drying_time_hours'].mean() * 60:.1f})")

    anchor = FISH_PROFILES[ANCHOR_FISH]
    check = drying_hours(
        ANCHOR_WEIGHT_KG, anchor["thickness"], anchor["fat"],
        ANCHOR_TEMP_C, REF_HUMIDITY, base_rate,
    )
    print()
    print(f"anchor check: {ANCHOR_FISH} {ANCHOR_WEIGHT_KG*1000:.0f}g @ "
          f"{ANCHOR_TEMP_C}C -> {check*60:.1f} min (measured {ANCHOR_HOURS*60:.0f} min)")


if __name__ == "__main__":
    main()
