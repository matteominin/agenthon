# TASKS

Stati ammessi — TODO | DOING (owner) | REVIEW | DONE.
I due sviluppatori possono iniziare in parallelo il filone Core e il filone UI usando i casi demo. Compilare le note di consegna in massimo tre righe.

## T0 — Specifica e scheletro · DONE

- Scope — `AGENTS.md`, `SPEC.md`, `TASKS.md`, `DECISIONS.md`, `data/demo/`.
- Done when — Flussi e priorità definiti, responsabilità assegnabili e scenari sintetici pronti.
- Delivery notes — Specifica, backlog e decisioni in root. Fixture in `data/demo/requests.json`, verificabili con `python3 -m json.tool data/demo/requests.json`. Flusso di revisione aggiornato per i dati mancanti e le azioni selettive. Fixture in inglese e lingua dei testi visibili definita nella specifica.

## T1 — Contratti JSON · DONE

- Scope — `schemas/`, `tests/test_contracts.py`.
- Dipende da — T0.
- Done when — Richiesta, output agenti, revisione, scelta utente, cronologia admin e trace hanno schema e fixture valide.
- Delivery notes — Contratti Draft 2020-12 in `schemas/`. Eseguire `uv run --no-project --with jsonschema -- python -m unittest discover -s tests -p test_contracts.py`.

## T2 — Rilevazione e oscuramento (Core) · DONE

- Scope — `src/agenthon/pii/`, `tests/test_pii.py`.
- Dipende da — T1.
- Done when — I casi pulito e PII producono un esito validato, i segnaposto rimangono stabili durante la revisione e i falsi positivi noti della demo in inglese sono coperti dai test. Prima dell’integrazione, concordare i prefissi inglesi dei segnaposto nei contratti condivisi.
- Delivery notes — Rilevamento locale in `src/agenthon/pii/` con segnaposto `NAME`, `EMAIL`, `PHONE` e `SSN`. Con spaCy, `en_core_web_sm` e jsonschema disponibili, eseguire `PYTHONPATH=src python -m unittest discover -s tests -p test_pii.py`.

## T3 — Rephrase e Suggestion (Core) · DONE

- Scope — `src/agenthon/rephrase/`, `src/agenthon/suggestion/`, `tests/test_rephrase.py`, `tests/test_suggestion.py`.
- Dipende da — T1, T2. Prima dell'integrazione, concordare come rappresentare nei contratti le informazioni mancanti, anche quando non sono associate a un segnaposto.
- Done when — Rephrase propone comunque un testo strutturato quando manca contesto e individua le informazioni assenti. Suggestion le segnala e propone azioni solo per dettagli con un beneficio sostanziale per la risposta. I test coprono casi ipotetici espliciti, conservazione dei segnaposto, assenza dei valori rimossi e distinzione tra avvisi e azioni.
- Delivery notes — Proposte e scenari condizionali in `src/agenthon/rephrase/`; avvisi e azioni selettive in `src/agenthon/suggestion/`. Eseguire con `PYTHONPATH=src` i test `test_rephrase.py`, `test_suggestion.py` e `test_contracts.py` via unittest discover.

## T4 — Proxy, DeepSeek e trace (Core) · DONE

- Scope — `src/agenthon/proxy/`, `src/agenthon/models/`, `src/agenthon/trace/`, `tests/test_proxy.py`, `.env.example`.
- Dipende da — T1, T2, T3.
- Done when — Bypass pulito, revisione, ricontrollo dopo modifica, invio approvato, rotta simulata, cronologia admin in memoria e trace funzionano con un provider di test. DeepSeek riscrive il prompt oscurato, genera avvisi e azioni per la revisione e usa un system prompt conciso per le risposte finali.
- Delivery notes — Il proxy usa DeepSeek per Rephrase e Suggestion sul testo oscurato e un system prompt conciso per le risposte finali.
  Con spaCy, `en_core_web_sm` e jsonschema disponibili, eseguire `PYTHONPATH=src python -m unittest discover -s tests -p test_proxy.py`.
  Quattro casi demo verificati con DeepSeek live. Per ripetere la prova, impostare `TDB_TEST_DEEPSEEK=1` e `DEEPSEEK_API_KEY`.

## T5 — Chat e revisione (UI) · DONE

- Scope — `src/agenthon/ui/chat.py`, `src/agenthon/ui/openwebui_pipe.py`, `tests/test_chat.py`.
- Dipende da — T0 per prototipo con fixture, T1 e T4 per integrazione.
- Done when — L'anteprima è editabile, distingue i livelli di gravità e resta visibile accanto alle segnalazioni sulle informazioni mancanti. Le azioni suggerite compaiono solo per i dettagli ad alto impatto. Le tre azioni di revisione usano il proxy e mostrano revisione, errore o risposta in chat.
- Delivery notes — Pipe Open WebUI e scheda in `src/agenthon/ui/`. La chat segnala quando la verifica rileva PII nel testo modificato e richiede di approvare la proposta aggiornata.
  I test verificano i quattro casi demo e l'aggiunta di una nuova email durante la modifica, con il proxy e un provider di test.
  Eseguire `PYTHONPATH=src uv run --no-project --with markdown-it-py --with jsonschema -- python -m unittest discover -s tests -p test_chat.py`.

## T6 — Dashboard admin (UI) · DONE

- Scope — `src/agenthon/ui/admin.py`, `tests/test_admin.py`.
- Dipende da — T0 per prototipo con fixture, T1 e T4 per integrazione.
- Done when — Tutte le richieste compaiono subito. Il dettaglio mostra prompt originale, prompt inviato e risposta quando disponibili. Il flag si attiva al primo rilevamento PII e resta visibile dopo l'esecuzione.
- Delivery notes — `build_admin` in `src/agenthon/ui/admin.py`. Filtri rischio, gravità e stato. La dashboard legge cronologia e trace da `Proxy.history` e `Proxy.trace_events`. Verificati selezione, prompt inviato, risposta e persistenza del flag PII dopo la rotta simulata. Eseguire `PYTHONPATH=src uv run --no-project --with gradio==6.32.0 --with jsonschema -- python -m unittest discover -s tests -p test_admin.py`.

## T7 — Entrypoint e prova demo (UI + Core) · TODO

- Scope — `src/agenthon/__init__.py`, `src/agenthon/ui/app.py`, `README.md`, `pyproject.toml`, `uv.lock`.
- Dipende da — T4, T5, T6. Concordare le dipendenze prima di aggiungerle.
- Done when — `uv run agenthon` apre la demo. I casi sintetici e gli errori simulati si verificano seguendo il README. Prompt, anteprime, suggerimenti, risposte ed entrambe le viste sono in inglese.
- Delivery notes —

## T8 — Revisione fedele al prompt · DONE

- Scope — `src/agenthon/{pii,rephrase,models,proxy}/`, `src/agenthon/ui/chat.py`, `tests/test_{pii,rephrase,proxy,chat}.py`, `data/demo/review-cases.json`, `SPEC.md`.
- Done when — L'apertura italiana «Se ho» resta intatta e il testo proposto conserva lingua e contenuto attorno ai segnaposto.
- Delivery notes — Corretto il falso positivo di spaCy e mantenuto il testo oscurato esatto nella proposta. Rephrase e Suggestion alimentano gli avvisi.
  Gli otto casi in `data/demo/review-cases.json` includono prompt, anteprime attese e verifiche per la UI.
  Con le dipendenze demo, eseguire `PYTHONPATH=src:tests python -m unittest test_pii test_rephrase test_proxy test_chat`.
