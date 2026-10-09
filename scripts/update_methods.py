"""Brings calculation.json's prayer-method parameters in line with the Aladhan methods catalogue.

Aladhan (api.aladhan.com/v1/methods) is the widely used public catalogue of the calculation
authorities' twilight angles and intervals. For each authority the app knows, its Fajr angle and
its Isha angle or interval are copied in; nothing else in the file is touched (per-prayer minute
adjustments stay as they are). Prints what changed; writes `changes.md` for the workflow when a
change is large enough to be worth a human glance. Non-zero exit on any failure.
"""
import json
import os
import re
import sys
import urllib.request

import calcdata

URL = "https://api.aladhan.com/v1/methods"
HEADERS = {"User-Agent": "islam-habits-content-updater (+https://github.com/coded-dreams/islam-habits-content)"}

# Aladhan key -> the app's PrayerCalculationSource name.
ALADHAN_TO_APP = {
    "MWL": "MUSLIM_WORLD_LEAGUE",
    "ISNA": "NORTH_AMERICA",
    "EGYPT": "EGYPTIAN",
    "MAKKAH": "UMM_AL_QURA",
    "KARACHI": "KARACHI",
    "DUBAI": "DUBAI",
    "QATAR": "QATAR",
    "KUWAIT": "KUWAIT",
    "SINGAPORE": "SINGAPORE",
    "TURKEY": "TURKEY",
    "JAKIM": "JAKIM",
    "KEMENAG": "KEMENAG",
}
# A change at least this big is still applied, but also reported for a human to see.
NOTABLE_ANGLE_DEGREES = 1.0
NOTABLE_INTERVAL_MINUTES = 5


def parse_isha(value):
    """Aladhan gives Isha as an angle (17.5) or an interval ("90 min")."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"ishaAngle": float(value), "ishaInterval": 0}
    match = re.fullmatch(r"\s*(\d+)\s*min\s*", str(value))
    if match:
        return {"ishaInterval": int(match.group(1))}
    raise ValueError(f"unrecognised Isha value {value!r}")


def main():
    with urllib.request.urlopen(urllib.request.Request(URL, headers=HEADERS), timeout=60) as r:
        payload = json.load(r)
    if payload.get("code") != 200:
        raise SystemExit(f"Aladhan returned code {payload.get('code')}")
    catalogue = payload["data"]

    data = calcdata.load(calcdata.METHODS_PATH)
    methods = data.setdefault("methods", {})
    changes, notable = [], []
    for aladhan_key, app_key in ALADHAN_TO_APP.items():
        params = (catalogue.get(aladhan_key) or {}).get("params") or {}
        if "Fajr" not in params or "Isha" not in params:
            notable.append(f"- {app_key}: Aladhan no longer lists Fajr/Isha for {aladhan_key}; left unchanged")
            continue
        incoming = {"fajrAngle": float(params["Fajr"]), **parse_isha(params["Isha"])}
        current = methods.get(app_key, {})
        merged = {**current, **incoming}
        if "ishaInterval" in incoming and incoming["ishaInterval"] > 0:
            merged.pop("ishaAngle", None)
        if merged == current:
            continue
        for field in ("fajrAngle", "ishaAngle", "ishaInterval"):
            before, after = current.get(field), merged.get(field)
            if before == after:
                continue
            changes.append(f"- {app_key}.{field}: {before} -> {after}")
            if before is not None and after is not None:
                limit = NOTABLE_INTERVAL_MINUTES if field == "ishaInterval" else NOTABLE_ANGLE_DEGREES
                if abs(after - before) >= limit:
                    notable.append(f"- {app_key}.{field}: {before} -> {after}")
        methods[app_key] = merged

    if not changes:
        print("Methods already current")
        return
    calcdata.write(calcdata.METHODS_PATH, data)
    print("Methods updated:\n" + "\n".join(changes))
    if notable:
        with open(os.path.join(calcdata.ROOT, "changes.md"), "w", encoding="utf-8") as f:
            f.write("The weekly method sync applied these notable changes:\n\n" + "\n".join(notable) + "\n")


if __name__ == "__main__":
    main()
