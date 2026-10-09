"""Validates calculation.json and magnetic-model.json. Exit code 1 (and the problems listed) if
either is invalid."""
import os
import sys

import calcdata

failed = False
for path in (calcdata.METHODS_PATH, calcdata.MODEL_PATH):
    name = os.path.basename(path)
    errors = calcdata.validate(path, calcdata.load(path))
    if errors:
        failed = True
        print(f"{name} is invalid:")
        for e in errors:
            print("  -", e)
    else:
        print(f"{name} is valid")
sys.exit(1 if failed else 0)
