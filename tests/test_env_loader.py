"""Validator: project-root .env loading (stdlib loader, no new dependency).

Proves keys placed in `.env` reach the backend process (the exact failure the
user hit: keys "given before" never arrived because nothing loaded `.env`).
Uses fake values only; never touches real credentials or training files.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.env import load_dotenv  # noqa: E402


class EnvLoader(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__import__("tempfile").mkdtemp(prefix="aqua_env_test_")) / ".env"

    def tearDown(self):
        for k in ("T_GROQ", "T_GEMINI", "T_QUOTED", "T_EXPORT"):
            os.environ.pop(k, None)
        try:
            self.tmp.unlink()
            self.tmp.parent.rmdir()
        except OSError:
            pass

    def test_file_values_loaded_when_missing(self):
        self.tmp.write_text('T_GROQ=gsk_test_fake\nT_GEMINI=AIza_test_fake\n', encoding="utf-8")
        out = load_dotenv(self.tmp)
        self.assertEqual(os.environ.get("T_GROQ"), "gsk_test_fake")
        self.assertEqual(out["T_GROQ"], "file")

    def test_process_env_wins_over_file(self):
        self.tmp.write_text('T_GROQ=from_file\n', encoding="utf-8")
        with mock.patch.dict(os.environ, {"T_GROQ": "from_shell"}):
            out = load_dotenv(self.tmp)
            self.assertEqual(os.environ["T_GROQ"], "from_shell")
            self.assertEqual(out["T_GROQ"], "env")

    def test_quotes_comments_exports_and_junk_handled(self):
        self.tmp.write_text(
            '# comment\n\nexport T_EXPORT=abc\nT_QUOTED="quoted value"\n'
            "NOEQUALS\n=noname\nT_GROQ=ok\n",
            encoding="utf-8",
        )
        load_dotenv(self.tmp)
        self.assertEqual(os.environ.get("T_EXPORT"), "abc")
        self.assertEqual(os.environ.get("T_QUOTED"), "quoted value")
        self.assertEqual(os.environ.get("T_GROQ"), "ok")
        self.assertNotIn("NOEQUALS", os.environ)

    def test_bom_file_loads_first_line(self):
        # PowerShell Set-Content -Encoding utf8 writes a BOM; the first key
        # must still load (regression: BOM used to poison the first key).
        self.tmp.write_bytes(b'\xef\xbb\xbfT_GROQ=gsk_test_fake\nT_GEMINI=AIza_test_fake\n')
        load_dotenv(self.tmp)
        self.assertEqual(os.environ.get("T_GROQ"), "gsk_test_fake")
        self.assertEqual(os.environ.get("T_GEMINI"), "AIza_test_fake")

    def test_missing_file_never_raises(self):
        self.assertEqual(load_dotenv(self.tmp.parent / "does-not-exist"), {})


if __name__ == "__main__":
    unittest.main()
