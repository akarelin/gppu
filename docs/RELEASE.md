# Release Process — `gppu`

Releases are driven by the [`gppu`](../.github/workflows/gppu.yml) workflow via **Actions → gppu → Run workflow**. Tagging happens inside the workflow; do not create `gppu/v*` tags by hand.

## Tag scheme

- Stable: `gppu/vX.Y.Z`
- Beta: `gppu/vX.Y.ZbN` (PEP 440 pre-release; published as a GitHub pre-release)
- `gppu/latest` always points to the most recent **stable** tag, **and** the GitHub Release named `gppu/latest` carries renamed assets (`gppu-latest-py3-none-any.whl`, `gppu-latest.tar.gz`) at a stable download URL.

The "latest tag" — stable or beta, whichever has the highest version — drives what the next dispatch produces.

## Workflow inputs

| Input | Effect |
|---|---|
| `bump` = `patch` | Create the next tag (see matrix below). |
| `bump` = `none` | Rebuild the latest existing tag — no new tag is created. |
| `beta` = `true` | Mark the new tag as a beta (`bN` suffix, GitHub pre-release). |
| `run_tests` | Run the test matrix before releasing. |
| `test_windows`, `test_sql`, `test_tui` | Add extra OS / extras combinations to the test matrix. |

## What `bump=patch` produces

Given the most recent `gppu/v*` tag:

| Latest tag | `beta=false` | `beta=true` |
|---|---|---|
| `vX.Y.Z` (stable) | `vX.Y.(Z+1)` — next patch | `vX.Y.(Z+1)b1` — first beta of next patch |
| `vX.Y.ZbN` (beta) | `vX.Y.Z` — **finalize the beta** | `vX.Y.Zb(N+1)` — next beta |

The "finalize the beta" row is the key flow: cut betas with `bump=patch beta=true` until the version is ready, then run once more with `bump=patch beta=false` to drop the `bN` suffix and publish the stable release.

## Typical flows

**Cut a new beta**

1. Land changes on `master`.
2. Dispatch `gppu` with `bump=patch beta=true`. If the latest tag is stable, this becomes `…b1`; if it's already a beta, it increments.

**Finalize a beta as stable**

1. Confirm the latest tag is `gppu/vX.Y.ZbN` and master is what you want to ship.
2. Dispatch `gppu` with `bump=patch beta=false`. The workflow tags `gppu/vX.Y.Z` on the dispatch ref, creates the GitHub release, force-updates the `gppu/latest` git tag, and clobber-uploads the freshly-built wheel/sdist to the `gppu/latest` GitHub Release so the stable download URL serves the new version.
3. `run_tests=false` is fine here if the beta already passed CI on the same commit — the release job only needs the tag and the build.

**Re-run a failed release without creating a new tag**

If the release step fails after the tag has been pushed (transient API error, etc.), dispatch with `bump=none` to rebuild and re-release the existing latest tag.

## Behind the scenes

- `setuptools_scm` reads `gppu/v*` tags only (`tool.setuptools_scm` in `pyproject.toml`), so other modules' tags don't perturb the version.
- The release job uses `RELEASE_PAT` (PAT secret) for `gh release create` so the release is attributed to the repo owner, not `github-actions[bot]`.
- `gppu/latest` is only moved forward on stable releases (`IS_PRE=false`). This step updates **both** the git tag (`git push -f`) and the GitHub Release assets (`gh release upload --clobber`, with dist files renamed `gppu-<VERSION>-*` → `gppu-latest-*`). GitHub does not auto-refresh Release assets when a tag is moved, so the explicit clobber-upload is required — without it, consumers pinned to `releases/download/gppu/latest/gppu-latest-py3-none-any.whl` keep getting whatever version was uploaded when the Release was first created.
