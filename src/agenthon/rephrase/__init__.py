"""Deterministic reframing of already redacted employee requests."""

import re


_ADDRESSED_DRAFT = re.compile(
    r"\A(?P<format>(?:draft|write)\s+(?:an?|the)\s+(?:short\s+)?(?:email|(?:text\s+)?message))"
    r"\s+to\s+(?P<recipient>[^.!?\n]+?),\s+"
    r"(?P<goal>(?:asking|reminding|requesting)\s+[^\n]+)\Z",
    re.IGNORECASE,
)
_SHIFT_PLAN = re.compile(
    r"\b(?:build|create|draft|generate|make|plan|prepare|produce)"
    r"(?:\s+(?:a|an|the|our|new|weekly|daily|monthly|tentative|proposed)){0,4}\s+"
    r"(?:(?:(?:staff|work)\s+)?shift\s+(?:schedule|plan|coverage)"
    r"|staff(?:ing)?\s+(?:schedule|plan|roster)|(?:work\s+)?roster|rota)\b"
    r"|\b(?:assign|schedule)\s+shifts\b",
    re.IGNORECASE,
)
_AVAILABILITY = re.compile(
    r"\b(?:available|can work|works?|unavailable|availability\s*:)\s+"
    r"(?:only\s+)?(?:on\s+|from\s+)?"
    r"(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|"
    r"sat(?:urday)?|sun(?:day)?|weekdays?|weekends?|mornings?|afternoons?|evenings?"
    r"|nights?|\d{1,2}(?::\d{2}(?:\s*(?:am|pm))?|\s*(?:am|pm)))\b",
    re.IGNORECASE,
)
_SKILLS = re.compile(
    r"\b(?:certified\s+(?:as|for|in)|trained\s+(?:as|in|on)|qualified\s+(?:as|for|to)"
    r"|can\s+(?:cover|operate|handle)|(?:skills|qualifications)\s*:)\s+\w",
    re.IGNORECASE,
)

_CONTACT_LIMITATIONS = {
    "name": (
        "A person's name is hidden.",
        "A draft can be prepared, but the exact name is unavailable for a personal salutation.",
    ),
    "email": ("An email address is hidden.", "A draft can be prepared, but the exact address is unavailable."),
    "phone": ("A phone number is hidden.", "A draft can be prepared, but the exact number is unavailable."),
    "tax_id": (
        "A taxpayer identifier is hidden.",
        "Any step requiring an exact identity match remains conditional.",
    ),
}


def _missing_information(prompt, entities, shift_plan):
    missing = []
    for entity in entities:
        detail, limitation = _CONTACT_LIMITATIONS[entity["type"]]
        missing.append({"label": entity["label"], "detail": detail, "limitation": limitation})

    if not shift_plan:
        return missing
    if not _AVAILABILITY.search(prompt):
        missing.append({
            "detail": "Individual shift availability is missing.",
            "limitation": "The draft schedule cannot establish which assignments are feasible.",
            "guidance": "Provide availability windows by placeholder or role.",
        })
    if not _SKILLS.search(prompt):
        missing.append({
            "detail": "Staff skills or qualifications are missing.",
            "limitation": "The draft schedule cannot verify that each shift has the skills it needs.",
            "guidance": "Provide skills by placeholder or role and the skills each shift requires.",
        })
    return missing


def rephrase(data):
    """Build an English proposal from the redacted prompt and typed placeholders."""
    prompt, entities = data["prompt"], data["entities"]
    shift_plan = bool(_SHIFT_PLAN.search(prompt))
    missing = _missing_information(prompt, entities, shift_plan)
    proposed_prompt = prompt
    if missing:
        instructions = (
            "Keep the placeholders as written. Use any roles and facts already given. "
            "Provide the parts of the requested result that can be prepared with the available information. "
            "Explain any conditions that affect the result."
        )
        if shift_plan and any("guidance" in detail for detail in missing):
            instructions += (
                " Show how shift assignments would change under different availability or skill conditions. "
                "Label each scenario as hypothetical and keep its assumptions separate from the facts given."
            )
        objective = f"Objective\n{prompt}"
        draft = _ADDRESSED_DRAFT.fullmatch(prompt)
        if draft:
            objective = (
                f"Objective\n{draft['format']} {draft['goal']}"
                f"\n\nRecipient\n{draft['recipient']}"
            )
        proposed_prompt = f"{objective}\n\nResponse instructions\n{instructions}"

    return {
        "proposed_prompt": proposed_prompt,
        "changed": proposed_prompt != prompt,
        "confidence": 1,
        "missing_information": missing,
    }
