from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping, Sequence

from .models import DeviceProfile, MessageEdit, SipResponse


class SipMessageModifier(ABC):
    """Interface for SIP message mutation/injection logic."""

    @abstractmethod
    def apply(self, template: str, edits: Sequence[MessageEdit]) -> str:
        raise NotImplementedError


class SipMessageSender(ABC):
    """Interface for dispatching SIP messages toward a device under test."""

    @abstractmethod
    def send(self, device: DeviceProfile, raw_message: str, context: Mapping[str, Any]) -> str:
        """Send one SIP message and return a correlation ID."""
        raise NotImplementedError


class SipMessageReader(ABC):
    """Interface for collecting SIP responses from a device under test."""

    @abstractmethod
    def read(self, device: DeviceProfile, correlation_id: str, timeout_seconds: float) -> Sequence[SipResponse]:
        raise NotImplementedError


class SipTransport(SipMessageSender, SipMessageReader, ABC):
    """Composed transport interface used by the test engine."""

    @abstractmethod
    def open(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


class TransportFactory(ABC):
    """Factory interface used for pluggable transport backends."""

    @abstractmethod
    def create(self, settings: Mapping[str, Any]) -> SipTransport:
        raise NotImplementedError
