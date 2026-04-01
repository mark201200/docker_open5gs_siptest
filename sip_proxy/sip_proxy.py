#!/usr/bin/env python3
import asyncio
import json
import os
import re
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Tuple


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    transport: str = "udp"


@dataclass(frozen=True)
class CancelRoute:
    target: Endpoint
    outbound_branch: str


class SIPMessage:
    def __init__(self, start_line: str, headers: List[str], body: str) -> None:
        self.start_line = start_line
        self.headers = headers
        self.body = body

    @property
    def is_response(self) -> bool:
        return self.start_line.startswith("SIP/2.0")

    @property
    def method(self) -> str:
        if self.is_response:
            return ""
        return self.start_line.split(" ", 1)[0].strip().upper()

    def get_header(self, name: str) -> Optional[str]:
        name_l = name.lower()
        for line in self.headers:
            if ":" not in line:
                continue
            h, v = line.split(":", 1)
            if h.strip().lower() == name_l:
                return v.strip()
        return None

    def get_headers(self, name: str) -> List[Tuple[int, str]]:
        out: List[Tuple[int, str]] = []
        name_l = name.lower()
        for i, line in enumerate(self.headers):
            if ":" not in line:
                continue
            h, v = line.split(":", 1)
            if h.strip().lower() == name_l:
                out.append((i, v.strip()))
        return out

    def set_header(self, name: str, value: str) -> None:
        idxs = self.get_headers(name)
        if idxs:
            i, _ = idxs[0]
            self.headers[i] = f"{name}: {value}"
            for j, _ in reversed(idxs[1:]):
                self.headers.pop(j)
        else:
            self.headers.append(f"{name}: {value}")

    def remove_header(self, name: str) -> None:
        idxs = self.get_headers(name)
        for i, _ in reversed(idxs):
            self.headers.pop(i)

    def insert_header(self, name: str, value: str, after_names: Optional[List[str]] = None) -> None:
        if not after_names:
            self.headers.insert(0, f"{name}: {value}")
            return

        after_set = {n.lower() for n in after_names}
        insert_at = 0
        for i, line in enumerate(self.headers):
            if ":" not in line:
                continue
            h = line.split(":", 1)[0].strip().lower()
            if h in after_set:
                insert_at = i + 1
        self.headers.insert(insert_at, f"{name}: {value}")

    def to_bytes(self) -> bytes:
        body_bytes = self.body.encode("latin1", errors="replace")
        self.set_header("Content-Length", str(len(body_bytes)))
        payload = self.start_line + "\r\n" + "\r\n".join(self.headers) + "\r\n\r\n"
        return payload.encode("latin1", errors="replace") + body_bytes

    @staticmethod
    def parse(data: bytes) -> "SIPMessage":
        text = data.decode("latin1", errors="replace")
        head, sep, body = text.partition("\r\n\r\n")
        if not sep:
            head, sep, body = text.partition("\n\n")
        lines = head.splitlines()
        if not lines:
            raise ValueError("Malformed SIP payload: empty start line")
        start_line = lines[0].strip()
        headers = [line.rstrip("\r") for line in lines[1:]]
        return SIPMessage(start_line, headers, body)


def split_header_uri_list(value: str) -> List[str]:
    parts: List[str] = []
    buf: List[str] = []
    depth = 0
    in_quotes = False
    for ch in value:
        if ch == '"':
            in_quotes = not in_quotes
        elif not in_quotes:
            if ch == "<":
                depth += 1
            elif ch == ">" and depth > 0:
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append("".join(buf).strip())
                buf = []
                continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p]


def extract_uri(value: str) -> str:
    value = value.strip()
    if "<" in value and ">" in value:
        return value[value.find("<") + 1:value.find(">")].strip()
    return value


def parse_sip_uri(uri: str) -> Tuple[str, int, str, str]:
    raw = extract_uri(uri.strip())
    raw = raw.strip().strip('"').strip("'")

    if raw.lower().startswith("sip:"):
        raw = raw[4:]
    elif raw.lower().startswith("sips:"):
        raw = raw[5:]

    user = ""
    if "@" in raw:
        user, raw = raw.split("@", 1)

    transport = "udp"
    params = ""
    if ";" in raw:
        hostport, params = raw.split(";", 1)
        m = re.search(r"(?:^|;)transport=([^;]+)", params, flags=re.IGNORECASE)
        if m:
            transport = m.group(1).lower()
    else:
        hostport = raw

    hostport = hostport.strip()
    host = hostport
    port = 5060

    # Support IPv6 host form: [addr]:port
    if hostport.startswith("[") and "]" in hostport:
        end = hostport.find("]")
        host = hostport[1:end]
        remainder = hostport[end + 1 :].strip()
        if remainder.startswith(":"):
            p = remainder[1:].strip()
            if p.isdigit():
                port = int(p)
    elif ":" in hostport and hostport.count(":") == 1:
        host, p = hostport.split(":", 1)
        if p.isdigit():
            port = int(p)

    return host.strip().strip("<>").strip('"').strip("'"), port, transport, user.strip()


def split_sip_stream_messages(buffer: bytes) -> Tuple[List[bytes], bytes]:
    messages: List[bytes] = []

    while True:
        sep = b"\r\n\r\n"
        header_end = buffer.find(sep)
        if header_end < 0:
            sep = b"\n\n"
            header_end = buffer.find(sep)
            if header_end < 0:
                break

        head = buffer[:header_end].decode("latin1", errors="replace")
        content_length = 0
        for line in head.splitlines():
            if ":" not in line:
                continue
            h, v = line.split(":", 1)
            if h.strip().lower() == "content-length":
                try:
                    content_length = int(v.strip())
                except ValueError:
                    content_length = 0
                break

        total = header_end + len(sep) + content_length
        if len(buffer) < total:
            break

        messages.append(buffer[:total])
        buffer = buffer[total:]

    return messages, buffer


class SIPProxy:
    def __init__(self) -> None:
        self.listen_ip = os.getenv("SIP_PROXY_LISTEN_IP", "0.0.0.0")
        self.listen_port = int(os.getenv("SIP_PROXY_LISTEN_PORT", "5062"))
        self.api_ip = os.getenv("SIP_PROXY_API_LISTEN_IP", "0.0.0.0")
        self.api_port = int(os.getenv("SIP_PROXY_API_PORT", "8088"))

        self.pcscf_ip = os.getenv("SIP_PROXY_PCSCF_IP", "")
        self.pcscf_port = int(os.getenv("SIP_PROXY_PCSCF_PORT", "5060"))

        self.default_core_ip = os.getenv("SIP_PROXY_DEFAULT_CORE_IP", "")
        self.default_core_port = int(os.getenv("SIP_PROXY_DEFAULT_CORE_PORT", "4060"))

        self.advertised_host = os.getenv("SIP_PROXY_ADVERTISED_HOST", self.listen_ip)
        self.route_user = os.getenv("SIP_PROXY_ROUTE_USER", "sipproxy")

        self.log_messages = env_bool("SIP_PROXY_LOG_MESSAGES", False)
        self.insert_record_route = env_bool("SIP_PROXY_INSERT_RECORD_ROUTE", True)

        rewrite_json = os.getenv("SIP_PROXY_REWRITE_RULES", "[]")
        try:
            self.rewrite_rules = json.loads(rewrite_json)
            if not isinstance(self.rewrite_rules, list):
                self.rewrite_rules = []
        except json.JSONDecodeError:
            self.rewrite_rules = []

        self.transactions: Dict[str, Endpoint] = {}
        self.transaction_upstream_vias: Dict[str, List[str]] = {}
        self.cancel_routes: Dict[str, CancelRoute] = {}
        self.registrar_contacts: Dict[str, Dict[str, str]] = {}

        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.udp_transport = None
        self.tcp_server: Optional[asyncio.AbstractServer] = None

    def _log(self, msg: str) -> None:
        print(f"[sip-proxy] {msg}", flush=True)

    def _is_from_pcscf(self, src_host: str) -> bool:
        return bool(self.pcscf_ip) and src_host == self.pcscf_ip

    def _extract_branch(self, via_value: str) -> Optional[str]:
        m = re.search(r"(?:^|;)branch=([^;\s]+)", via_value, flags=re.IGNORECASE)
        return m.group(1) if m else None

    def _transaction_key(self, branch: str, cseq: str) -> str:
        return f"{branch}|{cseq.strip()}"

    def _cancel_route_key(self, src_host: str, inbound_branch: str, call_id: str, cseq_num: str) -> str:
        return f"{src_host}|{inbound_branch}|{call_id.strip()}|{cseq_num.strip()}"

    def _parse_cseq(self, cseq: str) -> Tuple[str, str]:
        parts = cseq.strip().split()
        if len(parts) < 2:
            return "", ""
        return parts[0], parts[1].upper()

    def _is_our_via(self, via_value: str) -> bool:
        m = re.match(r"^\s*SIP/2\.0/[A-Za-z]+\s+([^;]+)", via_value)
        if not m:
            return False

        sent_by = m.group(1).strip()
        host = sent_by
        port = 5060

        if sent_by.startswith("[") and "]" in sent_by:
            end = sent_by.find("]")
            host = sent_by[1:end]
            remainder = sent_by[end + 1 :].strip()
            if remainder.startswith(":") and remainder[1:].isdigit():
                port = int(remainder[1:])
        elif ":" in sent_by and sent_by.count(":") == 1:
            host, p = sent_by.split(":", 1)
            if p.isdigit():
                port = int(p)

        known_hosts = {self.advertised_host.lower(), self.listen_ip.lower(), socket.gethostname().lower()}
        return port == self.listen_port and host.lower() in known_hosts

    def _via_values(self, msg: SIPMessage) -> List[str]:
        values: List[str] = []
        for line in msg.headers:
            if ":" not in line:
                continue
            h, v = line.split(":", 1)
            if h.strip().lower() in {"via", "v"}:
                values.append(v.strip())
        return values

    def _replace_vias(self, msg: SIPMessage, via_values: List[str]) -> None:
        msg.remove_header("Via")
        msg.remove_header("v")
        for via_value in reversed(via_values):
            msg.insert_header("Via", via_value)

    def _apply_rewrites(self, msg: SIPMessage) -> None:
        if not self.rewrite_rules:
            return

        raw = msg.start_line + "\r\n" + "\r\n".join(msg.headers) + "\r\n\r\n" + msg.body
        for rule in self.rewrite_rules:
            pattern = rule.get("pattern")
            repl = rule.get("replace", "")
            if not pattern:
                continue
            raw = re.sub(pattern, repl, raw)

        reparsed = SIPMessage.parse(raw.encode("latin1", errors="replace"))
        msg.start_line = reparsed.start_line
        msg.headers = reparsed.headers
        msg.body = reparsed.body

    def _store_registration_hint(self, msg: SIPMessage, src: Endpoint) -> None:
        if msg.method != "REGISTER":
            return
        to_h = msg.get_header("To") or msg.get_header("t")
        if not to_h:
            return
        aor = extract_uri(to_h)
        contact = msg.get_header("Contact") or msg.get_header("m")
        self.registrar_contacts[aor] = {
            "last_contact": contact or "",
            "last_seen_from": f"{src.host}:{src.port}/{src.transport}",
            "updated_at": str(int(time.time())),
        }

    def _pop_proxy_route_if_needed(self, msg: SIPMessage) -> None:
        routes = msg.get_headers("Route")
        if not routes:
            return

        i, route_value = routes[0]
        entries = split_header_uri_list(route_value)
        if not entries:
            return

        first_uri = extract_uri(entries[0])
        host, port, _, user = parse_sip_uri(first_uri)
        host_match = host in {self.advertised_host, self.listen_ip, socket.gethostname()}
        if host_match and port == self.listen_port and (not user or user == self.route_user):
            entries = entries[1:]
            if entries:
                msg.headers[i] = "Route: " + ", ".join(entries)
            else:
                msg.headers.pop(i)

    def _determine_target_from_header(self, msg: SIPMessage) -> Optional[Endpoint]:
        target = msg.get_header("X-SIP-Proxy-Target")
        if not target:
            return None
        msg.remove_header("X-SIP-Proxy-Target")

        # Header may contain a name-addr or a comma-separated list; use the first URI.
        entries = split_header_uri_list(target)
        target_uri = extract_uri(entries[0]) if entries else extract_uri(target)

        host, port, transport, _ = parse_sip_uri(target_uri)
        if not host:
            return None

        # Some P-CSCF templates can forward unresolved placeholders (e.g. icscf.IMS_DOMAIN).
        # Fall back to configured core IP to keep routing deterministic.
        if self.default_core_ip and "IMS_DOMAIN" in host.upper():
            host = self.default_core_ip
        return Endpoint(host=host, port=port, transport=transport)

    async def _send_udp(self, data: bytes, target: Endpoint) -> None:
        if not self.udp_transport:
            raise RuntimeError("UDP transport is not ready")
        self.udp_transport.sendto(data, (target.host, target.port))

    async def _send_tcp(self, data: bytes, target: Endpoint) -> None:
        writer: Optional[asyncio.StreamWriter] = None
        try:
            _, writer = await asyncio.open_connection(target.host, target.port)
            writer.write(data)
            await writer.drain()
        except socket.gaierror as exc:
            # Keep proxy transparent: if name resolution fails, fallback to core IP.
            if self.default_core_ip and target.host != self.default_core_ip:
                self._log(
                    f"DNS resolution failed for target {target.host}:{target.port} ({exc}); "
                    f"retrying via {self.default_core_ip}:{target.port}"
                )
                _, writer = await asyncio.open_connection(self.default_core_ip, target.port)
                writer.write(data)
                await writer.drain()
            else:
                raise
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()

    async def _send(self, data: bytes, target: Endpoint) -> None:
        if target.transport.lower() == "tcp":
            await self._send_tcp(data, target)
        else:
            await self._send_udp(data, Endpoint(target.host, target.port, "udp"))

    async def handle_packet(self, data: bytes, src: Endpoint) -> None:
        try:
            msg = SIPMessage.parse(data)
        except Exception as exc:
            self._log(f"Dropping malformed SIP packet from {src.host}:{src.port}: {exc}")
            return

        self._store_registration_hint(msg, src)

        if self.log_messages:
            self._log(f"RX {src.host}:{src.port} {msg.start_line}")

        self._apply_rewrites(msg)

        if msg.is_response:
            await self._handle_response(msg, src)
            return

        await self._handle_request(msg, src)

    async def handle_datagram(self, data: bytes, addr: Tuple[str, int]) -> None:
        src = Endpoint(host=addr[0], port=addr[1], transport="udp")
        await self.handle_packet(data, src)

    async def handle_tcp_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        if not peer:
            writer.close()
            await writer.wait_closed()
            return

        src = Endpoint(host=peer[0], port=peer[1], transport="tcp")
        pending = b""

        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break

                pending += chunk
                messages, pending = split_sip_stream_messages(pending)
                for payload in messages:
                    try:
                        await self.handle_packet(payload, src)
                    except Exception as exc:
                        self._log(f"Unhandled error while processing TCP SIP message: {exc}")
        finally:
            writer.close()
            await writer.wait_closed()

    async def _handle_request(self, msg: SIPMessage, src: Endpoint) -> None:
        from_pcscf = self._is_from_pcscf(src.host)
        target = self._determine_target_from_header(msg)

        inbound_vias = self._via_values(msg)
        inbound_top_via = inbound_vias[0] if inbound_vias else ""
        inbound_branch = self._extract_branch(inbound_top_via) or ""
        call_id = msg.get_header("Call-ID") or ""
        cseq = msg.get_header("CSeq") or ""
        cseq_num, _ = self._parse_cseq(cseq)

        if not from_pcscf:
            self._pop_proxy_route_if_needed(msg)

        if target is None:
            if from_pcscf:
                target = Endpoint(self.default_core_ip, self.default_core_port, "udp")
            else:
                target = Endpoint(self.pcscf_ip, self.pcscf_port, "udp")

        if not target.host:
            self._log("No valid target host for SIP request; dropping")
            return

        # Keep core leg stable over UDP for P-CSCF-originated requests.
        # One-shot TCP connect/close can make upstream proxies reply to closed
        # ephemeral ports, causing REGISTER timeout (504) downstream.
        if from_pcscf and target.transport.lower() == "tcp":
            target = Endpoint(target.host, target.port, "udp")

        cancel_route: Optional[CancelRoute] = None
        if msg.method == "CANCEL" and inbound_branch and call_id and cseq_num:
            key = self._cancel_route_key(src.host, inbound_branch, call_id, cseq_num)
            cancel_route = self.cancel_routes.get(key)
            if cancel_route is not None:
                target = cancel_route.target

        via_branch = cancel_route.outbound_branch if cancel_route else f"z9hG4bK-proxy-{uuid.uuid4().hex[:16]}"
        via_transport = "TCP" if target.transport.lower() == "tcp" else "UDP"
        via_value = f"SIP/2.0/{via_transport} {self.advertised_host}:{self.listen_port};branch={via_branch};rport"
        # Via must be prepended, not appended, so the response pops our Via first.
        msg.insert_header("Via", via_value)

        if self.insert_record_route and msg.method in {"INVITE", "SUBSCRIBE", "MESSAGE", "REFER", "UPDATE"}:
            to_h = (msg.get_header("To") or "").lower()
            if "tag=" not in to_h:
                rr = f"<sip:{self.route_user}@{self.advertised_host}:{self.listen_port};lr>"
                msg.insert_header("Record-Route", rr, after_names=["Via", "v"])

        top_via = msg.get_header("Via") or msg.get_header("v") or ""
        branch = self._extract_branch(top_via) or via_branch
        # For TCP-originated requests from P-CSCF, return responses to the
        # P-CSCF listener, not to the ephemeral client TCP source port.
        response_target = src
        if from_pcscf and src.transport == "tcp" and self.pcscf_ip:
            response_target = Endpoint(self.pcscf_ip, self.pcscf_port, "tcp")

        self.transactions[self._transaction_key(branch, cseq)] = response_target
        if inbound_vias:
            self.transaction_upstream_vias[self._transaction_key(branch, cseq)] = inbound_vias

        if msg.method == "INVITE" and inbound_branch and call_id and cseq_num:
            key = self._cancel_route_key(src.host, inbound_branch, call_id, cseq_num)
            self.cancel_routes[key] = CancelRoute(target=target, outbound_branch=branch)

        out = msg.to_bytes()
        await self._send(out, target)

        if self.log_messages:
            self._log(f"TX {target.host}:{target.port}/{target.transport} {msg.start_line}")

    async def _handle_response(self, msg: SIPMessage, src: Endpoint) -> None:
        vias = msg.get_headers("Via")
        if not vias:
            self._log("Response without Via header dropped")
            return

        top_via_idx, top_via_val = vias[0]
        if not self._is_our_via(top_via_val):
            self._log("Response top Via does not belong to proxy; dropping to avoid corrupt forwarding")
            return

        branch = self._extract_branch(top_via_val) or ""
        cseq = msg.get_header("CSeq") or ""
        key = self._transaction_key(branch, cseq)

        target = self.transactions.get(key)
        if target is None:
            if self._is_from_pcscf(src.host):
                target = Endpoint(self.default_core_ip, self.default_core_port, "udp")
            else:
                target = Endpoint(self.pcscf_ip, self.pcscf_port, "udp")

        msg.headers.pop(top_via_idx)

        # Downstream entities may collapse or mutate pre-existing Via chains.
        # Re-apply the exact upstream chain captured on request ingress so that
        # each upstream hop can pop its own Via safely.
        expected_upstream_vias = self.transaction_upstream_vias.get(key, [])
        if expected_upstream_vias:
            current_vias = self._via_values(msg)
            if current_vias != expected_upstream_vias:
                self._replace_vias(msg, expected_upstream_vias)
        elif not self._via_values(msg):
            self._log("Response lost all Via headers and no upstream Via context exists; dropping")
            return

        out = msg.to_bytes()
        await self._send(out, target)

        if self.log_messages:
            self._log(f"TX {target.host}:{target.port}/{target.transport} {msg.start_line}")

    async def inject_message(self, to_uri: str, body: str, from_uri: Optional[str], content_type: str) -> Dict[str, str]:
        if not self.default_core_ip:
            raise RuntimeError("SIP_PROXY_DEFAULT_CORE_IP is not configured")

        call_id = f"{uuid.uuid4().hex}@{self.advertised_host}"
        tag = uuid.uuid4().hex[:10]
        branch = f"z9hG4bK-inject-{uuid.uuid4().hex[:16]}"
        from_uri = from_uri or f"sip:proxy@{self.advertised_host}"

        lines = [
            f"MESSAGE {to_uri} SIP/2.0",
            f"Via: SIP/2.0/UDP {self.advertised_host}:{self.listen_port};branch={branch};rport",
            "Max-Forwards: 70",
            f"From: <{from_uri}>;tag={tag}",
            f"To: <{to_uri}>",
            f"Call-ID: {call_id}",
            "CSeq: 1 MESSAGE",
            f"Contact: <sip:proxy@{self.advertised_host}:{self.listen_port}>",
            f"Content-Type: {content_type}",
            f"Content-Length: {len(body.encode('utf-8'))}",
            "",
            body,
        ]
        payload = "\r\n".join(lines).encode("utf-8")

        target = Endpoint(self.default_core_ip, self.default_core_port, "udp")
        await self._send(payload, target)
        return {
            "call_id": call_id,
            "target": f"{target.host}:{target.port}/{target.transport}",
        }


class SIPUDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, proxy: SIPProxy):
        self.proxy = proxy

    def connection_made(self, transport) -> None:
        self.proxy.udp_transport = transport
        self.proxy._log(f"SIP UDP listening on {self.proxy.listen_ip}:{self.proxy.listen_port}")

    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        asyncio.create_task(self.proxy.handle_datagram(data, addr))


class ProxyAPIHandler(BaseHTTPRequestHandler):
    server_version = "SipProxyApi/1.0"

    def _json_response(self, code: int, payload: Dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json_response(200, {"status": "ok"})
            return

        if self.path == "/registrations":
            proxy: SIPProxy = self.server.proxy  # type: ignore[attr-defined]
            self._json_response(200, proxy.registrar_contacts)
            return

        self._json_response(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/inject/message":
            self._json_response(404, {"error": "not found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._json_response(400, {"error": "invalid json"})
            return

        to_uri = payload.get("to_uri")
        body = payload.get("body", "")
        from_uri = payload.get("from_uri")
        content_type = payload.get("content_type", "text/plain")

        if not to_uri:
            self._json_response(400, {"error": "missing to_uri"})
            return

        proxy: SIPProxy = self.server.proxy  # type: ignore[attr-defined]

        async def run_inject() -> Dict[str, str]:
            return await proxy.inject_message(to_uri=to_uri, body=body, from_uri=from_uri, content_type=content_type)

        future = asyncio.run_coroutine_threadsafe(run_inject(), proxy.loop)
        try:
            result = future.result(timeout=5)
        except Exception as exc:
            self._json_response(500, {"error": str(exc)})
            return

        self._json_response(202, {"status": "accepted", **result})


def start_api_server(proxy: SIPProxy) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((proxy.api_ip, proxy.api_port), ProxyAPIHandler)
    server.proxy = proxy  # type: ignore[attr-defined]

    def _serve() -> None:
        proxy._log(f"API listening on {proxy.api_ip}:{proxy.api_port}")
        server.serve_forever()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    return server


async def run() -> None:
    proxy = SIPProxy()
    proxy.loop = asyncio.get_running_loop()

    if not proxy.pcscf_ip:
        proxy._log("SIP_PROXY_PCSCF_IP is empty; proxy cannot route traffic to P-CSCF")

    transport, _ = await proxy.loop.create_datagram_endpoint(
        lambda: SIPUDPProtocol(proxy),
        local_addr=(proxy.listen_ip, proxy.listen_port),
    )
    proxy._log(f"SIP TCP listening on {proxy.listen_ip}:{proxy.listen_port}")
    proxy.tcp_server = await asyncio.start_server(
        proxy.handle_tcp_client,
        host=proxy.listen_ip,
        port=proxy.listen_port,
    )

    api = start_api_server(proxy)

    try:
        await asyncio.Future()
    finally:
        api.shutdown()
        if proxy.tcp_server is not None:
            proxy.tcp_server.close()
            await proxy.tcp_server.wait_closed()
        transport.close()


if __name__ == "__main__":
    asyncio.run(run())
