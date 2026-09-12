# Publishing a release to the tap

The formula next to this file is a draft: it cannot be installed until a real
release exists, because Homebrew verifies the tarball's checksum.

## One-time setup

1. Create a repository named **`homebrew-tap`** under the same account. The
   `homebrew-` prefix is what makes `brew tap ganggangstone/tap` work.
2. Put the formula at `Formula/agent-hud.rb` in that repository.

## For each release

1. Tag and push the release in this repository:

   ```bash
   git tag v0.1.0 && git push origin v0.1.0
   ```

2. Get the checksum of the tarball GitHub generates for that tag:

   ```bash
   curl -sL https://github.com/ganggangstone/agent-hud/archive/refs/tags/v0.1.0.tar.gz | shasum -a 256
   ```

3. In the tap's `Formula/agent-hud.rb`, update `url` (the version in the path)
   and `sha256` with what you just got, and commit.

4. Check it before anyone else does:

   ```bash
   brew install --build-from-source ganggangstone/tap/agent-hud
   brew test agent-hud
   brew audit --strict --online ganggangstone/tap/agent-hud
   ```

`brew audit` is the same check Homebrew runs on submissions; it catches a
missing license, a bad URL, and style problems.

## Two installers, one procedure

`install.sh` and this formula both install the same `server.py` and both set up
a launchd service. **They are two copies of one procedure and they will drift.**
Before changing either, decide whether the other needs the same change — and if
the formula becomes the recommended path, delete `install.sh` rather than
maintaining both.

Known differences today:

| | `install.sh` | formula |
|---|---|---|
| Python | whatever `python3` resolves to | `python@3.13` from Homebrew |
| Service | writes a launchd plist directly | `brew services` |
| Updates | `git pull` | `brew upgrade` |
| Data | `~/.claude/tools/agent-hud` | same, via `AGENT_HUD_HOME` |
