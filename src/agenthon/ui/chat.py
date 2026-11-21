"""Employee chat and explicit prompt review for the TDB demo."""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from html import escape

import gradio as gr


REVIEW_REASONS = {
    "pii_found": "Personal information was detected.",
    "uncertain_detection": "The privacy check was inconclusive.",
    "invalid_output": "The privacy check returned an invalid result.",
    "timeout": "The request timed out.",
    "model_error": "The model could not answer.",
    "stale_review": "This review is out of date.",
}
CATEGORIES = {"name": "Name", "email": "Email", "phone": "Phone", "tax_id": "Tax ID"}
SEVERITY_COLORS = {
    "low": ("#15543a", "#d8f3e5"),
    "medium": ("#674300", "#ffedc2"),
    "high": ("#8e2430", "#fce1e4"),
}
ACTIONS = {
    "remove": "Remove this detail",
    "generalize": "Use a more general detail",
    "add_context": "Add non-identifying context",
}


@dataclass(frozen=True)
class _ChatState:
    messages: list[dict] = field(default_factory=list)
    review: dict | None = None
    editing: bool = False


def _review_details(review):
    suggestions = review["suggestions"]
    severity_by_label = {
        item["label"]: item["severity"] for item in suggestions if "label" in item
    }
    sections = []
    if review["entities"]:
        badges = []
        for entity in review["entities"]:
            category = CATEGORIES[entity["type"]]
            label = escape(entity["label"])
            severity = severity_by_label.get(entity["label"])
            foreground, background = SEVERITY_COLORS.get(severity, ("#344159", "#e8edf5"))
            text = f"{severity.capitalize()} severity" if severity else "Severity unavailable"
            badges.append(
                f'<li style="margin:0.35rem 0"><span style="display:inline-block;'
                f'padding:0.2rem 0.55rem;border-radius:0.35rem;color:{foreground};'
                f'background:{background}"><strong>{category}</strong> · {text} · '
                f'<code>{label}</code></span></li>'
            )
        sections.append("<h4>Detected information</h4><ul>" + "".join(badges) + "</ul>")

    notices = [
        f"<li>{escape(item['message'])}</li>" for item in suggestions if "action" not in item
    ]
    if notices:
        sections.append("<h4>Missing information</h4><ul>" + "".join(notices) + "</ul>")

    actions = []
    for item in suggestions:
        if "action" not in item:
            continue
        label = f" <code>{escape(item['label'])}</code>" if "label" in item else ""
        actions.append(
            f"<li><strong>{ACTIONS[item['action']]}</strong>{label} · {escape(item['message'])}</li>"
        )
    if actions:
        sections.append("<h4>Suggested actions</h4><ul>" + "".join(actions) + "</ul>")
    return "".join(sections)


def build_chat(
    submit_request: Callable[[dict], dict],
    submit_decision: Callable[[dict], dict],
) -> None:
    """Add the employee view to the active Blocks context.

    The first two callbacks consume proxy.json request and decision objects and
    return validated result objects. Review items with an action are the
    targeted suggestions selected by the proxy for high-impact details.
    """
    state = gr.State(_ChatState())
    # Carry the displayed revision in each browser event, alongside server-side state.
    shown_review = gr.JSON(visible=False)
    chat = gr.Chatbot(
        label="Employee chat",
        placeholder="Ask the model a question.",
        render_markdown=False,
        allow_tags=False,
        feedback_options=None,
    )
    with gr.Row() as composer:
        prompt = gr.Textbox(label="Your prompt", lines=2, scale=5)
        send = gr.Button("Send", variant="primary", scale=1)
    status = gr.Markdown(visible=False)

    with gr.Group(visible=False) as review_panel:
        review_reason = gr.Markdown()
        with gr.Row():
            preview = gr.Textbox(label="Prompt preview", lines=7, interactive=False, scale=3)
            details = gr.HTML(js_on_load=None, scale=2)
        with gr.Row():
            approve = gr.Button("Send redacted version", variant="primary")
            edit = gr.Button("Edit")
            local = gr.Button("Use local model (simulated with DeepSeek)")
            recheck = gr.Button("Check and send edited prompt", variant="primary", visible=False)
            cancel = gr.Button("Cancel edit", visible=False)

    outputs = [
        state, shown_review, chat, composer, prompt, status, review_panel,
        review_reason, preview, details, approve, edit, local, recheck, cancel,
    ]

    def render(current, *, prompt_text="", draft=None, message=""):
        review = current.review
        reference = None
        proposal = None
        allowed = []
        if review is not None:
            reference = {"request_id": review["request_id"], "revision": review["revision"]}
            proposal = review["proposed_prompt"]
            allowed = review["allowed_actions"]
        editing = current.editing
        return (
            current,
            reference,
            current.messages,
            gr.update(visible=review is None),
            prompt_text,
            gr.update(value=message, visible=bool(message)),
            gr.update(visible=review is not None),
            "### Review required\n" + REVIEW_REASONS[review["reason"]] if review else "",
            gr.update(
                value=(proposal or "") if draft is None else draft,
                label="Edit prompt" if editing else "Prompt preview",
                visible=proposal is not None or editing,
                interactive=editing,
            ),
            _review_details(review) if review else "",
            gr.update(visible=proposal is not None and not editing and "approve" in allowed),
            gr.update(visible=not editing and "edit" in allowed),
            gr.update(visible=proposal is not None and not editing and "local_simulated" in allowed),
            gr.update(visible=editing),
            gr.update(visible=editing and proposal is not None),
        )

    def receive(result, messages):
        if result["status"] == "review_required":
            return render(_ChatState(messages, result, result["proposed_prompt"] is None))
        if result["status"] == "completed":
            answer = {"role": "assistant", "content": result["answer"]}
            return render(_ChatState([*messages, answer]))
        return render(_ChatState(messages), message=f"Request failed. {REVIEW_REASONS[result['reason']]}")

    def send_prompt(text, current):
        if current.review is not None:
            return (gr.skip(),) * len(outputs)
        if not text.strip():
            return render(current, prompt_text=text, message="Enter a prompt to continue.")
        try:
            result = submit_request({"prompt": text})
        except TimeoutError:
            return render(current, prompt_text=text, message="The proxy timed out.")
        messages = [*current.messages, {"role": "user", "content": text}]
        return receive(result, messages)

    def is_displayed_review(current, reference):
        review = current.review
        return review is not None and reference == {
            "request_id": review["request_id"], "revision": review["revision"],
        }

    def open_editor(current, reference):
        if not is_displayed_review(current, reference) or current.editing:
            return (gr.skip(),) * len(outputs)
        if "edit" in current.review["allowed_actions"]:
            return render(replace(current, editing=True))
        return (gr.skip(),) * len(outputs)

    def cancel_edit(current, reference):
        if not is_displayed_review(current, reference) or not current.editing:
            return (gr.skip(),) * len(outputs)
        if current.review["proposed_prompt"] is not None:
            return render(replace(current, editing=False))
        return (gr.skip(),) * len(outputs)

    def decide(action, current, reference, draft=None):
        if not is_displayed_review(current, reference):
            return (gr.skip(),) * len(outputs)
        if action not in current.review["allowed_actions"] or current.editing != (action == "edit"):
            return (gr.skip(),) * len(outputs)
        payload = {**reference, "action": action}
        if action == "edit":
            if not draft or not draft.strip():
                return render(current, draft=draft, message="Enter an edited prompt to continue.")
            payload["prompt"] = draft
        elif current.review["proposed_prompt"] is None:
            return (gr.skip(),) * len(outputs)
        try:
            result = submit_decision(payload)
        except TimeoutError:
            return render(current, draft=draft, message="The proxy timed out.")
        return receive(result, current.messages)

    event_options = {
        "outputs": outputs,
        "api_visibility": "private",
        "concurrency_id": f"chat-{chat._id}",
    }
    review_inputs = [state, shown_review]
    gr.on([send.click, prompt.submit], send_prompt, [prompt, state], **event_options)
    edit.click(open_editor, review_inputs, **event_options)
    cancel.click(cancel_edit, review_inputs, **event_options)
    approve.click(lambda current, reference: decide("approve", current, reference), review_inputs, **event_options)
    local.click(lambda current, reference: decide("local_simulated", current, reference), review_inputs, **event_options)
    recheck.click(
        lambda current, reference, draft: decide("edit", current, reference, draft),
        [*review_inputs, preview],
        **event_options,
    )
