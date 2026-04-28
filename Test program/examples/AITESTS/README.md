# AITESTS SIP Malformed Suites

This folder contains aggressive malformed SIP tests that use:

- send mode (`message.template` with optional `edits`)
- intercept-only mode (`intercept_only: true` + `intercept_edits`)
- combined send + intercept mode (send a template and mutate live traffic in proxy)

## Files

- `test_suite_ai_send_invite_malformed.yaml`
- `test_suite_ai_send_register_malformed.yaml`
- `test_suite_ai_intercept_only_live_mutations.yaml`
- `test_suite_ai_send_and_intercept_combo.yaml`

## Example commands

```bash
cd "Test program"
python main.py validate --test-config examples/AITESTS/test_suite_ai_send_invite_malformed.yaml
python main.py validate --test-config examples/AITESTS/test_suite_ai_intercept_only_live_mutations.yaml
python main.py run-standard --test-config examples/AITESTS/test_suite_ai_send_and_intercept_combo.yaml --runtime-config examples/runtime_sip_proxy_http.yaml --device pixel_8
```

## Notes

- These suites intentionally violate SIP expectations and may trigger unstable behavior.
- Start with one suite at a time and monitor proxy/phone logs while running.
- Keep your lab isolated from production networks.
- `test_suite_ai_send_invite_malformed.yaml` now uses IMS-like identity/security headers first, then applies malformed elements, which improves forwarding beyond P-CSCF pre-checks.
- REGISTER cases are core-path robustness checks (P-CSCF to IMS core) and are not expected to terminate on the called phone.
