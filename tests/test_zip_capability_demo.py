from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from capabilities import CapabilityManager, CapabilityStore
from core import ContextBus, NexaKernel, SkillRegistry


class ZipCapabilityDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()

        # Workspace directory
        self.workspace = self.root / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)

        # Create a real ZIP archive in workspace
        self.archive_path = self.workspace / "test_data.zip"
        with zipfile.ZipFile(self.archive_path, "w") as zf:
            zf.writestr("doc1.txt", "Content of doc1")
            zf.writestr("subfolder/doc2.json", '{"key": "value"}')

        # Capability persistence and storage
        self.cap_db = self.root / "capabilities.db"
        self.cap_storage = self.root / "capabilities_code"
        self.store = CapabilityStore(self.cap_db)
        self.manager = CapabilityManager(
            store=self.store,
            storage_dir=self.cap_storage,
        )

        # Kernel setup
        self.context_bus = ContextBus()
        self.context_bus.set_active_workspace(self.workspace)
        self.registry = SkillRegistry()
        self.kernel = NexaKernel(
            registry=self.registry,
            context_bus=self.context_bus,
            capability_manager=self.manager,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_zip_capability_gap_detection_build_register_and_reuse(self):
        # 1. Verify before request: no zip skill exists in registry
        metadata_names = [m.name for m in self.registry.list_metadata()]
        self.assertNotIn("zip_extract", metadata_names)

        # 2. First request: "Extract this ZIP file test_data.zip into output_dir"
        response = self.kernel.process("extract test_data.zip into output_dir")

        # Must succeed through dynamically built skill
        self.assertEqual(response.status, "success")
        self.assertIn("Successfully extracted", response.message)

        # 3. Verify extracted contents exist in workspace
        dest = self.workspace / "output_dir"
        self.assertTrue((dest / "doc1.txt").is_file())
        self.assertEqual(
            (dest / "doc1.txt").read_text(encoding="utf-8"),
            "Content of doc1",
        )
        self.assertTrue((dest / "subfolder" / "doc2.json").is_file())

        # 4. Verify capability was registered in registry
        metadata_names_after = [m.name for m in self.registry.list_metadata()]
        self.assertIn("zip_extract", metadata_names_after)

        # 5. Verify capability was persisted in database
        saved = self.store.get_capability("file.zip.extract")
        self.assertIsNotNone(saved)
        self.assertEqual(saved.spec.name, "zip_extract")
        self.assertEqual(saved.test_status, "passed")
        self.assertEqual(saved.usage_count, 1)

        # 6. Verify observability events were recorded
        events = self.store.get_events(limit=20)
        event_types = [e.event_type.value for e in events]
        self.assertIn("CAPABILITY_REQUESTED", event_types)
        self.assertIn("CAPABILITY_MISSING", event_types)
        self.assertIn("CAPABILITY_BUILD_STARTED", event_types)
        self.assertIn("CAPABILITY_BUILD_COMPLETED", event_types)
        self.assertIn("CAPABILITY_TEST_PASSED", event_types)
        self.assertIn("CAPABILITY_REGISTERED", event_types)
        self.assertIn("CAPABILITY_EXECUTED", event_types)

        # 7. Future request: "unzip test_data.zip into second_output"
        # Must reuse the registered skill immediately without rebuilding!
        events_count_before = len(self.store.get_events())
        response2 = self.kernel.process("unzip test_data.zip into second_output")

        self.assertEqual(response2.status, "success")
        self.assertTrue((self.workspace / "second_output" / "doc1.txt").is_file())

        # Usage count incremented
        saved2 = self.store.get_capability("file.zip.extract")
        self.assertEqual(saved2.usage_count, 2)

        # 8. Test restart persistence: create a fresh registry and load from store
        new_registry = SkillRegistry()
        new_manager = CapabilityManager(
            store=self.store,
            storage_dir=self.cap_storage,
        )
        loaded_count = new_manager.load_all_into_registry(new_registry)
        self.assertEqual(loaded_count, 1)
        self.assertIn("zip_extract", [m.name for m in new_registry.list_metadata()])

        # Execute through new kernel
        new_kernel = NexaKernel(
            registry=new_registry,
            context_bus=self.context_bus,
            capability_manager=new_manager,
        )
        response3 = new_kernel.process("unzip test_data.zip into third_output")
        self.assertEqual(response3.status, "success")
        self.assertTrue((self.workspace / "third_output" / "doc1.txt").is_file())


if __name__ == "__main__":
    unittest.main()
