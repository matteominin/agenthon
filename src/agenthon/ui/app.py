"""Run the admin dashboard and the loopback transport used by Open WebUI."""
import os
from pathlib import Path

from fastapi import FastAPI
import gradio as gr
from pydantic import BaseModel, Field
import uvicorn

from agenthon.proxy import Proxy
from agenthon.ui.admin import build_admin
from agenthon.ui.chat import Chat


class Turn(BaseModel):
    user: str = Field(min_length=1)
    chat: str = Field(min_length=1)
    prompt: str = Field(min_length=1)


CSS = Path(__file__).with_name("admin.css").read_text(encoding="utf-8")


def build_services(proxy):
    chat = Chat(proxy)
    transport = FastAPI(docs_url=None, redoc_url=None)
    @transport.post("/turn")
    def turn(data: Turn):
        return chat.turn((data.user, data.chat), data.prompt)

    with gr.Blocks(title="TDB · Request history", analytics_enabled=False) as dashboard:
        gr.HTML('<header><b>TDB</b><span>Privacy administration</span></header>', elem_id="masthead", apply_default_css=False, js_on_load=None)
        build_admin(dashboard, proxy.history, proxy.trace_events)
    return transport, dashboard


def main():
    transport, dashboard = build_services(Proxy())
    theme = gr.themes.Base(primary_hue="emerald", neutral_hue="slate", font=["system-ui", "sans-serif"])
    dashboard.launch(server_name=os.getenv("TDB_ADMIN_HOST", "127.0.0.1"),
                     server_port=int(os.getenv("TDB_ADMIN_PORT", "7860")), share=False,
                     prevent_thread_lock=True, css=CSS, theme=theme, footer_links=[])
    uvicorn.run(transport, host="127.0.0.1", port=8765, access_log=False)


if __name__ == "__main__":
    main()
