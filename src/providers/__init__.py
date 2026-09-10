from __future__ import annotations

from .contracts import (
    TranscriptionResult,
    VisionResult,
    BoundingBox,
    UIElement,
    BrowserResult,
    STTProvider,
    TTSProvider,
    VisionProvider,
    BrowserProvider,
    CredentialProvider,
    LLMProvider,
    StorageProvider
)
from .registry import ProviderRegistry

__all__ = [
    "TranscriptionResult",
    "VisionResult",
    "BoundingBox",
    "UIElement",
    "BrowserResult",
    "STTProvider",
    "TTSProvider",
    "VisionProvider",
    "BrowserProvider",
    "CredentialProvider",
    "LLMProvider",
    "StorageProvider",
    "ProviderRegistry",
]
