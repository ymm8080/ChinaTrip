"""Input adapters for the trip-level solver (P1-B).

Design refs: cpsat_design_functions_2026-11-17.md — F-11 travel matrix,
F-12 hours/entry caps, F-13 weather, F-14 access intervals, F-15 duration
tiers (Q1), audit M4/M14.

Boundary rule (audit M2): these adapters import read-only pure helpers from
app.services.itinerary.* only; no DB/network I/O here.
"""
