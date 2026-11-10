# homebrew-blazerops

Homebrew tap for the BlazerOps CLI.

```sh
brew install hyades-space/blazerops/blazerops
```

The formula downloads the release binary from https://blazerops.ai, pinned by sha256.

## How the formula follows releases

The CLI's release workflow publishes each release to `https://blazerops.ai/v<version>/` (four
binaries and `SHA256SUMS`) and then points `https://blazerops.ai/latest/VERSION` at it. This
tap's [`bump`](.github/workflows/bump.yml) workflow runs hourly and on demand (Actions → bump →
Run workflow). When `latest/VERSION` names a newer release than the formula, it:

1. downloads that release's `SHA256SUMS` and all four binaries, and refuses unless each binary
   matches its line (blazerops.ai answers a missing file with 200 and the website's HTML, so the
   checksum is the only proof a file is real);
2. rewrites `version` and the four `sha256` values, and nothing else;
3. runs `brew style` and `brew audit --strict` on the result;
4. opens a PR `blazerops <version>` from `bump/blazerops-<version>` with this repo's own
   `GITHUB_TOKEN`, and starts [`ci`](.github/workflows/ci.yml) on it (Linux and macOS).

Merging that PR releases the formula. It opens no second PR for a version that already has one,
even a closed one; to retry, delete the `bump/blazerops-<version>` branch. GitHub stops a public
repo's schedules after 60 days without activity, so if a release gets no PR within the hour,
check that the workflow is enabled and run it by hand.

Tests: `python3 -m unittest discover -s tests -v` (the bump script, against a local stand-in for
blazerops.ai) and `python3 tests/e2e_bump_docker.py` (the bump job end to end in Homebrew's
docker image).
