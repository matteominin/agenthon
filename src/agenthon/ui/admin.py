"""Administrator request history and trace details for the TDB demo."""

from collections import Counter
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from functools import lru_cache
from html import escape
import json

import gradio as gr

from agenthon.pii import PIIDetector
from agenthon.suggestion import _SEVERITY
from agenthon.ui.chat import CATEGORIES


HEADERS = ["Time (UTC)", "Request ID", "Status", "Route", "PII Risk", "User ID", "PII in final prompt"]
STATUS = {
    "processing": "Processing",
    "review_required": "Review required",
    "completed": "Completed",
    "failed": "Failed",
}
ROUTE = {
    None: "Pending",
    "deepseek": "DeepSeek",
    "local_simulated": "Local (simulated with DeepSeek)",
}


def _timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _history_rows(entries, user_for_request, audits):
    ordered = sorted(entries, key=lambda entry: _timestamp(entry["timestamp"]), reverse=True)
    return [
        [
            _timestamp(entry["timestamp"]).strftime("%Y-%m-%d %H:%M:%S"),
            entry["request_id"],
            STATUS[entry["status"]],
            "—" if entry["status"] == "failed" and entry["route"] is None else ROUTE[entry["route"]],
            "Detected" if entry["risk_flag"] else "—",
            user_for_request(entry["request_id"]) or "Unavailable",
            audits[entry["request_id"]][0],
        ]
        for entry in ordered
    ]


def _request_table(rows, selected):
    body = []
    for stamp, request_id, status, route, risk, user, pii in rows:
        rid = escape(request_id, quote=True)
        state = status.lower().replace(" ", "-")
        body.append(
            f'<tr data-id="{rid}" aria-current="{str(request_id == selected).lower()}">'
            f'<td data-title="Time (UTC)"><time>{escape(stamp)}</time></td>'
            f'<td data-title="Request ID"><button type="button" class="request-link" title="{rid}">{rid}</button></td>'
            f'<td data-title="Status"><span class="state {state}">{escape(status)}</span></td>'
            f'<td data-title="Route">{escape(route)}</td>'
            f'<td data-title="PII risk"><span class="{"risk" if risk == "Detected" else "quiet"}">{risk}</span></td>'
            f'<td data-title="User ID" style="overflow-wrap:anywhere">{escape(user)}</td>'
            f'<td data-title="PII in final prompt">{escape(pii)}</td>'
            '</tr>'
        )
    headings = "".join(f'<th scope="col">{label}</th>' for label in HEADERS)
    return f'<table class="ledger"><thead><tr>{headings}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def _prevented_count(events, sent_pii):
    counts = Counter()
    for event in events:
        if event["agent"] == "pii" and event["action"] == "redact":
            # Revisions can detect the same values again. The largest count
            # per category is the minimum number of distinct values removed.
            counts |= Counter(event["output"].get("entity_counts", {}))
    disclosed = Counter(kind for kind, _ in sent_pii)
    return (counts - disclosed).total()


def _audit_sent_prompt(entry, scan_prompt, sent_pii):
    if entry["sent_prompt"] is None:
        return "—", (), "No final model call recorded."
    delivery = "DeepSeek replied." if entry["status"] == "completed" else "Delivery to DeepSeek unconfirmed."
    findings = {(CATEGORIES[kind], value.casefold()): value for kind, value in sent_pii}
    try:
        result, values = scan_prompt(entry["sent_prompt"])
    except TimeoutError:
        return "Check timed out", tuple((category, value) for (category, _), value in findings.items()), delivery
    for item in result["entities"]:
        value = values[item["label"]]
        findings.setdefault((CATEGORIES[item["type"]], value.casefold()), value)
    findings = tuple((category, value) for (category, _), value in findings.items())
    label = ", ".join(dict.fromkeys(category for category, _ in findings))
    if result["status"] == "uncertain" and not label:
        return "Check incomplete", findings, delivery
    if result["status"] == "uncertain":
        label = f"{label} (partial check)"
    if findings and entry["status"] != "completed":
        label = f"{label} (unconfirmed)"
    return label or "None detected", findings, delivery


def _sent_prompt_details(audit):
    label, findings, delivery = audit
    items = "".join(
        f'<li style="overflow-wrap:anywhere"><b>{escape(category)}</b> · {escape(value)}</li>'
        for category, value in findings
    )
    values = f"<ul>{items}</ul>" if items else ""
    return f"<section><h3>PII in final prompt</h3><p>{escape(label)} · {escape(delivery)}</p>{values}</section>"


def _has_severity(events, severity):
    for event in events:
        output = event["output"]
        if output.get("severity") == severity:
            return True
        if any(_SEVERITY[kind] == severity for kind in output.get("entity_counts", {})):
            return True
    return False


def _trace_output(event):
    output = event["output"]
    summary = event.get("summary")
    if summary:
        reason = output.get("reason")
        return f"{reason}: {summary}" if reason else summary
    return json.dumps(output, sort_keys=True) if output else "—"


def _trace_rows(events):
    return [
        [
            _timestamp(event["timestamp"]).strftime("%H:%M:%S"),
            event["agent"], event["action"],
            json.dumps(event["input"], sort_keys=True) if event["input"] else "—", _trace_output(event),
            "—" if event["confidence"] is None else f"{event['confidence']:.0%}",
        ]
        for event in sorted(events, key=lambda event: _timestamp(event["timestamp"]))
    ]


def build_admin(
    app: gr.Blocks,
    list_requests: Callable[[], Sequence[dict]],
    list_trace: Callable[[str], Sequence[dict]],
    *,
    refresh_seconds: float = 1,
    user_for_request: Callable[[str], str | None] = lambda request_id: None,
    sent_pii_for_request: Callable[[str], Sequence[tuple[str, str]]] = lambda request_id: (),
) -> None:
    """Add the admin view to the active Blocks context.

    The proxy callbacks return snapshots of validated admin_request.json records
    and trace events with optional admin summaries for a request ID. The proxy owns the risk flag.
    """
    selected = gr.State(None)
    previous_rows = gr.State([])
    scan_prompt = lru_cache(maxsize=128)(PIIDetector().detect)
    timer = gr.Timer(refresh_seconds)
    gr.Markdown("# Request history", elem_classes=["view-title"])
    totals = gr.HTML(elem_id="request-counts", apply_default_css=False, js_on_load=None)
    with gr.Row(elem_id="history-filters"):
        risk_filter = gr.Dropdown(["All", "Detected", "No detection"], value="All", label="PII risk", filterable=False)
        severity_filter = gr.Dropdown(["All", "Low", "Medium", "High"], value="All", label="Severity", filterable=False)
        status_filter = gr.Dropdown(["All", *STATUS.values()], value="All", label="Status", filterable=False)
    filters = [risk_filter, severity_filter, status_filter]
    table = gr.HTML(
        value=_request_table([], None), elem_id="request-grid", apply_default_css=False,
        js_on_load="""element.addEventListener('click', event => {
            const row = event.target.closest('tr[data-id]');
            if (row) trigger('click', {request_id: row.dataset.id});
        });""",
    )
    notice = gr.Markdown("Waiting for the first request.", elem_id="history-notice")

    with gr.Column(visible=False, elem_id="request-detail") as detail:
        summary = gr.HTML(apply_default_css=False, js_on_load=None)
        with gr.Row(elem_id="prompt-comparison"):
            original = gr.Textbox(label="Original prompt", interactive=False, lines=5, max_lines=12, buttons=["copy"])
            sent = gr.Textbox(label="Sent prompt", interactive=False, lines=5, max_lines=12, buttons=["copy"])
        gr.Markdown("### Model response")
        response = gr.Markdown(
            sanitize_html=True, container=True, padding=True, max_height=360, buttons=["copy"],
        )
        with gr.Accordion("Execution trace", open=False):
            trace = gr.Dataframe(headers=["Time (UTC)", "Agent", "Action", "Input", "Output", "Confidence"],
                                 datatype="str", value=[], interactive=False, wrap=True, buttons=[], show_label=False)

    outputs = [selected, previous_rows, table, notice, detail, summary, original, sent, response, trace, totals]

    def refresh(request_id, last_rows, risk, severity, status, *, force=False):
        events_for = lru_cache(maxsize=None)(list_trace)
        sent_pii_for = lru_cache(maxsize=None)(sent_pii_for_request)
        try:
            history = list_requests()
            entries = [
                entry for entry in history
                if (risk in (None, "All") or entry["risk_flag"] == (risk == "Detected"))
                and (status in (None, "All") or STATUS[entry["status"]] == status)
                and (severity in (None, "All") or _has_severity(events_for(entry["request_id"]), severity.lower()))
            ]
        except TimeoutError:
            return (gr.skip(),) * 3 + ("Request history timed out. Retrying…",) + (gr.skip(),) * 7

        prevented = 0
        trace_incomplete = False
        for entry in history:
            if entry["status"] == "completed" and entry["risk_flag"]:
                try:
                    request = entry["request_id"]
                    prevented += _prevented_count(events_for(request), sent_pii_for(request))
                except TimeoutError:
                    trace_incomplete = True
        counts = [
            ("PII values kept off the internet", f"≥{prevented}"),
            ("Total requests", len(history)),
            ("Awaiting review", sum(e["status"] == "review_required" for e in history)),
            ("PII risk", sum(e["risk_flag"] for e in history)),
        ]
        summary_counts = '<div class="counts" style="grid-template-columns:repeat(auto-fit,minmax(min(125px,100%),1fr))">' + "".join(
            f"<div><span>{label}</span><strong>{count}</strong></div>" for label, count in counts
        ) + "</div><small>Minimum from recorded redactions on completed requests."
        if trace_incomplete:
            summary_counts += " Some trace data is unavailable."
        summary_counts += "</small>"
        audits = {
            entry["request_id"]: _audit_sent_prompt(entry, scan_prompt, sent_pii_for(entry["request_id"]))
            for entry in entries
        }
        rows = _history_rows(entries, user_for_request, audits)
        table_update = _request_table(rows, request_id) if force or rows != last_rows else gr.skip()
        entry = next((entry for entry in entries if entry["request_id"] == request_id), None)
        if entry is None:
            message = "Select a request to view its details." if rows else "No requests yet."
            if history and not rows:
                message = "No requests match these filters."
            return None, rows, table_update, message, gr.update(visible=False), "", "", "", "", [], summary_counts

        badge = '<span class="risk">PII Risk</span>' if entry["risk_flag"] else ""
        heading = (
            f'<div class="detail-head"><div><h2>Request details</h2><code>{escape(request_id)}</code></div>'
            f'<div><span class="state {entry["status"].replace("_", "-")}">{STATUS[entry["status"]]}</span> {badge}</div></div>'
            f'<p style="overflow-wrap:anywhere">User ID · {escape(user_for_request(request_id) or "Unavailable")}</p>'
            + _sent_prompt_details(audits[request_id])
        )
        try:
            events = _trace_rows(events_for(request_id))
            message = ""
        except TimeoutError:
            events = []
            message = "Trace timed out. Retrying…"

        return (
            request_id, rows, table_update, message, gr.update(visible=True), heading,
            entry["original_prompt"], entry["sent_prompt"] or "Unavailable",
            entry["response"] or "Unavailable", events, summary_counts,
        )

    def select(last_rows, risk, severity, status, event: gr.EventData):
        return refresh(event.request_id, last_rows, risk, severity, status, force=True)

    event_options = {
        "outputs": outputs,
        "api_visibility": "private",
        "concurrency_id": f"admin-{table._id}",
        "show_progress": "hidden",
    }
    gr.on([app.load, timer.tick, *(widget.input for widget in filters)], refresh,
          [selected, previous_rows, *filters], **event_options)
    selection = table.click(select, [previous_rows, *filters], **event_options)
    selection.then(fn=None, js="""() => requestAnimationFrame(() =>
        document.getElementById('request-detail')?.scrollIntoView({block:'start'}))""")
