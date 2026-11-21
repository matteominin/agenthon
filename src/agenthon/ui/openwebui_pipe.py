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


# The trusted Pipe binds each action to the review iframe and assistant message.
REVIEW_BRIDGE = Template("""
const review = $review;
const key = Symbol.for('tdb.review.controls');
if (!window[key]) {
    const reviews = new Map();
    window[key] = reviews;
    window.addEventListener('message', async event => {
        if (event.data?.type !== 'tdb:review') return;
        const {token, action, draft} = event.data;
        const current = reviews.get(token);
        if (!current || !Object.hasOwn(current.commands, action)) return;
        const frame = Array.from(document.querySelectorAll('iframe[srcdoc]')).find(candidate =>
            candidate.contentWindow === event.source &&
            candidate.getAttribute('srcdoc').includes('data-reference="' + token + '"')
        );
        if (!frame || (frame.closest('[data-chat]')?.getAttribute('data-chat') ?? 'main') !== 'main') return;
        if (action === 'edit' && (typeof draft !== 'string' || !draft.trim())) return;
        const text = current.commands[action] + (action === 'edit' ? '\\n\\n' + draft : '') + current.suffix;
        const payload = {
            ...current.payload,
            messages: [{role: 'user', content: text}],
            tdb_review: text,
        };
        reviews.delete(token);
        const notify = type => event.source.postMessage({type, token}, '*');
        notify('tdb:review-dispatched');
        try {
            const auth = localStorage.getItem('token');
            const response = await fetch('/api/chat/completions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', ...(auth && {Authorization: 'Bearer ' + auth})},
                body: JSON.stringify(payload),
            });
            if (!response.ok) throw new Error('Review action could not be submitted');
        } catch {
            reviews.set(token, current);
            notify('tdb:review-failed');
        }
    });
}
window[key].set(review.token, review);
""")


class Pipe:
    async def pipe(self, body, __user__, __metadata__, __event_emitter__=None, __task__=None):
        if __task__ or __metadata__.get("task"):
            return ""
        inline_review = "tdb_review" in body
        message_id = __metadata__.get("message_id")
        if inline_review:
            if not message_id or message_id != __metadata__.get("assistant_message_id"):
                return "This review is out of date."
            text = body["tdb_review"]
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
        if inline_review:
            data["inline_review"] = True
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
        if __event_emitter__ and (inline_review or result.get("embed")):
            review = result.get("review")
            model_id = __metadata__.get("model_id") or body.get("model")
            session_id = __metadata__.get("session_id")
            registered = review and all((model_id, session_id, message_id))
            if registered:
                payload = {
                    "model": model_id, "session_id": session_id, "chat_id": chat_id,
                    "id": message_id, "assistant_message_id": message_id, "stream": False,
                }
                code = REVIEW_BRIDGE.substitute(review=json.dumps({**review, "payload": payload}))
                await __event_emitter__({"type": "execute", "data": {"code": code}})
            await __event_emitter__({
                "type": "embeds",
                "data": {"embeds": [result["embed"]] if result.get("embed") else [], "replace": True},
            })
            if registered:
                return ""
        return result["message"]
