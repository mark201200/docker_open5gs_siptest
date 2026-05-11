# Test Program Architecture - Comunicazione con SIP Proxy e Kamailio

## 1. Panoramica Generale

Il **Test Program** è una CLI Python (`ims-thesis-tester`) interface-first per testare la conformità SIP di smartphone IMS e per eseguire testing differenziale tra dispositivi. Il progetto è strutturato in due modalità operative:

1. **Modalità Standard**: invia messaggi SIP costruiti e valida le risposte against expected values da un file di test
2. **Modalità Differenziale**: esegue gli stessi test su due telefoni e riporta le differenze di risposta

## 2. Struttura del Progetto

```
Test program/
├── main.py                      # Entry point
├── pyproject.toml              # Configurazione Python/setuptools
├── requirements.txt            # Dipendenze
├── README.md                   # Documentazione base
├── ims_tester/                 # Package principale
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                  # Command line interface
│   ├── models.py               # Domain models e report models
│   ├── interfaces.py           # Interfacce astratte per transport e message I/O
│   ├── adapters.py             # Implementazioni pluggable (stub, sip-proxy-http)
│   ├── editor.py               # Default SIP message modifier
│   ├── engine.py               # Test runners (standard e differential)
│   ├── config.py               # YAML config loaders
│   ├── reporter.py             # Report generation
│   └── errors.py               # Custom exceptions
├── docs/                       # Documentazione
│   ├── test-config.md          # Schema test suite files
│   ├── runtime-config.md       # Schema runtime files
│   ├── user-manual.md          # Manuale utente
│   └── test-program-architecture.md  # Questo file
├── examples/                   # File YAML di esempio
│   ├── runtime_sip_proxy_http.yaml
│   ├── runtime_stub.yaml
│   ├── test_suite_register.yaml
│   └── ...
└── tests/                      # Test suite
```

## 3. Comunicazione con SIP Proxy/Kamailio

### 3.1 Architettura di Comunicazione

```
┌─────────────────┐
│  Test Program   │
│   (ims-tester)  │
└────────┬────────┘
         │
    HTTP (JSON)
         │
    ┌────▼──────────┐
    │  SIP Proxy    │
    │ (sip_proxy.py)│
    │ API HTTP      │
    └────┬──────────┘
         │
    UDP/TCP (SIP 2.0)
         │
    ┌────▼──────────────┐
    │  Device Under     │
    │  Test (UE/Phone)  │
    └───────────────────┘
```

### 3.2 Transport Plugin Architecture

Il Test Program utilizza un'architettura **interface-first** dove il transport è completamente pluggable:

**Interfaccia astratta** (`interfaces.py`):
```python
class SipTransport(SipMessageSender, SipMessageReader, ABC):
    @abstractmethod
    def open(self) -> None: ...
    
    @abstractmethod
    def close(self) -> None: ...
    
    @abstractmethod
    def send(self, device: DeviceProfile, raw_message: str, context: Mapping[str, Any]) -> str:
        """Send SIP message and return correlation ID"""
        ...
    
    @abstractmethod
    def read(self, device: DeviceProfile, correlation_id: str, timeout_seconds: float) -> Sequence[SipResponse]:
        """Collect SIP responses from device under test"""
        ...
```

**Due implementazioni fornite**:

1. **StubSipTransport** (`adapters.py`):
   - Transport di sviluppo offline
   - Restituisce risposte SIP inscenate da configurazione YAML
   - Utile per testing deterministico senza infrastruttura reale
   - Non contatta elementi di rete reali

2. **SipProxyHttpTransport** (`adapters.py`):
   - HTTP bridge verso sip_proxy tester API
   - Comunica tramite REST JSON
   - Supporta auto-discovery di dispositivi da SIP REGISTER
   - Implementa regole live-edit per intercettazione di messaggi

## 4. Protocolli Utilizzati

### 4.1 SIP (Session Initiation Protocol)

**Versione**: SIP/2.0 (RFC 3261)

**Metodi SIP testati**:
- `REGISTER` - Registrazione IMS
- `INVITE` - Iniziazione sessione
- `CANCEL` - Cancellazione sessione
- Risposte (1xx, 2xx, 3xx, 4xx, 5xx, 6xx)

**Parsing SIP in sip_proxy.py**:
```python
class SIPMessage:
    - start_line: first line (INVITE sip:... SIP/2.0 or SIP/2.0 200 OK)
    - headers: list of header lines
    - body: message body
    
    Methods:
    - is_response: bool (check if SIP/2.0 response)
    - method: str (extract method name)
    - get_header(name): extract single header
    - get_headers(name): extract all headers (multi-valued)
    - set_header/remove_header/insert_header: modifica headers
    - to_bytes(): serializa to network bytes
    - parse(): deserializza da network bytes
```

### 4.2 HTTP (per comunicazione Test Program ↔ SIP Proxy)

**Versione**: HTTP/1.1

**Endpoints API del SIP Proxy** (definiti in `adapters.py`):

| Endpoint | Metodo | Scopo |
|----------|--------|-------|
| `/health` | GET | Health check del proxy |
| `/tester/send` | POST | Invia messaggio SIP al dispositivo |
| `/tester/read` | POST | Legge risposte SIP da dispositivo |
| `/tester/live-edit-rules` | GET/POST/DELETE | Gestisce regole di intercettazione |
| `/tester/live-edit-rules/invite-content-type` | POST | Specifica live-edit per INVITE Content-Type |
| `/tester/live-edit-wait` | POST | Attende evento live-edit |
| `/tester/discovered-devices` | GET | Lista dispositivi auto-scoperti |

**Formato JSON dei payload HTTP**:

Esempio `/tester/send` request:
```json
{
  "correlation_id": "unique-uuid-hex",
  "raw_message": "REGISTER sip:ims.mnc001.mcc001.3gppnetwork.org SIP/2.0\r\n...",
  "target_uri": "sip:192.0.2.100:5060",
  "submit_timeout_seconds": 10.0
}
```

Esempio `/tester/send` response:
```json
{
  "correlation_id": "unique-uuid-hex",
  "status": "submitted"
}
```

Esempio `/tester/read` request:
```json
{
  "correlation_id": "unique-uuid-hex",
  "timeout_seconds": 3.0
}
```

Esempio `/tester/read` response:
```json
{
  "responses": [
    {
      "raw_message": "SIP/2.0 401 Unauthorized\r\n...",
      "status_code": 401,
      "reason_phrase": "Unauthorized",
      "headers": {"via": ["SIP/2.0/UDP ..."], ...},
      "body": ""
    }
  ]
}
```

### 4.3 UDP/TCP (per comunicazione SIP Proxy ↔ Dispositivi)

**Protocollo**: SIP/2.0 nativo

**Porte standard**:
- SIP Proxy ascolta su: 5062 (UDP) [configurabile `SIP_PROXY_LISTEN_PORT`]
- P-CSCF (core): 5060 (UDP/TCP) [configurabile `SIP_PROXY_PCSCF_PORT`]
- Dispositivi: genericamente 5060+

**Formato transport**: Raw bytes SIP (non JSON)

## 5. Flusso di Esecuzione End-to-End

### 5.1 Fase 1: Inizializzazione

```python
# cli.py -> main() entry point
runtime_config = load_yaml(runtime_config_path)
test_suite = load_yaml(test_config_path)

# Istanzia transport based on runtime_config.transport.name
transport = create_transport(runtime_config.transport)
transport.open()  # Connette verso sip_proxy (HTTP health check)
```

### 5.2 Fase 2: Selezione Device

```python
# Se no --device specified, scopri disponibili
if auto_discovery_enabled:
    # Per sip-proxy-http: chiama GET /tester/discovered-devices
    devices = transport.read_discovered_devices()  # SIP REGISTER intercettati
else:
    # Usa dispositivi da runtime config o file
    devices = runtime_config.devices
```

### 5.3 Fase 3: Esecuzione Test per Device

```python
for test_case in suite.cases:
    # Applica edits al template SIP message
    rendered_message = modifier.apply(
        template=test_case.message.template,
        edits=test_case.message.edits
    )
    
    # Invia messaggio SIP tramite transport
    # (per sip-proxy-http: POST /tester/send con raw SIP)
    correlation_id = transport.send(device, rendered_message, context)
    
    # Attende risposta SIP
    # (per sip-proxy-http: POST /tester/read con polling)
    responses = transport.read(device, correlation_id, timeout_seconds)
    
    # Valida risposta contro expected_response
    case_result = validate_response(responses, test_case.expected_response)
```

### 5.4 Fase 4: Reporting

```python
report = ComplianceReport(
    suite_id=suite.suite_id,
    total_cases=len(suite.cases),
    passed_cases=count_passed,
    case_results=[...],
    started_at_utc=...,
    finished_at_utc=...
)
# Stampa/salva report (JSON, YAML, human-readable)
```

## 6. Metodi e API Dettagliati

### 6.1 CLI Commands (`cli.py`)

```bash
ims-tester validate --test-config FILE
  # Valida schema YAML del test suite

ims-tester list-devices --runtime-config FILE
  # Lista dispositivi configurati + scoperti da REGISTER

ims-tester run-standard --test-config FILE --runtime-config FILE [--device ID]
  # Esegui modalità standard (expected-response checks)
  # Se no --device, prompt interattivo

ims-tester compare --test-config FILE --runtime-config FILE --device-a ID --device-b ID
  # Esegui modalità differenziale (compare due dispositivi)

ims-tester live-edit-list --runtime-config FILE
  # Stampa regole live-edit attive in sip_proxy

ims-tester live-edit-clear --runtime-config FILE
  # Rimuovi tutte le regole live-edit attive
```

### 6.2 Message Editing Interface (`editor.py`, `interfaces.py`)

**Operazioni supportate su template SIP**:

```python
@dataclass(frozen=True)
class MessageEdit:
    target: str          # "header", "body", "uri", "start-line"
    action: str          # "replace", "corrupt", "remove", "insert"
    field: str           # header name o URI part
    value: str           # nuovo valore
    pattern: str         # regex pattern (per replace)
    replacement: str     # sostituzione (per replace)
```

Esempi:
```yaml
edits:
  - target: header
    action: corrupt
    field: Contact
    value: <sip:broken>
  
  - target: header
    action: remove
    field: Authorization
  
  - target: body
    action: replace
    pattern: 'SDP.*'
    replacement: 'new-sdp-value'
```

### 6.3 SIP Proxy Tester API (`sip_proxy.py`)

**Componenti interni SIP Proxy**:

1. **Transaction tracking**:
   - Mappa: `branch|cseq` → inbound `Endpoint`
   - Mappa: `branch|cseq` → upstream Via headers
   - Correlazione: transaction tester → transaction proxy

2. **Device discovery**:
   - Intercetta SIP REGISTER incoming
   - Estrae `Contact` header → device IP/port
   - Mappa: `device_key` → `DeviceProfile` (host, port, display_name, metadata)
   - Max 512 entries (configurable `SIP_PROXY_DISCOVERED_REGISTER_MAX_ENTRIES`)

3. **Live edit rules**:
   - Regole di trasformazione SIP in real-time
   - Attivabili via HTTP API
   - Supportate operazioni:
     - Rewrite SDP Content-Type su INVITE
     - Injeziona header
     - Modifica URI

4. **Tester response buffering**:
   - Per ogni correlation_id: buffer risposte SIP
   - Max 32 risposte buffered (configurable `SIP_PROXY_TESTER_MAX_BUFFERED_RESPONSES`)
   - Event signaling quando risposta arriva
   - API: GET /tester/read con timeout

### 6.4 Domain Models (`models.py`)

```python
@dataclass(frozen=True)
class DeviceProfile:
    device_id: str                    # ID unico (es. "pixel_8")
    display_name: str                 # Nome leggibile
    address: str                      # IP del dispositivo
    metadata: Dict[str, Any]          # Metadata custom (OS, vendor, etc.)

@dataclass(frozen=True)
class MessageSpec:
    message_type: str                 # "REGISTER", "INVITE", etc.
    template: str                     # Raw SIP template
    edits: List[MessageEdit]          # Modifiche pre-send
    intercept_edits: List[MessageEdit]  # Modifiche su intercettazione
    intercept_only: bool              # Solo intercettazione (no send)
    intercept_message_type: str       # Tipo messaggio da intercettare ("*" = any)
    intercept_direction: str          # "request" o "response"
    intercept_wait_timeout_seconds: float  # Timeout attesa

@dataclass(frozen=True)
class ExpectedResponse:
    status_code: Optional[int]        # Es. 200, 401, etc.
    reason_contains: List[str]        # Reason phrase deve contenere
    header_contains: Dict[str, str]   # Headers che deve contenere
    header_absent: List[str]          # Headers assenti
    body_contains: List[str]          # Body deve contenere

@dataclass(frozen=True)
class TestCase:
    case_id: str
    description: str
    message: MessageSpec
    expected_response: ExpectedResponse
    timeout_seconds: Optional[float]

@dataclass(frozen=True)
class SipResponse:
    raw_message: str                  # Raw SIP
    status_code: int                  # 200, 401, etc.
    reason_phrase: str                # "OK", "Unauthorized", etc.
    headers: Dict[str, List[str]]     # Parsed headers
    body: str                         # Message body
```

## 7. Configurazione Runtime YAML

### 7.1 Configurazione Stub Transport

```yaml
transport:
  name: stub
  settings:
    default_status: 501
    default_reason: Not Implemented
    simulated_latency_seconds: 0.05
    canned_responses:
      pixel_8:
        REGISTER:
          - |
            SIP/2.0 401 Unauthorized
            Via: SIP/2.0/UDP 192.0.2.100:5060;branch=z9hG4bK-1
            Content-Length: 0
      _default:
        REGISTER:
          - |
            SIP/2.0 400 Bad Request
            Content-Length: 0

devices:
  - id: pixel_8
    name: Pixel 8
    address: 192.168.10.21
    metadata:
      os: Android 14
      vendor: Google
```

### 7.2 Configurazione SIP Proxy HTTP Transport

```yaml
transport:
  name: sip-proxy-http
  settings:
    api_base_url: http://127.0.0.1:8088
    send_path: /tester/send
    read_path: /tester/read
    health_path: /health
    live_edit_rules_path: /tester/live-edit-rules
    live_edit_invite_content_type_path: /tester/live-edit-rules/invite-content-type
    live_edit_wait_path: /tester/live-edit-wait
    discovered_devices_path: /tester/discovered-devices
    request_timeout_seconds: 10
    default_target_port: 5060
    default_target_transport: udp
    check_health_on_open: true

# Opzionale: auto-discovery da REGISTER intercettati
devices: []
```

## 8. Intercettazione Live (Live Edit)

### 8.1 Caso Use: INVITE Content-Type Rewrite

```yaml
message:
  type: INVITE
  template: |
    INVITE sip:user@domain.org SIP/2.0
    ...
  intercept_edits:
    - target: header
      action: replace
      field: Content-Type
      value: application/custom
  intercept_message_type: INVITE
  intercept_direction: request
  intercept_wait_timeout_seconds: 30.0
  intercept_only: false  # invia + intercetta
```

### 8.2 Caso Use: Intercept-Only (no send)

```yaml
message:
  intercept_only: true      # Non inviare, solo attendere traffico
  intercept_message_type: REGISTER
  intercept_direction: response
  intercept_wait_timeout_seconds: 30.0
```

**Flusso API HTTP**:
1. `POST /tester/live-edit-rules` - Registra regola intercettazione
2. `POST /tester/live-edit-wait` - Attende evento live-edit (long-poll)
3. `POST /tester/read` - Legge risposte da correlazione

## 9. Exit Codes

| Code | Significato |
|------|-------------|
| 0 | Successo |
| 2 | Errore validazione configurazione |
| 10 | run-standard completato ma almeno 1 test fallito |
| 11 | compare completato e differenze trovate |

## 10. Variabili di Ambiente (SIP Proxy)

```bash
# Configurazione ascolto SIP
SIP_PROXY_LISTEN_IP=0.0.0.0          # IP ascolto SIP
SIP_PROXY_LISTEN_PORT=5062           # Porta ascolto SIP

# Configurazione API HTTP
SIP_PROXY_API_LISTEN_IP=0.0.0.0      # IP ascolto API
SIP_PROXY_API_PORT=8088              # Porta API
SIP_PROXY_API_ENABLED=true

# Routing
SIP_PROXY_PCSCF_IP=                  # IP P-CSCF (opz.)
SIP_PROXY_PCSCF_PORT=5060
SIP_PROXY_DEFAULT_CORE_IP=           # IP core default
SIP_PROXY_DEFAULT_CORE_PORT=4060

# Advertissement
SIP_PROXY_ADVERTISED_HOST=0.0.0.0
SIP_PROXY_ROUTE_USER=sipproxy

# Logging e behavior
SIP_PROXY_LOG_MESSAGES=false
SIP_PROXY_INSERT_RECORD_ROUTE=true
SIP_PROXY_ALLOW_UNSAFE_LIVE_INVITE_SDP_REWRITE=false

# Tester-specific
SIP_PROXY_TESTER_MAX_BUFFERED_RESPONSES=32
SIP_PROXY_TESTER_ROUTE_VIA_PCSCF=true
SIP_PROXY_DISCOVERED_REGISTER_MAX_ENTRIES=512
SIP_PROXY_LIVE_EDIT_MAX_BUFFERED_HITS=256

# Rewrite rules (JSON)
SIP_PROXY_REWRITE_RULES='[]'
```

## 11. Flusso Dettagliato: run-standard

```
┌─ CLI: run-standard --test-config X.yaml --runtime-config Y.yaml [--device ID]
│
├─ Load Y.yaml (runtime config) → RuntimeConfig object
│
├─ Load X.yaml (test suite) → TestSuite object
│
├─ Istanzia transport (stub o sip-proxy-http)
│
├─ transport.open()
│   └─ (sip-proxy-http): GET /health → verifica proxy
│
├─ Se no --device:
│   ├─ transport.read_discovered_devices()
│   │  └─ (sip-proxy-http): GET /tester/discovered-devices
│   └─ Prompt interattivo per scelta
│
├─ ComplianceTestRunner.run(suite, device)
│   │
│   └─ for each test_case in suite.cases:
│       │
│       ├─ Se intercept rules:
│       │  └─ transport._replace_live_edit_rules(rules)
│       │     └─ (sip-proxy-http): DELETE /tester/live-edit-rules (clear existing)
│       │     └─ (sip-proxy-http): POST /tester/live-edit-rules (add new)
│       │
│       ├─ render_message = modifier.apply(template, edits)
│       │
│       ├─ correlation_id = transport.send(device, render_message, context)
│       │  └─ (sip-proxy-http): POST /tester/send
│       │     {
│       │       "correlation_id": UUID,
│       │       "raw_message": render_message,
│       │       "target_uri": device.address,
│       │       "submit_timeout_seconds": X
│       │     }
│       │
│       ├─ responses = transport.read(device, correlation_id, timeout)
│       │  └─ (sip-proxy-http): POST /tester/read
│       │     {
│       │       "correlation_id": UUID,
│       │       "timeout_seconds": X
│       │     }
│       │     Loop fino a risposta o timeout
│       │
│       ├─ validate_response(responses, expected_response)
│       │  ├─ Check: status_code match?
│       │  ├─ Check: reason_phrase contains?
│       │  ├─ Check: required headers present?
│       │  ├─ Check: required headers absent?
│       │  └─ Check: body contains strings?
│       │
│       └─ case_result = CaseResult(passed=..., details=...)
│
├─ report = ComplianceReport(...)
│
├─ Stampa/salva report
│
├─ transport.close()
│
└─ exit(0 if all passed else 10)
```

## 12. Differenze tra Transport Implementations

| Aspetto | Stub | SIP Proxy HTTP |
|---------|------|----------------|
| **Dipendenze esterne** | Nessuna | sip_proxy running on 127.0.0.1:8088 |
| **Device discovery** | Da config YAML | Auto-discovery da SIP REGISTER |
| **Latenza simulata** | Configurable | Real network latency |
| **Uso** | Dev/testing offline | Production conformance testing |
| **Determinismo** | 100% deterministico | Non deterministico (dipende device) |
| **Live edit** | Non supportato | Completamente supportato |
# Test Program HTTP integration con sip_proxy

Questo documento descrive solo il canale HTTP tra il Test Program e `sip_proxy`: come viene usato, quali endpoint vengono chiamati e come funziona l'attesa delle risposte. Non tratta il resto dell'architettura e non entra nel codice.

## Cosa fa il canale HTTP

Quando il Test Program usa il backend `sip-proxy-http`, non parla direttamente SIP con il telefono. Invia richieste HTTP JSON al proxy, e il proxy si occupa del traffico SIP reale verso il dispositivo.

Il canale HTTP serve per:

1. verificare che il proxy sia disponibile
2. inviare un messaggio SIP verso il dispositivo
3. leggere le risposte associate a quel messaggio
4. ottenere l'elenco dei device scoperti da REGISTER
5. configurare o leggere le regole di live edit

## Implementazione lato Test Program

L'implementazione HTTP sta in `SipProxyHttpTransport`. Usa `urllib.request` e scambia JSON.

Comportamento essenziale:

1. all'apertura fa una GET su `/health`
2. per inviare usa una POST su `/tester/send`
3. per leggere usa una POST su `/tester/read`
4. per i device auto-discover usa una GET su `/tester/discovered-devices`
5. per le regole live edit usa GET, POST e DELETE su `/tester/live-edit-rules`
6. per l'attesa di un evento live edit usa una POST su `/tester/live-edit-wait`

Il payload contiene sempre JSON. Il messaggio SIP vero e proprio passa come testo grezzo nel campo `raw_message`.

## Endpoint usati

| Endpoint | Metodo | Scopo |
|---|---|---|
| `/health` | GET | Controllo iniziale di disponibilita |
| `/tester/send` | POST | Invia il messaggio SIP al proxy |
| `/tester/read` | POST | Recupera le risposte legate a una correlation id |
| `/tester/discovered-devices` | GET | Elenca i dispositivi scoperti |
| `/tester/live-edit-rules` | GET | Legge le regole attive |
| `/tester/live-edit-rules` | POST | Aggiunge o sostituisce regole |
| `/tester/live-edit-rules` | DELETE | Rimuove le regole attive |
| `/tester/live-edit-rules/invite-content-type` | POST | Regola specifica per INVITE |
| `/tester/live-edit-wait` | POST | Attende un hit di live edit |

## Polling o altro

Dal lato del Test Program **non c'e polling continuo**.

Il flusso di lettura funziona cosi:

1. il programma fa una POST su `/tester/read` con `correlation_id` e `timeout_seconds`
2. il proxy controlla se ci sono gia risposte nel buffer
3. se ci sono, le restituisce subito
4. se non ci sono, il proxy aspetta un evento interno fino al timeout richiesto
5. quando arriva una risposta, il proxy la sblocca e la restituisce

Quindi il meccanismo e piu vicino a un **long polling server-side con event waiting** che a un polling periodico del client.

## Implementazione lato sip_proxy

Sul proxy le risposte vengono memorizzate per `correlation_id` in un buffer dedicato. Quando arriva una nuova risposta, il proxy segnala un evento asincrono; la chiamata HTTP a `/tester/read` resta in attesa fino a quando:

1. arriva almeno una risposta
2. scade il timeout richiesto

Lo stesso modello vale per `/tester/live-edit-wait`, che aspetta un evento di intercettazione invece di fare polling ripetuto.

## Flusso tipico

1. il Test Program fa `GET /health`
2. se serve, fa `GET /tester/discovered-devices`
3. invia il messaggio con `POST /tester/send`
4. aspetta la risposta con `POST /tester/read`
5. opzionalmente legge o aggiorna le regole live edit

## Dettagli utili

La destinazione SIP viene risolta dal Test Program in questo ordine:

1. `context.target_uri`
2. `device.metadata.target_uri`
3. `device.address`

L'invio usa un `correlation_id` generato dal client, e la lettura usa la stessa chiave per recuperare le risposte corrette.

## In sintesi

Il canale HTTP tra Test Program e `sip_proxy` e un bridge JSON sopra HTTP. Il programma invia un messaggio con POST e poi fa una singola read con timeout. Non c'e polling continuo lato client; la waiting logic e gestita dal proxy con buffer e eventi asincroni.
