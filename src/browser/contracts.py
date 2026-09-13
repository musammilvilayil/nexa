from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

@dataclass(frozen=True)
class PageInfo:
    url: str
    title: str
    status_code: int = 200
    is_loaded: bool = True

@dataclass(frozen=True)
class LinkInfo:
    text: str
    url: str
    is_external: bool = False

@dataclass(frozen=True)
class FormField:
    name: str
    field_type: str  # text, password, email, select, etc.
    selector: str = ""
    value: str = ""
    required: bool = False

@dataclass(frozen=True)
class TabInfo:
    tab_id: int
    url: str
    title: str
    is_active: bool = False

@dataclass(frozen=True)
class BrowserActionResult:
    success: bool
    message: str = ""
    page: PageInfo | None = None
    data: Any = None
    error: str | None = None
    action: str = ""
    target: str = ""
    observation: dict[str, Any] = field(default_factory=dict)
    screenshot: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "action": self.action,
            "target": self.target,
            "observation": self.observation,
            "error": self.error,
            "screenshot": self.screenshot,
            "metadata": self.metadata,
            "message": self.message,
            "page": {
                "url": self.page.url,
                "title": self.page.title,
                "status_code": self.page.status_code,
                "is_loaded": self.page.is_loaded,
            } if self.page else None,
            "data": self.data,
        }
