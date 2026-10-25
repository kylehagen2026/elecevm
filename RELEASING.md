# Releasing

Releases are cut by `.github/workflows/release.yml`, which runs on every push to
`main` that touches `pyproject.toml`, `src/elecevm/__init__.py` or `CHANGELOG.md`
(or by hand from the Actions tab):

1. Bump `version` in `pyproject.toml` and `__version__` in `src/elecevm/__init__.py`;
   add the version's section to `CHANGELOG.md` (its text becomes the release notes).
2. Push to `main`. If no tag `vX.Y.Z` exists yet, the workflow creates it, publishes
   the GitHub Release and attaches the wheel and sdist. The release is installable
   immediately: `pip install https://github.com/kylehagen2026/elecevm/releases/download/vX.Y.Z/elecevm-X.Y.Z-py3-none-any.whl`.
3. The `pypi` job then publishes through **trusted publishing**. One-time setup on
   https://pypi.org: add a pending publisher for project `elecevm` with owner
   `kylehagen2026`, repository `elecevm`, workflow `release.yml`, environment `pypi`.
   Until that exists the `pypi` job fails and can be re-run from the Actions tab
   once it does. No API token is stored anywhere.
