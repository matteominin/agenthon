"""Administrator request history and trace details for the TDB demo."""

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from html import escape
import json

import gradio as gr

from agenthon.suggestion import _SEVERITY


HEADERS = ["Time (UTC)", "Request ID", "Status", "Route", "PII Risk"]
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


def _history_rows(entries):
    ordered = sorted(entries, key=lambda entry: _timestamp(entry["timestamp"]), reverse=True)
    return [
        [
            _timestamp(entry["timestamp"]).strftime("%Y-%m-%d %H:%M:%S"),
            entry["request_id"],
            STATUS[entry["status"]],
            "—" if entry["status"] == "failed" and entry["route"] is None else ROUTE[entry["route"]],
            "Detected" if entry["risk_flag"] else "—",
        ]
        for entry in ordered
    ]


def _has_severity(events, severity):
    for event in events:
        output = event["output"]
        if output.get("severity") == severity:
            return True
        if any(_SEVERITY[kind] == severity for kind in output.get("entity_counts", {})):
            return True
    return False


def _trace_rows(events):
    return [
        [
            _timestamp(event["timestamp"]).strftime("%H:%M:%S"),
            event["agent"], event["action"],
            json.dumps(event["input"], sort_keys=True), json.dumps(event["output"], sort_keys=True),
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
) -> None:
    """Add the admin view to the active Blocks context.

    The proxy callbacks return snapshots of validated admin_request.json records
    and trace_event.json records for a request ID. The proxy owns the risk flag.
    """
    selected = gr.State(None)
    previous_rows = gr.State([])
    timer = gr.Timer(refresh_seconds)
    gr.Markdown("# Request history", elem_classes=["view-title"])
    totals = gr.HTML(elem_id="request-counts", js_on_load=None)
    with gr.Row(elem_id="history-filters"):
        risk_filter = gr.Dropdown(["All", "Detected", "No detection"], value="All", label="PII risk", filterable=False)
        severity_filter = gr.Dropdown(["All", "Low", "Medium", "High"], value="All", label="Severity", filterable=False)
        status_filter = gr.Dropdown(["All", *STATUS.values()], value="All", label="Status", filterable=False)
    filters = [risk_filter, severity_filter, status_filter]
    table = gr.Dataframe(
        value=[], headers=HEADERS, datatype="str", interactive=False, label="Requests", elem_id="request-grid",
    )
    notice = gr.Markdown("Select a request to view its details.")

    with gr.Group(visible=False, elem_id="request-detail") as detail:
        summary = gr.HTML(js_on_load=None)
        original = gr.Textbox(label="Original prompt", interactive=False, lines=3)
        with gr.Row():
            sent = gr.Textbox(label="Sent prompt", interactive=False, lines=3)
            response = gr.Textbox(label="Model response", interactive=False, lines=3)
        trace = gr.Dataframe(label="Trace", headers=["Time (UTC)", "Agent", "Action", "Input", "Output", "Confidence"],
                             datatype="str", value=[], interactive=False, wrap=True)

    outputs = [selected, previous_rows, table, notice, detail, summary, original, sent, response, trace, totals]

    def refresh(request_id, last_rows, risk, severity, status):
        try:
            history = list_requests()
            entries = [
                entry for entry in history
                if (risk in (None, "All") or entry["risk_flag"] == (risk == "Detected"))
                and (status in (None, "All") or STATUS[entry["status"]] == status)
                and (severity in (None, "All") or _has_severity(list_trace(entry["request_id"]), severity.lower()))
            ]
        except TimeoutError:
            return (gr.skip(),) * 3 + ("Request history timed out. Retrying…",) + (gr.skip(),) * 7

        counts = [
            ("Total requests", len(history)),
            ("Awaiting review", sum(e["status"] == "review_required" for e in history)),
            ("PII risk", sum(e["risk_flag"] for e in history)),
        ]
        summary_counts = '<div class="counts">' + "".join(
            f"<div><strong>{count}</strong><span>{label}</span></div>" for label, count in counts
        ) + "</div>"
        rows = _history_rows(entries)
        table_update = rows if rows != last_rows else gr.skip()
        entry = next((entry for entry in entries if entry["request_id"] == request_id), None)
        if entry is None:
            message = "Select a request to view its details." if rows else "No requests yet."
            if history and not rows:
                message = "No requests match these filters."
            return None, rows, table_update, message, gr.update(visible=False), "", "", "", "", [], summary_counts

        risk = ""
        if entry["risk_flag"]:
            risk = ' <strong style="color:#8e2430;background:#fce1e4;padding:0.2rem 0.4rem">PII Risk</strong>'
        heading = f'<h3>Request {escape(request_id)}</h3><p>{STATUS[entry["status"]]}{risk}</p>'
        try:
            events = _trace_rows(list_trace(request_id))
            message = ""
        except TimeoutError:
            events = []
            message = "Trace timed out. Retrying…"

        return (
            request_id, rows, table_update, message, gr.update(visible=True), heading,
            entry["original_prompt"], entry["sent_prompt"] or "Unavailable",
            entry["response"] or "Unavailable", events, summary_counts,
        )

    def select(last_rows, risk, severity, status, event: gr.SelectData):
        if not event.row_value or len(event.row_value) != len(HEADERS):
            return (gr.skip(),) * len(outputs)
        # The selected row carries its ID even if polling has reordered the table.
        return refresh(event.row_value[1], last_rows, risk, severity, status)

    event_options = {
        "outputs": outputs,
        "api_visibility": "private",
        "concurrency_id": f"admin-{table._id}",
        "show_progress": "hidden",
    }
    gr.on([app.load, timer.tick, *(widget.input for widget in filters)], refresh,
          [selected, previous_rows, *filters], **event_options)
    table.select(select, [previous_rows, *filters], **event_options)
