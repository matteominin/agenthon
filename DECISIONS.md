# DECISIONS

## D1 — PII in locale

Per P0 il rilevatore locale usa il modello inglese spaCy `en_core_web_sm` per i nomi e pattern Python per email, numeri di telefono e identificativi fiscali statunitensi come gli SSN. L’intera demo si svolge in inglese. [Modelli inglesi di spaCy](https://spacy.io/models/en/)

## D2 — Rephrase e Suggestion nel proxy

Due componenti Python con interfacce JSON e regole deterministiche per P0. Rephrase ristruttura il prompt oscurato per compensare le informazioni sottratte, usando contesto generico, casi ipotetici espliciti o richieste condizionate ai dati mancanti. La proposta distingue i fatti disponibili dalle ipotesi. Suggestion segnala le informazioni mancanti e propone azioni solo quando aggiungere contesto non identificativo avrebbe un impatto rilevante sulla risposta. La scelta resta al dipendente.

Nel payload di revisione gli avvisi hanno solo `message` e gli eventuali `label` e `severity`. Le azioni sono elementi distinti con il campo `action`.

## D3 — Un provider reale e una rotta simulata

DeepSeek via API gestisce sia la rotta normale sia la simulazione del modello locale. Per la rotta simulata il proxy invia solo la proposta oscurata e la UI indica esplicitamente l'uso di DeepSeek. [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)

## D4 — Cronologia admin in memoria e trace a metadati

Il proxy conserva mappa dei valori, testo e risposte in memoria. La mappa scade con la revisione, la cronologia admin con la sessione demo. Il trace JSONL conserva solo metadati. La vista admin della demo include il prompt originale e usa dati sintetici.

Il proxy consuma atomicamente la coppia `request_id` e `revision` prima del ricontrollo o dell’invio, così ogni revisione può produrre un solo invio.

## D5 — UI riusabile

Gradio Blocks è la base proposta per le viste dipendente e admin. Si riusano i componenti chat e tabella. L'approvazione resta un passaggio esplicito con le azioni nella scheda.

## D6 — RAG dopo il percorso P0

La demo parte dal prompt diretto. Quando si aggiunge RAG, il proxy dovrà controllare anche il contesto recuperato prima di una chiamata esterna.
