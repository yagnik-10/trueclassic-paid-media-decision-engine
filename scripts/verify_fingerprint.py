#!/usr/bin/env python
"""Print and VERIFY the full-artifact fingerprint against the pinned value.

    python scripts/verify_fingerprint.py

Prints both the canonical-tables fingerprint and the (primary) full-artifact
fingerprint, then verifies the full-artifact fingerprint matches the value pinned
in the regression test. Exits non-zero on any mismatch.
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
)


def main() -> int:
    m = build_manifest(generate())
    canonical = m["canonical_tables_fingerprint"]
    full = m["full_artifact_fingerprint"]
    print(f"canonical-tables fingerprint: {canonical}")
    print(f"full-artifact fingerprint:    {full}  (PRIMARY)")

    ok = True
    if canonical != EXPECTED_CANONICAL_TABLES_FINGERPRINT:
        print(f"  MISMATCH canonical: expected {EXPECTED_CANONICAL_TABLES_FINGERPRINT}")
        ok = False
    if full != EXPECTED_FULL_ARTIFACT_FINGERPRINT:
        print(f"  MISMATCH full-artifact: expected {EXPECTED_FULL_ARTIFACT_FINGERPRINT}")
        ok = False
    print("VERIFIED: full-artifact fingerprint matches pinned value" if ok else "FINGERPRINT MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
