from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from ims_tester.models import DeviceProfile


@dataclass
class DummyUrlopenResponse:
    body: bytes

    def read(self) -> bytes:  # urllib returns bytes
        return self.body

    def __enter__(self) -> "DummyUrlopenResponse":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> bool:
        return False


def write_text(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def write_yaml(tmp_path: Path, name: str, content: str) -> Path:
    return write_text(tmp_path, name, content)


@pytest.fixture
def device_pixel() -> DeviceProfile:
    return DeviceProfile(
        device_id="pixel_8",
        display_name="Pixel 8",
        address="10.0.0.10",
        metadata={
            "phone_number": "15551234567",
            "imsi": "001010123456789",
            "user_agent": "PixelUA",
        },
    )


@pytest.fixture
def device_galaxy() -> DeviceProfile:
    return DeviceProfile(
        device_id="galaxy_s24",
        display_name="Galaxy S24",
        address="10.0.0.11",
        metadata={
            "phone_number": "15557654321",
            "imsi": "001010987654321",
            "user_agent": "GalaxyUA",
        },
    )


@pytest.fixture
def register_template() -> str:
    return (
        "REGISTER sip:$DEVICE_ADDRESS SIP/2.0\r\n"
        "Via: SIP/2.0/UDP $DEVICE_ADDRESS;branch=z9hG4bK-1\r\n"
        "To: <$PHONE_SIP_URI>\r\n"
        "From: <$PHONE_SIP_URI>;tag=abc\r\n"
        "Call-ID: 1\r\n"
        "CSeq: 1 REGISTER\r\n"
        "Content-Length: 0\r\n"
        "\r\n"
    )


@pytest.fixture
def sip_ok_response() -> str:
    return "SIP/2.0 200 OK\r\nVia: 1\r\nVia: 2\r\nContent-Length: 0\r\n\r\n"


@pytest.fixture
def http_error_body_fp() -> io.BytesIO:
    return io.BytesIO(b"{\"error\": \"boom\"}")
