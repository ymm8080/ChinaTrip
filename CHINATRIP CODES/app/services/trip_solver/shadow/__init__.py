"""Shadow evaluation harness (F-60/F-61/F-62, P2-A).

Offline batch replay of the committed golden corpus through both engines:
the legacy side consumes recorded runs (`tests/golden/legacy/`), the
model side solves live, twice, deterministically. Reports land under
`DESIGN/Global CP-SAT/shadow/` (audit M6). See `__main__.py` for the CLI.
"""
