"""F-60 golden corpus loader (P2-A).

A scenario = a committed snapshot fixture (`tests/golden/*.json`, M3
anonymization + schema_version) plus, where one exists, the recorded
legacy run of the same request (`tests/golden/legacy/<stem>_legacy.json`).
Corpus v1 (this package): G-01 (session 24379abd-derived, ids stripped)
+ the incident-derived variants g02…g04 built by
tests/golden/build_corpus_v1.py. P2-B expands to ≥ 12 scenarios (F-62).
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from typing import Any, Optional

from ..snapshot import load_golden, snapshot_hash
from ..types import FactSnapshot

LEGACY_DIRNAME = "legacy"


@dataclass
class Scenario:
    name: str
    path: str
    snapshot: FactSnapshot
    expect: list[dict[str, Any]]
    provenance: dict[str, Any]
    legacy_path: Optional[str]
    legacy_raw: Optional[dict[str, Any]]
    snapshot_hash: str

    @property
    def has_recording(self) -> bool:
        return self.legacy_raw is not None


def _legacy_path_for(corpus_dir: str, stem: str) -> Optional[str]:
    path = os.path.join(corpus_dir, LEGACY_DIRNAME, "%s_legacy.json" % stem)
    return path if os.path.exists(path) else None


def load_scenario(path: str, legacy_dir: Optional[str] = None) -> Scenario:
    snapshot, expect, provenance = load_golden(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    legacy_path = _legacy_path_for(
        legacy_dir or os.path.dirname(path), stem
    )
    legacy_raw: Optional[dict[str, Any]] = None
    if legacy_path:
        import json

        with open(legacy_path, "r", encoding="utf-8") as fh:
            legacy_raw = json.load(fh)
    return Scenario(
        name=stem,
        path=path,
        snapshot=snapshot,
        expect=expect,
        provenance=provenance,
        legacy_path=legacy_path,
        legacy_raw=legacy_raw,
        snapshot_hash=snapshot_hash(snapshot),
    )


def load_corpus(corpus_dir: Optional[str] = None) -> list[Scenario]:
    """All committed scenarios (snapshot fixtures) in the golden corpus.

    `build_*.py` scripts are builders, not scenarios; the legacy/
    subdirectory holds recordings, not snapshots. Order is by name so the
    report is stable (determinism applies to the harness too).
    """
    if corpus_dir is None:
        corpus_dir = default_corpus_dir()
    paths = sorted(
        p
        for p in glob.glob(os.path.join(corpus_dir, "*.json"))
        if not os.path.basename(p).startswith("~")
    )
    return [load_scenario(p) for p in paths]


def default_corpus_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    code_root = os.path.abspath(os.path.join(here, "..", "..", "..", ".."))
    return os.path.join(code_root, "tests", "golden")


def default_report_dir() -> str:
    """M6: reports live under DESIGN/Global CP-SAT/shadow/<date>/ (repo
    root sibling of the code root), retained ≥ 8 weeks."""
    import datetime

    here = os.path.dirname(os.path.abspath(__file__))
    code_root = os.path.abspath(os.path.join(here, "..", "..", "..", ".."))
    repo_root = os.path.abspath(os.path.join(code_root, ".."))
    stamp = datetime.date.today().isoformat()
    return os.path.join(repo_root, "DESIGN", "Global CP-SAT", "shadow", stamp)
