# HTTP tra Test Program e sip_proxy

Questo documento descrive solo il canale HTTP tra il Test Program e `sip_proxy`: quali endpoint usa, come sono strutturate le richieste e come viene gestita l'attesa delle risposte.

## Ruolo del canale HTTP

Quando il Test Program usa il backend `sip-proxy-http`, non parla direttamente SIP con il telefono. Invia richieste HTTP JSON al proxy, e `sip_proxy` si occupa del traffico SIP reale verso il dispositivo.

Il canale HTTP serve per:

1. verificare che il proxy sia pronto
2. inviare un messaggio SIP al proxy
3. leggere le risposte associate a una `correlation_id`
4. ottenere i device scoperti tramite SIP REGISTER
5. configurare o leggere le regole di live edit

## Come e implementato lato Test Program

L'implementazione HTTP si trova nel transport `SipProxyHttpTransport`. Usa la libreria standard Python `urllib.request` e scambia JSON.

Sequenza tipica:

1. all'apertura fa una GET su `/health`
2. per inviare usa una POST su `/tester/send`
3. per leggere usa una POST su `/tester/read`
4. per elencare i device scoperti usa una GET su `/tester/discovered-devices`
5. per le regole live edit usa GET, POST e DELETE su `/tester/live-edit-rules`
6. per l'attesa di un hit live edit usa una POST su `/tester/live-edit-wait`

Il payload contiene sempre JSON. Il messaggio SIP vero e proprio passa come stringa raw nel campo `raw_message`.

## Endpoint usati

| Endpoint | Metodo | Scopo |
|---|---|---|
| `/health` | GET | Check iniziale di disponibilita |
| `/tester/send` | POST | Invia il messaggio SIP verso il proxy |
| `/tester/read` | POST | Recupera le risposte legate a una `correlation_id` |
| `/tester/discovered-devices` | GET | Elenca i dispositivi scoperti |
| `/tester/live-edit-rules` | GET | Legge le regole attive |
| `/tester/live-edit-rules` | POST | Aggiunge o sostituisce regole |
| `/tester/live-edit-rules` | DELETE | Rimuove tutte le regole |
| `/tester/live-edit-rules/invite-content-type` | POST | Regola specifica per INVITE |
| `/tester/live-edit-wait` | POST | Attende un hit di live edit |

## Polling o altro

Dal lato del Test Program **non c'e polling continuo**.

Il flusso di lettura e questo:

1. il programma fa una POST su `/tester/read` con `correlation_id` e `timeout_seconds`
2. il proxy controlla se ha gia risposte nel buffer
3. se le ha, le restituisce subito
4. se non le ha, il proxy aspetta un evento interno fino al timeout richiesto
5. quando arriva una risposta, la chiamata HTTP si sblocca e la restituisce

Quindi il meccanismo e piu vicino a un **long polling lato server con attesa event-driven** che a un polling periodico del client.

Lo stesso vale per `/tester/live-edit-wait`: il client fa una sola richiesta con timeout, e il proxy risponde quando l'evento arriva oppure quando scade il tempo.

## Come funziona lato sip_proxy

Sul proxy le risposte vengono memorizzate per `correlation_id` in un buffer dedicato. Quando arriva una nuova risposta, il proxy segnala un evento asincrono. La read HTTP resta in attesa fino a quando:

1. arriva almeno una risposta
2. scade il timeout richiesto

Questo vale sia per le risposte SIP normali sia per gli eventi di live edit.

## Risoluzione del target

Prima di spedire il messaggio, il Test Program risolve la destinazione SIP in questo ordine:

1. `context.target_uri`
2. `device.metadata.target_uri`
3. `device.address`

Il client genera anche una `correlation_id` e la riusa nella richiesta di lettura, cosi il proxy puo associare correttamente risposta e test case.

## In sintesi

Il canale HTTP tra Test Program e `sip_proxy` e un bridge JSON sopra HTTP. Il programma invia un messaggio con POST e poi fa una singola read con timeout. Non c'e polling continuo lato client; l'attesa e gestita dal proxy con buffer e eventi asincroni.
