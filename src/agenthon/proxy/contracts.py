import json
from functools import cache
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schemas"
_SCHEMA_NAMES = ("agents", "proxy", "admin_request", "trace_event")


@cache
def _validators():
    schemas = {
        name: json.loads((_SCHEMA_DIR / f"{name}.json").read_text(encoding="utf-8"))
        for name in _SCHEMA_NAMES
    }
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )
    return {
        name: Draft202012Validator(
            schema, registry=registry, format_checker=FormatChecker()
        )
        for name, schema in schemas.items()
    }


def validate_contract(schema_name, payload, definition=None):
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError("Invalid structured data.") from None
    validator = _validators()[schema_name]
    if definition is not None:
        schema_id = validator.schema["$id"]
        validator = validator.evolve(schema={"$ref": f"{schema_id}#/$defs/{definition}"})
    if not validator.is_valid(payload):
        # Validation errors can embed the whole value, including private prompts.
        raise ValueError("Invalid structured data.")
