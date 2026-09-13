from __future__ import annotations
import threading
from typing import Any

class ProviderRegistry:
    """Central registry mapping provider type names to active implementations.
    
    Supports registration, lookup, hot-swapping, and listing.
    Thread-safe via a threading.Lock.
    """
    
    def __init__(self) -> None:
        self._providers: dict[str, Any] = {}
        self._lock = threading.Lock()
        
    def register(self, provider_type: str, provider: Any, *, replace: bool = False) -> None:
        with self._lock:
            if provider_type in self._providers and not replace:
                raise ValueError(f"Provider {provider_type} is already registered.")
            self._providers[provider_type] = provider
            
    def get(self, provider_type: str) -> Any | None:
        with self._lock:
            return self._providers.get(provider_type)
            
    def require(self, provider_type: str) -> Any:
        with self._lock:
            if provider_type not in self._providers:
                raise KeyError(f"Provider {provider_type} is not registered.")
            return self._providers[provider_type]
            
    def replace(self, provider_type: str, provider: Any) -> None:
        self.register(provider_type, provider, replace=True)
        
    def remove(self, provider_type: str) -> None:
        with self._lock:
            if provider_type in self._providers:
                del self._providers[provider_type]
                
    def list_providers(self) -> dict[str, str]:
        with self._lock:
            return {ptype: repr(provider) for ptype, provider in self._providers.items()}
            
    def is_registered(self, provider_type: str) -> bool:
        with self._lock:
            return provider_type in self._providers
