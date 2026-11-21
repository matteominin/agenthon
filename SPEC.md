# SPEC — TDB

## Problema

Un dipendente può inserire dati personali in una richiesta a un LLM aziendale. Serve un controllo prima dell'invio e una vista admin che mostri dove si è presentato il rischio.

## Soluzione

Un proxy analizza ogni richiesta, inoltra direttamente quelle senza rilevazioni e mette in pausa le altre per una revisione del dipendente. La dashboard admin mostra l'intera attività e segnala le richieste per cui è stato rilevato un rischio.

## Flusso della demo

1. La chat manda il prompt al proxy. Il rilevatore PII gira in locale e riconosce nomi, email, telefoni e codici fiscali italiani.
2. Se il controllo termina senza rilevazioni, il proxy chiama DeepSeek e restituisce la risposta alla chat. Se l'analisi fallisce o ha esito incerto, passa la richiesta in revisione senza chiamare il modello.
3. Se trova PII, il proxy sostituisce i valori con segnaposto come `[NOME_1]` e `[EMAIL_1]`. La mappa segnaposto → valore originale vive in memoria nel proxy per la durata della revisione.
4. Il componente Rephrase gira dentro il proxy. Usa il prompt oscurato e le categorie per recuperare, se serve, un ruolo generico già esplicito, per esempio `[NOME_1] è il referente del progetto`. Altrimenti conserva il prompt oscurato. Prima di restituire il risultato, usa la mappa in memoria per verificare che i segnaposto restino presenti e i valori rimossi non ricompaiano.
5. Suggestion assegna a ogni segnaposto una gravità e propone un'azione. Può suggerire di generalizzare un dettaglio, rimuoverlo o aggiungere contesto non identificativo.
6. La chat mostra la proposta con etichette colorate e trattiene la richiesta fino alla scelta dell'utente. **Invia versione oscurata** approva il testo visibile. **Modifica** apre un editor e il proxy ricontrolla il testo prima di ogni invio. **Usa modello locale (simulato con DeepSeek)** percorre una rotta distinta e invia a DeepSeek la stessa proposta oscurata mostrata all'utente.
7. La dashboard mostra ogni richiesta dal momento in cui arriva al proxy. Il dettaglio mostra il prompt originale, quello inviato al modello e la risposta quando disponibili. Il flag di rischio scatta al primo rilevamento PII e resta visibile dopo eventuali modifiche, approvazione o scelta della rotta locale simulata.

## Componenti e contratti proposti

| Componente | Input | Output JSON |
|---|---|---|
| PII | Prompt originale nel proxy | Testo oscurato, segnaposto tipizzati, stato e confidenza. L'associazione ai valori originali resta nel proxy. |
| Rephrase | Testo oscurato e segnaposto tipizzati | Testo proposto, indicatore di modifica e confidenza. |
| Suggestion | Testo proposto e segnaposto tipizzati | Elenco di suggerimenti per segnaposto, con gravità e confidenza. |
| Proxy | Richiesta o scelta dell'utente | ID, stato (`completed`, `review_required`, `failed`) e payload adatto allo stato. |
| Dashboard admin | Cronologia del proxy | Richieste, risposte disponibili e flag di rischio per richiesta. |
| Trace | Esito di ogni passaggio | Timestamp, ID richiesta, agente, input/output sintetici, azione e confidenza. |

I passaggi si scambiano JSON validato secondo i contratti in `schemas/`, incluso `schemas/admin_request.json` per la cronologia admin. Il proxy lega ogni scelta alla revisione visualizzata. Quando manca una proposta verificata, la UI offre soltanto la modifica. Il trace contiene tipi, conteggi, stati e motivi predefiniti. Per output strutturato non valido o timeout transitorio, il proxy ritenta una volta, poi restituisce un motivo sintetico per la revisione o un errore esplicito se è già in esecuzione.

## Interfaccia

- **Dipendente.** Chat principale e scheda di revisione inline con anteprima esatta del testo da inviare. Ogni etichetta mostra la categoria e la gravità in testo e colore, con il relativo suggerimento accanto. Il testo da approvare si può modificare nella stessa scheda.
- **Admin.** Tabella di tutte le richieste, ordinate dalla più recente, con colonne per orario, ID, stato, rotta e flag **Rischio PII**. La riga apre prompt originale, prompt inviato, risposta del modello e trace. Le richieste in attesa o fallite mostrano lo stato anche quando la risposta manca. I filtri per rischio, gravità e stato sono P1.
- **Base UI.** Riutilizzare i componenti Python di Gradio Blocks per chat, scheda di revisione e tabella. La demo espone le due viste come sezioni distinte. [Gradio Blocks](https://gradio.app/docs/gradio/blocks) · [Gradio Dataframe](https://gradio.app/docs/gradio/dataframe)

## Priorità

- **P0** — Richiesta pulita fino a DeepSeek, rilevazione e oscuramento, Rephrase e Suggestion, approvazione e modifica con ricontrollo, rotta locale simulata e dashboard admin con cronologia completa e flag di rischio.
- **P1** — Aggiornamento in tempo reale del trace, filtri admin e più casi limite del rilevatore.
- **P2** — Modello locale effettivo e RAG con controllo PII anche sul contesto recuperato.

## Fuori scope per la demo

Proxy trasparente per client terzi, autenticazione e ruoli reali, allegati, persistenza delle conversazioni e rilevazione generalizzata dei segreti aziendali.

## Demo e criteri di riuscita

Replay dei casi sintetici in `data/demo/requests.json`. La richiesta pulita produce una risposta senza revisione e compare in dashboard senza flag. Quella con PII resta in attesa, mostra segnaposto e suggerimenti, e compare con il flag prima della risposta. Una modifica che reintroduce PII apre una nuova revisione. L'invio approvato e la rotta locale simulata usano il testo esatto mostrato nella scheda. La dashboard mostra le risposte, distingue le due rotte e conserva il flag dopo l'esecuzione.
