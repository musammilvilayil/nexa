from __future__ import annotations
import sys
import unittest
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from providers.registry import ProviderRegistry

class MockProvider:
    def __init__(self, name: str):
        self.name = name
    def __repr__(self) -> str:
        return f"MockProvider({self.name})"

class TestProviderRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = ProviderRegistry()

    def test_register_and_get(self):
        provider = MockProvider("p1")
        self.registry.register("test_type", provider)
        self.assertEqual(self.registry.get("test_type"), provider)
        self.assertTrue(self.registry.is_registered("test_type"))

    def test_require_missing(self):
        with self.assertRaises(KeyError):
            self.registry.require("missing_type")

    def test_require_existing(self):
        provider = MockProvider("p1")
        self.registry.register("test_type", provider)
        self.assertEqual(self.registry.require("test_type"), provider)

    def test_duplicate_registration_raises(self):
        self.registry.register("test_type", MockProvider("p1"))
        with self.assertRaises(ValueError):
            self.registry.register("test_type", MockProvider("p2"))

    def test_replace_hotswap(self):
        self.registry.register("test_type", MockProvider("p1"))
        new_provider = MockProvider("p2")
        self.registry.replace("test_type", new_provider)
        self.assertEqual(self.registry.get("test_type"), new_provider)

    def test_remove(self):
        self.registry.register("test_type", MockProvider("p1"))
        self.registry.remove("test_type")
        self.assertFalse(self.registry.is_registered("test_type"))
        self.assertIsNone(self.registry.get("test_type"))
        # Removing non-existent should not raise
        self.registry.remove("missing_type")

    def test_list_providers(self):
        p1 = MockProvider("p1")
        p2 = MockProvider("p2")
        self.registry.register("type1", p1)
        self.registry.register("type2", p2)
        
        providers = self.registry.list_providers()
        self.assertEqual(providers["type1"], "MockProvider(p1)")
        self.assertEqual(providers["type2"], "MockProvider(p2)")

if __name__ == "__main__":
    unittest.main()
