"""Review messages and optional ways to improve a redacted request."""


_SEVERITY = {"name": "medium", "email": "medium", "phone": "medium", "tax_id": "high", "contract_id": "medium"}


def suggest(rephrased, entities):
    """Explain missing information and show actions only for high-impact details."""
    entity_types = {entity["label"]: entity["type"] for entity in entities}
    items = []
    for missing in rephrased.get("missing_information", []):
        labels = {}
        if "label" in missing:
            label = missing["label"]
            labels = {"label": label, "severity": _SEVERITY[entity_types[label]]}
        message = f"{missing['detail']} {missing['limitation']}"
        items.append({**labels, "message": message})
        if "guidance" in missing:
            items.append({**labels, "message": missing["guidance"], "action": "add_context"})
    return {"items": items, "confidence": 1}
