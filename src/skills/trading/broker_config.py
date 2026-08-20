from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Protocol

from .live import BrokerAdapter


@dataclass(frozen=True)
class BrokerSelection:
    """Non-secret owner configuration selecting a reviewed broker factory.

    This object intentionally carries only routing metadata. Broker credentials
    remain the responsibility of the reviewed factory and should be read from a
    local secret store or process environment at construction time.
    """

    provider: str
    account: str | None = None

    def __post_init__(self) -> None:
        provider = self.provider.strip().lower()
        if not provider or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for ch in provider):
            raise ValueError("broker provider must be a safe identifier")
        account = None if self.account is None else self.account.strip()
        if account == "":
            account = None
        if account is not None and (len(account) > 128 or "\x00" in account):
            raise ValueError("broker account selector is invalid")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "account", account)


class TrustedBrokerFactory(Protocol):
    """Reviewed application-owned factory for one concrete BrokerAdapter."""

    def __call__(self, selection: BrokerSelection) -> BrokerAdapter:
        ...


class BrokerFactoryRegistry:
    """Explicit allow-list of reviewed broker factories.

    Environment text can select only a factory that trusted application code has
    already registered. It can never import a module, evaluate a class name, or
    manufacture a broker adapter from arbitrary text.
    """

    def __init__(self, factories: Mapping[str, TrustedBrokerFactory] | None = None) -> None:
        self._factories: dict[str, TrustedBrokerFactory] = {}
        for name, factory in (factories or {}).items():
            self.register(name, factory)

    def register(self, name: str, factory: TrustedBrokerFactory) -> None:
        key = BrokerSelection(name).provider
        if key in self._factories:
            raise ValueError(f"broker factory already registered: {key}")
        if not callable(factory):
            raise TypeError("broker factory must be callable")
        self._factories[key] = factory

    @property
    def providers(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    def create(self, selection: BrokerSelection) -> BrokerAdapter:
        factory = self._factories.get(selection.provider)
        if factory is None:
            raise PermissionError(f"broker provider is not in the trusted factory registry: {selection.provider}")
        broker = factory(selection)
        if broker is None:
            raise RuntimeError("trusted broker factory returned no adapter")
        return broker


def broker_selection_from_env() -> BrokerSelection | None:
    """Read only a broker selector; never create or arm live execution.

    Merely setting NEXA_LIVE_BROKER_PROVIDER has no effect on build_runtime().
    Trusted owner-controlled application code must explicitly call the broker
    registry path and pass the resulting adapter into build_runtime().
    """

    provider = os.getenv("NEXA_LIVE_BROKER_PROVIDER", "").strip()
    if not provider:
        return None
    account = os.getenv("NEXA_LIVE_BROKER_ACCOUNT", "").strip() or None
    return BrokerSelection(provider=provider, account=account)


def build_selected_trusted_broker(
    registry: BrokerFactoryRegistry,
    *,
    selection: BrokerSelection | None = None,
) -> BrokerAdapter | None:
    """Resolve an explicitly selected adapter from an explicit trusted registry."""

    chosen = selection if selection is not None else broker_selection_from_env()
    if chosen is None:
        return None
    return registry.create(chosen)
