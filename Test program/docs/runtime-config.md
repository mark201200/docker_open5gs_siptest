# Runtime Configuration (YAML)

This file defines execution context, not test logic:

- Which transport backend is used.
- Which devices are available for execution and comparison.

This separation keeps your test suite reusable across phones and transport methods.

## Top-Level Schema

- transport (mapping, required)
  - name (string, required)
  - settings (mapping, optional)
- discovery (mapping, optional)
  - method (string, optional, default: sip-proxy) - `sip-proxy` or `open5gs`
  - settings (mapping, optional) - method-specific settings
- devices (list, optional for sip-proxy-http, otherwise required)
  - id (string, required, unique)
  - name (string, optional)
  - address (string, required)
  - metadata (mapping, optional)

Available transport backend names:

- stub
- sip-proxy-http
- kamailio-forward

Available discovery methods:

- `sip-proxy` (default) - Auto-discover devices from SIP REGISTER traffic via sip-proxy-http
- `open5gs` - Discover devices from Open5GS pdu-info API + MongoDB

## Device Discovery Methods

### SIP REGISTER Discovery (sip-proxy)

This is the default method. Requires `transport.name: sip-proxy-http`.

Behavior:

- `sip_proxy` tracks SIP REGISTER traffic and builds an in-memory inventory of discovered devices.
- Each discovered record includes inferred subscriber identities and device IP (from Contact URI).
- Identity metadata keeps both `imsi` and `phone_number` when available.
- `sip_proxy` also inspects `SUBSCRIBE` requests as identity hints and can enrich existing discovered records with a phone number.
- `ims_tester` fetches this list from `/tester/discovered-devices` and merges it with statically configured `devices`.
- If `run-standard` is executed without `--device`, the CLI prompts from the merged list and accepts comma-separated selections like `1,2,3`.
- When multiple devices are selected for `run-standard`, the CLI automatically switches to differential comparison mode.
- If `transport.name` is `sip-proxy-http`, you may set `devices: []` and rely fully on discovery.

Example:

```yaml
discovery:
  method: sip-proxy
  # No settings required for sip-proxy method
```

### Open5GS Discovery (open5gs)

This method discovers devices from Open5GS using the pdu-info API and MongoDB.

Behavior:

- Queries Open5GS `/api/v1/subscribers` endpoint to get active PDU sessions with UE IP and IMSI
- Queries MongoDB `subscribers` collection to get phone numbers (MSISDN) by IMSI
- Returns devices with IMSI and phone number in metadata
- Device ID is derived from IMSI (format: `ue_<IMSI>`)
- Device address is the UE IP from PDU session

Required settings:

- `open5gs_api_url` (string, required) - Base URL of Open5GS API (e.g., `http://127.0.0.1:3000`)
- `mongodb_uri` (string, required) - MongoDB connection URI (e.g., `mongodb://127.0.0.1:27017`)

Optional settings:

- `mongodb_db` (string, optional, default: `open5gs`) - MongoDB database name
- `request_timeout_seconds` (number, optional, default: 10.0) - Timeout for API requests

Note: Requires `pymongo` package. Install with: `pip install pymongo`

Example:

```yaml
discovery:
  method: open5gs
  settings:
    open5gs_api_url: http://127.0.0.1:3000
    mongodb_uri: mongodb://127.0.0.1:27017
    mongodb_db: open5gs
    request_timeout_seconds: 10
```

## Stub Transport Settings

The current implementation provides a stub transport backend:

- default_status (integer, optional, default: 501)
- default_reason (string, optional, default: Not Implemented)
- simulated_latency_seconds (number, optional)
- canned_responses (mapping, optional)

Supported canned_responses forms:

1. Per-device with fallback:

```yaml
canned_responses:
  pixel_8:
    REGISTER:
      - |
        SIP/2.0 403 Forbidden
        Content-Length: 0
  _default:
    REGISTER:
      - |
        SIP/2.0 400 Bad Request
        Content-Length: 0
```

## SIP Proxy HTTP Transport Settings

Use this backend to communicate with `sip_proxy` through its tester API.

- api_base_url (string, required)
- send_path (string, optional, default: /tester/send)
- read_path (string, optional, default: /tester/read)
- health_path (string, optional, default: /health)
- live_edit_rules_path (string, optional, default: /tester/live-edit-rules)
- live_edit_invite_content_type_path (string, optional, default: /tester/live-edit-rules/invite-content-type)
- live_edit_wait_path (string, optional, default: /tester/live-edit-wait)
- discovered_devices_path (string, optional, default: /tester/discovered-devices)
- request_timeout_seconds (number, optional, default: 10.0)
- default_target_port (integer, optional, default: 5060)
- default_target_transport (string, optional: udp|tcp, default: udp)
- check_health_on_open (boolean, optional, default: true)

Device address resolution for this backend:

- If `device.metadata.target_uri` exists, it is used directly.
- Else `device.address` is converted to SIP URI.

Phone-number substitution for SIP templates:

- If `device.metadata.phone_number` exists (or `phone`/`msisdn`), it populates `$PHONE`, `$PHONE_NUMBER`, `$PHONE_SIP_URI`, and `$PHONE_TEL_URI`.
- Supported `device.address` forms: `host`, `host:port`, `sip:...`, `<sip:...>`.

Example:

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

# Optional for sip-proxy-http: rely on auto-discovered REGISTER inventory.
devices: []
```

## Kamailio Forward Transport Settings

Use this backend to send SIP test vectors to P-CSCF with a special header
that instructs Kamailio to forward the message directly to a target device.
It keeps IMS behavior unchanged for all other traffic.

P-CSCF must include a route that detects the target header and forwards the
request to the provided destination (see kamailio_pcscf.cfg changes).

- pcscf_host (string, required)
- pcscf_port (integer, optional, default: 5060)
- pcscf_transport (string, optional, default: udp) (only udp is supported)
- listen_host (string, optional, default: 0.0.0.0)
- listen_port (integer, optional, default: 0)
- advertised_host (string, required when listen_host is wildcard)
- target_header (string, optional, default: X-IMS-Tester-Target)
- inject_via (boolean, optional, default: true)
- via_branch_prefix (string, optional, default: z9hG4bK-ims-tester-)
- default_target_port (integer, optional, default: 5060)
- default_target_transport (string, optional: udp|tcp, default: udp)
- max_buffered_responses (integer, optional, default: 32)

Device address resolution for this backend:

- If `device.metadata.target_uri` exists, it is used directly.
- Else `device.address` is converted to SIP URI.

Example:

```yaml
transport:
  name: kamailio-forward
  settings:
    pcscf_host: 10.0.0.5
    pcscf_port: 5060
    pcscf_transport: udp
    listen_host: 0.0.0.0
    listen_port: 0
    advertised_host: 10.0.0.20
    target_header: X-IMS-Tester-Target
    inject_via: true
    default_target_port: 5060
    default_target_transport: udp

devices:
  - id: pixel_8
    name: Pixel 8
    address: 10.0.0.10
    metadata:
      phone_number: "15551234567"
```

2. Shorthand by method only:

```yaml
canned_responses:
  REGISTER:
    - |
      SIP/2.0 401 Unauthorized
      Content-Length: 0
```

## Example Runtime File

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
            SIP/2.0 403 Forbidden
            Via: SIP/2.0/UDP test.local;branch=z9hG4bK-1
            Content-Length: 0
      _default:
        REGISTER:
          - |
            SIP/2.0 400 Bad Request
            Via: SIP/2.0/UDP test.local;branch=z9hG4bK-2
            Content-Length: 0

devices:
  - id: pixel_8
    name: Pixel 8
    address: 192.168.10.21
    metadata:
      os: Android 14
      vendor: Google

  - id: galaxy_s24
    name: Galaxy S24
    address: 192.168.10.22
    metadata:
      os: Android 14
      vendor: Samsung
```

## Proxy-Side Requirements

The `sip_proxy` container must expose tester API endpoints and have API enabled:

- `SIP_PROXY_API_ENABLED=true`
- `SIP_PROXY_API_LISTEN_IP` and `SIP_PROXY_API_PORT` configured (defaults: `0.0.0.0:8088`)
- reachable from where `ims_tester` runs
