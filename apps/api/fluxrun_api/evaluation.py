"""Deterministic scorer plugins. No user-supplied Python is evaluated."""
import json
import math
import re
from fastapi import HTTPException
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError, SchemaError
from .domain import item_access, redact
from .observability_models import Trace

SCORERS = {"exact_match", "normalized_match", "contains", "regex", "json_schema", "numeric_tolerance", "latency_threshold", "token_threshold"}


def validate_cases(db, request, user, project_id, data):
    cases = data.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 1000:
        raise HTTPException(422, "Dataset version requires 1–1000 cases")
    output = []
    for case in cases:
        if not isinstance(case, dict) or "input" not in case:
            raise HTTPException(422, "Each case requires input")
        if set(case) - {"input", "expected", "actual", "source_trace_id", "latency_ms", "tokens", "tags"}:
            raise HTTPException(422, "Unknown evaluation case field")
        if case.get("source_trace_id"):
            from uuid import UUID
            trace, _ = item_access(db, request, user, Trace, UUID(case["source_trace_id"]))
            if trace.project_id != project_id: raise HTTPException(422, "Trace must belong to the same project")
        output.append(redact(case))
    return {"cases": output}


def validate_scorers(scorers):
    if not 1 <= len(scorers) <= 8: raise HTTPException(422, "Choose 1–8 scorers")
    names = set()
    for scorer in scorers:
        name = scorer.get("name")
        if name not in SCORERS or name in names: raise HTTPException(422, "Unknown or duplicate scorer")
        names.add(name)
        if scorer.get("version", 1) != 1: raise HTTPException(422, "Unsupported scorer version")
        config = scorer.get("config", {})
        if name == "regex":
            pattern = config.get("pattern", "")
            # Initial safe subset: literal alternatives, anchors and bounded character classes.
            # Disallow repeats/groups/backreferences which can cause catastrophic backtracking.
            if not isinstance(pattern, str) or len(pattern) > 200 or re.search(r"[()*+{}\\]", pattern): raise HTTPException(422, "Regex scorer accepts literals, anchors, alternatives and character classes; repetition/groups are disabled")
            try: re.compile(pattern)
            except re.error: raise HTTPException(422, "Invalid regex pattern")
        if name == "json_schema":
            schema = config.get("schema", {})
            if '"$ref"' in json.dumps(schema): raise HTTPException(422, "External and recursive schema references are disabled")
            try: Draft202012Validator.check_schema(schema)
            except SchemaError: raise HTTPException(422, "Invalid scorer JSON schema")
    return [{"name": s["name"], "version": 1, "config": s.get("config", {})} for s in scorers]


def score(name, config, case, actual):
    expected = case.get("expected")
    if name == "exact_match": return float(actual == expected)
    if name == "normalized_match": return float(" ".join(str(actual).lower().split()) == " ".join(str(expected).lower().split()))
    if name == "contains": return float(str(expected) in str(actual))
    if name == "regex": return float(re.search(config.get("pattern", ""), str(actual)[:16000]) is not None)
    if name == "numeric_tolerance":
        actual_num, expected_num = float(actual), float(expected)
        return float(math.isfinite(actual_num) and abs(actual_num-expected_num) <= float(config.get("tolerance", 0.01)))
    if name == "json_schema":
        try:
            value = json.loads(actual) if isinstance(actual, str) else actual
            Draft202012Validator(config.get("schema", {})).validate(value)
            return 1.0
        except (ValueError, ValidationError): return 0.0
    if name in {"latency_threshold", "token_threshold"}:
        key = "latency_ms" if name == "latency_threshold" else "tokens"
        if key not in case: raise ValueError(f"Case is missing {key}")
        return float(float(case[key]) <= float(config.get("maximum", 1000)))
    raise ValueError("Unknown scorer")
