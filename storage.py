"""
storage.py
==========
JSON-file persistence for the Body Fat Tracker, with schema versioning and
automatic migration from the older single-unit-system format.

Schema v2 (current) stores every measurement as its own {"value", "unit"}
pair, so a single entry can freely mix imperial and metric units field by
field (e.g. height in cm, weight in lb, waist in in, hip in cm). Alongside
the raw entered values, a "canonical" block stores everything pre-converted
to inches/lb, which is what the calculators and history graphs consume --
this keeps unit-mixing invisible to the rest of the app and means the raw
user-entered values are never lost or silently rewritten.

Schema v1 (legacy) entries -- a single top-level "unit_system" field plus
flat numeric height/weight/measurements -- are transparently upgraded to v2
the first time they're loaded. A one-time backup of the pre-migration file
is written next to the data file so nothing is ever lost in the upgrade.
"""

import json
import os

import calculators as calc

SCHEMA_VERSION = 2

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bodyfat_history.json")
BACKUP_FILE = DATA_FILE + ".v1backup.json"

ALL_MEASUREMENT_KEYS = (
    "neck", "chest", "shoulders", "waist", "hip", "thigh", "knee", "ankle",
    "biceps", "forearm", "wrist", "calf",
)


# ---------------------------------------------------------------------------
# Canonical-value helpers
# ---------------------------------------------------------------------------

def _wrapped_to_inches(wrapped):
    """{'value':V,'unit':U} (length) -> inches, or None."""
    if not wrapped:
        return None
    return calc.to_inches(wrapped.get("value"), wrapped.get("unit"))


def _wrapped_to_lb(wrapped):
    """{'value':V,'unit':U} (mass) -> lb, or None."""
    if not wrapped:
        return None
    return calc.to_lb(wrapped.get("value"), wrapped.get("unit"))


def build_canonical(height_wrapped, weight_wrapped, measurements_wrapped):
    """Builds the 'canonical' inches/lb block from wrapped {value,unit} fields."""
    canonical = {
        "height_in": _wrapped_to_inches(height_wrapped),
        "weight_lb": _wrapped_to_lb(weight_wrapped),
    }
    for key in ALL_MEASUREMENT_KEYS:
        canonical[f"{key}_in"] = _wrapped_to_inches((measurements_wrapped or {}).get(key))
    return canonical


def canonical_for_calculators(entry):
    """Extracts a flat dict (sex/age/height_in/weight_lb/neck/waist/...) from
    a v2 entry's 'canonical' block, ready to hand to calculators.run_all_methods
    / calculators.physique_analysis."""
    canonical = entry.get("canonical") or {}
    out = {
        "sex": entry.get("sex"),
        "age": entry.get("age"),
        "height_in": canonical.get("height_in"),
        "weight_lb": canonical.get("weight_lb"),
    }
    for key in ALL_MEASUREMENT_KEYS:
        out[key] = canonical.get(f"{key}_in")
    return out


# ---------------------------------------------------------------------------
# Migration: v1 (flat, single unit_system) -> v2 (per-field value/unit)
# ---------------------------------------------------------------------------

def _migrate_v1_entry(e):
    unit_system = e.get("unit_system", "imperial")
    length_unit = "cm" if unit_system == "metric" else "in"
    mass_unit = "kg" if unit_system == "metric" else "lb"

    def wrap_length(val):
        return None if val is None else {"value": val, "unit": length_unit}

    def wrap_mass(val):
        return None if val is None else {"value": val, "unit": mass_unit}

    height_wrapped = wrap_length(e.get("height"))
    weight_wrapped = wrap_mass(e.get("weight"))
    measurements_wrapped = {
        key: wrap_length(val) for key, val in (e.get("measurements") or {}).items()
    }
    # Old entries never had a "shoulders" field -- make sure the key exists
    # (as None) so v2 consumers can rely on it always being present.
    measurements_wrapped.setdefault("shoulders", None)

    canonical = build_canonical(height_wrapped, weight_wrapped, measurements_wrapped)

    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp": e.get("timestamp"),
        "sex": e.get("sex"),
        "age": e.get("age"),
        "height": height_wrapped,
        "weight": weight_wrapped,
        "measurements": measurements_wrapped,
        "canonical": canonical,
        "results": e.get("results", {}),
        "enabled_methods": e.get("enabled_methods") or list((e.get("results") or {}).keys()),
        "average_bf": e.get("average_bf"),
        "bmi": e.get("bmi"),
        "analysis": None,  # not available for legacy entries; recomputed on demand for display
        "migrated_from": "v1",
    }


def _migrate_entry(e):
    if e.get("schema_version") == SCHEMA_VERSION:
        return e
    return _migrate_v1_entry(e)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_history():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []

    needs_migration = any(e.get("schema_version") != SCHEMA_VERSION for e in data)
    upgraded = [_migrate_entry(e) for e in data]

    if needs_migration:
        # One-time safety backup of the pre-migration file, so the original
        # data is always recoverable even if something in the upgrade logic
        # above turns out to be wrong.
        if not os.path.exists(BACKUP_FILE):
            try:
                with open(BACKUP_FILE, "w") as bf:
                    json.dump(data, bf, indent=2)
            except OSError:
                pass
        save_history(upgraded)

    return upgraded


def save_history(entries):
    with open(DATA_FILE, "w") as f:
        json.dump(entries, f, indent=2)


def add_entry(entry):
    entries = load_history()
    entry.setdefault("schema_version", SCHEMA_VERSION)
    entries.append(entry)
    save_history(entries)
    return entries


def delete_entry(index):
    entries = load_history()
    if 0 <= index < len(entries):
        del entries[index]
        save_history(entries)
    return entries