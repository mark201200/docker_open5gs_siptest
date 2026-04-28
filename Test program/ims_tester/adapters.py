from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable, Dict, List, Mapping

from .interfaces import SipTransport
from .models import DeviceProfile, SipResponse


class StubSipTransport(SipTransport):
    """
    Development transport.

    This does not contact real network elements. It returns canned SIP responses
    from runtime configuration so the CLI and test model can be exercised before
    Kamailio/proxy adapters are implemented.
    """

    def __init__(self, settings: Mapping[str, Any] | None = None) -> None:
        self.settings: Dict[str, Any] = dict(settings or {})
        self._opened = False
        self._sent_messages: Dict[str, Dict[str, Any]] = {}

    def open(self) -> None:
        self._opened = True

    def close(self) -> None:
        self._opened = False
        self._sent_messages.clear()

    def send(self, device: DeviceProfile, raw_message: str, context: Mapping[str, Any]) -> str:
        self._ensure_open()
        correlation_id = uuid.uuid4().hex
        self._sent_messages[correlation_id] = {
            "device_id": device.device_id,
            "method": self._extract_method(raw_message),
            "message": raw_message,
            "context": dict(context),
        }
        return correlation_id

    def read(self, device: DeviceProfile, correlation_id: str, timeout_seconds: float) -> List[SipResponse]:
        self._ensure_open()
        record = self._sent_messages.get(correlation_id)
        if record is None:
            return []

        latency = float(self.settings.get("simulated_latency_seconds", 0.0) or 0.0)
        if latency > 0:
            time.sleep(min(latency, timeout_seconds))

        method = str(record.get("method", "UNKNOWN"))
        raw_responses = self._resolve_canned_responses(device.device_id, method)
        if not raw_responses:
            status_code = int(self.settings.get("default_status", 501) or 501)
            reason = str(self.settings.get("default_reason", "Not Implemented") or "Not Implemented")
            raw_responses = [f"SIP/2.0 {status_code} {reason}\r\nContent-Length: 0\r\n\r\n"]

        return [SipResponse.parse(raw) for raw in raw_responses]

    def _ensure_open(self) -> None:
        if not self._opened:
            raise RuntimeError("Transport is not open")

    @staticmethod
    def _extract_method(raw_message: str) -> str:
        first_line = raw_message.replace("\r\n", "\n").split("\n", 1)[0].strip()
        if not first_line:
            return "UNKNOWN"
        if first_line.upper().startswith("SIP/2.0"):
            return "RESPONSE"
        return first_line.split(" ", 1)[0].upper()

    def _resolve_canned_responses(self, device_id: str, method: str) -> List[str]:
        payload = self.settings.get("canned_responses", {})
        if not isinstance(payload, Mapping):
            return []

        buckets: List[Mapping[str, Any]] = []

        device_bucket = payload.get(device_id)
        if isinstance(device_bucket, Mapping):
            buckets.append(device_bucket)

        default_bucket = payload.get("_default")
        if isinstance(default_bucket, Mapping):
            buckets.append(default_bucket)

        # Optional shorthand: canned_responses as direct METHOD -> [responses].
        if all(isinstance(k, str) for k in payload.keys()) and any(
            isinstance(v, (list, str)) for v in payload.values()
        ):
            buckets.append(payload)

        for bucket in buckets:
            resolved = self._normalize_response_list(bucket.get(method) or bucket.get("*"))
            if resolved:
                return resolved

        return []

    @staticmethod
    def _normalize_response_list(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        return []


class SipProxyHttpTransport(SipTransport):
    """HTTP bridge between ims_tester and sip_proxy tester API."""

    def __init__(self, settings: Mapping[str, Any] | None = None) -> None:
        self.settings: Dict[str, Any] = dict(settings or {})
        self.api_base_url = str(self.settings.get("api_base_url", "")).strip().rstrip("/")
        if not self.api_base_url:
            raise ValueError("sip-proxy-http transport requires settings.api_base_url")

        self.send_path = str(self.settings.get("send_path", "/tester/send")).strip() or "/tester/send"
        self.read_path = str(self.settings.get("read_path", "/tester/read")).strip() or "/tester/read"
        self.health_path = str(self.settings.get("health_path", "/health")).strip() or "/health"
        self.live_edit_rules_path = (
            str(self.settings.get("live_edit_rules_path", "/tester/live-edit-rules")).strip()
            or "/tester/live-edit-rules"
        )
        self.live_edit_invite_content_type_path = (
            str(
                self.settings.get(
                    "live_edit_invite_content_type_path",
                    "/tester/live-edit-rules/invite-content-type",
                )
            ).strip()
            or "/tester/live-edit-rules/invite-content-type"
        )
        self.live_edit_wait_path = (
            str(self.settings.get("live_edit_wait_path", "/tester/live-edit-wait")).strip()
            or "/tester/live-edit-wait"
        )
        self.discovered_devices_path = (
            str(self.settings.get("discovered_devices_path", "/tester/discovered-devices")).strip()
            or "/tester/discovered-devices"
        )

        self.request_timeout_seconds = float(self.settings.get("request_timeout_seconds", 10.0) or 10.0)
        self.default_target_port = int(self.settings.get("default_target_port", 5060) or 5060)
        self.default_target_transport = (
            str(self.settings.get("default_target_transport", "udp")).strip().lower() or "udp"
        )
        if self.default_target_transport not in {"udp", "tcp"}:
            self.default_target_transport = "udp"

        self.check_health_on_open = bool(self.settings.get("check_health_on_open", True))
        self._opened = False

    def open(self) -> None:
        if self.check_health_on_open:
            health = self._get_json(self.health_path, timeout=self.request_timeout_seconds)
            if str(health.get("status", "")).lower() != "ok":
                raise RuntimeError(f"sip_proxy health endpoint is not ready: {health}")
        self._opened = True

    def close(self) -> None:
        self._opened = False

    def send(self, device: DeviceProfile, raw_message: str, context: Mapping[str, Any]) -> str:
        self._ensure_open()
        correlation_id = uuid.uuid4().hex
        target_uri = self._resolve_target_uri(device, context)

        payload = {
            "correlation_id": correlation_id,
            "raw_message": raw_message,
            "target_uri": target_uri,
            "submit_timeout_seconds": float(context.get("submit_timeout_seconds", self.request_timeout_seconds)),
        }

        response = self._post_json(self.send_path, payload, timeout=self.request_timeout_seconds)
        returned_correlation = str(response.get("correlation_id", correlation_id)).strip()
        return returned_correlation or correlation_id

    def read(self, device: DeviceProfile, correlation_id: str, timeout_seconds: float) -> List[SipResponse]:
        self._ensure_open()
        read_timeout = timeout_seconds if timeout_seconds > 0 else 0.0

        payload = {
            "correlation_id": correlation_id,
            "timeout_seconds": read_timeout,
        }

        response = self._post_json(
            self.read_path,
            payload,
            timeout=max(self.request_timeout_seconds, read_timeout + 1.0),
        )

        raw_responses = response.get("responses", [])
        if not isinstance(raw_responses, list):
            return []

        return [SipResponse.parse(str(item)) for item in raw_responses if str(item).strip()]

    def list_discovered_devices(self) -> List[DeviceProfile]:
        self._ensure_open()

        try:
            response = self._get_json(self.discovered_devices_path, timeout=self.request_timeout_seconds)
        except RuntimeError as exc:
            # Keep compatibility with older sip_proxy images that do not expose
            # discovered device inventory yet.
            if " 404 " in f" {exc} ":
                return []
            raise

        raw_devices = response.get("devices", [])
        if not isinstance(raw_devices, list):
            return []

        devices: List[DeviceProfile] = []
        for item in raw_devices:
            if not isinstance(item, Mapping):
                continue

            device_id = str(item.get("id", "")).strip()
            address = str(item.get("address", "")).strip()
            if not device_id or not address:
                continue

            display_name = str(item.get("name", device_id)).strip() or device_id
            metadata = item.get("metadata", {})
            if not isinstance(metadata, Mapping):
                metadata = {}

            devices.append(
                DeviceProfile(
                    device_id=device_id,
                    display_name=display_name,
                    address=address,
                    metadata=dict(metadata),
                )
            )

        return devices

    def list_live_edit_rules(self) -> List[Dict[str, Any]]:
        self._ensure_open()
        response = self._get_json(self.live_edit_rules_path, timeout=self.request_timeout_seconds)
        rules_raw = response.get("rules", [])
        if not isinstance(rules_raw, list):
            return []
        return [dict(rule) for rule in rules_raw if isinstance(rule, Mapping)]

    def replace_live_edit_rules(self, rules: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        self._ensure_open()
        payload = {"rules": [dict(rule) for rule in rules]}
        response = self._post_json(self.live_edit_rules_path, payload, timeout=self.request_timeout_seconds)
        rules_raw = response.get("rules", [])
        if not isinstance(rules_raw, list):
            return []
        return [dict(rule) for rule in rules_raw if isinstance(rule, Mapping)]

    def add_live_edit_rule(self, rule: Mapping[str, Any]) -> Dict[str, Any]:
        self._ensure_open()
        payload = {"rule": dict(rule)}
        response = self._post_json(self.live_edit_rules_path, payload, timeout=self.request_timeout_seconds)
        result = response.get("rule", {})
        if not isinstance(result, Mapping):
            return {}
        return dict(result)

    def clear_live_edit_rules(self) -> int:
        self._ensure_open()
        response = self._delete_json(self.live_edit_rules_path, timeout=self.request_timeout_seconds)
        return int(response.get("cleared", 0) or 0)

    def set_invite_content_type_live_edit(self, content_type: str = "test", clear_existing: bool = True) -> Dict[str, Any]:
        self._ensure_open()
        payload = {
            "content_type": content_type,
            "clear_existing": clear_existing,
        }
        response = self._post_json(
            self.live_edit_invite_content_type_path,
            payload,
            timeout=self.request_timeout_seconds,
        )
        result = response.get("rule", {})
        if not isinstance(result, Mapping):
            return {}
        return dict(result)

    def wait_for_live_edit_match(
        self,
        rule_ids: List[str],
        timeout_seconds: float,
        method: str = "*",
        direction: str = "any",
    ) -> Dict[str, Any]:
        self._ensure_open()
        payload = {
            "rule_ids": list(rule_ids),
            "timeout_seconds": float(timeout_seconds),
            "method": method,
            "direction": direction,
        }
        response = self._post_json(
            self.live_edit_wait_path,
            payload,
            timeout=max(self.request_timeout_seconds, float(timeout_seconds) + 1.0),
        )
        if not isinstance(response, Mapping):
            return {}
        return dict(response)

    def _ensure_open(self) -> None:
        if not self._opened:
            raise RuntimeError("Transport is not open")

    def _resolve_target_uri(self, device: DeviceProfile, context: Mapping[str, Any]) -> str:
        context_target_uri = str(context.get("target_uri", "")).strip()
        if context_target_uri:
            return self._normalize_target_uri(context_target_uri)

        metadata_target_uri = str(device.metadata.get("target_uri", "")).strip()
        if metadata_target_uri:
            return self._normalize_target_uri(metadata_target_uri)

        return self._normalize_target_uri(device.address)

    def _normalize_target_uri(self, raw_target: str) -> str:
        value = (raw_target or "").strip()
        if not value:
            raise ValueError("Target URI/address is empty")

        if value.startswith("<") and value.endswith(">"):
            value = value[1:-1].strip()

        if value.lower().startswith("sip:") or value.lower().startswith("sips:"):
            return value

        host = value
        port = self.default_target_port

        if host.startswith("[") and "]" in host:
            end = host.find("]")
            base_host = host[1:end]
            remainder = host[end + 1 :].strip()
            host = base_host
            if remainder.startswith(":") and remainder[1:].isdigit():
                port = int(remainder[1:])
        elif host.count(":") == 1 and host.rsplit(":", 1)[1].isdigit():
            host_part, port_part = host.rsplit(":", 1)
            host = host_part
            port = int(port_part)

        host = host.strip()
        if not host:
            raise ValueError("Target host is empty")

        if ":" in host and not host.startswith("["):
            host = f"[{host}]"

        return f"sip:{host}:{port};transport={self.default_target_transport}"

    def _build_url(self, path: str) -> str:
        normalized_path = path if path.startswith("/") else "/" + path
        return self.api_base_url + normalized_path

    def _get_json(self, path: str, timeout: float) -> Dict[str, Any]:
        request = urllib.request.Request(self._build_url(path), method="GET")
        return self._execute_json_request(request, timeout)

    def _post_json(self, path: str, payload: Mapping[str, Any], timeout: float) -> Dict[str, Any]:
        body = json.dumps(dict(payload)).encode("utf-8")
        request = urllib.request.Request(
            self._build_url(path),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._execute_json_request(request, timeout)

    def _delete_json(self, path: str, timeout: float) -> Dict[str, Any]:
        request = urllib.request.Request(self._build_url(path), method="DELETE")
        return self._execute_json_request(request, timeout)

    def _execute_json_request(self, request: urllib.request.Request, timeout: float) -> Dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=max(timeout, 0.2)) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP error from sip_proxy API: {exc.code} {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot reach sip_proxy API: {exc}") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON from sip_proxy API: {raw}") from exc

        if not isinstance(parsed, Mapping):
            raise RuntimeError(f"Unexpected JSON response from sip_proxy API: {parsed}")

        return dict(parsed)


class TransportRegistry:
    def __init__(self) -> None:
        self._factories: Dict[str, Callable[[Mapping[str, Any]], SipTransport]] = {
            "stub": lambda settings: StubSipTransport(settings),
            "sip-proxy-http": lambda settings: SipProxyHttpTransport(settings),
        }

    def register(self, name: str, factory: Callable[[Mapping[str, Any]], SipTransport]) -> None:
        self._factories[name.lower()] = factory

    def create(self, name: str, settings: Mapping[str, Any] | None = None) -> SipTransport:
        key = name.lower().strip()
        factory = self._factories.get(key)
        if factory is None:
            available = ", ".join(sorted(self._factories.keys()))
            raise ValueError(f"Unknown transport '{name}'. Available transports: {available}")
        return factory(settings or {})

    def available_transports(self) -> List[str]:
        return sorted(self._factories.keys())
