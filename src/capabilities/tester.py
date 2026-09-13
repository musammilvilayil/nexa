from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from bridges import ProcessResult, SubprocessBridge

from .contracts import CapabilityTestResult


class CapabilityTester:
    """Runs test suites for newly generated skills in an isolated sandbox environment."""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        src_path: Path | None = None,
    ) -> None:
        self.timeout = float(timeout)
        self.src_path = (src_path or Path(__file__).resolve().parents[1]).resolve()

    def run_tests(self, skill_code: str, test_code: str) -> CapabilityTestResult:
        with tempfile.TemporaryDirectory(prefix="nexa-cap-test-") as temp_dir:
            temp_path = Path(temp_dir).resolve()

            skill_file = temp_path / "skill.py"
            test_file = temp_path / "test_skill.py"

            skill_file.write_text(skill_code, encoding="utf-8")
            test_file.write_text(test_code, encoding="utf-8")

            bridge = SubprocessBridge(
                [Path(sys.executable).name],
                default_timeout=self.timeout,
                inherit_environment=False,
                allowed_env_keys=("PYTHONPATH", "SYSTEMROOT", "PATH", "TEMP", "TMP"),
            )

            # Pass PYTHONPATH pointing to NEXA src/ and temp directory
            pythonpath = f"{str(self.src_path)};{str(temp_path)}"

            try:
                proc = bridge.run(
                    sys.executable,
                    ["-m", "unittest", "test_skill.py", "-v"],
                    cwd=temp_path,
                    timeout=self.timeout,
                    env_overrides={"PYTHONPATH": pythonpath},
                )
                output = f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
                if proc.ok:
                    return CapabilityTestResult(
                        passed=True,
                        output=output,
                    )
                return CapabilityTestResult(
                    passed=False,
                    output=output,
                    error=f"Unittest failed with exit code {proc.returncode}",
                )
            except Exception as exc:
                return CapabilityTestResult(
                    passed=False,
                    output="",
                    error=f"Sandbox test execution exception: {exc}",
                )
