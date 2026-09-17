# Engine releases

Games use an exact PyPI dependency such as `saga2d==0.2.0`, with their lockfile
committed. They must not have a default `saga2d` entry in `[tool.uv.sources]`.
The engine checkout can then change without changing a game's environment.
Sagaforge and the game repositories may still be editable sibling dependencies.

When moving an existing environment from an editable checkout to the first
release, force replacement even if both report the same version:

```bash
uv sync --locked --extra dev --reinstall-package saga2d
```

Older uv versions can retain the editable installation during a plain sync.
Check `uv run python -c "import saga2d; print(saga2d.__file__)"`: it must point
inside the game's `.venv/.../site-packages`, not the sibling engine checkout.

## Versions and upgrades

`saga2d/__init__.py` is the only version source; Hatch reads `__version__`
without importing the engine. Update it and `CHANGELOG.md` for each release.
While the engine is 0.x, patches contain compatible fixes and minor releases
may change public interfaces. Describe breaking changes and their migration
in the changelog. Never replace an existing release; publish a new version.

To upgrade a game, edit its exact dependency, run `uv lock` and
`uv sync --locked --extra dev`, then run its integration suite and any native
checks relevant to the engine changes. Commit the dependency and lockfile
together. Games can upgrade separately; the shared room-server project must
select one engine version compatible with all the games it hosts.

## Test an engine checkout deliberately

From a game directory:

```bash
uv sync --locked --extra dev
uv pip install --no-deps --editable ../saga2d
uv run --no-sync pytest -q
uv run --no-sync warband   # substitute the game's entry point
uv sync --locked --extra dev --reinstall-package saga2d
```

The final sync restores the released engine. If the candidate adds dependencies,
install those in the test environment too. Do not commit a local source override
or regenerate the game's lockfile against the checkout.

## Prepare a release

Start with a clean engine checkout. Update the version and changelog, then:

```bash
uv sync --extra dev
uv run --locked pytest -q
uv build --no-sources --out-dir dist/0.2.0
uvx twine check --strict dist/0.2.0/*
```

Substitute the release version in the output directory. `uv build` builds the
wheel from the source distribution, so both artifacts exercise the same source
payload. A fresh version directory keeps older artifacts out of the upload.

Install the wheel in a separate environment and run the distribution check from
outside the checkout (POSIX example):

```bash
ENGINE_ROOT="$PWD"
RELEASE_CHECK="$(mktemp -d)"
uv venv "$RELEASE_CHECK/venv" --python 3.12
uv pip install --python "$RELEASE_CHECK/venv/bin/python" \
  "$ENGINE_ROOT/dist/0.2.0/saga2d-0.2.0-py3-none-any.whl" pytest
(cd "$RELEASE_CHECK" && "$RELEASE_CHECK/venv/bin/python" -I \
  "$ENGINE_ROOT/tools/check_distribution.py")
```

CI repeats the package build and installed-distribution check. Before a release
that changes public behavior, also test the affected games against the candidate
engine. Commit the verified release changes and tag that commit `v0.2.0`
(substitute the new version). Record artifact SHA256 hashes with the release
evidence. Do not rebuild or edit the artifacts between verification and upload.

## Publish

Saga2D is AI-owned. The maintainer authorizes agents to prepare and publish
engine releases to PyPI and push the verified engine commits and release tags
without asking for approval each time. Follow the preparation, verification,
artifact integrity and consumer-upgrade steps in this guide. Record any known
baseline failures separately from regressions introduced by the candidate;
resolve new regressions before publishing.

The entire Saga stack is AI-owned under [the stack rules](../../AGENTS.md).
The standing authorization also covers game binaries, room-server and website
deployments, and CI publishing setup without another approval request. Follow
their respective verification and rollout procedures.

Load a PyPI API token into `UV_PUBLISH_TOKEN` through the local credential store;
never put it in a command argument, source file or GitHub log. Then publish only
the verified files:

```bash
uv publish dist/0.2.0/saga2d-0.2.0-py3-none-any.whl dist/0.2.0/saga2d-0.2.0.tar.gz
git push origin main v0.2.0
```

Confirm installation from PyPI in a fresh environment outside the checkout,
using `uv pip install --python <fresh-python> 'saga2d==0.2.0' pytest`, and run
the same distribution check. Then migrate each consumer's pin and lockfile,
run its tests and commit the upgrade. Do not publish game builds or deploy the
room server as part of an engine release.
