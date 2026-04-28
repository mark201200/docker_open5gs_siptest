# Test Suite Configuration (YAML)

This file defines the test logic itself:

- Which SIP message template to send.
- Which fields to edit/corrupt.
- Optional intercept-only rules that wait for live traffic instead of sending a template.
- Repetition policy (count/rate).
- Expected response checks.

Device selection and transport backend are not defined here. They are defined in runtime config.

## Top-Level Schema

- suite (mapping, required)
  - id (string, required)
  - title (string, optional)
  - default_timeout_seconds (number > 0, optional, default: 3.0)
- tests (list, required, at least one)

## Per-Test Schema

- id (string, required, unique)
- description (string, optional)
- timeout_seconds (number > 0, optional; overrides suite default)
- message (mapping, required)
  - type (string, required): SIP method identifier like REGISTER, INVITE, MESSAGE.
  - template (string, required unless intercept_only=true): full SIP message template.
  - edits (list, optional)
  - intercept_edits (list, optional)
  - intercept_only (boolean, optional, default: false)
  - intercept_message_type (string, optional, default: message.type): method filter for intercept rules and wait (use ANY or * for wildcard)
  - intercept_direction (string, optional, default: request): request, response, or any
  - intercept_wait_timeout_seconds (number > 0, optional, default: 30.0)
  - repeat (mapping, optional)
    - count (integer >= 1, default: 1)
    - rate_per_second (number > 0, default: 1.0)
- expected_response (mapping, recommended)
  - status_code (integer, optional)
  - reason_contains (list[string], optional)
  - header_contains (mapping header->substring, optional)
  - header_absent (list[string], optional)
  - body_contains (list[string], optional)

## Edit Operations

Each edit item:

- target: one of start_line, header, body.
- action: one of set, remove, append, corrupt.
- field: required when target=header.
- value: optional; used by set/append/corrupt.
- pattern: optional regex used by corrupt.
- replacement: optional replacement for pattern.

Notes:

- start_line does not support remove.
- Content-Length is not recalculated automatically; malformed header/body combinations are preserved.

## Device Placeholders in Template and Edits

When running a case against a selected device, placeholder variables can be used
inside `message.template` and `message.edits[*].value`.

Supported placeholders:

- `$DEVICE_ID`: runtime device id.
- `$DEVICE_NAME`: runtime display name.
- `$DEVICE_ADDRESS`: runtime address.
- `$PHONE`: raw subscriber number used for addressing (prefers phone number, falls back to IMSI).
- `$PHONE_NUMBER`: raw phone number from device metadata.
- `$PHONE_SIP_URI`: `sip:<phone_or_imsi>`.
- `$PHONE_TEL_URI`: `tel:<phone_or_imsi>`.
- `$IMSI`: IMSI from device metadata.
- `$IMSI_URI`: `sip:<imsi>` when available.

Phone lookup reads metadata keys in this order: `phone_number`, `phone`, `msisdn`.

Example:

```yaml
message:
  type: INVITE
  template: |
    INVITE sip:placeholder@example.com SIP/2.0
    To: <sip:placeholder@example.com>
    Content-Length: 0

  edits:
    - target: start_line
      action: set
      value: INVITE tel:$PHONE;phone-context=ims.mnc001.mcc001.3gppnetwork.org SIP/2.0
    - target: header
      action: set
      field: To
      value: <sip:$PHONE;phone-context=ims.mnc001.mcc001.3gppnetwork.org>
```

## Intercept Edits

Use `message.intercept_edits` to declare live in-proxy rewrites for this test case.
These rules are applied through `ims_proxy` before case traffic is sent or waited on.

Supported combinations:

- target=header with action=set or remove
- target=start_line with action=set
- target=body with action=set

`message.intercept_edits` uses the same item structure as `message.edits`
(`target`, `action`, `field`, `value`, etc.), but with the constraints above.

Notes:

- Rules are scoped to `message.intercept_message_type` (default: `message.type`).
- Rule direction uses `message.intercept_direction`.
- In `run-standard`, live intercept rules are automatically scoped to the selected device:
  `request` matches packets coming from the selected device host, `response` matches packets sent to the selected device host, and `any` matches either direction.
  Device host is derived from `device.metadata.target_uri` when present, otherwise from `device.address`.
  To stay reliable on proxy/core-facing legs, matching also uses SIP identity metadata (`phone_number`/`phone`/`msisdn`, `imsi`) when available.
- Runners clear proxy live rules automatically after the run.
- For INVITE Content-Type fuzzing on real calls, use `intercept_direction: request`.
  Rewriting INVITE responses can break PRACK/offer-answer negotiation.
- By default, `sip_proxy` skips live (non-tester) INVITE SDP `Content-Type`/`Content-Length`
  rewrites to avoid destabilizing call setup. Override only when needed with
  `SIP_PROXY_ALLOW_UNSAFE_LIVE_INVITE_SDP_REWRITE=true`.

## Intercept-Only Mode

Set `message.intercept_only: true` when you want the test runner to passively wait for real SIP traffic instead of sending `message.template`.

In this mode:

- `message.template` is not required.
- At least one `message.intercept_edits` item is required.
- Runner waits up to `message.intercept_wait_timeout_seconds` (or case/suite timeout overrides) for a matching live proxy hit.
- Case iteration passes when a matching intercepted message is observed.
- `expected_response` can be omitted or set to `{}` because no sent-message response is asserted.

## Example

```yaml
suite:
  id: ims_register_checks
  title: IMS REGISTER robustness checks
  default_timeout_seconds: 3.0

tests:
  - id: register_corrupt_contact
    description: Corrupt Contact header and expect rejection
    message:
      type: REGISTER
      template: |
        REGISTER sip:ims.mnc001.mcc001.3gppnetwork.org SIP/2.0
        Via: SIP/2.0/UDP 192.0.2.100:5060;branch=z9hG4bK-1
        From: <sip:001010123456789@ims.mnc001.mcc001.3gppnetwork.org>;tag=1234
        To: <sip:001010123456789@ims.mnc001.mcc001.3gppnetwork.org>
        Call-ID: reg-1@tester
        CSeq: 1 REGISTER
        Contact: <sip:001010123456789@192.0.2.100:5060>
        Max-Forwards: 70
        Content-Length: 0

      edits:
        - target: header
          action: corrupt
          field: Contact
          value: <sip:broken-contact>
      repeat:
        count: 2
        rate_per_second: 1.0
    expected_response:
      status_code: 400
      reason_contains:
        - bad

  - id: invite_add_unknown_header
    description: Add vendor header and inspect response consistency
    message:
      type: INVITE
      template: |
        INVITE sip:alice@example.com SIP/2.0
        Via: SIP/2.0/UDP 192.0.2.100:5060;branch=z9hG4bK-2
        From: <sip:bob@example.com>;tag=222
        To: <sip:alice@example.com>
        Call-ID: call-1@tester
        CSeq: 1 INVITE
        Max-Forwards: 70
        Content-Length: 0

      edits:
        - target: header
          action: append
          field: X-Thesis-Test
          value: case-invite-unknown-header
      intercept_edits:
        - target: header
          action: set
          field: Content-Type
          value: TEST
    expected_response:
      status_code: 100
```
