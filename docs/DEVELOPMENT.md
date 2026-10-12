# Development

For maintainers and contributors: running the tests, the performance and
end-to-end gates, shipping pins, and where the design notes live.

## Tests

The unit tests run on the Command Line Tools' Python, the same interpreter `daoc`
uses (CI does the same, see `.github/workflows/tests.yml`):

```bash
/usr/bin/python3 -m unittest discover -s tests -v
```

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

## Design and notes

- [DESIGN.md](DESIGN.md) — repo layout, manifest schema, install flows, server
  updates and saved progress
- [REVIEW.md](REVIEW.md) — review of the ported code and scripts
- [CLIENT-NOTES.md](CLIENT-NOTES.md) — client findings under Wine on Apple
  silicon (x87 performance, privacy prompt, prefix user, linkdead wait)
- [SERVER-NOTES.md](SERVER-NOTES.md) — upstream server issues documented, not
  patched
- [server/README.md](../server/README.md) — the macOS server port: build
  pipeline, differences from the Linux repo, maintenance
