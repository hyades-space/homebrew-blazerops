#!/usr/bin/env python3
"""Bump Formula/blazerops.rb to the release https://blazerops.ai serves as latest.

    python3 .github/scripts/bump_formula.py check          # is latest/VERSION newer?
    python3 .github/scripts/bump_formula.py bump X.Y.Z      # verify v<X.Y.Z>/, rewrite the formula

`check` prints `version=<X.Y.Z>` and `newer=true|false` (appended to $GITHUB_OUTPUT when set).
`bump` downloads v<X.Y.Z>/SHA256SUMS and all four binaries, refuses unless every binary hashes
to its SHA256SUMS line, then rewrites `version` and the four `sha256` values and nothing else.
With --summary FILE it also writes a Markdown summary (the PR body).

blazerops.ai answers a key that does not exist with 200 and the website's HTML, so a 200 proves
nothing. VERSION must be a release version, SHA256SUMS must be checksum lines, and each binary
must hash to its line; anything else is refused by name.

The host is the one the formula's url lines name. DOWNLOAD_HOST overrides it (tests only; any
host but https:// or loopback http:// is refused). Standard library only.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORMULA = ROOT / "Formula" / "blazerops.rb"
ASSETS = ("blazerops-darwin-arm64", "blazerops-darwin-x86_64",
          "blazerops-linux-arm64", "blazerops-linux-x86_64")
RELEASE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
VERSION_LINE = re.compile(r'^(\s*version ")([^"]*)(".*)$')
URL_LINE = re.compile(r'^\s*url "(https?://[^/"]+)/v#\{version\}/([^"/]+)"\s*$')
SHA_LINE = re.compile(r'^(\s*sha256 ")([0-9a-f]{64})(".*)$')
SUMS_LINE = re.compile(r"^([0-9a-f]{64}) [ *](\S+)$")
NO_RELEASE = "0.0.0"
TIMEOUT_S = 60
MAX_TEXT = 64 * 1024
MAX_BINARY = 512 * 1024 * 1024


class Refused(Exception):
    """A check failed; the message says which and why."""


def looks_like_html(head: bytes) -> bool:
    return head.lstrip()[:15].lower().startswith((b"<!doctype html", b"<html"))


def snippet(data: bytes) -> str:
    text = data[:80].decode("utf-8", "replace").replace("\n", "\\n")
    return text + ("..." if len(data) > 80 else "")


class Formula:
    """The lines bump_formula.py may change, located once and checked."""

    def __init__(self, path: Path):
        self.path = path
        self.lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        versions = [i for i, line in enumerate(self.lines) if VERSION_LINE.match(line)]
        if len(versions) != 1:
            raise Refused(f"{path.name}: expected one `version` line, found {len(versions)}")
        self.version_at = versions[0]
        self.sha_at: dict[str, int] = {}
        hosts = set()
        for i, line in enumerate(self.lines):
            m = URL_LINE.match(line)
            if not m:
                continue
            host, asset = m.groups()
            hosts.add(host)
            j = i + 1
            while j < len(self.lines) and not self.lines[j].strip():
                j += 1
            if j == len(self.lines) or not SHA_LINE.match(self.lines[j]):
                raise Refused(f"{path.name}:{i + 1}: url for {asset} is not followed by a sha256")
            if asset in self.sha_at:
                raise Refused(f"{path.name}: {asset} has two url lines")
            self.sha_at[asset] = j
        if sorted(self.sha_at) != sorted(ASSETS):
            raise Refused(f"{path.name}: url lines name {sorted(self.sha_at)}, expected {list(ASSETS)}")
        if len(hosts) != 1:
            raise Refused(f"{path.name}: url lines name more than one host: {sorted(hosts)}")
        self.host = hosts.pop()

    @property
    def version(self) -> str:
        return VERSION_LINE.match(self.lines[self.version_at]).group(2)

    def sha256(self, asset: str) -> str:
        return SHA_LINE.match(self.lines[self.sha_at[asset]]).group(2)

    def rewritten(self, version: str, sums: dict[str, str]) -> list[str]:
        lines = list(self.lines)
        lines[self.version_at] = VERSION_LINE.sub(rf"\g<1>{version}\g<3>", lines[self.version_at])
        for asset, at in self.sha_at.items():
            lines[at] = SHA_LINE.sub(rf"\g<1>{sums[asset]}\g<3>", lines[at])
        return lines


def release_tuple(version: str) -> tuple[int, int, int]:
    m = RELEASE.fullmatch(version)
    if not m:
        raise Refused(f"{version!r} is not a release version X.Y.Z")
    return tuple(int(p) for p in m.groups())


def download_host(formula: Formula) -> str:
    host = os.environ.get("DOWNLOAD_HOST") or formula.host
    u = urllib.parse.urlsplit(host)
    loopback = u.hostname in ("127.0.0.1", "localhost", "::1")
    if not (u.scheme == "https" or (u.scheme == "http" and loopback)) or u.path not in ("", "/"):
        raise Refused(f"refusing download host {host!r}: https:// (or loopback http://) only")
    return host.rstrip("/")


def fetch(url: str, sink, limit: int) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": "homebrew-blazerops-bump"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            if urllib.parse.urlsplit(resp.geturl()).scheme != urllib.parse.urlsplit(url).scheme:
                raise Refused(f"{url} redirected to {resp.geturl()}")
            n = 0
            while chunk := resp.read(1 << 20):
                n += len(chunk)
                if n > limit:
                    raise Refused(f"{url} is larger than {limit} bytes")
                sink(chunk)
            return n
    except OSError as e:  # URLError, HTTPError, timeouts
        raise Refused(f"downloading {url} failed: {e}") from e


def fetch_text(url: str) -> bytes:
    buf = bytearray()
    fetch(url, buf.extend, MAX_TEXT)
    return bytes(buf)


def parse_sums(url: str, data: bytes) -> dict[str, str]:
    if looks_like_html(data):
        raise Refused(f"{url} is a web page, not a checksum list (the release is not published "
                      f"there): {snippet(data)}")
    sums: dict[str, str] = {}
    for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
        if not line.strip():
            continue
        m = SUMS_LINE.match(line)
        if not m:
            raise Refused(f"{url}:{n} is not a checksum line: {line[:80]!r}")
        digest, name = m.groups()
        if name in sums:
            raise Refused(f"{url} lists {name} twice")
        sums[name] = digest
    missing = [a for a in ASSETS if a not in sums]
    if missing:
        raise Refused(f"{url} has no checksum for {', '.join(missing)}")
    return {a: sums[a] for a in ASSETS}


def verify_binary(url: str, expected: str) -> None:
    h = hashlib.sha256()
    head = bytearray()

    def sink(chunk: bytes) -> None:
        if len(head) < 64:
            head.extend(chunk[:64 - len(head)])
        h.update(chunk)

    size = fetch(url, sink, MAX_BINARY)
    got = h.hexdigest()
    if got != expected:
        what = "a web page (the file is not published)" if looks_like_html(bytes(head)) else f"{size} bytes"
        raise Refused(f"{url} does not match SHA256SUMS: expected {expected}, got {got} ({what})")


def emit(pairs: dict[str, str]) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{k}={v}\n" for k, v in pairs.items())
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(lines)
    print(lines, end="")


def check(formula: Formula) -> int:
    host = download_host(formula)
    url = f"{host}/latest/VERSION"
    data = fetch_text(url)
    latest = data.decode("utf-8", "replace").strip()
    current = formula.version
    if not RELEASE.fullmatch(latest):
        if current == NO_RELEASE:
            print(f"::notice::no release is published at {host} yet ({url} is not a version: "
                  f"{snippet(data)})")
            emit({"version": "", "newer": "false"})
            return 0
        raise Refused(f"{url} is not a release version (got {snippet(data)}); the formula is at "
                      f"{current}, so the host has lost the latest release")
    if release_tuple(latest) < release_tuple(current):
        raise Refused(f"{url} says {latest}, older than the formula's {current}")
    newer = release_tuple(latest) > release_tuple(current)
    print(f"formula {current}, {host} latest {latest}: {'bump' if newer else 'up to date'}")
    emit({"version": latest, "newer": "true" if newer else "false"})
    return 0


def bump(formula: Formula, version: str, summary: Path | None) -> int:
    if release_tuple(version) <= release_tuple(formula.version):
        raise Refused(f"{version} is not newer than the formula's {formula.version}")
    host = download_host(formula)
    base = f"{host}/v{version}"
    sums = parse_sums(f"{base}/SHA256SUMS", fetch_text(f"{base}/SHA256SUMS"))
    for asset in ASSETS:
        verify_binary(f"{base}/{asset}", sums[asset])
        print(f"verified {asset} {sums[asset]}")
    before = formula.lines
    after = formula.rewritten(version, sums)
    changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    allowed = {formula.version_at, *formula.sha_at.values()}
    if len(before) != len(after) or not set(changed) <= allowed or formula.version_at not in changed:
        raise Refused("the rewrite changed lines other than version and the four sha256 values")
    formula.path.write_text("".join(after), encoding="utf-8")
    reread = Formula(formula.path)
    if reread.version != version or any(reread.sha256(a) != sums[a] for a in ASSETS):
        raise Refused(f"{formula.path.name} does not read back as {version} with the verified sums")
    sys.stdout.writelines(difflib.unified_diff(before, after, "a/Formula/blazerops.rb",
                                               "b/Formula/blazerops.rb"))
    if summary:
        rows = "\n".join(f"| `{a}` | `{sums[a]}` |" for a in ASSETS)
        summary.write_text(
            f"Bumps `blazerops` from {formula.version} to **{version}**, the release "
            f"{formula.host}/latest/VERSION names.\n\n"
            f"Each binary was downloaded from `{formula.host}/v{version}/` and hashed to its line "
            f"in that release's `SHA256SUMS` before the formula was rewritten:\n\n"
            f"| Binary | sha256 |\n| --- | --- |\n{rows}\n\n"
            f"`brew style` and `brew audit --strict` passed on the bumped formula. "
            f"Opened by `.github/workflows/bump.yml`.\n", encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--formula", type=Path, default=FORMULA)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="is latest/VERSION newer than the formula?")
    b = sub.add_parser("bump", help="verify a release and rewrite the formula")
    b.add_argument("version")
    b.add_argument("--summary", type=Path, help="write a Markdown summary here")
    args = ap.parse_args(argv)
    try:
        formula = Formula(args.formula)
        if args.cmd == "check":
            return check(formula)
        return bump(formula, args.version, args.summary)
    except Refused as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
