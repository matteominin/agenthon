# DECISIONS

## D1 — PII in locale

Proposta per P0: spaCy `it_core_news_sm` per i nomi, pattern Python per email, telefono e codice fiscale. La demo parte in italiano. [Modelli italiani di spaCy](https://spacy.io/models/it/)

## D2 — Rephrase e Suggestion nel proxy

Due componenti Python con interfacce JSON e regole deterministiche per P0. Rephrase usa il contesto già presente nel prompt oscurato. Suggestion propone interventi per tipo di entità e lascia la scelta al dipendente.

## D3 — Un provider reale e una rotta simulata

DeepSeek via API gestisce sia la rotta normale sia la simulazione del modello locale. Per la rotta simulata il proxy invia solo la proposta oscurata e la UI indica esplicitamente l'uso di DeepSeek. [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)

## D4 — Cronologia admin in memoria e trace a metadati

Il proxy conserva mappa dei valori, testo e risposte in memoria. La mappa scade con la revisione, la cronologia admin con la sessione demo. Il trace JSONL conserva solo metadati. La vista admin della demo include il prompt originale e usa dati sintetici.

## D5 — UI riusabile

Gradio Blocks è la base proposta per le viste dipendente e admin. Si riusano i componenti chat e tabella. L'approvazione resta un passaggio esplicito con le azioni nella scheda.

## D6 — RAG dopo il percorso P0

La demo parte dal prompt diretto. Quando si aggiunge RAG, il proxy dovrà controllare anche il contesto recuperato prima di una chiamata esterna.
