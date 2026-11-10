# Homebrew formula for the BlazerOps CLI.
#
#   brew install hyades-space/blazerops/blazerops
#
# Binary-based: it downloads the same release binary the curl | sh installer uses, from
# https://blazerops.ai, pinned by sha256. `version` and the four `sha256` values are bumped by
# .github/workflows/bump.yml: it opens a PR once https://blazerops.ai/latest/VERSION names a
# newer release and every binary matches that release's SHA256SUMS.
class Blazerops < Formula
  desc "Code-first pipeline authoring CLI for the BlazerOps platform"
  homepage "https://blazerops.ai"
  version "0.0.0" # bumped per release
  license "Apache-2.0"

  on_macos do
    on_arm do
      url "https://blazerops.ai/v#{version}/blazerops-darwin-arm64"
      sha256 "0000000000000000000000000000000000000000000000000000000000000000"
    end
    on_intel do
      url "https://blazerops.ai/v#{version}/blazerops-darwin-x86_64"
      sha256 "0000000000000000000000000000000000000000000000000000000000000000"
    end
  end

  on_linux do
    on_arm do
      url "https://blazerops.ai/v#{version}/blazerops-linux-arm64"
      sha256 "0000000000000000000000000000000000000000000000000000000000000000"
    end
    on_intel do
      url "https://blazerops.ai/v#{version}/blazerops-linux-x86_64"
      sha256 "0000000000000000000000000000000000000000000000000000000000000000"
    end
  end

  def install
    bin.install Dir["blazerops-*"].first => "blazerops"
  end

  test do
    assert_match "blazerops #{version}", shell_output("#{bin}/blazerops --version")
  end
end
