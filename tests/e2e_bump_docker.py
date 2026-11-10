#!/usr/bin/env python3
"""End-to-end rehearsal of .github/workflows/bump.yml's bump job, locally, in docker (HYA-1854).

    python3 tests/e2e_bump_docker.py [--image ghcr.io/homebrew/ubuntu24.04:latest]

Serves a fake release 9.8.7 on loopback the way https://blazerops.ai serves one (missing keys
answer 200 with HTML), runs `bump_formula.py check` and `bump` against a scratch copy of this
repo's committed HEAD, then taps that copy in Homebrew's image and runs the same `brew style` and
`brew audit --strict` the workflow runs. Not run by CI (it needs docker); bump.yml does the real
thing against the real host.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "9.8.7"
ASSETS = ("blazerops-darwin-arm64", "blazerops-darwin-x86_64",
          "blazerops-linux-arm64", "blazerops-linux-x86_64")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--image", default="ghcr.io/homebrew/ubuntu24.04:latest")
    args = ap.parse_args()

    bins = {a: os.urandom(4096) for a in ASSETS}
    files = {f"/v{VERSION}/{a}": b for a, b in bins.items()}
    files[f"/v{VERSION}/SHA256SUMS"] = "".join(
        f"{hashlib.sha256(b).hexdigest()}  {a}\n" for a, b in bins.items()).encode()
    files["/latest/VERSION"] = f"{VERSION}\n".encode()

    class Site(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = files.get(self.path, b"<!doctype html><html></html>\n")
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {**os.environ, "DOWNLOAD_HOST": f"http://127.0.0.1:{server.server_address[1]}"}
    env.pop("GITHUB_OUTPUT", None)

    # A scratch dir under $HOME, not /tmp: a snap docker cannot mount /tmp.
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        tap = Path(d) / "homebrew-blazerops"
        subprocess.run(["git", "clone", "-q", str(ROOT), str(tap)], check=True)
        script = [sys.executable, str(tap / ".github/scripts/bump_formula.py")]
        check = subprocess.run([*script, "check"], env=env, capture_output=True, text=True)
        print(check.stdout + check.stderr, end="")
        if check.returncode or f"version={VERSION}" not in check.stdout or "newer=true" not in check.stdout:
            print("FAIL: check did not find the fake release")
            return 1
        bump = subprocess.run([*script, "bump", VERSION], env=env, capture_output=True, text=True)
        print(bump.stdout + bump.stderr, end="")
        if bump.returncode:
            print("FAIL: bump refused the fake release")
            return 1
        brew = subprocess.run(
            ["docker", "run", "--rm", "-v", f"{tap}:/src:ro", args.image, "bash", "-c",
             "set -e; T=$(brew --repository)/Library/Taps/hyades-space; mkdir -p \"$T\"; "
             "cp -r /src \"$T/homebrew-blazerops\"; export HOMEBREW_NO_AUTO_UPDATE=1; "
             # As setup-homebrew does: Homebrew 6+ loads no formula from an untrusted tap.
             "brew trust hyades-space/blazerops; "
             "brew --version | head -1; "
             "brew style hyades-space/blazerops; "
             "brew audit --strict --formula hyades-space/blazerops/blazerops; "
             "brew info --json=v2 hyades-space/blazerops/blazerops "
             "| grep -o '\"stable\": *\"[^\"]*\"'"],
            capture_output=True, text=True)
        print(brew.stdout + brew.stderr, end="")
        if brew.returncode or f'"stable": "{VERSION}"' not in brew.stdout.replace('":"', '": "'):
            print("FAIL: brew style / audit --strict / info on the bumped formula")
            return 1
    server.shutdown()
    print(f"PASS: check found {VERSION}, bump verified four binaries, brew style + audit --strict pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
