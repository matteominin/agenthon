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


class ContractError(ValueError):
    def __init__(self, diagnostic):
        super().__init__("Invalid structured data.")
        self.diagnostic = diagnostic


def validate_contract(schema_name, payload, definition=None):
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError):
        raise ContractError("Response could not be serialized as JSON.") from None
    validator = _validators()[schema_name]
    if definition is not None:
        schema_id = validator.schema["$id"]
        validator = validator.evolve(schema={"$ref": f"{schema_id}#/$defs/{definition}"})
    error = next(validator.iter_errors(payload), None)
    if error is not None:
        # Use names from the schema. Error messages and instance paths can contain private data.
        path = list(error.absolute_schema_path)
        fields = [field for parent, field in zip(path, path[1:]) if parent == "properties"]
        location = ".".join(fields) if fields else definition or schema_name
        raise ContractError(f"Contract check failed at {location} ({error.validator}).")
