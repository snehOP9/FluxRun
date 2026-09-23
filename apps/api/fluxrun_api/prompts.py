"""Non-executable {{variable}} templates with strict variable matching."""
import re
from fastapi import HTTPException
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def templates(data):
    if data.get("type", "text") == "text":
        if not isinstance(data.get("template"), str):
            raise HTTPException(422, "Text prompt requires a template string")
        return [data["template"]]
    messages = data.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 50:
        raise HTTPException(422, "Chat prompt requires 1–50 messages")
    if any(not isinstance(m, dict) or m.get("role") not in {"system", "user", "assistant", "tool"} or not isinstance(m.get("content"), str) for m in messages):
        raise HTTPException(422, "Invalid chat message role or content")
    return [m["content"] for m in messages]


def validate_prompt(data):
    variables = set()
    for template in templates(data):
        if len(template) > 64000:
            raise HTTPException(422, "Prompt template exceeds 64,000 characters")
        remainder = VARIABLE.sub("", template)
        if "{{" in remainder or "}}" in remainder:
            raise HTTPException(422, "Malformed placeholder. Use {{variable_name}} only.")
        variables.update(VARIABLE.findall(template))
    for name in ("response_schema", "variables_schema"):
        schema = data.get(name)
        if schema:
            try: Draft202012Validator.check_schema(schema)
            except SchemaError: raise HTTPException(422, f"Invalid {name}")
    config = data.get("model_config", {})
    if not isinstance(config, dict) or set(config) - {"model", "provider", "temperature", "max_tokens", "top_p", "seed"}:
        raise HTTPException(422, "Model configuration contains unsupported fields")
    return sorted(variables)


def render_prompt(data, values):
    required = set(validate_prompt(data))
    if set(values) != required:
        raise HTTPException(422, f"Variables must match exactly: {', '.join(sorted(required)) or '(none)'}")
    if data.get("variables_schema"):
        try: Draft202012Validator(data["variables_schema"]).validate(values)
        except ValidationError: raise HTTPException(422, "Variables do not match the declared schema")
    def render(template): return VARIABLE.sub(lambda m: str(values[m.group(1)]), template)
    return render(data["template"]) if data.get("type", "text") == "text" else [{**m, "content": render(m["content"])} for m in data["messages"]]
