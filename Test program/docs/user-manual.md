# Manuale utente del Test program

Questo documento descrive come usare il Test program IMS, quali modalita` supporta e quali comandi espone dalla riga di comando.

Il progetto e' pensato per eseguire test SIP/IMS in modo ripetibile, sia su un backend fittizio (`stub`) sia tramite il tester API del `sip_proxy` (`sip-proxy-http`).

## Requisiti minimi

- Python 3.13 o ambiente equivalente compatibile con il progetto.
- Dipendenze installate con `pip install -r requirements.txt`.
- Un file di configurazione per i test e, quando serve, un file di runtime.

Avvio tipico da cartella `Test program`:

```bash
python main.py --help
```

## Struttura dei file di configurazione

Il Test program separa la logica del test dall'ambiente di esecuzione.

- `docs/test-config.md` descrive la suite di test: messaggi SIP, edit, intercept e aspettative.
- `docs/runtime-config.md` descrive il runtime: transport, dispositivi e parametri del backend.

In breve:

- Il file test dice cosa verificare.
- Il file runtime dice dove e contro quali dispositivi eseguire la suite.

## Modalita` di utilizzo

### 1. Validazione di una suite

Usa questa modalita' quando vuoi controllare che il file YAML della suite sia valido prima di eseguire i test.

```bash
python main.py validate --test-config examples/test_suite_register.yaml
```

Comportamento:

- verifica la struttura del file YAML;
- controlla id, campi richiesti e vincoli principali;
- non invia alcun messaggio SIP.

### 2. Esecuzione standard su un dispositivo

Questa e' la modalita' principale. Esegue la suite contro un solo dispositivo e confronta le risposte con quelle attese.

```bash
python main.py run-standard --test-config examples/test_suite_register.yaml --runtime-config examples/runtime_stub.yaml --device pixel_8
```

Se non specifichi `--device`, il programma prova a selezionare i dispositivi disponibili e, se ce ne sono piu` di uno, chiede una scelta interattiva.

I selettori accettati per un dispositivo sono:

- device id;
- nome visualizzato;
- indirizzo;
- numero telefonico;
- IMSI.

Se i dispositivi disponibili sono piu' di uno, puoi selezionarli anche inserendo numeri o id separati da virgole, per esempio `1,2,3`.

Opzioni utili:

- `--report-json <path>` scrive un report JSON della sessione;
- `--no-wait` evita la pausa tra un caso e l'altro.

Nota importante:

- se selezioni piu' dispositivi con `run-standard`, il programma passa automaticamente alla comparazione differenziale;
- i casi con `message.intercept_only: true` sono supportati in questa modalita`.

### 3. Esecuzione su `sip-proxy-http` con discovery dei dispositivi

Quando il runtime usa `sip-proxy-http`, il Test program puo` leggere i dispositivi registrati dal proxy e unirli a quelli configurati nel file runtime.

```bash
python main.py list-devices --runtime-config examples/runtime_sip_proxy_http.yaml
```

Questa modalita' e' utile per verificare:

- quali dispositivi sono configurati staticamente;
- quali dispositivi sono stati scoperti tramite traffico SIP REGISTER;
- quali selettori sono disponibili per l'esecuzione.

### 4. Comparazione differenziale tra due o piu` dispositivi

La modalita' `compare` esegue la stessa suite su due o piu` dispositivi e confronta i risultati.

```bash
python main.py compare --test-config examples/test_suite_register.yaml --runtime-config examples/runtime_stub.yaml --device pixel_8 --device galaxy_s24
```

In alternativa puoi usare selettori separati da virgola:

```bash
python main.py compare --test-config examples/test_suite_register.yaml --runtime-config examples/runtime_stub.yaml --device pixel_8,galaxy_s24
```

Se non passi `--device`, il programma propone una selezione interattiva tra i dispositivi disponibili.

### 5. Intercept e live rewrite durante l'esecuzione

La suite puo' includere regole di intercept live definite nel test file con `message.intercept_edits`.

In questo caso il runner puo':

- inviare un template SIP e applicare rewrite sul traffico che passa nel proxy;
- aspettare solo traffico reale con `intercept_only: true`;
- combinare invio e mutazione live nello stesso caso.

Esempi utili:

```bash
python main.py run-standard --test-config examples/test_suite_invite_intercept_content_type_test.yaml --runtime-config examples/runtime_sip_proxy_http.yaml
python main.py run-standard --test-config examples/test_suite_invite_intercept_only_content_type_test.yaml --runtime-config examples/runtime_sip_proxy_http.yaml
```

Indicazioni pratiche:

- per il fuzzing su INVITE reale, usa in genere `intercept_direction: request`;
- le regole live vengono pulite automaticamente al termine dell'esecuzione;
- il backend `sip-proxy-http` deve essere attivo e raggiungibile.

### 6. Gestione manuale delle regole live del proxy

Il Test program offre anche due comandi di manutenzione per il proxy:

```bash
python main.py live-edit-list --runtime-config examples/runtime_sip_proxy_http.yaml
python main.py live-edit-clear --runtime-config examples/runtime_sip_proxy_http.yaml
```

- `live-edit-list` mostra le regole attive nel proxy in formato JSON;
- `live-edit-clear` rimuove tutte le regole attive.

Questi comandi funzionano solo con il transport `sip-proxy-http`.

## Comandi disponibili

### `validate`

Valida un file di test suite.

Parametri:

- `--test-config`: percorso del file YAML della suite.

### `list-devices`

Mostra i dispositivi disponibili per l'esecuzione.

Parametri:

- `--runtime-config`: percorso del file YAML runtime.

### `run-standard`

Esegue una suite di test contro uno o piu` dispositivi.

Parametri:

- `--test-config`: percorso del file YAML della suite;
- `--runtime-config`: percorso del file YAML runtime;
- `--device`: selettore dispositivo, anche ripetibile o separato da virgole;
- `--report-json`: file opzionale per il report JSON;
- `--no-wait`: disabilita l'attesa tra i casi.

### `compare`

Esegue la comparazione tra due o piu` dispositivi.

Parametri:

- `--test-config`: percorso del file YAML della suite;
- `--runtime-config`: percorso del file YAML runtime;
- `--device`: selettore dispositivo, ripetibile o separato da virgole;
- `--report-json`: file opzionale per il report JSON;
- `--no-wait`: disabilita l'attesa tra i casi.

### `live-edit-list`

Mostra le regole live attive del proxy.

Parametri:

- `--runtime-config`: deve puntare a un runtime con transport `sip-proxy-http`.

### `live-edit-clear`

Cancella tutte le regole live attive del proxy.

Parametri:

- `--runtime-config`: deve puntare a un runtime con transport `sip-proxy-http`.

## Codici di uscita

Il programma usa questi codici di ritorno principali:

- `0`: esecuzione riuscita;
- `1`: errore generico o comando non valido;
- `2`: errore di validazione della configurazione;
- `10`: `run-standard` completato ma con almeno un caso fallito;
- `11`: `compare` completato con differenze trovate.

## Flusso consigliato di utilizzo

1. Valida la suite con `validate`.
2. Verifica i dispositivi disponibili con `list-devices`.
3. Esegui una suite breve con `run-standard`.
4. Usa `compare` se vuoi confrontare due terminali o due telefoni.
5. Usa i comandi `live-edit-*` solo quando ti serve intervenire manualmente sulle regole del proxy.

## Esempi rapidi

Esecuzione con backend fittizio:

```bash
python main.py run-standard --test-config examples/test_suite_register.yaml --runtime-config examples/runtime_stub.yaml --device pixel_8
```

Esecuzione contro il proxy reale con dispositivi rilevati via REGISTER:

```bash
python main.py list-devices --runtime-config examples/runtime_sip_proxy_http.yaml
python main.py run-standard --test-config examples/test_suite_register.yaml --runtime-config examples/runtime_sip_proxy_http.yaml
```

Comparazione di due dispositivi:

```bash
python main.py compare --test-config examples/test_suite_register.yaml --runtime-config examples/runtime_stub.yaml --device pixel_8 --device galaxy_s24
```

## Riferimenti utili

- `docs/test-config.md`: formato e semantica della suite di test.
- `docs/runtime-config.md`: formato del runtime e configurazione dei transport.
- `examples/`: esempi pronti all'uso.
