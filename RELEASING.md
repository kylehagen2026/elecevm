# Releasing

1. Bump `version` in `pyproject.toml` and `__version__` in `src/elecevm/__init__.py`; add the CHANGELOG entry.
2. Commit, tag `vX.Y.Z`, push the tag, and publish a GitHub Release from it.
3. `release.yml` builds the sdist and wheel and publishes to PyPI through **trusted publishing**:
   on https://pypi.org, add a pending publisher for project `elecevm` with owner `kylehagen2026`,
   repository `elecevm`, workflow `release.yml`, environment `pypi`; then create the `pypi`
   environment under the repo's Settings → Environments. No API token is stored anywhere.
