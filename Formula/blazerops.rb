# Homebrew formula for the BlazerOps CLI — lives in the tap repo
# `hyades-space/homebrew-blazerops` (as `Formula/blazerops.rb`).
#
#   brew install hyades-space/blazerops/blazerops
#
# Binary-based: it downloads the same signed release binary the curl|sh installer uses,
# pinned by sha256. The `version` + four `sha256` values are bumped per release (see
# RELEASING.md — an automated PR from the release workflow).
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
    assert_match "blazerops", shell_output("#{bin}/blazerops --version 2>&1", 0)
  end
end
