from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from bridges import ProcessResult, SubprocessBridge

from .validator import StaticValidationReport, StaticValidator


@dataclass(frozen=True)
class SandboxResult:
    passed: bool
    validation_passed: bool
    tests_ran: bool
    process: ProcessResult | None
    validation: tuple[tuple[str, StaticValidationReport], ...]
    reason: str


class SandboxRunner:
    """Temporary-directory runner for generated skill candidates.

    This is process isolation plus a conservative static gate, not a hardened VM.
    Secrets are not inherited into the child environment. Promotion still requires
    a separate policy decision after tests pass.
    """

    def __init__(
        self,
        *,
        validator: StaticValidator | None = None,
        timeout: float = 30.0,
        support_pythonpath: str | Path | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.validator = validator or StaticValidator()
        self.timeout = float(timeout)
        self.support_pythonpath = Path(
            support_pythonpath or Path(__file__).resolve().parents[1]
        ).resolve()

    def run(self, files: Mapping[str, str]) -> SandboxResult:
        if not files:
            raise ValueError("sandbox files cannot be empty")

        validation: list[tuple[str, StaticValidationReport]] = []
        normalized: dict[Path, str] = {}
        for name, source in files.items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                raise ValueError(f"unsafe sandbox path: {name}")
            if not isinstance(source, str):
                raise ValueError("sandbox source must be text")
            normalized[relative] = source
            if relative.suffix == ".py":
                report = self.validator.validate(source)
                validation.append((relative.as_posix(), report))

        unsafe = [(name, report) for name, report in validation if not report.safe]
        if unsafe:
            return SandboxResult(
                passed=False,
                validation_passed=False,
                tests_ran=False,
                process=None,
                validation=tuple(validation),
                reason="static validation failed",
            )

        with tempfile.TemporaryDirectory(prefix="nexa-sandbox-") as temp:
            root = Path(temp).resolve()
            for relative, source in normalized.items():
                target = (root / relative).resolve()
                if not target.is_relative_to(root):
                    raise ValueError(f"sandbox path escaped root: {relative}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source, encoding="utf-8")

            bridge = SubprocessBridge(
                [Path(sys.executable).name],
                default_timeout=self.timeout,
                inherit_environment=False,
                allowed_env_keys=("PYTHONPATH",),
            )
            pythonpath = str(self.support_pythonpath)
            process = bridge.run(
                sys.executable,
                ["-m", "unittest", "discover", "-s", ".", "-p", "test_*.py", "-v"],
                cwd=root,
                timeout=self.timeout,
                env_overrides={"PYTHONPATH": pythonpath},
            )
            return SandboxResult(
                passed=process.ok,
                validation_passed=True,
                tests_ran=True,
                process=process,
                validation=tuple(validation),
                reason="tests passed" if process.ok else "tests failed",
            )
