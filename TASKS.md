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
- Done when — Bypass pulito, revisione, ricontrollo dopo modifica, invio approvato, rotta simulata, cronologia admin in memoria e trace funzionano con un provider di test. Verifica finale con DeepSeek e dati sintetici.
- Delivery notes — `Proxy.submit`, `decide`, `history` e `trace_events` in `src/agenthon/proxy/`. Quattro casi demo verificati con spaCy e DeepSeek live.
  Con spaCy, `en_core_web_sm` e jsonschema disponibili, eseguire `PYTHONPATH=src python -m unittest discover -s tests -p test_proxy.py`.
  Per la verifica live aggiungere `TDB_TEST_DEEPSEEK=1` ed esportare `DEEPSEEK_API_KEY` nell’ambiente.

## T5 — Chat e revisione (UI) · REVIEW

- Scope — `src/agenthon/ui/chat.py`, `tests/test_chat.py`.
- Dipende da — T0 per prototipo con fixture, T1 e T4 per integrazione.
- Done when — L'anteprima è editabile, distingue i livelli di gravità e resta visibile accanto alle segnalazioni sulle informazioni mancanti. Le azioni suggerite compaiono solo per i dettagli ad alto impatto. Le tre azioni di revisione usano il proxy e mostrano revisione, errore o risposta in chat.
- Delivery notes — `build_chat` in `src/agenthon/ui/chat.py`. Anteprima, revisioni e tre azioni verificate con fixture. Avvisi e azioni letti dal contratto T4. Integrazione verificata con `Proxy.submit` e `Proxy.decide`. Eseguire `PYTHONPATH=src uv run --no-project --with gradio==6.32.0 --with jsonschema -- python -m unittest discover -s tests -p test_chat.py`.

## T6 — Dashboard admin (UI) · REVIEW

- Scope — `src/agenthon/ui/admin.py`, `tests/test_admin.py`.
- Dipende da — T0 per prototipo con fixture, T1 e T4 per integrazione.
- Done when — Tutte le richieste compaiono subito. Il dettaglio mostra prompt originale, prompt inviato e risposta quando disponibili. Il flag si attiva al primo rilevamento PII e resta visibile dopo l'esecuzione.
- Delivery notes — `build_admin` in `src/agenthon/ui/admin.py`. Cronologia aggiornata ogni secondo, dettaglio e flag PII verificati con fixture. Per collegare T4 usare `Proxy.history` e `Proxy.trace_events`. Eseguire `PYTHONPATH=src uv run --no-project --with gradio==6.32.0 --with jsonschema -- python -m unittest discover -s tests -p test_admin.py`.

## T7 — Entrypoint e prova demo (UI + Core) · TODO

- Scope — `src/agenthon/__init__.py`, `src/agenthon/ui/app.py`, `README.md`, `pyproject.toml`, `uv.lock`.
- Dipende da — T4, T5, T6. Concordare le dipendenze prima di aggiungerle.
- Done when — `uv run agenthon` apre la demo. I casi sintetici e gli errori simulati si verificano seguendo il README. Prompt, anteprime, suggerimenti, risposte ed entrambe le viste sono in inglese.
- Delivery notes —
