from __future__ import annotations

import re
from typing import Any, Mapping

from bridges import GeminiBridge
from core.contracts import RiskTier

from .contracts import CapabilityPlan


class CapabilityPlanner:
    """Detects capability gaps and analyzes requirements to produce an implementation plan."""

    # Patterns for zip extraction
    ZIP_EXTRACT_RE = re.compile(
        r"^(?:(?:please\s+)?(?:extract|unzip|decompress)\s+(?:this\s+)?(?:zip\s+)?(?:file\s+)?['\"]?([^'\"\s]+\.zip)['\"]?(?:\s+(?:to|into)\s+['\"]?([^'\"\s]+)['\"]?)?|"
        r"(?:extract\s+this\s+zip\s+file)|"
        r"(?:unzip\s+this\s+file)|"
        r"(?:/zip\s+extract\s+['\"]?([^'\"\s]+)['\"]?))$",
        re.IGNORECASE,
    )

    ZIP_CREATE_RE = re.compile(
        r"^(?:(?:please\s+)?(?:create\s+zip|zip|compress)(?:\s+(?:directory|folder|file))?\s+['\"]?([^'\"\s]+)['\"]?\s+(?:into|as|to)\s+['\"]?([^'\"\s]+\.zip)['\"]?|"
        r"(?:/zip\s+create\s+['\"]?([^'\"\s]+)['\"]?\s+['\"]?([^'\"\s]+)['\"]?))$",
        re.IGNORECASE,
    )

    def __init__(self, bridge: GeminiBridge | None = None) -> None:
        self.bridge = bridge

    def detect_gap(
        self,
        text: str,
        context: Mapping[str, Any],
    ) -> CapabilityPlan | None:
        clean = " ".join(text.strip().split())

        # 1. Deterministic pattern checks
        # Check ZIP extraction
        match = self.ZIP_EXTRACT_RE.search(clean)
        if match or ("extract" in clean.lower() and "zip" in clean.lower()) or clean.lower().startswith("unzip"):
            archive = ""
            dest = ""
            if match:
                groups = [g for g in match.groups() if g]
                if groups:
                    archive = groups[0]
                    if len(groups) > 1:
                        dest = groups[1]

            # Fallback path search in text if not captured by groups
            if not archive:
                words = clean.split()
                for w in words:
                    cleaned_w = w.strip("'\",;:")
                    if cleaned_w.lower().endswith(".zip"):
                        archive = cleaned_w
                        break

            return CapabilityPlan(
                capability_id="file.zip.extract",
                name="zip_extract",
                description="Extract ZIP archives securely within workspace root",
                purpose="Safely unpacks ZIP archive files into target workspace directories while preventing directory traversal vulnerabilities",
                operation="extract",
                risk_tier=RiskTier.MUTATE,
                intents=(
                    "extract zip",
                    "unzip",
                    "extract archive",
                    "/zip extract",
                ),
                dependencies=("zipfile", "pathlib"),
                extracted_params={
                    "archive_path": archive or "archive.zip",
                    "destination": dest or ".",
                },
            )

        # Check ZIP creation
        match = self.ZIP_CREATE_RE.search(clean)
        if match or ("create zip" in clean.lower() or "zip folder" in clean.lower() or "zip directory" in clean.lower() or "zip " in clean.lower()):
            source = ""
            archive = ""
            if match:
                groups = [g for g in match.groups() if g]
                if len(groups) >= 2:
                    source, archive = groups[0], groups[1]
                elif len(groups) == 1:
                    archive = groups[0]

            if not archive:
                words = clean.split()
                for w in words:
                    cleaned_w = w.strip("'\",;:")
                    if cleaned_w.lower().endswith(".zip"):
                        archive = cleaned_w
                        break

            return CapabilityPlan(
                capability_id="file.zip.create",
                name="zip_create",
                description="Create ZIP archives from files or directories within workspace",
                purpose="Safely compresses files/directories into a ZIP file within workspace",
                operation="create",
                risk_tier=RiskTier.MUTATE,
                intents=("create zip", "zip file", "compress zip", "/zip create", "zip directory", "zip"),
                dependencies=("zipfile", "pathlib"),
                extracted_params={
                    "source_path": source or ".",
                    "archive_path": archive or "output.zip",
                },
            )

        # 2. LLM-based gap detection if Gemini bridge is available
        if self.bridge and self.bridge.available():
            try:
                schema = {
                    "type": "object",
                    "properties": {
                        "is_capability_gap": {"type": "boolean"},
                        "capability_id": {"type": "string"},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "purpose": {"type": "string"},
                        "operation": {"type": "string"},
                        "risk_tier": {
                            "type": "string",
                            "enum": ["read", "mutate", "remote", "destructive"],
                        },
                        "intents": {"type": "array", "items": {"type": "string"}},
                        "dependencies": {"type": "array", "items": {"type": "string"}},
                        "extracted_params": {"type": "object"},
                    },
                    "required": [
                        "is_capability_gap",
                        "capability_id",
                        "name",
                        "description",
                        "purpose",
                        "operation",
                        "risk_tier",
                        "intents",
                        "dependencies",
                    ],
                }
                prompt = (
                    f"Analyze the user request to determine if it asks for an actionable tool capability that NEXA lacks.\n"
                    f"USER REQUEST: '{clean}'\n"
                    f"Respond with structured JSON."
                )
                res = self.bridge.generate_json(prompt, schema)
                if res.get("is_capability_gap"):
                    return CapabilityPlan(
                        capability_id=res["capability_id"],
                        name=res["name"],
                        description=res["description"],
                        purpose=res["purpose"],
                        operation=res["operation"],
                        risk_tier=RiskTier(res["risk_tier"]),
                        intents=tuple(res["intents"]),
                        dependencies=tuple(res["dependencies"]),
                        extracted_params=res.get("extracted_params", {}),
                    )
            except Exception:
                pass

        return None
