"""Run the admin dashboard and the loopback transport used by Open WebUI."""
import os

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


CSS = """
.gradio-container { max-width:1220px!important; padding:24px clamp(14px,3vw,46px) 48px!important }
#masthead { background:#29233d; border-radius:18px; padding:20px 24px; margin-bottom:14px }
#masthead header {display:flex;align-items:center;gap:14px;color:#fff;font:600 18px/1.25 system-ui}
#masthead header span {color:#fff!important}
#masthead b {background:#d6f29a;color:#252437;border-radius:8px;padding:7px 10px;font:800 16px/1.4 monospace}
#request-counts .counts {display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
#request-counts .counts div {border-top:3px solid #a79abc;background:var(--block-background-fill);padding:12px 15px}
#request-counts .counts div:last-child {border-color:#c17d65}
#request-counts .counts strong {display:block;font-size:27px;letter-spacing:-.04em}
#request-counts .counts span {font-size:13px;font-weight:600}
#history-filters label span {color:var(--body-text-color)!important;background:transparent!important}
@media(max-width:600px){#request-counts .counts{gap:5px} #request-counts .counts div{padding:8px}}
.view-title h1 {font-size:clamp(30px,4vw,48px)!important;letter-spacing:-.045em;line-height:1.15}
#history-filters {padding:12px;border:1px solid var(--border-color-primary);border-radius:14px}
#request-detail {padding:18px;border-left:4px solid #8270a9;border-radius:12px}
#request-detail h3 {overflow-wrap:anywhere}
"""


def build_services(proxy):
    chat = Chat(proxy)
    transport = FastAPI(docs_url=None, redoc_url=None)
    @transport.post("/turn")
    def turn(data: Turn):
        return chat.turn((data.user, data.chat), data.prompt)

    with gr.Blocks(title="TDB · Request history", analytics_enabled=False) as dashboard:
        gr.HTML('<header><b>TDB</b><span>Privacy administration</span></header>', elem_id="masthead")
        build_admin(dashboard, proxy.history, proxy.trace_events)
    return transport, dashboard


def main():
    transport, dashboard = build_services(Proxy())
    theme = gr.themes.Soft(primary_hue="violet", neutral_hue="slate", font=["system-ui", "sans-serif"])
    dashboard.launch(server_name=os.getenv("TDB_ADMIN_HOST", "127.0.0.1"),
                     server_port=int(os.getenv("TDB_ADMIN_PORT", "7860")), share=False,
                     prevent_thread_lock=True, css=CSS, theme=theme, footer_links=[])
    uvicorn.run(transport, host="127.0.0.1", port=8765, access_log=False)


if __name__ == "__main__":
    main()
