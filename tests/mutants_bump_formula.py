#!/usr/bin/env python3
"""Mutation check for tests/test_bump_formula.py (HYA-1854).

    python3 -u tests/mutants_bump_formula.py

Each mutant removes one refusal from .github/scripts/bump_formula.py; the named test must then
fail. Refuses a dirty bump_formula.py (so `git checkout -- <file>` always restores a killed run),
runs the unmodified suite first, and restores the file in `finally`. Exit 0 when every mutant is
killed by its named test.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".github/scripts/bump_formula.py"
SUITE = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]

# (old, new, the test that must fail, what the mutant breaks)
MUTANTS = [
    ("    if got != expected:\n", "    if False:\n",
     "test_bump_refuses_a_corrupted_binary", "binaries are not checked against SHA256SUMS"),
    ("    if looks_like_html(data):\n", "    if False:\n",
     "test_bump_refuses_sha256sums_that_is_the_site_html", "an HTML SHA256SUMS is not named"),
    ("    if missing:\n", "    if False:\n",
     "test_bump_refuses_sha256sums_missing_a_binary_or_malformed", "a binary without a checksum"),
    ("        if name in sums:\n", "        if False:\n",
     "test_bump_refuses_sha256sums_missing_a_binary_or_malformed", "duplicate checksum lines"),
    ("        if not m:\n            raise Refused(f\"{url}:{n} is not a checksum line",
     "        if not m:\n            continue\n            raise Refused(f\"{url}:{n} is not a checksum line",
     "test_bump_refuses_sha256sums_missing_a_binary_or_malformed", "junk lines in SHA256SUMS"),
    ("    if not RELEASE.fullmatch(latest):\n", "    if not latest:\n",
     "test_check_before_any_release_is_quiet", "HTML for latest/VERSION before a release"),
    ("    if release_tuple(latest) < release_tuple(current):\n", "    if False:\n",
     "test_check_refuses_a_latest_older_than_the_formula", "latest older than the formula"),
    ("    if release_tuple(version) <= release_tuple(formula.version):\n", "    if False:\n",
     "test_bump_refuses_a_version_that_is_not_newer", "bump to a version that is not newer"),
    ('RELEASE = re.compile(r"(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)")',
     'RELEASE = re.compile(r"([0-9]+)\\.([0-9]+)\\.([0-9]+)")',
     "test_check_refuses_a_version_that_is_not_x_y_z", "leading zeros accepted"),
    ("    if not (u.scheme == \"https\" or (u.scheme == \"http\" and loopback))",
     "    if False and not (u.scheme == \"https\" or (u.scheme == \"http\" and loopback))",
     "test_refuses_a_plain_http_host", "plain http download host"),
]


def suite() -> subprocess.CompletedProcess:
    return subprocess.run(SUITE, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          timeout=600, env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"})


def main() -> int:
    dirty = subprocess.run(["git", "status", "--porcelain", "--", str(TARGET)], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout
    if dirty.strip():
        print(f"refusing: {TARGET.name} has uncommitted changes")
        return 2
    base = suite()
    if base.returncode != 0:
        print(f"refusing: the unmodified suite fails\n{base.stderr}")
        return 2
    original = TARGET.read_bytes()
    text = original.decode("utf-8")
    survived = []
    for old, new, test, what in MUTANTS:
        if text.count(old) != 1:
            print(f"STALE     {what}: anchor found {text.count(old)} times")
            survived.append(what)
            continue
        try:
            TARGET.write_text(text.replace(old, new), encoding="utf-8")
            res = suite()
        finally:
            TARGET.write_bytes(original)
        killed = res.returncode != 0 and (f"{test} " in res.stderr) and (
            f"FAIL: {test} " in res.stderr or f"ERROR: {test} " in res.stderr)
        print(f"{'killed' if killed else 'SURVIVED'}  {what}  [{test}]")
        if not killed:
            survived.append(what)
    print(f"{len(MUTANTS) - len(survived)} of {len(MUTANTS)} mutants killed by their named test")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
