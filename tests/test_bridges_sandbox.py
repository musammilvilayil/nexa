import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bridges import GeminiBridge, OllamaBridge, SubprocessBridge
from sandbox import SandboxRunner, StaticValidator


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("unexpected test status")

    def json(self):
        return self._payload


class BridgeAndSandboxTests(unittest.TestCase):
    @patch("bridges.subprocess_bridge.subprocess.run")
    def test_subprocess_bridge_never_uses_shell_and_does_not_inherit_secrets(self, run):
        run.return_value = subprocess.CompletedProcess(["python"], 0, stdout="ok", stderr="")
        bridge = SubprocessBridge([Path(sys.executable).name])
        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret"}, clear=False):
            result = bridge.run(sys.executable, ["arg;still-one-argument"])
        self.assertTrue(result.ok)
        kwargs = run.call_args.kwargs
        self.assertFalse(kwargs["shell"])
        self.assertNotIn("GEMINI_API_KEY", kwargs["env"])
        self.assertEqual(run.call_args.args[0][1], "arg;still-one-argument")

    def test_static_validator_blocks_direct_escape_hatches(self):
        report = StaticValidator().validate(
            "import os\nvalue = eval('1+1')\nos.system('whoami')\n"
        )
        self.assertFalse(report.safe)
        codes = {finding.code for finding in report.findings}
        self.assertIn("forbidden_import", codes)
        self.assertIn("forbidden_call", codes)

    def test_static_validator_blocks_direct_filesystem_database_and_nexa_internals(self):
        report = StaticValidator().validate(
            "from pathlib import Path\n"
            "import sqlite3\n"
            "from skills.trading.promotion import StrategyPromotionStore\n"
        )
        self.assertFalse(report.safe)
        blocked = [finding.message for finding in report.findings if finding.code == "forbidden_import"]
        self.assertTrue(any("pathlib" in message for message in blocked))
        self.assertTrue(any("sqlite3" in message for message in blocked))
        self.assertTrue(any("skills" in message for message in blocked))

    def test_static_validator_allows_only_narrow_core_skill_contract(self):
        validator = StaticValidator()
        safe = validator.validate(
            "from core import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata\n"
        )
        unsafe = validator.validate("from core import NexaKernel, SQLiteAuditLedger\n")
        bare = validator.validate("import core\n")
        self.assertTrue(safe.safe)
        self.assertFalse(unsafe.safe)
        self.assertFalse(bare.safe)

    def test_sandbox_runs_safe_unittest_candidate(self):
        files = {
            "skill.py": "def add(a, b):\n    return a + b\n",
            "test_skill.py": (
                "import unittest\n"
                "from skill import add\n\n"
                "class TestAdd(unittest.TestCase):\n"
                "    def test_add(self):\n"
                "        self.assertEqual(add(2, 3), 5)\n"
            ),
        }
        result = SandboxRunner(timeout=15).run(files)
        self.assertTrue(result.validation_passed)
        self.assertTrue(result.tests_ran)
        self.assertTrue(result.passed, result.process.stderr if result.process else result.reason)

    @patch("bridges.gemini_bridge.httpx.post")
    def test_gemini_bridge_uses_env_key_and_validates_structured_json(self, post):
        post.return_value = _FakeResponse(
            {
                "candidates": [
                    {"content": {"parts": [{"text": '{"lesson":"risk first"}'}]}}
                ]
            }
        )
        schema = {
            "type": "object",
            "properties": {"lesson": {"type": "string"}},
            "required": ["lesson"],
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=False):
            result = GeminiBridge(model="gemini-test", max_retries=0).generate_json("teach", schema)
        self.assertEqual(result["lesson"], "risk first")
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["x-goog-api-key"], "test-key")

    @patch("bridges.ollama_bridge.httpx.post")
    def test_ollama_bridge_disables_streaming_and_thinking(self, post):
        post.return_value = _FakeResponse({"message": {"content": "hello"}})
        result = OllamaBridge(model="qwen3:1.7b").chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result, "hello")
        payload = post.call_args.kwargs["json"]
        self.assertFalse(payload["stream"])
        self.assertFalse(payload["think"])


if __name__ == "__main__":
    unittest.main()
