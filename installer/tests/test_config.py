"""Tests for config storage (JSON / YAML / TOML)."""

import os
import tempfile
import unittest
from pathlib import Path

from installer.core import config as cfg


class YamlParseTests(unittest.TestCase):
    def test_flat_mapping(self):
        text = "key: value\nnum: 3\nflag: true\nnil: null\n"
        self.assertEqual(cfg._load_yaml(text), {"key": "value", "num": 3,
                                                "flag": True, "nil": None})

    def test_nested_mapping_and_lists(self):
        text = (
            "packages:\n"
            "  git:\n"
            "    verify: git\n"
            "    systems:\n"
            "      apt: [git]\n"
            "      brew: [git]\n"
        )
        data = cfg._load_yaml(text)
        self.assertEqual(data["packages"]["git"]["systems"]["apt"], ["git"])
        self.assertEqual(data["packages"]["git"]["verify"], "git")

    def test_comments_and_blank_lines_ignored(self):
        data = cfg._load_yaml("# comment\n\na: 1\n\n# another\nb: two\n")
        self.assertEqual(data, {"a": 1, "b": "two"})

    def test_dump_yaml_roundtrip(self):
        data = {"a": 1, "b": "x", "nested": {"c": [1, 2]}}
        reparsed = cfg._load_yaml(cfg._dump_yaml(data))
        self.assertEqual(reparsed, data)


class TomlTests(unittest.TestCase):
    def test_load_toml(self):
        data = cfg._load_toml("a = 1\nb = \"x\"\n[c]\nd = true\n")
        self.assertEqual(data["a"], 1)
        self.assertEqual(data["c"]["d"], True)

    def test_dump_toml_roundtrip(self):
        data = {"a": 1, "b": "x", "c": True, "d": [1, 2]}
        reparsed = cfg._load_toml(cfg._dump_toml(data))
        self.assertEqual(reparsed, data)


class ConfigStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_json_roundtrip(self):
        store = cfg.ConfigStore("test-app", "config.json", "json", self.dir)
        c = cfg.Config({"k": "v", "n": 1})
        store.save(c)
        self.assertEqual(store.load().to_dict(), {"k": "v", "n": 1})

    def test_yaml_read_write(self):
        store = cfg.ConfigStore("test-app", "config.yaml", "yaml", self.dir)
        store.save(cfg.Config({"k": "v"}))
        self.assertEqual(store.load().to_dict(), {"k": "v"})

    def test_toml_read_write(self):
        store = cfg.ConfigStore("test-app", "config.toml", "toml", self.dir)
        store.save(cfg.Config({"k": "v", "num": 3}))
        self.assertEqual(store.load().to_dict(), {"k": "v", "num": 3})

    def test_missing_file_returns_empty(self):
        store = cfg.ConfigStore("test-app", "config.json", "json", self.dir)
        self.assertEqual(store.load().to_dict(), {})

    def test_corrupt_file_raises(self):
        store = cfg.ConfigStore("test-app", "config.json", "json", self.dir)
        store.path.write_text("{not json")
        with self.assertRaises(cfg.ConfigError):
            store.load()

    def test_file_mode_is_0600(self):
        store = cfg.ConfigStore("test-app", "config.json", "json", self.dir)
        store.save(cfg.Config({"token": "secret"}))
        if os.name != "nt":
            self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)

    def test_merged_user_overrides_default(self):
        merged = cfg.Config({"a": 1, "b": 1}).merged({"a": 2, "c": 3})
        self.assertEqual(merged, {"a": 2, "b": 1, "c": 3})


if __name__ == "__main__":
    unittest.main()
