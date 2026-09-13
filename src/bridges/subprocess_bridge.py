from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


class SubprocessBridgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProcessResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class SubprocessBridge:
    """Strict argument-array subprocess wrapper.

    There is deliberately no command-string or shell mode. Skills must provide a
    pre-approved executable and a sequence of inert arguments.
    """

    MINIMAL_ENV_KEYS = (
        "HOME",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    )

    def __init__(
        self,
        allowed_executables: Iterable[str],
        *,
        default_timeout: float = 30.0,
        max_output_chars: int = 200_000,
        inherit_environment: bool = False,
        allowed_env_keys: Iterable[str] = (),
    ) -> None:
        names = {Path(item).name.lower() for item in allowed_executables if str(item).strip()}
        if not names:
            raise ValueError("allowed_executables cannot be empty")
        if default_timeout <= 0:
            raise ValueError("default_timeout must be positive")
        if max_output_chars <= 0:
            raise ValueError("max_output_chars must be positive")
        self.allowed_executables = frozenset(names)
        self.default_timeout = float(default_timeout)
        self.max_output_chars = int(max_output_chars)
        self.inherit_environment = bool(inherit_environment)
        self.allowed_env_keys = frozenset(str(key) for key in allowed_env_keys)

    def run(
        self,
        executable: str | Path,
        args: Iterable[str] = (),
        *,
        cwd: str | Path | None = None,
        timeout: float | None = None,
        env_overrides: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        executable_text = str(executable)
        if not executable_text.strip() or "\x00" in executable_text:
            raise SubprocessBridgeError("invalid executable")
        basename = Path(executable_text).name.lower()
        if basename not in self.allowed_executables:
            raise SubprocessBridgeError(f"executable is not allow-listed: {basename}")

        normalized_args: list[str] = []
        for arg in args:
            if not isinstance(arg, str):
                raise SubprocessBridgeError("subprocess arguments must be strings")
            if "\x00" in arg:
                raise SubprocessBridgeError("NUL byte is not allowed in subprocess argument")
            normalized_args.append(arg)

        resolved_cwd = None
        if cwd is not None:
            resolved = Path(cwd).expanduser().resolve()
            if not resolved.exists() or not resolved.is_dir():
                raise SubprocessBridgeError("cwd must be an existing directory")
            resolved_cwd = str(resolved)

        effective_timeout = self.default_timeout if timeout is None else float(timeout)
        if effective_timeout <= 0:
            raise SubprocessBridgeError("timeout must be positive")

        environment = self._environment(env_overrides or {})
        command = [executable_text, *normalized_args]
        try:
            completed = subprocess.run(
                command,
                cwd=resolved_cwd,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=effective_timeout,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise SubprocessBridgeError(f"process timed out after {effective_timeout:g}s") from exc
        except OSError as exc:
            raise SubprocessBridgeError(f"process launch failed: {exc}") from exc

        return ProcessResult(
            args=tuple(command),
            returncode=completed.returncode,
            stdout=self._bounded(completed.stdout or ""),
            stderr=self._bounded(completed.stderr or ""),
        )

    def _environment(self, overrides: Mapping[str, str]) -> dict[str, str]:
        if self.inherit_environment:
            environment = os.environ.copy()
        else:
            environment = {
                key: os.environ[key]
                for key in self.MINIMAL_ENV_KEYS
                if key in os.environ
            }

        for key, value in overrides.items():
            if key not in self.allowed_env_keys:
                raise SubprocessBridgeError(f"environment override is not allowed: {key}")
            if not isinstance(value, str) or "\x00" in value:
                raise SubprocessBridgeError(f"invalid environment value for {key}")
            environment[key] = value
        return environment

    def _bounded(self, text: str) -> str:
        if len(text) <= self.max_output_chars:
            return text
        suffix = "\n<output truncated>"
        keep = max(0, self.max_output_chars - len(suffix))
        return text[:keep] + suffix
