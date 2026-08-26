"""Generate a SIMULATED dataset for the dynamic (in-progress) drying model.

    *** THIS IS SYNTHETIC DATA. NO ROW HERE WAS MEASURED. ***

The initial-prediction dataset (fish_drying_oven_3000.csv) answers "how long
will this batch take?" before drying starts. This dataset answers a different
question: "given that drying has been running for N minutes and the batch now
weighs X, how much longer?"

That needs multiple observations per run, so a batch appears here as a
trajectory of rows sharing one run_id, sampled at successive elapsed times.

Consistency with the existing dataset
-------------------------------------
Everything physical is imported from generate_oven_dataset so the two datasets
describe the same oven: the same 12 species with the same thickness/fat
profiles, the same weight/humidity/temperature bands, the same drying-time
physics, and the same measured anchor (balaya 163 g / 100 C / 30 min).

How a run is simulated
----------------------
1. Draw a batch: species, weight, humidity, temperature - sampled from the
   same distributions the initial dataset uses.
2. Compute its *true* total drying time from the shared physics model, then
   perturb it. Real runs deviate from the physics ideal (oven hot spots,
   uneven loading, fish-to-fish variation), and that deviation is precisely
   what a dynamic model exists to correct for.
3. Compute the *initial predicted* time as the unperturbed physics estimate.
   The gap between predicted and actual is the error the model learns to close.
4. Walk the run forward in time. Moisture loss follows thin-layer exponential
   decay - fast at first, asymptotic later - toward TARGET_LOSS_FRACTION.
5. Add sensor noise to the recorded weight, and let temperature/humidity drift
   slightly during the run, as a real chamber does.

Assumptions worth knowing
-------------------------
* "Fully dried" is 65% weight loss, matching TARGET_WEIGHT_LOSS_PERCENT in
  drying_time_service.py.
* Exponential (thin-layer) moisture loss. Standard for hot-air drying of thin
  food samples, but a simplification: it ignores the constant-rate period some
  foods show early on.
* The physics is anchored to ONE real observation. Everything else - and every
  temperature above 100 C especially - is extrapolation.

Output: datasets/dynamic_drying_time_simulated.csv (grams / minutes).
Note the units: this CSV is in g/min for readability, while the FastAPI
service's inference contract is kg/hours. The training script converts.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_oven_dataset import (  # noqa: E402  (path set above)
    FISH_PROFILES,
    FISH_SAMPLE_WEIGHTS,
    REF_HUMIDITY,
    TEMP_MAX_C,
    TEMP_MIN_C,
    calibrate_base_rate,
    choose_temperature,
    drying_hours,
)

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "datasets" / "dynamic_drying_time_simulated.csv"

RANDOM_SEED = 4242
N_RUNS = 420                     # independent drying runs
OBS_PER_RUN = (4, 9)             # observations sampled per run (inclusive)

# Weight band, matching the initial dataset (0.090-0.265 kg).
WEIGHT_MIN_G = 90.0
WEIGHT_MAX_G = 265.0

# Humidity band, matching the initial dataset (19.3-42.0 %).
HUMIDITY_MIN = 19.0
HUMIDITY_MAX = 42.0

# "Fully dried" - keep in sync with TARGET_WEIGHT_LOSS_PERCENT in
# app/services/drying_time_service.py.
TARGET_LOSS_FRACTION = 0.65

# How far a real run drifts from the physics ideal (multiplicative, 1.0 = ideal).
ACTUAL_VS_PREDICTED_SIGMA = 0.13

# Exponential drying curve shape. Higher = more front-loaded moisture loss.
DECAY_SHARPNESS = 2.30

# Load-cell noise on a recorded weight, in grams (HX711 on this rig).
WEIGHT_NOISE_G = 0.4

# In-run drift of chamber conditions.
TEMP_DRIFT_SIGMA = 1.2
HUMIDITY_DRIFT_SIGMA = 1.5

# Never record an observation before this - a weight-loss rate computed over a
# few seconds is meaningless, and the service does not use one either.
MIN_ELAPSED_MIN = 3.0


def _sample_fish(rng: np.random.Generator) -> str:
    names = list(FISH_SAMPLE_WEIGHTS.keys())
    probs = np.array([FISH_SAMPLE_WEIGHTS[n] for n in names], dtype=float)
    return str(rng.choice(names, p=probs / probs.sum()))


def _loss_fraction_at(elapsed_min: float, total_min: float) -> float:
    """Fraction of the final moisture loss achieved by `elapsed_min`.

    Thin-layer exponential decay, normalised so the curve reaches exactly
    TARGET_LOSS_FRACTION at total_min rather than approaching it forever.
    """
    if total_min <= 0:
        return TARGET_LOSS_FRACTION
    progress = min(1.0, max(0.0, elapsed_min / total_min))
    shaped = (1.0 - np.exp(-DECAY_SHARPNESS * progress)) / (
        1.0 - np.exp(-DECAY_SHARPNESS)
    )
    return TARGET_LOSS_FRACTION * float(shaped)


def build_dataset() -> pd.DataFrame:
    rng = np.random.default_rng(RANDOM_SEED)
    base_rate = calibrate_base_rate()
    rows: list[dict] = []

    for run_index in range(N_RUNS):
        fish = _sample_fish(rng)
        profile = FISH_PROFILES[fish]

        initial_weight_g = float(rng.uniform(WEIGHT_MIN_G, WEIGHT_MAX_G))
        humidity = float(rng.uniform(HUMIDITY_MIN, HUMIDITY_MAX))
        temperature = choose_temperature(
            rng, profile["thickness"], profile["fat"], initial_weight_g / 1000.0
        )

        # The physics estimate: what the initial model would predict.
        predicted_hours = drying_hours(
            initial_weight_g / 1000.0,
            profile["thickness"],
            profile["fat"],
            temperature,
            humidity,
            base_rate,
        )
        predicted_min = predicted_hours * 60.0

        # The run's true duration deviates from that estimate.
        deviation = float(rng.normal(1.0, ACTUAL_VS_PREDICTED_SIGMA))
        deviation = float(np.clip(deviation, 0.70, 1.40))
        actual_min = max(MIN_ELAPSED_MIN + 1.0, predicted_min * deviation)

        n_obs = int(rng.integers(OBS_PER_RUN[0], OBS_PER_RUN[1] + 1))
        # Spread observations across the run, never past its end.
        fractions = np.sort(rng.uniform(0.05, 0.97, size=n_obs))
        run_id = f"RUN-{run_index + 1:04d}"
        # Weight must never rise within a run. Sensor noise alone can produce
        # that near the asymptote, where consecutive true weights differ by
        # less than the noise band - and a batch that gains weight while
        # drying is a contradiction to train on, not realism.
        previous_weight_g = float("inf")

        for obs_index, fraction in enumerate(fractions):
            elapsed_min = max(MIN_ELAPSED_MIN, float(fraction * actual_min))
            if elapsed_min >= actual_min:
                continue

            lost_fraction = _loss_fraction_at(elapsed_min, actual_min)
            true_current_g = initial_weight_g * (1.0 - lost_fraction)
            measured_g = true_current_g + float(rng.normal(0.0, WEIGHT_NOISE_G))
            # A scale never reads above the starting weight in a drying run,
            # and never above the previous observation of the same run.
            current_weight_g = float(min(measured_g, initial_weight_g, previous_weight_g))
            previous_weight_g = current_weight_g

            obs_temp = float(
                np.clip(
                    temperature + rng.normal(0.0, TEMP_DRIFT_SIGMA),
                    TEMP_MIN_C,
                    TEMP_MAX_C,
                )
            )
            obs_humidity = float(
                np.clip(
                    humidity + rng.normal(0.0, HUMIDITY_DRIFT_SIGMA),
                    0.0,
                    100.0,
                )
            )

            # Round the stored inputs first, then derive every dependent
            # column from those rounded values. Deriving from full precision
            # and rounding afterwards leaves the published CSV failing its own
            # arithmetic - at small elapsed times the divisor's rounding is
            # enough to shift the rate visibly.
            initial_r = round(initial_weight_g, 2)
            current_r = round(current_weight_g, 2)
            elapsed_r = round(elapsed_min, 2)
            actual_r = round(actual_min, 2)

            weight_loss_r = round(initial_r - current_r, 2)
            weight_loss_percentage = round(weight_loss_r / initial_r * 100.0, 3)
            weight_loss_rate = round(weight_loss_r / elapsed_r, 4)
            remaining_min = round(max(actual_r - elapsed_r, 0.0), 2)

            rows.append(
                {
                    "run_id": run_id,
                    "batch_id": f"SIM-{run_index + 1:04d}",
                    "observation_index": obs_index,
                    "fish_type": fish,
                    "initial_weight_g": initial_r,
                    "current_weight_g": current_r,
                    "temperature_c": round(obs_temp, 2),
                    "humidity_percent": round(obs_humidity, 2),
                    "elapsed_time_min": elapsed_r,
                    "weight_loss_g": weight_loss_r,
                    "weight_loss_percentage": weight_loss_percentage,
                    "weight_loss_rate_g_per_min": weight_loss_rate,
                    "initial_predicted_total_time_min": round(predicted_min, 2),
                    "actual_total_drying_time_min": actual_r,
                    "remaining_drying_time_min": remaining_min,
                }
            )

    return pd.DataFrame(rows)


def validate(df: pd.DataFrame) -> list[str]:
    """Check the derived columns really follow their definitions."""
    problems: list[str] = []

    def check(name: str, mask: pd.Series) -> None:
        count = int(mask.sum())
        if count:
            problems.append(f"{name}: {count} row(s)")

    loss = df.initial_weight_g - df.current_weight_g
    check("weight_loss_g inconsistent", (loss - df.weight_loss_g).abs() > 0.011)
    pct = loss / df.initial_weight_g * 100.0
    check("weight_loss_percentage inconsistent", (pct - df.weight_loss_percentage).abs() > 0.011)
    rate = loss / df.elapsed_time_min
    check("weight_loss_rate inconsistent", (rate - df.weight_loss_rate_g_per_min).abs() > 0.011)
    remaining = (df.actual_total_drying_time_min - df.elapsed_time_min).clip(lower=0.0)
    check("remaining_drying_time inconsistent", (remaining - df.remaining_drying_time_min).abs() > 0.011)

    check("negative remaining time", df.remaining_drying_time_min < 0)
    check("current weight exceeds initial", df.current_weight_g > df.initial_weight_g)
    check("elapsed exceeds actual total", df.elapsed_time_min > df.actual_total_drying_time_min)
    check("non-positive elapsed", df.elapsed_time_min <= 0)
    check("negative weight loss", df.weight_loss_g < 0)
    check("weight loss beyond target", df.weight_loss_percentage > TARGET_LOSS_FRACTION * 100.0 + 1.0)

    # Within a run, weight must fall (or hold) as elapsed time increases.
    for run_id, group in df.groupby("run_id"):
        ordered = group.sort_values("elapsed_time_min")
        if (ordered.current_weight_g.diff().dropna() > 0).any():
            problems.append(f"weight increased within run {run_id}")
            break

    return problems


def main() -> None:
    df = build_dataset()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)

    print(f"Wrote {len(df)} rows across {df.run_id.nunique()} runs -> {OUT_PATH.relative_to(ROOT)}")
    print("*** SIMULATED DATA - not measured. See module docstring. ***\n")

    problems = validate(df)
    if problems:
        print("VALIDATION FAILED:")
        for p in problems:
            print("  -", p)
    else:
        print("Validation passed: all derived formulas consistent, no impossible values.")

    print()
    print("observations per run : %d - %d (mean %.1f)" % (
        df.groupby("run_id").size().min(),
        df.groupby("run_id").size().max(),
        df.groupby("run_id").size().mean(),
    ))
    for col in [
        "initial_weight_g", "current_weight_g", "temperature_c", "humidity_percent",
        "elapsed_time_min", "weight_loss_percentage", "weight_loss_rate_g_per_min",
        "actual_total_drying_time_min", "remaining_drying_time_min",
    ]:
        print("%-32s %8.2f  %8.2f  %8.2f" % (col, df[col].min(), df[col].mean(), df[col].max()))


if __name__ == "__main__":
    main()
