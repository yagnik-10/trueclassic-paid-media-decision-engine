#!/usr/bin/env python
"""Print and VERIFY the pinned full-artifact fingerprints. Exits non-zero on mismatch.

    python scripts/verify_fingerprint.py

Verifies BOTH deterministic profiles against their pinned values, independent of
the runtime default:
  - golden    : the regression BENCHMARK anchor (the test suite pins to it),
  - realistic : the PRIMARY data the engine/API/report use by default (D-035).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.decision_engine.synth.generator import generate  # noqa: E402
from backend.decision_engine.synth.manifest import build_manifest  # noqa: E402
from tests.test_fingerprints import (  # noqa: E402
    EXPECTED_CANONICAL_TABLES_FINGERPRINT,
    EXPECTED_FULL_ARTIFACT_FINGERPRINT,
    EXPECTED_REALISTIC_CANONICAL_TABLES_FINGERPRINT,
    EXPECTED_REALISTIC_FULL_ARTIFACT_FINGERPRINT,
)

_PINS = {
    "realistic (PRIMARY)": (EXPECTED_REALISTIC_CANONICAL_TABLES_FINGERPRINT,
                            EXPECTED_REALISTIC_FULL_ARTIFACT_FINGERPRINT),
    "golden (benchmark)": (EXPECTED_CANONICAL_TABLES_FINGERPRINT,
                           EXPECTED_FULL_ARTIFACT_FINGERPRINT),
}


def main() -> int:
    ok = True
    for label, (exp_canon, exp_full) in _PINS.items():
        profile = label.split()[0]
        m = build_manifest(generate(profile=profile))
        canonical, full = m["canonical_tables_fingerprint"], m["full_artifact_fingerprint"]
        print(f"[{label}]")
        print(f"  canonical-tables fingerprint: {canonical}")
        print(f"  full-artifact fingerprint:    {full}")
        if canonical != exp_canon:
            print(f"  MISMATCH canonical: expected {exp_canon}")
            ok = False
        if full != exp_full:
            print(f"  MISMATCH full-artifact: expected {exp_full}")
            ok = False
    print("VERIFIED: both profiles match pinned values" if ok else "FINGERPRINT MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
