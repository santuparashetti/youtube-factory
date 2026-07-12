#!/usr/bin/env python3
"""
Enforce the import direction rule:
    Allowed:    ytfactory  ->  video_core
    Forbidden:  video_core ->  ytfactory

Exits with code 1 and prints violations if any file under src/video_core/
imports from ytfactory, EXCEPT for the known Bucket-C dependencies listed
below (deferred to Phase 2 — WORKSPACE_DIR move).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
VIDEO_CORE = ROOT / "src" / "video_core"

IMPORT_PATTERN = re.compile(r"(?:from|import)\s+(ytfactory\b[^\s]*)")

# Bucket C items not yet moved — tracked here so any NEW violation is caught.
# Remove entries from this list as each phase resolves them.
# ytfactory.config.settings resolved by Phase 1 (SharedSettings extraction).
KNOWN_BUCKET_C = {
    "ytfactory.shared.constants",  # WORKSPACE_DIR — Phase 2
}

violations = []
for py_file in VIDEO_CORE.rglob("*.py"):
    if "__pycache__" in py_file.parts:
        continue
    for lineno, line in enumerate(py_file.read_text().splitlines(), 1):
        m = IMPORT_PATTERN.search(line)
        if m:
            module = m.group(1).split()[0]
            if not any(module.startswith(known) for known in KNOWN_BUCKET_C):
                violations.append(f"{py_file.relative_to(ROOT)}:{lineno}: {line.strip()}")

if violations:
    print("LAYERING VIOLATION — video_core must not import from ytfactory:")
    for v in violations:
        print(f"  {v}")
    sys.exit(1)

print(
    f"OK — no new layering violations in {VIDEO_CORE.relative_to(ROOT)} "
    f"({sum(1 for _ in VIDEO_CORE.rglob('*.py'))} files checked). "
    f"Known Bucket-C deps still open: {sorted(KNOWN_BUCKET_C)}"
)
