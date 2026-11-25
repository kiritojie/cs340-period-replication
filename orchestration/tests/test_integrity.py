"""Outer SHA checks; all evidence is synthetic and no target is launched."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "rq1_integrity_under_test", ROOT / "orchestration/rq1_integrity.py")
INTEGRITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INTEGRITY)


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rq1-integrity-", dir=str(ROOT))
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def raw(self, name="stdout.log", value=b"synthetic raw log\n"):
        path = self.base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return path

    def test_nested_manifests_cover_logs_and_nested_manifest_bytes(self):
        self.raw()
        nested = self.raw("round/stdout.log")
        INTEGRITY.seal_tree(nested.parent)
        INTEGRITY.seal_tree(self.base)
        result = INTEGRITY.verify_tree(self.base)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["manifests"], 2)
        self.assertEqual(result["entries"], 4)

    def test_unlisted_raw_file_is_rejected(self):
        self.raw()
        INTEGRITY.seal_tree(self.base)
        self.raw("stderr.log")
        with self.assertRaisesRegex(ValueError, "unlisted.*stderr.log"):
            INTEGRITY.verify_tree(self.base)

    def test_modified_or_missing_raw_file_is_rejected(self):
        path = self.raw()
        INTEGRITY.seal_tree(self.base)
        path.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch.*stdout.log"):
            INTEGRITY.verify_tree(self.base)
        path.unlink()
        with self.assertRaisesRegex(ValueError, "missing evidence.*stdout.log"):
            INTEGRITY.verify_tree(self.base)

    def test_unsafe_and_duplicate_manifest_entries_are_rejected(self):
        path = self.raw()
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = self.base / "SHA256SUMS"
        for name in ("../outside.log", "/outside.log", "C:/outside.log", "a/../stdout.log"):
            with self.subTest(name=name):
                manifest.write_text(checksum + "  " + name + "\n")
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    INTEGRITY.verify_tree(self.base)
        manifest.write_text((checksum + "  stdout.log\n") * 2)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            INTEGRITY.verify_tree(self.base)

    def test_windows_separators_are_normalized_before_duplicate_check(self):
        path = self.raw("round/stdout.log")
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = self.base / "SHA256SUMS"
        manifest.write_text(checksum + "  round\\stdout.log\n")
        self.assertEqual(INTEGRITY.verify_tree(self.base)["status"], "PASS")
        manifest.write_text(checksum + "  round\\stdout.log\n" + checksum + "  round/stdout.log\n")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            INTEGRITY.verify_tree(self.base)

    def test_malformed_empty_and_absent_manifests_are_rejected(self):
        self.raw()
        with self.assertRaisesRegex(ValueError, "no SHA256SUMS"):
            INTEGRITY.verify_tree(self.base)
        manifest = self.base / "SHA256SUMS"
        for text, message in (("", "empty"), ("abc  stdout.log\n", "malformed")):
            manifest.write_text(text)
            with self.assertRaisesRegex(ValueError, message):
                INTEGRITY.verify_tree(self.base)

    def test_seal_is_exclusive_and_never_overwrites_manifest(self):
        self.raw()
        manifest = INTEGRITY.seal_tree(self.base)
        original = manifest.read_bytes()
        with self.assertRaises(FileExistsError):
            INTEGRITY.seal_tree(self.base)
        self.assertEqual(manifest.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
