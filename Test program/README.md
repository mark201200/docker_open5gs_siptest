# IMS Smartphone Test CLI

Class-based Python CLI for IMS SIP testing in two modes:

1. Standard-based check: send crafted SIP messages and validate response against expected values in a test file.
2. Differential check: run the same test against two phones and report response differences.

The code is interface-first so transport and message I/O backends can be implemented later (Kamailio route relay, proxy container integration, etc.) without changing the test engine.

## Project Structure

- ims_tester/models.py: domain models and report models.
- ims_tester/interfaces.py: interfaces for message send/read/modify and transport factory.
- ims_tester/editor.py: default SIP message modifier implementation.
- ims_tester/adapters.py: pluggable transport registry with `stub` and `sip-proxy-http` backends, plus device discoverers.
- ims_tester/config.py: YAML config loaders and validation.
- ims_tester/engine.py: standard and differential runners.
- ims_tester/cli.py: command line app.
- docs/test-config.md: schema documentation for test suite files.
- docs/runtime-config.md: schema documentation for runtime files.
- docs/discovery-methods.md: documentation for device discovery methods (sip-proxy vs open5gs).
- docs/user-manual.md: user manual with CLI modes and commands.
- examples/: sample YAML files.

## Quick Start

1. Create/activate a Python environment.
2. Install dependencies:

   pip install -r requirements.txt

3. Validate the sample test suite:

   python main.py validate --test-config examples/test_suite_register.yaml

4. List available devices (configured + auto-discovered from SIP REGISTER when using sip-proxy-http):

   python main.py list-devices --runtime-config examples/runtime_stub.yaml

5. Run standard mode with an explicit device:

   python main.py run-standard --test-config examples/test_suite_register.yaml --runtime-config examples/runtime_stub.yaml --device pixel_8

6. Run standard mode without `--device` (interactive selection from generated device list):

   python main.py run-standard --test-config examples/test_suite_register.yaml --runtime-config examples/runtime_sip_proxy_http.yaml

   In the prompt, enter one or more device numbers or IDs separated by commas, for example `1,2` or `1,2,3`.

7. Run differential mode:

   python main.py compare --test-config examples/test_suite_register.yaml --runtime-config examples/runtime_stub.yaml --device-a pixel_8 --device-b galaxy_s24

8. Run against the real sip_proxy tester API:

   python main.py run-standard --test-config examples/test_suite_register.yaml --runtime-config examples/runtime_sip_proxy_http.yaml

9. Run YAML-driven live interception (send + intercept; defined inside test file):

   python main.py run-standard --test-config examples/test_suite_invite_intercept_content_type_test.yaml --runtime-config examples/runtime_sip_proxy_http.yaml

10. Run intercept-only mode (wait for matching live traffic, no template send):

   python main.py run-standard --test-config examples/test_suite_invite_intercept_only_content_type_test.yaml --runtime-config examples/runtime_sip_proxy_http.yaml

11. Optional manual rule inspection:

   python main.py live-edit-list --runtime-config examples/runtime_sip_proxy_http.yaml

12. Optional manual rule clear:

   python main.py live-edit-clear --runtime-config examples/runtime_sip_proxy_http.yaml

## Command Summary

- validate: validates a test suite YAML file.
- list-devices: prints configured devices plus SIP REGISTER-discovered devices (sip-proxy-http).
- run-standard: executes expected-response checks for one or more devices; if `--device` is omitted, prompts from available devices.
- compare: executes two-device response comparison.
- live-edit-list: prints currently active ims_proxy live edit rules.
- live-edit-clear: removes all active ims_proxy live edit rules.

Note: `message.intercept_only: true` cases are supported in `run-standard` mode.

Exit codes:

- 0: success.
- 2: configuration validation error.
- 10: run-standard completed but at least one case failed.
- 11: compare completed and differences were found.

## Interface-First Design

Transports are pluggable. This project includes:

- `stub` for deterministic/offline runs
- `sip-proxy-http` for real communication through the `sip_proxy` tester API

When using `sip-proxy-http`, runtime YAML can omit `devices` and rely on auto-discovery from observed SIP REGISTER traffic.

You can still add more backends later by implementing:

- SipMessageSender
- SipMessageReader
- SipMessageModifier
- SipTransport

See docs/runtime-config.md for how backend selection is configured.
