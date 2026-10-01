"""Tests for the coin logo generator (site/logos/coin.py).

Covers:
  - the default run reproduces the committed coin.txt / coin.mask;
  - the command documented for coin-small reproduces coin-small.txt / .mask;
  - the plain & crosses itself twice and the curled one three times, at
    every size from the smallest allowed up to the default;
  - the command line rejects too few rows and a rim outside 0..1.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path

LOGOS = Path(__file__).resolve().parents[1] / "site" / "logos"


def _load():
    spec = importlib.util.spec_from_file_location("coin_logo", LOGOS / "coin.py")
    mod = importlib.util.module_from_spec(spec)
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True   # no __pycache__ in site/
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


coin = _load()


def _committed(name):
    return tuple((LOGOS / f"{name}.{ext}").read_text(encoding="utf-8").splitlines()
                 for ext in ("txt", "mask"))


class CommittedLogos(unittest.TestCase):

    def test_default_run_reproduces_coin(self):
        args = coin.parse_args([])
        chars, mask, _ = coin.coin(args.rows, args.curl, args.rim)
        self.assertEqual((chars, mask), _committed("coin"))

    def test_documented_command_reproduces_coin_small(self):
        args = coin.parse_args(["--rows", "15", "--name", "coin-small"])
        self.assertIn("--rows 15 --name coin-small", coin.__doc__)
        chars, mask, _ = coin.coin(args.rows, args.curl, args.rim)
        self.assertEqual((chars, mask), _committed("coin-small"))


class Crossings(unittest.TestCase):

    def test_plain_two_curl_three(self):
        for rows in range(coin.MIN_ROWS, coin.DEFAULT_ROWS + 1):
            for curl, want in ((False, 2), (True, 3)):
                with self.subTest(rows=rows, curl=curl):
                    path = coin.cord_path(rows, curl)
                    self.assertEqual(len(coin.crossings(path, rows)), want)

    def test_coin_reports_its_crossings(self):
        self.assertEqual(coin.coin(coin.MIN_ROWS, curl=True)[2], 3)


class CommandLine(unittest.TestCase):

    def _rejects(self, argv):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            coin.parse_args(argv)
        self.assertNotEqual(cm.exception.code, 0)

    def test_rejects_bad_rows_and_rim(self):
        for argv in (["--rows", "0"], ["--rows", "-3"], ["--rows", "5"],
                     ["--rim", "1"], ["--rim", "0"], ["--rim", "1.5"]):
            with self.subTest(argv=argv):
                self._rejects(argv)

    def test_accepts_the_edges(self):
        args = coin.parse_args(["--rows", str(coin.MIN_ROWS), "--rim", "0.99"])
        self.assertEqual((args.rows, args.rim), (coin.MIN_ROWS, 0.99))

    def test_coin_validates_too(self):
        with self.assertRaises(ValueError):
            coin.coin(0)
        with self.assertRaises(ValueError):
            coin.coin(rim=1)


if __name__ == "__main__":
    unittest.main()
