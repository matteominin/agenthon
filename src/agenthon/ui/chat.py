"""Review cards and revision-bound chat turns for the Open WebUI Pipe."""
from html import escape
import re
import secrets
from threading import Lock

from markdown_it import MarkdownIt

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


# Render user-authored Markdown as local text, including URLs and image syntax.
MARKDOWN = MarkdownIt("commonmark", {"html": False, "breaks": True}).disable(
    ["image", "link", "autolink", "reference"]
)


def review_card(review, token, originals=None):
    proposal = review["proposed_prompt"]
    originals = originals or {}
    preview = MARKDOWN.render(proposal or "")
    allowed = review["allowed_actions"]
    editable = "edit" in allowed
    badges = []
    severities = {s["label"]: s["severity"] for s in review["suggestions"] if "label" in s}
    for entity in review["entities"]:
        severity = severities.get(entity["label"], _SEVERITY[entity["type"]])
        label = escape(entity["label"])
        value = originals.get(entity["label"])
        original = (
            f'<span class="original" data-label="{label}">{escape(value)}</span>'
            if value is not None else label
        )
        badges.append(
            f'<span class="badge {severity}">{CATEGORIES[entity["type"]]} · {severity.title()} severity'
            f' · {original}</span>'
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
    #preview{{background:white;border:1px solid #dedbea;border-radius:9px;padding:14px 16px;overflow-wrap:anywhere}}
    #preview pre{{white-space:pre-wrap}}#preview h3{{margin:12px 0 4px}}#preview h3:first-child{{margin-top:0}}
    #preview .mask{{background:#302940;color:white;border:0;font:600 0.88em monospace;padding:2px 6px}}
    #preview .mask[aria-pressed="true"]{{background:#e9e4f4;color:#382e50}}
    button:focus-visible{{outline:3px solid #7665b1;outline-offset:2px}}
    .original{{font-weight:650;overflow-wrap:anywhere}}.hint{{font-size:13px;color:#564e63}}
    textarea{{width:100%;min-height:175px;font:inherit;padding:12px;color:#252344;background:white;border:1px solid #b8b2cd;border-radius:8px}}
    .badge,button{{display:inline-block;padding:5px 9px;border-radius:7px;margin:2px;font-size:13px}}
    .medium{{background:#fff0c6;color:#6c4400}}.high{{background:#ffe1e1;color:#802531}}.low{{background:#d6f3e4;color:#204f36}}
    ul{{padding-left:20px;margin:4px 0 14px}}button{{cursor:pointer;background:white;color:#342b51;border:1px solid #b8b2cd;font-weight:600}}
    button.primary{{color:white;background:#514182}}[hidden]{{display:none!important}}
    @media(max-width:590px){{.grid{{grid-template-columns:1fr}}}}
    </style><article><h2>Review before sending</h2><p>{REASONS[review["reason"]]}</p>
    {('<p><strong>Redacted information</strong></p>' + ''.join(badges)) if badges else ''}<div class="grid"><div><label for="draft">{'Prompt preview' if proposal is not None else 'Edit prompt'}</label>
    <div id="preview" {'hidden' if proposal is None else ''}>{preview}</div>
    <p class="hint" {'hidden' if not originals or proposal is None else ''}>Click a masked item to reveal or hide it. Sending keeps the placeholders.</p>
    <textarea id="draft" {'hidden' if proposal is not None else ''}>
{escape(proposal or '')}</textarea></div>
    <aside>{guidance}</aside></div>{''.join(buttons)}</article>
    <script>
    const draft=document.querySelector('#draft');
    const preview=document.querySelector('#preview');
    const originals=new Map(Array.from(document.querySelectorAll('.original'), el=>[el.dataset.label, el.textContent]));
    const walker=document.createTreeWalker(preview,NodeFilter.SHOW_TEXT);
    const nodes=[];
    while(walker.nextNode()) nodes.push(walker.currentNode);
    for(const node of nodes) {{
      const parts=node.textContent.split(/(\\[(?:NAME|EMAIL|PHONE|SSN)_[1-9][0-9]*\\])/g);
      if(!parts.some(part=>originals.has(part))) continue;
      node.replaceWith(...parts.map(part=>{{
        if(!originals.has(part)) return document.createTextNode(part);
        const button=document.createElement('button');
        button.type='button'; button.className='mask'; button.textContent=part;
        button.dataset.label=part; button.setAttribute('aria-pressed','false');
        button.setAttribute('aria-label','Reveal '+part);
        return button;
      }}));
    }}
    preview.addEventListener('click', event=>{{
      const item=event.target.closest('.mask');
      if(!item) return;
      const label=item.dataset.label, reveal=item.getAttribute('aria-pressed')==='false';
      for(const button of preview.querySelectorAll('.mask')) {{
        if(button.dataset.label!==label) continue;
        button.textContent=reveal?originals.get(label):label;
        button.setAttribute('aria-pressed',String(reveal));
        button.setAttribute('aria-label',reveal?'Hide '+originals.get(label):'Reveal '+label);
      }}
    }});
    document.querySelector('#edit')?.addEventListener('click',()=>{{
      preview.hidden=true;document.querySelector('.hint').hidden=true;draft.hidden=false;draft.focus();document.querySelector('label').textContent='Edit prompt';
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
        action = None
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
        originals = self.proxy.review_originals(**ref) if result["entities"] else {}
        message = "Review required before sending."
        if action == "edit" and result["reason"] == "pii_found":
            message = "Personal information was detected in the edited prompt. Review the updated version before sending."
        return {"message": message, "embed": review_card(result, token, originals)}
