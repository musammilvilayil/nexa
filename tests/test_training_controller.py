from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from training.task_generator import TrainingTask, generate_tasks, save_tasks_jsonl
from training.verifiers import RealResultVerifier, VerificationResult
from training.training_controller import TrainingController, TrainingMode, FailureRootCause


class TestTrainingSubsystem(unittest.TestCase):
    """Unit tests for training generator, verifiers, and closed-loop controller."""

    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.sandbox_dir = self.data_dir / "sandbox"
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_task_generator_generates_at_least_5000_tasks(self):
        tasks = generate_tasks(self.sandbox_dir)
        self.assertGreaterEqual(len(tasks), 5000)
        tasks_file = self.data_dir / "tasks.jsonl"
        save_tasks_jsonl(tasks, tasks_file)
        self.assertTrue(tasks_file.exists())
        self.assertGreater(tasks_file.stat().st_size, 100000)

    def test_02_verifiers_file_exists_and_content(self):
        test_file = self.sandbox_dir / "verifier_test.txt"
        test_file.write_text("Hello NEXA Autonomous Training Verifier", encoding="utf-8")

        res_exists = RealResultVerifier.verify("file_exists", {"path": str(test_file)})
        self.assertTrue(res_exists.passed)

        res_content = RealResultVerifier.verify("file_content", {"path": str(test_file), "expected_content": "Autonomous Training"})
        self.assertTrue(res_content.passed)

        res_missing = RealResultVerifier.verify("file_exists", {"path": str(self.sandbox_dir / "nonexistent.txt")})
        self.assertFalse(res_missing.passed)

    def test_03_verifiers_storage_audit(self):
        res = RealResultVerifier.verify("storage_audit", {}, {"success": True, "message": "Storage report: C: 50GB, D: 900GB"})
        self.assertTrue(res.passed)

    def test_04_training_controller_checkpoint_persistence(self):
        tasks = [
            TrainingTask(
                task_id=1,
                category="Storage Analysis",
                difficulty="LEVEL 1",
                prompt="analyze my storage on C: and D:",
                description="Storage test",
                required_skills=["storage_audit"],
                expected_result="Verified",
                verifier_type="storage_audit",
                verifier_params={},
                risk_level="READ",
            ),
            TrainingTask(
                task_id=2,
                category="Self-Diagnosis Tasks",
                difficulty="LEVEL 2",
                prompt="Run capability verification",
                description="Self test",
                required_skills=["self_test"],
                expected_result="Verified",
                verifier_type="self_test",
                verifier_params={},
                risk_level="READ",
            ),
        ]
        save_tasks_jsonl(tasks, self.data_dir / "tasks.jsonl")

        ctrl = TrainingController(data_dir=self.data_dir, mode=TrainingMode.TEST_ONLY)
        self.assertEqual(ctrl.stats.total_tasks, 2)

        stats = ctrl.run_training(max_tasks=2)
        self.assertEqual(stats.completed_tasks, 2)
        self.assertGreaterEqual(stats.passed, 1)

        # Verify checkpoint file exists
        self.assertTrue(ctrl.checkpoint_file.exists())
        data = json.loads(ctrl.checkpoint_file.read_text(encoding="utf-8"))
        self.assertEqual(data.get("last_completed_task"), 2)

        # Resume from checkpoint
        ctrl2 = TrainingController(data_dir=self.data_dir)
        last_task = ctrl2.load_checkpoint()
        self.assertEqual(last_task, 2)


if __name__ == "__main__":
    unittest.main()
