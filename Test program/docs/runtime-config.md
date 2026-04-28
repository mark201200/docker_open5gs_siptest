# Runtime Configuration (YAML)

This file defines execution context, not test logic:

- Which transport backend is used.
- Which devices are available for execution and comparison.

This separation keeps your test suite reusable across phones and transport methods.

## Top-Level Schema

- transport (mapping, required)
  - name (string, required)
  - settings (mapping, optional)
- devices (list, optional for sip-proxy-http, otherwise required)
  - id (string, required, unique)
  - name (string, optional)
  - address (string, required)
  - metadata (mapping, optional)

Available transport backend names:

- stub
- sip-proxy-http

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

REGISTER auto-discovery behavior:

- `sip_proxy` tracks SIP REGISTER traffic and builds an in-memory inventory of discovered devices.
- Each discovered record includes inferred subscriber identities and device IP (from Contact URI).
- Identity metadata keeps both `imsi` and `phone_number` when available.
- `sip_proxy` also inspects `SUBSCRIBE` requests as identity hints and can enrich existing discovered records with a phone number.
- `ims_tester` fetches this list from `/tester/discovered-devices` and merges it with statically configured `devices`.
- If `run-standard` is executed without `--device`, the CLI prompts from the merged list.
- If `transport.name` is `sip-proxy-http`, you may set `devices: []` and rely fully on discovery.

Device address resolution for this backend:

- If `device.metadata.target_uri` exists, it is used directly.
- Else `device.address` is converted to SIP URI.
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
