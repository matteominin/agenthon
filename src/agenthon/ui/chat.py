"""Review cards and revision-bound chat turns for the Open WebUI Pipe."""
from html import escape
import re
import secrets
from threading import Lock

from agenthon.suggestion import _SEVERITY


BUTTONS = {
    "approve": "Send redacted version",
    "edit": "Check edited prompt",
    "local_simulated": "Use local model (simulated with DeepSeek)",
}
CATEGORIES = {"name": "Name", "email": "Email", "phone": "Phone", "tax_id": "Tax ID"}
REASONS = {
    "pii_found": "Personal information was detected.",
    "uncertain_detection": "The privacy check was inconclusive.",
    "invalid_output": "The privacy check returned an invalid result.",
    "timeout": "The request timed out.",
    "model_error": "The model could not answer.",
    "stale_review": "This review is out of date.",
}
COMMAND = re.compile(
    r"(" + "|".join(re.escape(label) for label in BUTTONS.values()) +
    r") \[TDB:([A-Za-z0-9_-]{16})\](?:\n([\s\S]*)\n\[/TDB edit\])?\Z"
)


def review_card(review, token):
    proposal = review["proposed_prompt"]
    allowed = review["allowed_actions"]
    editable = "edit" in allowed
    badges = []
    severities = {s["label"]: s["severity"] for s in review["suggestions"] if "label" in s}
    for entity in review["entities"]:
        severity = severities.get(entity["label"], _SEVERITY[entity["type"]])
        badges.append(
            f'<span class="badge {severity}">{CATEGORIES[entity["type"]]} · {severity.title()} severity'
            f' · {escape(entity["label"])}</span>'
        )

    def notes(title, items):
        if not items:
            return ""
        return f"<h3>{title}</h3><ul>" + "".join(f"<li>{escape(s['message'])}</li>" for s in items) + "</ul>"

    suggestions = review["suggestions"]
    guidance = notes("Missing information", [s for s in suggestions if "action" not in s])
    guidance += notes("Suggested actions", [s for s in suggestions if "action" in s])
    buttons = []
    if proposal is not None and "approve" in allowed:
        buttons.append('<button data-choice="approve" class="primary">Send redacted version</button>')
    if editable:
        buttons.append('<button id="edit"' + (' hidden' if proposal is None else '') + '>Edit</button>')
        buttons.append('<button data-choice="edit" class="primary"' +
                       (' hidden' if proposal is not None else '') + '>Check edited prompt</button>')
    if proposal is not None and "local_simulated" in allowed:
        buttons.append('<button data-choice="local_simulated">Use local model (simulated with DeepSeek)</button>')
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><style>
    *{{box-sizing:border-box}}body{{margin:0;font:15px/1.5 system-ui;color:#252344}}
    article{{padding:20px;background:#fbfaff;border:1px solid #d9d5eb;border-top:4px solid #6151a4;border-radius:14px}}
    h2,h3,p{{margin:0 0 8px}}h2{{font-size:20px}}h3,label{{font-size:14px;font-weight:700}}
    .grid{{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:18px;margin:16px 0}}
    textarea{{width:100%;min-height:175px;font:inherit;padding:12px;color:#252344;background:white;border:1px solid #b8b2cd;border-radius:8px}}
    .badge,button{{display:inline-block;padding:5px 9px;border-radius:7px;margin:2px;font-size:13px}}
    .medium{{background:#fff0c6;color:#6c4400}}.high{{background:#ffe1e1;color:#802531}}.low{{background:#d6f3e4;color:#204f36}}
    ul{{padding-left:20px;margin:4px 0 14px}}button{{cursor:pointer;background:white;color:#342b51;border:1px solid #b8b2cd;font-weight:600}}
    button.primary{{color:white;background:#514182}}[hidden]{{display:none!important}}
    @media(max-width:590px){{.grid{{grid-template-columns:1fr}}}}
    </style><article><h2>Review before sending</h2><p>{REASONS[review["reason"]]}</p>
    {''.join(badges)}<div class="grid"><div><label for="draft">{'Prompt preview' if proposal is not None else 'Edit prompt'}</label>
    <textarea id="draft" {'readonly' if proposal is not None else ''}>
{escape(proposal or '')}</textarea></div>
    <aside>{guidance}</aside></div>{''.join(buttons)}</article>
    <script>
    const draft=document.querySelector('#draft');
    document.querySelector('#edit')?.addEventListener('click',()=>{{
      draft.readOnly=false;draft.focus();document.querySelector('label').textContent='Edit prompt';
      document.querySelectorAll('button').forEach(b=>b.hidden=b.dataset.choice!=='edit');
    }});
    document.querySelectorAll('[data-choice]').forEach(b=>b.onclick=()=>{{
      if(b.dataset.choice==='edit'&&!draft.value.trim()){{draft.focus();return}}
      const text=b.textContent+' [TDB:{token}]'+(b.dataset.choice==='edit'?'\\n'+draft.value+'\\n[/TDB edit]':'');
      parent.postMessage({{type:'input:prompt:submit',text}},'*');
    }});
    new ResizeObserver(()=>parent.postMessage({{type:'iframe:height',height:document.body.scrollHeight}},'*')).observe(document.body);
    </script></html>"""


class Chat:
    def __init__(self, proxy):
        self.proxy = proxy
        self.pending = {}
        self.lock = Lock()

    def turn(self, owner, text):
        command = COMMAND.fullmatch(text)
        if command:
            label, token, draft = command.groups()
            action = next(key for key, value in BUTTONS.items() if value == label)
            with self.lock:
                pending = self.pending.get(token)
                if not pending or pending[0] != owner or action not in pending[2]:
                    return {"message": REASONS["stale_review"]}
                if action == "edit" and not (draft or "").strip():
                    return {"message": "Enter an edited prompt."}
                del self.pending[token]
            decision = {**pending[1], "action": action}
            if action == "edit":
                decision["prompt"] = draft
            result = self.proxy.decide(decision)
        else:
            result = self.proxy.submit({"prompt": text})
        if result["status"] == "completed":
            return {"message": result["answer"]}
        if result["status"] == "failed":
            return {"message": "Request failed. " + REASONS[result["reason"]]}
        token = secrets.token_urlsafe(12)
        ref = {"request_id": result["request_id"], "revision": result["revision"]}
        with self.lock:
            self.pending[token] = (owner, ref, result["allowed_actions"])
        return {"message": "Review required before sending.", "embed": review_card(result, token)}
