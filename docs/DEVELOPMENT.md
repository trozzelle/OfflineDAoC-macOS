# Development

For maintainers and contributors: running the tests, the performance and
end-to-end gates, shipping pins, and where the design notes live.

## Tests

The unit tests run on the Command Line Tools' Python, the same interpreter `daoc`
uses (CI does the same, see `.github/workflows/tests.yml`):

```bash
/usr/bin/python3 -m unittest discover -s tests -v
```

CI also runs the suite on the app's bundled Python (`app/python.lock`) and the app's Swift
tests: `swift test --package-path app`.

## Benchmark

`daoc client bench [--seconds 300] [--tag bench]` is the performance gate. It
logs in as the saved Game account's most recently played character
(`DAOC_CHARACTER` picks another), plays for 5 minutes (NPC interaction plus
movement through the Connacht town), and reports average FPS, p95/p99 frame
time and 1%-low FPS from a per-present probe.

| Exit | Meaning |
|---|---|
| 0 | Pass: average of at least 60 FPS with p95 at or under 16.7 ms |
| 1 | Fail |
| 2 | Invalid run (no frames, server gone, character never moved) |

It raises the account to GM for the run (it needs `/jump` and `/target`) and puts
it back afterwards; if that restore fails, the next run does it first. Run it
from a GUI Terminal with the server up (`daoc server start`); it uses the same
port as `daoc client start` and needs `brew install mingw-w64` for its input
helper.

## Maintainer commands

The `dev` group is left out of `daoc --help`.

- `daoc dev ship-pins` writes the effective pins into `manifest.json` as the new
  Shipped pins (see [UPDATING.md](UPDATING.md#pins)).
- `daoc dev e2e` runs the end-to-end check on its own server on ports
  20300/20400, putting the config back when it's done.

## Releases

[release-please](https://github.com/googleapis/release-please-action) versions
the repo (`.github/workflows/release-please.yml`). Every push to `main` updates
a release PR that bumps `version.txt` and `CHANGELOG.md`; merging it tags
`vX.Y.Z` and publishes the GitHub Release. The next version comes from the
[Conventional Commits](https://www.conventionalcommits.org/) on `main`, so with
squash merges the PR title is what counts:

| Commit | Bump (before 1.0) | Use for |
|---|---|---|
| `fix(client): …` | patch | bug fixes, corrected pins or hashes |
| `feat(server): …` | minor | new commands, new Shipped pins |
| `feat!: …` | minor (major from 1.0) | removed or renamed commands, changed behavior users rely on |
| `docs:`, `test:`, `ci:`, `chore:` | none | everything else |

Users run release tags, not `main`: the release PR also rewrites the
`git clone --branch vX.Y.Z` lines in the README and [PLAY.md](PLAY.md) (between
the `x-release-please-start-version` markers), so they always name the latest
release. A fix reaches users only once its release PR is merged.

The workflow runs as a GitHub App, not `GITHUB_TOKEN`, so the release PR gets
the `tests.yml` checks. The App's client ID (`RELEASE_APP_CLIENT_ID`, a
variable) and private key (`RELEASE_APP_PRIVATE_KEY`, a secret) belong to the
repository's `main` environment.

## The app

- Try it: `app/dev-run.sh` builds the app from this checkout, signs it ad hoc and opens it on
  a test data folder (`~/Library/Application Support/OfflineDAoC-dev`, or `$DAOC_DEV_DATA`)
  that is kept between runs; `app/dev-run.sh --fresh` stops that folder's server and deletes
  it first, so Setup starts from nothing. The app's real data folder and this checkout's
  installs are never touched, but Setup's account step replaces the Game account the CLI
  keeps in the Keychain.
- Build and smoke: `app/build-app.sh /tmp/odaoc && app/sign-app.sh /tmp/odaoc/OfflineDAoC.app - && /tmp/odaoc/OfflineDAoC.app/Contents/MacOS/OfflineDAoC --self-test`.
- Releases: `app.yml` publishes the DMG on each release tag. Its five secrets
  (`DEVELOPER_ID_P12` (base64), `P12_PASSWORD`, `NOTARY_KEY_ID`, `NOTARY_ISSUER`,
  `NOTARY_KEY_P8`) live in the repository's `release` environment, not `main`: release
  runs are triggered by `v*` tags, and the `release` environment admits those tags (and
  branch `main`), whereas the `main` environment admits only the branch. The release-please
  App key stays in `main`.
- Prebuilt server: after a server pin moves, run
  `gh workflow run server-prebuilt.yml -f version=<version>` and merge its PR before the
  release, or the app falls back to a source build it cannot do. The workflow refuses to
  replace an asset that is already published (no `--clobber`), because a rebuild is not
  byte-identical and released manifests pin the old hash; to rebuild, delete the asset
  deliberately first.
- Manual pre-release check, on a clean macOS user account: download the DMG in Safari, open
  it through Gatekeeper, run Setup with the original client, Play into the world, create bots,
  quit with the server running.

## Design and notes

- [DESIGN.md](DESIGN.md) — repo layout, manifest schema, install flows, server
  updates and saved progress
- [REVIEW.md](REVIEW.md) — review of the ported code and scripts
- [CLIENT-NOTES.md](CLIENT-NOTES.md) — client findings under Wine on Apple
  silicon (x87 performance under Rosetta and FEX, privacy prompts, the Local
  Network stall, game.dll's `Shared` section, prefix user, linkdead wait)
- [SERVER-NOTES.md](SERVER-NOTES.md) — upstream server issues documented, not
  patched
- [server/README.md](../server/README.md) — the macOS server port: build
  pipeline, differences from the Linux repo, maintenance
