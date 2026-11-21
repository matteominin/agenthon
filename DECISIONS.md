# DECISIONS

## D1 — PII in locale

Per P0 il rilevatore locale usa il modello inglese spaCy `en_core_web_sm` per i nomi e pattern Python per email, numeri di telefono, identificativi fiscali statunitensi come gli SSN e ID espliciti di contratto. Gli ID di contratto usano il segnaposto `CONTRACT_ID` anche nelle occorrenze ripetute, come i nomi file. L’intera demo si svolge in inglese. [Modelli inglesi di spaCy](https://spacy.io/models/en/)

## D2 — Rephrase e Suggestion nel proxy

Il proxy invoca DeepSeek per Rephrase subito dopo l’oscuramento locale, inviando solo il prompt oscurato e i segnaposto tipizzati per individuare le informazioni mancanti. Rephrase può chiarire il testo oscurato. Il proxy verifica segnaposto, quantità, orari e formati riconosciuti, poi ricontrolla localmente la proposta per rilevare dati da oscurare. Suggestion usa la proposta verificata e le informazioni mancanti validate per produrre avvisi e azioni, con azioni solo quando aggiungere contesto non identificativo avrebbe un impatto rilevante sulla risposta.

Nel payload di revisione gli avvisi hanno solo `message` e gli eventuali `label` e `severity`. Le azioni sono elementi distinti con il campo `action`.

## D3 — Un provider reale e una rotta simulata

DeepSeek via API gestisce sia la rotta normale sia la simulazione del modello locale. Per la rotta simulata il proxy invia solo la proposta oscurata e la UI indica esplicitamente l'uso di DeepSeek. Entrambe le rotte usano un system prompt per risposte dirette e concise in inglese. [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)

## D4 — Cronologia admin in memoria e trace a metadati

Il proxy conserva mappa dei valori, testo e risposte in memoria. La mappa scade con la revisione, la cronologia admin con la sessione demo. La scheda del dipendente include i valori originali delle sole entità della revisione visualizzata. Open WebUI conserva la scheda nella conversazione secondo le proprie impostazioni. Il trace JSONL conserva solo metadati. La vista admin della demo include il prompt originale e usa dati sintetici.

Il proxy consuma atomicamente la coppia `request_id` e `revision` prima del ricontrollo o dell’invio, così ogni revisione può produrre un solo invio.

## D5 — UI riusabile

Open WebUI ospita la chat dipendente. Una Pipe collega il modello TDB al proxy e mostra la scheda di revisione inline. La dashboard admin usa Gradio Blocks e legge cronologia e trace della stessa istanza del proxy. Per l'approvazione con un clic, la Pipe registra nel browser un comando vincolato alla scheda e alla revisione, mantenendo l'iframe in sandbox.

## D6 — RAG dopo il percorso P0

La demo parte dal prompt diretto. Quando si aggiunge RAG, il proxy dovrà controllare anche il contesto recuperato prima di una chiamata esterna.
