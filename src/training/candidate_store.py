from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .skill_forge import SkillCandidate


_SAFE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")


class CandidateStore:
    """Persist validated generated skill candidates outside the live source tree.

    Staging is deliberately separate from runtime registration. A candidate can be
    inspected, tested again, or promoted later by policy, but this store never
    edits NEXA core/security code and never imports generated Python.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def stage(self, candidate: SkillCandidate) -> Path:
        name = candidate.name.strip()
        if not _SAFE_NAME_RE.fullmatch(name):
            raise ValueError("unsafe generated skill name")

        files = candidate.files()
        digest = self._digest(candidate)
        target = (self.root / name / digest[:16]).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("candidate staging path escaped configured root")
        target.mkdir(parents=True, exist_ok=True)

        for relative_name, source in files.items():
            relative = Path(relative_name)
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                raise ValueError(f"unsafe candidate file path: {relative_name}")
            destination = (target / relative).resolve()
            if not destination.is_relative_to(target):
                raise ValueError(f"candidate file escaped staging directory: {relative_name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(source, encoding="utf-8")

        manifest = {
            "name": name,
            "description": candidate.description,
            "risk_tier": candidate.risk_tier,
            "teacher_notes": candidate.teacher_notes,
            "sha256": digest,
            "staged_at_utc": datetime.now(timezone.utc).isoformat(),
            "runtime_registered": False,
            "promotion_required": True,
            "files": sorted(files),
        }
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return target

    @staticmethod
    def _digest(candidate: SkillCandidate) -> str:
        payload = json.dumps(
            asdict(candidate),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
