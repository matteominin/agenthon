# SPEC — TDB

## Problema

Un dipendente può inserire dati personali in una richiesta a un LLM aziendale. Serve un controllo prima dell'invio e una vista admin che mostri dove si è presentato il rischio.

## Soluzione

Un proxy analizza ogni richiesta, inoltra direttamente quelle senza rilevazioni e mette in pausa le altre per una revisione del dipendente. La dashboard admin mostra l'intera attività e segnala le richieste per cui è stato rilevato un rischio.

## Flusso della demo

1. La chat manda il prompt al proxy. Il rilevatore PII gira in locale e riconosce nomi, email, telefoni e identificativi fiscali statunitensi come gli SSN e ID di contratto esplicitamente etichettati nei prompt demo.
2. Se il controllo termina senza rilevazioni, il proxy chiama DeepSeek e restituisce la risposta alla chat. Se l'analisi fallisce o ha esito incerto, passa la richiesta in revisione senza chiamare il modello.
3. Se trova PII, il proxy sostituisce i valori con segnaposto come `[NAME_1]` e `[EMAIL_1]` nell’anteprima della demo. La mappa segnaposto → valore originale vive in memoria nel proxy per la durata della revisione.
4. Rephrase individua le informazioni mancanti da segnalare nella revisione. Il proxy propone una formulazione più chiara quando serve. Conserva lingua, segnaposto e dettagli disponibili, e ricontrolla la proposta in locale prima di mostrarla.
5. Suggestion segnala le informazioni mancanti e spiega che cosa limitano nella risposta. Propone un'azione solo quando rendere disponibile una versione non identificativa del dettaglio potrebbe migliorare in modo sostanziale il risultato atteso. Per esempio, per un piano di turni può suggerire di indicare fasce orarie e competenze al posto dei nominativi. La gravità del dato privato e l'utilità del contesto per la risposta sono valutazioni distinte.
6. La chat mostra la proposta con etichette colorate e trattiene la richiesta fino alla scelta dell'utente. **Send redacted version** approva il testo visibile. **Edit** apre un editor e il proxy ricontrolla il testo prima di ogni invio. **Use local model (simulated with DeepSeek)** percorre una rotta distinta e invia a DeepSeek la stessa proposta oscurata mostrata all'utente.
7. La dashboard mostra ogni richiesta dal momento in cui arriva al proxy. Il dettaglio mostra il prompt originale, quello inviato al modello e la risposta quando disponibili. Il flag di rischio scatta al primo rilevamento PII e resta visibile dopo eventuali modifiche, approvazione o scelta della rotta locale simulata.

## Componenti e contratti proposti

| Componente | Input | Output JSON |
|---|---|---|
| PII | Prompt originale nel proxy | Testo oscurato, segnaposto tipizzati, stato e confidenza. L'associazione ai valori originali resta nel proxy. |
| Rephrase | Testo oscurato e segnaposto tipizzati | Testo oscurato invariato, informazioni mancanti, indicatore di modifica e confidenza. |
| Suggestion | Testo proposto, segnaposto tipizzati e informazioni mancanti | Segnalazioni sulle informazioni mancanti e azioni facoltative per i dettagli ad alto impatto, con confidenza. |
| Proxy | Richiesta o scelta dell'utente | ID, stato (`completed`, `review_required`, `failed`) e payload adatto allo stato. |
| Dashboard admin | Cronologia del proxy | Richieste, risposte disponibili e flag di rischio per richiesta. |
| Trace | Esito di ogni passaggio | Timestamp, ID richiesta, agente, input/output sintetici, azione e confidenza. |

I passaggi si scambiano JSON validato secondo i contratti in `schemas/`, incluso `schemas/admin_request.json` per la cronologia admin. Il proxy lega ogni scelta alla revisione visualizzata. Quando manca una proposta verificata, la UI offre soltanto la modifica. Il trace contiene tipi, conteggi, stati e motivi predefiniti. Per output strutturato non valido o timeout transitorio, il proxy ritenta una volta, poi restituisce un motivo sintetico per la revisione o un errore esplicito se è già in esecuzione.

## Interfaccia

Gli esempi della demo, i suggerimenti, i messaggi di stato ed errore, le etichette e le azioni sono in inglese. L’anteprima conserva la lingua del prompt. Entrambe le rotte chiedono a DeepSeek di rispondere in inglese senza alterare il testo approvato dall’utente.

- **Dipendente.** Chat principale e scheda di revisione inline con anteprima esatta del testo da inviare. L’anteprima mostra il Markdown e rende cliccabile ogni segnaposto per rivelare o nascondere il valore originale. Il riepilogo elenca valori oscurati, categorie e gravità. La rivelazione è solo visiva: l’approvazione invia la proposta con i segnaposto. Accanto all'anteprima, la scheda indica quali informazioni mancano e come la loro assenza limita la risposta. Mostra un'azione solo dove il contesto aggiuntivo può migliorare sensibilmente il risultato. La proposta resta disponibile anche quando alcuni dati mancano. Il testo da approvare si può modificare nella stessa scheda.
- **Admin.** Tabella di tutte le richieste, ordinate dalla più recente, con colonne per orario, ID, stato, rotta e flag **PII Risk**. La riga apre prompt originale, prompt inviato, risposta del modello e trace. Le richieste in attesa o fallite mostrano lo stato anche quando la risposta manca. I filtri per rischio, gravità e stato sono P1.
- **Base UI.** Il dipendente usa la chat nativa di Open WebUI e il modello TDB. Una Pipe mostra la revisione nella conversazione. La dashboard amministrativa ha una UI separata in Gradio Blocks e legge lo stesso proxy. [Gradio Blocks](https://gradio.app/docs/gradio/blocks) · [Gradio Dataframe](https://gradio.app/docs/gradio/dataframe)

## Priorità

- **P0** — Richiesta pulita fino a DeepSeek, rilevazione e oscuramento, Rephrase e Suggestion, approvazione e modifica con ricontrollo, rotta locale simulata e dashboard admin con cronologia completa e flag di rischio.
- **P1** — Aggiornamento in tempo reale del trace, filtri admin e più casi limite del rilevatore.
- **P2** — Modello locale effettivo e RAG con controllo PII anche sul contesto recuperato.

## Fuori scope per la demo

Proxy trasparente per client terzi, autenticazione e ruoli reali, allegati, persistenza delle conversazioni e rilevazione generalizzata dei segreti aziendali.

## Demo e criteri di riuscita

Replay dei casi sintetici in `data/demo/requests.json`. La richiesta pulita produce una risposta senza revisione e compare in dashboard senza flag. Quella con PII resta in attesa e compare con il flag prima della risposta. La proposta conserva tutti i segnaposto e i dettagli operativi durante la riformulazione. La scheda indica le informazioni mancanti e suggerisce azioni solo per i dettagli ad alto impatto. Una modifica che reintroduce PII apre una nuova revisione. L'invio approvato e la rotta locale simulata usano il testo esatto mostrato nella scheda. La dashboard mostra le risposte, distingue le due rotte e conserva il flag dopo l'esecuzione.
