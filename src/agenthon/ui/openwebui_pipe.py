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
# request this one prebuilt command with placeholder IDs.
APPROVAL_BRIDGE = Template(r"""
const approval = $approval;
const key = Symbol.for('tdb.review.disclosureApprovals');
if (!window[key]) {
    const approvals = new Map();
    window[key] = approvals;
    window.addEventListener('message', async event => {
        if (event.data?.type !== 'tdb:approve') return;
        const token = event.data.token;
        const payload = approvals.get(token);
        if (!payload) return;
        const frame = Array.from(document.querySelectorAll('iframe[srcdoc]')).find(candidate =>
            candidate.contentWindow === event.source &&
            candidate.getAttribute('srcdoc').includes('data-reference="' + token + '"')
        );
        if (!frame || (frame.closest('[data-chat]')?.getAttribute('data-chat') ?? 'main') !== 'main') return;
        const revealed = event.data.revealed ?? [];
        if (!Array.isArray(revealed) || !revealed.every(label =>
            typeof label === 'string' && /^\[(NAME|EMAIL|PHONE|SSN|CONTRACT_ID)_[1-9][0-9]*\]$$/.test(label))) return;
        const marker = String.fromCodePoint(0xe0001);
        const command = revealed.length
            ? payload.tdb_approval.replace(marker, () => '\n\n' + JSON.stringify(revealed) + marker)
            : payload.tdb_approval;
        approvals.delete(token);
        const notify = type => event.source.postMessage({type, token}, '*');
        notify('tdb:approval-dispatched');
        try {
            const auth = localStorage.getItem('token');
            const response = await fetch('/api/chat/completions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', ...(auth && {Authorization: 'Bearer ' + auth})},
                body: JSON.stringify({...payload, tdb_approval: command}),
            });
            if (!response.ok) throw new Error('Approval could not be submitted');
        } catch {
            approvals.set(token, payload);
            notify('tdb:approval-failed');
        }
    });
}
window[key].set(approval.token, approval.payload);
""")


class Pipe:
    async def pipe(self, body, __user__, __metadata__, __event_emitter__=None, __task__=None):
        if __task__ or __metadata__.get("task"):
            return ""
        inline_approval = "tdb_approval" in body
        message_id = __metadata__.get("message_id")
        if inline_approval:
            if not message_id or message_id != __metadata__.get("assistant_message_id"):
                return "This review is out of date."
            text = body["tdb_approval"]
        else:
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
        if message_id:
            data["message_id"] = message_id
        if inline_approval:
            data["inline_approval"] = True
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
        if inline_approval and __event_emitter__:
            await __event_emitter__({"type": "embeds", "data": {"embeds": [], "replace": True}})
        if result.get("embed") and __event_emitter__:
            approval = result.get("approval")
            model_id = __metadata__.get("model_id") or body.get("model")
            session_id = __metadata__.get("session_id")
            if approval and all((model_id, session_id, message_id)):
                payload = {
                    "model": model_id, "session_id": session_id, "chat_id": chat_id,
                    "id": message_id, "assistant_message_id": message_id, "stream": False,
                    "messages": [{"role": "user", "content": approval["text"]}],
                    "tdb_approval": approval["text"],
                }
                registration = {"token": approval["token"], "payload": payload}
                code = APPROVAL_BRIDGE.substitute(approval=json.dumps(registration))
                await __event_emitter__({"type": "execute", "data": {"code": code}})
                await __event_emitter__({"type": "embeds", "data": {"embeds": [result["embed"]]}})
                return ""
            await __event_emitter__({"type": "embeds", "data": {"embeds": [result["embed"]]}})
        return result["message"]
