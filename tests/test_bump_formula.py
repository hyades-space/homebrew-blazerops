"""Tests for .github/scripts/bump_formula.py (HYA-1854).

    python3 -m unittest discover -s tests -v

A local HTTP server stands in for https://blazerops.ai, including its habit of answering a key
that does not exist with 200 and the website's HTML. Each test bumps a copy of the real
Formula/blazerops.rb. Standard library only.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import os
import shutil
import tempfile
import threading
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("bump_formula", ROOT / ".github/scripts/bump_formula.py")
bump_formula = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bump_formula)

ASSETS = bump_formula.ASSETS
SITE_HTML = b"<!doctype html>\n<html lang=\"en\"><head><title>BlazerOps</title></head></html>\n"


class Site(BaseHTTPRequestHandler):
    files: dict[str, bytes] = {}

    def do_GET(self):  # noqa: N802 - http.server's name
        body = self.files.get(self.path, SITE_HTML)  # the site's fallback: 200 + HTML
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def release(version: str, *, corrupt: str | None = None, drop: str | None = None,
            sums_extra: bytes = b"", sums: bytes | None = None) -> dict[str, bytes]:
    """The files the CLI release mirror publishes for `version`."""
    bins = {a: f"#!/bin/sh\necho 'blazerops {version}' # {a}\n".encode() for a in ASSETS}
    lines = b"".join(f"{hashlib.sha256(b).hexdigest()}  {a}\n".encode() for a, b in bins.items())
    files = {f"/v{version}/SHA256SUMS": sums if sums is not None else lines + sums_extra,
             "/latest/VERSION": f"{version}\n".encode()}
    for a, b in bins.items():
        if a == drop:
            continue
        files[f"/v{version}/{a}"] = b + b"tampered" if a == corrupt else b
    return files


class BumpFormulaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.host = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.formula = self.tmp / "blazerops.rb"
        shutil.copy(ROOT / "Formula/blazerops.rb", self.formula)
        self.output = self.tmp / "github_output"
        env = {"DOWNLOAD_HOST": self.host, "GITHUB_OUTPUT": str(self.output)}
        patcher = unittest.mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        Site.files = {}

    def run_script(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = bump_formula.main(["--formula", str(self.formula), *args])
        return rc, out.getvalue()

    def outputs(self) -> dict[str, str]:
        if not self.output.exists():
            return {}
        return dict(line.split("=", 1) for line in self.output.read_text().splitlines())

    def set_formula_version(self, version: str):
        text = self.formula.read_text(encoding="utf-8")
        self.formula.write_text(text.replace('version "0.0.0"', f'version "{version}"'),
                                encoding="utf-8")

    # ── the formula as committed ──────────────────────────────────────────────────────────────

    def test_the_committed_formula_parses(self):
        f = bump_formula.Formula(ROOT / "Formula/blazerops.rb")
        self.assertEqual(f.host, "https://blazerops.ai")
        self.assertEqual(sorted(f.sha_at), sorted(ASSETS))
        self.assertTrue(bump_formula.RELEASE.fullmatch(f.version), f.version)

    # ── check ─────────────────────────────────────────────────────────────────────────────────

    def test_check_before_any_release_is_quiet(self):
        rc, out = self.run_script("check")  # latest/VERSION answers the site's HTML
        self.assertEqual(rc, 0, out)
        self.assertIn("no release is published", out)
        self.assertEqual(self.outputs(), {"version": "", "newer": "false"})

    def test_check_finds_a_newer_release(self):
        Site.files = release("1.2.3")
        rc, out = self.run_script("check")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.outputs(), {"version": "1.2.3", "newer": "true"})

    def test_check_on_the_same_release_does_nothing(self):
        Site.files = release("1.2.3")
        self.set_formula_version("1.2.3")
        rc, out = self.run_script("check")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.outputs(), {"version": "1.2.3", "newer": "false"})

    def test_check_refuses_a_latest_older_than_the_formula(self):
        Site.files = release("1.2.3")
        self.set_formula_version("1.10.0")  # numeric, not string, order: 1.10.0 > 1.2.3
        rc, out = self.run_script("check")
        self.assertEqual(rc, 1, out)
        self.assertIn("older than the formula's 1.10.0", out)

    def test_check_refuses_html_once_a_release_exists(self):
        self.set_formula_version("1.2.3")
        rc, out = self.run_script("check")
        self.assertEqual(rc, 1, out)
        self.assertIn("lost the latest release", out)
        self.assertEqual(self.outputs(), {})

    def test_check_refuses_a_version_that_is_not_x_y_z(self):
        self.set_formula_version("1.2.3")
        for bad in (b"1.3.0rc1\n", b"v1.3.0\n", b"1.3\n", b"01.3.0\n", b"1.3.0/../x\n"):
            Site.files = {"/latest/VERSION": bad}
            rc, out = self.run_script("check")
            self.assertEqual(rc, 1, (bad, out))

    # ── bump ──────────────────────────────────────────────────────────────────────────────────

    def test_bump_rewrites_version_and_the_four_sums_only(self):
        files = release("1.2.3")
        Site.files = files
        before = self.formula.read_text(encoding="utf-8").splitlines()
        summary = self.tmp / "summary.md"
        rc, out = self.run_script("bump", "1.2.3", "--summary", str(summary))
        self.assertEqual(rc, 0, out)
        after = self.formula.read_text(encoding="utf-8").splitlines()
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        self.assertEqual(len(before), len(after))
        self.assertEqual(len(changed), 5, changed)
        f = bump_formula.Formula(self.formula)
        self.assertEqual(f.version, "1.2.3")
        for a in ASSETS:
            self.assertEqual(f.sha256(a), hashlib.sha256(files[f"/v1.2.3/{a}"]).hexdigest())
            self.assertIn(f"`{f.sha256(a)}`", summary.read_text())
        self.assertIn("from 0.0.0 to **1.2.3**", summary.read_text())

    def test_bump_refuses_a_corrupted_binary(self):
        Site.files = release("1.2.3", corrupt="blazerops-linux-arm64")
        before = self.formula.read_bytes()
        rc, out = self.run_script("bump", "1.2.3")
        self.assertEqual(rc, 1, out)
        self.assertIn("blazerops-linux-arm64 does not match SHA256SUMS", out)
        self.assertEqual(self.formula.read_bytes(), before)

    def test_bump_refuses_a_binary_that_is_the_site_html(self):
        Site.files = release("1.2.3", drop="blazerops-darwin-x86_64")
        before = self.formula.read_bytes()
        rc, out = self.run_script("bump", "1.2.3")
        self.assertEqual(rc, 1, out)
        self.assertIn("blazerops-darwin-x86_64 does not match SHA256SUMS", out)
        self.assertIn("a web page", out)
        self.assertEqual(self.formula.read_bytes(), before)

    def test_bump_refuses_sha256sums_that_is_the_site_html(self):
        Site.files = {k: v for k, v in release("1.2.3").items() if not k.endswith("SHA256SUMS")}
        before = self.formula.read_bytes()
        rc, out = self.run_script("bump", "1.2.3")
        self.assertEqual(rc, 1, out)
        self.assertIn("is a web page, not a checksum list", out)
        self.assertEqual(self.formula.read_bytes(), before)

    def test_bump_refuses_sha256sums_missing_a_binary_or_malformed(self):
        good = release("1.2.3")["/v1.2.3/SHA256SUMS"]
        cases = {
            "has no checksum for blazerops-linux-x86_64":
                b"".join(line + b"\n" for line in good.splitlines() if b"linux-x86_64" not in line),
            "is not a checksum line": good + b"not a checksum line\n",
            "lists blazerops-darwin-arm64 twice": good + good.splitlines()[0] + b"\n",
        }
        for message, sums in cases.items():
            Site.files = release("1.2.3", sums=sums)
            rc, out = self.run_script("bump", "1.2.3")
            self.assertEqual(rc, 1, (message, out))
            self.assertIn(message, out)

    def test_bump_ignores_extra_entries_in_sha256sums(self):
        Site.files = release("1.2.3", sums_extra=b"0" * 64 + b"  blazerops-windows-x86_64.exe\n")
        rc, out = self.run_script("bump", "1.2.3")
        self.assertEqual(rc, 0, out)

    def test_bump_refuses_a_version_that_is_not_newer(self):
        Site.files = release("1.2.3")
        self.set_formula_version("1.2.3")
        rc, out = self.run_script("bump", "1.2.3")
        self.assertEqual(rc, 1, out)
        self.assertIn("is not newer", out)

    def test_refuses_a_plain_http_host(self):
        Site.files = release("1.2.3")
        with unittest.mock.patch.dict(os.environ, {"DOWNLOAD_HOST": "http://blazerops.ai"}):
            rc, out = self.run_script("check")
        self.assertEqual(rc, 1, out)
        self.assertIn("https:// (or loopback http://) only", out)


if __name__ == "__main__":
    unittest.main()
