"""
title: TDB Privacy Proxy
description: Review personal data in Open WebUI before sending a prompt to DeepSeek.
"""
import asyncio
import json
import os
from string import Template
from urllib.error import URLError
from urllib.request import Request, urlopen


# Only the trusted Pipe can register an approval. The sandboxed frame can
# request this one prebuilt command, without supplying any prompt text.
APPROVAL_BRIDGE = Template("""
const approval = $approval;
const key = Symbol.for('tdb.review.approvals');
if (!window[key]) {
    const approvals = new Map();
    window[key] = approvals;
    window.addEventListener('message', event => {
        if (event.data?.type !== 'tdb:approve') return;
        const token = event.data.token;
        const text = approvals.get(token);
        if (!text) return;
        const frame = Array.from(document.querySelectorAll('iframe[srcdoc]')).find(candidate =>
            candidate.contentWindow === event.source &&
            candidate.getAttribute('srcdoc').includes('data-reference="' + token + '"')
        );
        if (!frame || (frame.closest('[data-chat]')?.getAttribute('data-chat') ?? 'main') !== 'main') return;
        approvals.delete(token);
        event.source.postMessage({type: 'tdb:approval-dispatched', token}, '*');
        window.postMessage({type: 'input:prompt:submit', text}, window.location.origin);
    });
}
window[key].set(approval.token, approval.text);
""")


class Pipe:
    async def pipe(self, body, __user__, __metadata__, __event_emitter__=None, __task__=None):
        if __task__ or __metadata__.get("task"):
            return ""
        messages = body.get("messages", [])
        if not messages or messages[-1]["role"] != "user":
            return "Enter a prompt to continue."
        text = messages[-1]["content"]
        if isinstance(text, list):
            text = "\n".join(item["text"] for item in text if item.get("type") == "text")
        chat_id = __metadata__.get("chat_id")
        if not chat_id or not __user__.get("id") or not isinstance(text, str) or not text.strip():
            return "Open a chat and enter a text prompt to continue."
        data = {"user": __user__["id"], "chat": chat_id, "prompt": text}
        url = os.environ.get("TDB_PROXY_URL", "http://127.0.0.1:8765")
        request = Request(url.rstrip("/") + "/turn", data=json.dumps(data).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")

        def call_proxy():
            with urlopen(request, timeout=100) as response:
                return json.load(response)

        try:
            result = await asyncio.to_thread(call_proxy)
        except (URLError, TimeoutError, ValueError):
            return "The privacy proxy is unavailable. Please try again."
        if result.get("embed") and __event_emitter__:
            if result.get("approval"):
                code = APPROVAL_BRIDGE.substitute(approval=json.dumps(result["approval"]))
                await __event_emitter__({"type": "execute", "data": {"code": code}})
            await __event_emitter__({"type": "embeds", "data": {"embeds": [result["embed"]]}})
        return result["message"]
