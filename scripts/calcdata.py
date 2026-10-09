"""Shared helpers for the two calculation-data files: load, validate, write. Standard library only.

- calculation.json: prayer-method parameters (a few KB, read at app start).
- magnetic-model.json: NOAA's World Magnetic Model for the Qibla compass (~400 KB for WMMHR).

Kept apart so the app starts without reading the big model, and so a method change never makes
phones re-download the model (each file has its own ETag). The checks here mirror the app's own
(CalculationDataParser.kt) - the app re-checks everything, but a file that fails here is never
committed in the first place.
"""
import json
import math
import os
import re

import wmm as wmm_model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METHODS_PATH = os.path.join(ROOT, "calculation.json")
MODEL_PATH = os.path.join(ROOT, "magnetic-model.json")
SCHEMA_VERSION = 1
# The app's caps: methods file 64 KB, model file 1.5 MB (room for the degree-133 WMMHR).
MAX_BYTES = {METHODS_PATH: 64 * 1024, MODEL_PATH: 1536 * 1024}

# PrayerCalculationSource names in the app (AUTO excluded). A key outside this set is ignored by
# the app, so it is refused here.
KNOWN_METHOD_KEYS = {
    "MUSLIM_WORLD_LEAGUE", "EGYPTIAN", "KARACHI", "UMM_AL_QURA", "DUBAI", "QATAR", "KUWAIT",
    "SINGAPORE", "NORTH_AMERICA", "TURKEY", "JAKIM", "KEMENAG",
}
ADJUSTMENT_KEYS = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump(data):
    """Pretty JSON, except that number-only arrays (coefficient and test-value rows) stay on one
    line each - one row per line keeps the file small and its diffs readable."""
    text = json.dumps(data, indent=2, ensure_ascii=False)
    text = re.sub(
        r"\[\s*(-?[0-9][-0-9.eE+]*(?:,\s*-?[0-9][-0-9.eE+]*)*)\s*\]",
        lambda m: "[" + ", ".join(v.strip() for v in m.group(1).split(",")) + "]",
        text,
    )
    return text + "\n"


def write(path, data):
    errors = validate(path, data)
    if errors:
        raise SystemExit(f"refusing to write an invalid {os.path.basename(path)}:\n  " + "\n  ".join(errors))
    with open(path, "w", encoding="utf-8") as f:
        f.write(dump(data))


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate(path, data):
    """Every problem with [data] (the file at [path]) as a list of messages; empty means valid."""
    errors = []
    limit = MAX_BYTES[path]
    if len(dump(data).encode()) > limit:
        errors.append(f"file is over {limit} bytes")
    if data.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(f"schemaVersion must be {SCHEMA_VERSION}")

    if path == MODEL_PATH:
        if set(data) - {"schemaVersion", "wmm"}:
            errors.append("magnetic-model.json holds only schemaVersion and wmm")
        if "wmm" not in data:
            errors.append("magnetic-model.json needs a wmm model")
    elif set(data) - {"schemaVersion", "methods"}:
        errors.append("calculation.json holds only schemaVersion and methods")

    w = data.get("wmm")
    if w is not None:
        try:
            if not (2020 <= w["epoch"] <= 2100):
                errors.append("wmm.epoch out of range")
            rows = w["coefficients"]
            degree = max(r[0] for r in rows)
            expected = {(n, m) for n in range(1, degree + 1) for m in range(n + 1)}
            got = [(r[0], r[1]) for r in rows]
            if not 12 <= degree <= 200:
                errors.append("wmm degree must be 12..200")
            elif len(got) != len(expected) or set(got) != expected:
                errors.append(f"wmm.coefficients must hold exactly one row for every n=1..{degree}, m=0..n")
            if not all(len(r) == 6 and all(_finite(v) for v in r[2:]) for r in rows):
                errors.append("wmm.coefficients rows must be [n, m, g, h, gDot, hDot] numbers")
            if not errors and not wmm_model.reproduces(w):
                errors.append("wmm does not reproduce its own NOAA test values")
        except (KeyError, TypeError, IndexError, ValueError) as e:
            errors.append(f"wmm is malformed: {e!r}")

    for key, m in (data.get("methods") or {}).items():
        where = f"methods.{key}"
        if key not in KNOWN_METHOD_KEYS:
            errors.append(f"{where}: unknown method key")
            continue
        if not isinstance(m, dict) or not m:
            errors.append(f"{where}: must be a non-empty object")
            continue
        for angle in ("fajrAngle", "ishaAngle"):
            if angle in m and not (_finite(m[angle]) and 0 <= m[angle] <= 25):
                errors.append(f"{where}.{angle} must be 0..25 degrees")
        if "ishaInterval" in m and not (isinstance(m["ishaInterval"], int) and 0 <= m["ishaInterval"] <= 150):
            errors.append(f"{where}.ishaInterval must be an integer 0..150 minutes")
        adj = m.get("adjustments")
        if adj is not None:
            if not isinstance(adj, dict) or set(adj) - set(ADJUSTMENT_KEYS):
                errors.append(f"{where}.adjustments has unknown keys")
            elif not all(isinstance(v, int) and -30 <= v <= 30 for v in adj.values()):
                errors.append(f"{where}.adjustments must be integers within +/-30 minutes")
        unknown = set(m) - {"fajrAngle", "ishaAngle", "ishaInterval", "adjustments"}
        if unknown:
            errors.append(f"{where}: unknown fields {sorted(unknown)}")
    return errors
