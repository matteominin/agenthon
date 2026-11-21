"""Detect and redact PII locally before the proxy calls a model."""

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import lru_cache
import re


_PREFIXES = {"name": "NAME", "email": "EMAIL", "phone": "PHONE", "tax_id": "SSN", "contract_id": "CONTRACT_ID"}
_TYPES_BY_PREFIX = {prefix: kind for kind, prefix in _PREFIXES.items()}
_LABEL = re.compile(r"\[(" + "|".join(_TYPES_BY_PREFIX) + r")_[1-9][0-9]*\]")
_ITALIAN_CONDITIONAL_OPENING = re.compile(
    r"(?:^|(?<=[.!?\n]))[ \t]*[Ss]e[ \t]+(?:ho|hai|ha|abbiamo|avete|hanno)(?=[ \t])"
)
_EMAIL = re.compile(
    r"(?<![\w.+-])[\w!#$%&'*+/=?^`{|}~-]+"
    r"(?:\.[\w!#$%&'*+/=?^`{|}~-]+)*@"
    r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}"
    r"(?![\w-]|\.[\w-])",
    re.IGNORECASE,
)
_PHONE = re.compile(
    r"(?<![\w+])(?:\+?1[ .-]?)?"
    r"(?:\([0-9]{3}\)[ .-]?[0-9]{3}[ .-]?[0-9]{4}"
    r"|[0-9]{3}([ .-])[0-9]{3}\1[0-9]{4}"
    r"|[2-9][0-9]{2}[2-9][0-9]{6})"
    r"(?:[ .-]*(?:ext\.?|x|#)[ .-]*[0-9]{1,6})?(?!\w)",
    re.IGNORECASE,
)
_SSN = re.compile(r"(?<![\w-])[0-9]{3}-[0-9]{2}-[0-9]{4}(?![\w-])")
_LABELED_SSN = re.compile(
    r"\b(?:SSN|social security (?:number|no\.?))"
    r"\s*(?:is\s+|[:#]\s*)?(?P<value>[0-9]{9}|[0-9]{3} [0-9]{2} [0-9]{4})(?![\w-])",
    re.IGNORECASE,
)

_CONTRACT_ID = re.compile(
    r"\b(?:contract\s+(?:with\s+)?(?:id|identifier)|(?:id|identificativo)\s+del\s+contratto)\b"
    r"(?:\s+(?:is|of))?\s*[:=#]?\s*"
    r"""(?:["“'](?P<quoted>[a-z0-9][a-z0-9_-]{2,})["”']"""
    r"|(?P<bare>(?=[a-z0-9_-]*\d)[a-z0-9][a-z0-9_-]{2,})(?![\w-]))",
    re.IGNORECASE,
)

NameFinder = Callable[[str], Iterable[tuple[int, int]]]


@dataclass(frozen=True)
class _Match:
    start: int
    end: int
    kind: str


@lru_cache(maxsize=1)
def _load_name_finder() -> NameFinder:
    import spacy

    model = spacy.load("en_core_web_sm")

    def find_names(prompt):
        # Preserve offsets and keep a lowercase Italian verb from being read as part of a name.
        scan = _ITALIAN_CONDITIONAL_OPENING.sub(lambda match: " " * len(match[0]), prompt)
        return (
            (entity.start_char, entity.end_char)
            for entity in model(scan).ents
            if entity.label_ == "PERSON"
        )

    return find_names


def _without_overlaps(matches: list[_Match]) -> list[_Match]:
    selected = []
    for match in sorted(matches, key=lambda item: item.end - item.start, reverse=True):
        if not any(match.start < item.end and item.start < match.end for item in selected):
            selected.append(match)
    return sorted(selected, key=lambda item: item.start)


def _contract_id_matches(prompt):
    values = {match["quoted"] or match["bare"] for match in _CONTRACT_ID.finditer(prompt)}
    for value in values:
        pattern = re.compile(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])", re.IGNORECASE)
        yield from (_Match(*match.span(), "contract_id") for match in pattern.finditer(prompt))


def retained_entities(prompt, previous):
    """Return review metadata for known placeholders still present in the prompt."""
    return [
        {"label": label, "type": _TYPES_BY_PREFIX[prefix]}
        for label, prefix in dict((match[0], match[1]) for match in _LABEL.finditer(prompt)).items()
        if label in previous
    ]


class PIIDetector:
    def __init__(self, find_names: NameFinder | None = None):
        self._find_names = find_names

    def detect(
        self, prompt: str, previous: dict[str, str] | None = None
    ) -> tuple[dict, dict[str, str]]:
        """Return the PII payload and the private map for its redactions.

        Previous labels are reserved throughout a review. Repeated values reuse
        their existing labels unless the text already contains that literal label.
        """
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("PII detection requires a nonempty prompt.")

        previous = previous or {}
        labels_in_prompt = {match[0] for match in _LABEL.finditer(prompt)}
        scan = _LABEL.sub(lambda match: " " * len(match[0]), prompt)
        structured = list(_contract_id_matches(prompt))
        structured.extend(
            _Match(*match.span(), kind)
            for pattern, kind in ((_EMAIL, "email"), (_PHONE, "phone"), (_SSN, "tax_id"))
            for match in pattern.finditer(scan)
        )
        structured.extend(
            _Match(*match.span("value"), "tax_id")
            for match in _LABELED_SSN.finditer(scan)
        )
        structured = _without_overlaps(structured)
        for item in reversed(structured):
            scan = scan[:item.start] + " " * (item.end - item.start) + scan[item.end:]

        known_labels = {}
        matches = list(structured)
        for label, value in previous.items():
            parsed_label = _LABEL.fullmatch(label)
            if parsed_label is None or not value:
                raise ValueError("Invalid private redaction map.")
            kind = _TYPES_BY_PREFIX[parsed_label[1]]
            known_labels[kind, value.casefold()] = label
            pattern = re.compile(r"(?<!\w)" + re.escape(value) + r"(?!\w)", re.IGNORECASE)
            matches.extend(_Match(*match.span(), kind) for match in pattern.finditer(scan))

        name_check_complete = True
        try:
            find_names = self._find_names if self._find_names is not None else _load_name_finder()
            matches.extend(_Match(start, end, "name") for start, end in find_names(scan))
        except TimeoutError:
            raise
        except (ImportError, OSError):
            name_check_complete = False

        redacted_prompt, entities, private = self._redact(
            prompt, _without_overlaps(matches), known_labels, labels_in_prompt, set(previous)
        )
        status = "detected" if entities else "clear"
        if not name_check_complete:
            status = "uncertain"
        return {
            "status": status,
            "redacted_prompt": redacted_prompt,
            "entities": entities,
            "confidence": 0.0 if status == "uncertain" else 0.9,
        }, private

    @staticmethod
    def _redact(prompt, matches, known_labels, labels_in_prompt, previous_labels):
        labels = {}
        private = {}
        entities = []
        reserved = labels_in_prompt | previous_labels
        next_number = Counter()
        parts = []
        cursor = 0
        for match in matches:
            value = prompt[match.start:match.end]
            identity = (match.kind, value.casefold())
            if identity not in labels:
                label = known_labels.get(identity)
                if label is None or label in labels_in_prompt:
                    prefix = _PREFIXES[match.kind]
                    while True:
                        next_number[prefix] += 1
                        label = f"[{prefix}_{next_number[prefix]}]"
                        if label not in reserved:
                            break
                    reserved.add(label)
                labels[identity] = label
                private[label] = value
                entities.append({"label": label, "type": match.kind})
            parts.extend((prompt[cursor:match.start], labels[identity]))
            cursor = match.end
        parts.append(prompt[cursor:])
        return "".join(parts), entities, private
