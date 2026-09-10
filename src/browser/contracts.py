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
