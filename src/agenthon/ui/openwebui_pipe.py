"""
title: TDB Privacy Proxy
description: Review personal data in Open WebUI before sending a prompt to DeepSeek.
"""
import asyncio
import json
import os
from urllib.error import URLError
from urllib.request import Request, urlopen


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
            await __event_emitter__({"type": "embeds", "data": {"embeds": [result["embed"]]}})
        return result["message"]
