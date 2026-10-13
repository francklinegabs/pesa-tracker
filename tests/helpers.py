import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from pesa.cli import main
from pesa.db import Ledger


class LedgerCase(unittest.TestCase):
    """Gives each test a fresh database in a temporary folder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "pesa.db"
        self.ledger = Ledger(self.path)

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def run_cli(self, *argv, expect=0) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = main(["--db", str(self.path), *argv])
        self.assertEqual(code, expect, out.getvalue())
        return out.getvalue()
