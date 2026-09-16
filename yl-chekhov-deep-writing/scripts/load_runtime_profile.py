#!/usr/bin/env python3
"""Load and fail-closed validate the public Chekhov runtime profile."""

from __future__ import annotations

import json
from pathlib import Path


PROFILE_PATH = Path(__file__).resolve().parents[1] / "assets" / "runtime-profile.json"
MECHANISM_CODES = {
    "m_reweight_ambiguous_fact",
    "m_constrain_judgment_with_observation",
    "m_extend_consequence_after_local_closure",
}
SHELL_MODES = {
    "accumulation_then_short_release",
    "clue_before_explanation_turn",
    "voice_checked_by_consequence",
}
FORBIDDEN_IDENTITY_TOKENS = ("契诃夫", "chekhov", "anton", "чехов")


def load_profile(path: Path = PROFILE_PATH) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "chekhov-runtime-profile-v1":
        raise ValueError("runtime_profile_schema_invalid")
    if data.get("profile_status") != "stable":
        raise ValueError("runtime_profile_not_stable")

    mechanisms = data.get("mechanism_parameters")
    if not isinstance(mechanisms, list) or len(mechanisms) != 3:
        raise ValueError("runtime_mechanism_count_invalid")
    if {item.get("runtime_code") for item in mechanisms} != MECHANISM_CODES:
        raise ValueError("runtime_mechanism_codes_invalid")
    for item in mechanisms:
        if not item.get("applicability_codes") or not item.get("cost_codes"):
            raise ValueError("runtime_mechanism_boundary_missing")
        if item.get("role_options") != ["primary", "auxiliary"]:
            raise ValueError("runtime_mechanism_roles_invalid")

    shell = data.get("shell_parameters")
    if not isinstance(shell, list) or len(shell) != 3:
        raise ValueError("runtime_shell_count_invalid")
    if {item.get("mode") for item in shell} != SHELL_MODES:
        raise ValueError("runtime_shell_modes_invalid")

    constraints = data.get("constraints")
    if not isinstance(constraints, dict):
        raise ValueError("runtime_constraints_missing")
    for key in (
        "forward_identity",
        "forward_source_text",
        "forward_research_cards",
    ):
        if constraints.get(key) is not False:
            raise ValueError(f"runtime_constraint_invalid:{key}")
    if constraints.get("max_primary_mechanisms") != 1:
        raise ValueError("runtime_primary_limit_invalid")
    if constraints.get("max_auxiliary_mechanisms") != 2:
        raise ValueError("runtime_auxiliary_limit_invalid")
    if constraints.get("max_shell_parameters") != 2:
        raise ValueError("runtime_shell_limit_invalid")

    runtime_payload = {
        "mechanism_parameters": mechanisms,
        "shell_parameters": shell,
        "constraints": constraints,
    }
    serialized = json.dumps(runtime_payload, ensure_ascii=False).casefold()
    if any(token in serialized for token in FORBIDDEN_IDENTITY_TOKENS):
        raise ValueError("runtime_identity_leak")
    return data


def main() -> int:
    try:
        profile = load_profile()
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "unavailable", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "available", "runtime_payload": profile}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
