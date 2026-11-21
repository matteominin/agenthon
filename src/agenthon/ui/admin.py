"""Administrator request history and trace details for the TDB demo."""

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from html import escape

import gradio as gr


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
            _timestamp(entry["timestamp"]).isoformat(sep=" ").removesuffix("+00:00"),
            entry["request_id"],
            STATUS[entry["status"]],
            "—" if entry["status"] == "failed" and entry["route"] is None else ROUTE[entry["route"]],
            "Detected" if entry["risk_flag"] else "—",
        ]
        for entry in ordered
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
    table = gr.Dataframe(
        value=[], headers=HEADERS, datatype="str", interactive=False, label="Requests",
    )
    notice = gr.Markdown("Select a request to view its details.")

    with gr.Group(visible=False) as detail:
        summary = gr.HTML(js_on_load=None)
        original = gr.Textbox(label="Original prompt", interactive=False, lines=3)
        with gr.Row():
            sent = gr.Textbox(label="Sent prompt", interactive=False, lines=3)
            response = gr.Textbox(label="Model response", interactive=False, lines=3)
        trace = gr.JSON(label="Trace", open=False)

    outputs = [selected, previous_rows, table, notice, detail, summary, original, sent, response, trace]

    def refresh(request_id, last_rows):
        try:
            entries = list_requests()
        except TimeoutError:
            return (gr.skip(),) * 3 + ("Request history timed out. Retrying…",) + (gr.skip(),) * 6

        rows = _history_rows(entries)
        table_update = rows if rows != last_rows else gr.skip()
        entry = next((entry for entry in entries if entry["request_id"] == request_id), None)
        if entry is None:
            message = "Select a request to view its details." if rows else "No requests yet."
            return None, rows, table_update, message, gr.update(visible=False), "", "", "", "", None

        risk = ""
        if entry["risk_flag"]:
            risk = ' <strong style="color:#8e2430;background:#fce1e4;padding:0.2rem 0.4rem">PII Risk</strong>'
        heading = f'<h3>Request {escape(request_id)}</h3><p>{STATUS[entry["status"]]}{risk}</p>'
        try:
            events = sorted(list_trace(request_id), key=lambda event: _timestamp(event["timestamp"]))
            message = ""
        except TimeoutError:
            events = []
            message = "Trace timed out. Retrying…"

        return (
            request_id, rows, table_update, message, gr.update(visible=True), heading,
            entry["original_prompt"], entry["sent_prompt"] or "Unavailable",
            entry["response"] or "Unavailable", events,
        )

    def select(last_rows, event: gr.SelectData):
        if not event.row_value or len(event.row_value) != len(HEADERS):
            return (gr.skip(),) * len(outputs)
        # The selected row carries its ID even if polling has reordered the table.
        return refresh(event.row_value[1], last_rows)

    event_options = {
        "outputs": outputs,
        "api_visibility": "private",
        "concurrency_id": f"admin-{table._id}",
        "show_progress": "hidden",
    }
    gr.on([app.load, timer.tick], refresh, [selected, previous_rows], **event_options)
    table.select(select, previous_rows, **event_options)
