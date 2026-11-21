"""Review cards and revision-bound chat turns for the Open WebUI Pipe."""
from html import escape
from pathlib import Path
from string import Template
import re
import secrets
from threading import Lock

from markdown_it import MarkdownIt

from agenthon.suggestion import _SEVERITY


BUTTONS = {
    "approve": "Send redacted version",
    "edit": "Check edited prompt",
    "local_simulated": "Use local model (simulated with DeepSeek)",
}
CATEGORIES = {"name": "Name", "email": "Email", "phone": "Phone", "tax_id": "Tax ID"}
REASONS = {
    "pii_found": "Personal information was detected.",
    "uncertain_detection": "The privacy check was inconclusive.",
    "invalid_output": "The privacy check returned an invalid result.",
    "timeout": "The request timed out.",
    "model_error": "The model could not answer.",
    "stale_review": "This review is out of date.",
}
LEGACY_COMMAND = re.compile(
    r"(" + "|".join(re.escape(label) for label in BUTTONS.values()) +
    r") \[TDB:([A-Za-z0-9_-]{16})\](?:\n([\s\S]*)\n\[/TDB edit\])?\Z"
)


COMMAND = re.compile(
    r"(" + "|".join(re.escape(label) for label in BUTTONS.values()) +
    r")(?:\n\n([\s\S]*))?\n\nReview reference: ([A-Za-z0-9_-]{16})\Z"
)


# Open WebUI uses the submitted text as the confirmation label too.
# A Unicode tag suffix carries the revision token without a visible label.
TAG_OFFSET = 0xE0000
TAGGED_COMMAND = re.compile(
    r"(" + "|".join(re.escape(label) for label in BUTTONS.values()) +
    r")(?:\n\n([\s\S]*))?\U000e0001([\U000e0020-\U000e007e]{16})\U000e007f\Z"
)
REDACTED_LABEL = re.compile(r"\[(?:NAME|EMAIL|PHONE|SSN)_[1-9][0-9]*\]")


def _parse_command(text):
    tagged = TAGGED_COMMAND.fullmatch(text)
    if tagged:
        label, draft, tags = tagged.groups()
        token = "".join(chr(ord(char) - TAG_OFFSET) for char in tags)
        return label, draft, token
    command = COMMAND.fullmatch(text)
    if command:
        return command.groups()
    legacy = LEGACY_COMMAND.fullmatch(text)
    if legacy:
        label, token, draft = legacy.groups()
        return label, draft, token
    return None


def _restore_answer(answer, sent_prompt, originals):
    used = set(REDACTED_LABEL.findall(sent_prompt))

    def restore(match):
        label = match[0]
        return originals.get(label, label) if label in used else label

    restored = REDACTED_LABEL.sub(restore, answer)
    if restored == answer:
        return answer

    # Render restored data as literal text so values cannot become URLs or
    # image sources even when the model puts a placeholder inside Markdown.
    fence = "~" * max(3, 1 + max(map(len, re.findall(r"~+", restored)), default=0))
    return f"{fence}text\n{restored}\n{fence}"


# Render user-authored Markdown as local text, including URLs and image syntax.
MARKDOWN = MarkdownIt("commonmark", {"html": False, "breaks": True}).disable(
    ["image", "link", "autolink", "reference"]
)


REVIEW_TEMPLATE = Template(Path(__file__).with_name("review.html").read_text(encoding="utf-8"))


def review_card(review, token, originals=None):
    proposal = review["proposed_prompt"]
    originals = originals or {}
    preview = MARKDOWN.render(proposal or "")
    allowed = review["allowed_actions"]
    editable = "edit" in allowed
    badges = []
    severities = {s["label"]: s["severity"] for s in review["suggestions"] if "label" in s}
    for entity in review["entities"]:
        severity = severities.get(entity["label"], _SEVERITY[entity["type"]])
        label = escape(entity["label"])
        value = originals.get(entity["label"])
        original = (
            f'<span class="original" data-label="{label}">{escape(value)}</span>'
            if value is not None else label
        )
        badges.append(
            f'<span class="badge {severity}">{CATEGORIES[entity["type"]]} · {severity.title()} severity'
            f' · {original}</span>'
        )

    suggested_actions = [s for s in review["suggestions"] if "action" in s]
    guidance = ""
    if suggested_actions:
        items = "".join(f"<li>{escape(s['message'])}</li>" for s in suggested_actions)
        guidance = f"<details open><summary>Suggested actions</summary><ul>{items}</ul></details>"
    has_preview = proposal is not None
    actions = []
    for action in ("local_simulated", "approve", "edit"):
        if action not in allowed or (not has_preview and action != "edit"):
            continue
        editing = action == "edit"
        mode = "edit" if editing else "preview"
        hidden = " hidden" if editing and has_preview else ""
        if editing and has_preview:
            actions.append('<button id="cancel" data-mode="edit" hidden>Cancel changes</button>')
        actions.append(
            f'<button data-choice="{action}" data-command="{BUTTONS[action]}" data-mode="{mode}" '
            f'class="{"" if action == "local_simulated" else "primary"}"{hidden}>{BUTTONS[action]}</button>'
        )
    return REVIEW_TEMPLATE.substitute(
        token=token, reason=REASONS[review["reason"]],
        badges='<div class="badges">' + "".join(badges) + '</div>' if badges else "",
        preview_hidden="" if has_preview else "hidden", edit_hidden="hidden" if has_preview else "",
        hint_hidden="" if has_preview and originals else "hidden", draft=escape(proposal or ""),
        edit_button='<button id="edit" data-mode="preview">Edit</button>' if editable and has_preview else "",
        preview=preview, guidance=guidance, actions="".join(actions),
    )


class Chat:
    def __init__(self, proxy):
        self.proxy = proxy
        self.pending = {}
        self.lock = Lock()

    def turn(self, owner, text):
        command = _parse_command(text)
        action = None
        originals = {}
        sent_prompt = ""
        if command:
            label, draft, token = command
            action = next(key for key, value in BUTTONS.items() if value == label)
            with self.lock:
                pending = self.pending.get(token)
                if not pending or pending[0] != owner or action not in pending[2]:
                    return {"message": REASONS["stale_review"]}
                if action == "edit" and not (draft or "").strip():
                    return {"message": "Enter an edited prompt."}
                del self.pending[token]
            decision = {**pending[1], "action": action}
            if action == "edit":
                decision["prompt"] = draft
            sent_prompt = draft if action == "edit" else pending[3]
            originals = self.proxy.review_originals(**pending[1], include_previous=True)
            result = self.proxy.decide(decision)
        else:
            result = self.proxy.submit({"prompt": text})
        if result["status"] == "completed":
            return {"message": _restore_answer(result["answer"], sent_prompt, originals)}
        if result["status"] == "failed":
            return {"message": "Request failed. " + REASONS[result["reason"]]}
        token = secrets.token_urlsafe(12)
        ref = {"request_id": result["request_id"], "revision": result["revision"]}
        with self.lock:
            self.pending[token] = (owner, ref, result["allowed_actions"], result["proposed_prompt"])
        originals = self.proxy.review_originals(**ref) if result["entities"] else {}
        message = "Review required before sending."
        if action == "edit" and result["reason"] == "pii_found":
            message = "Personal information was detected in the edited prompt. Review the updated version before sending."
        return {"message": message, "embed": review_card(result, token, originals)}
