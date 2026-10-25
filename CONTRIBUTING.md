# Contributing

Issues and pull requests are welcome. The bar for a change to the engine's
numbers is the Recommended Practice in `docs/standard.md`: a change that alters
how PV, EV or AC is computed must cite the section it implements or propose an
amendment to it.

Before opening a pull request:

```bash
pip install -e ".[dev]"
pytest
elecevm example --out /tmp/elecevm-example   # must finish with 13/13 checks passing
```

Field data is the most valuable contribution. If you have installed-quantity
and labor-hour records that support different milestone weights for a
commodity, open an issue with the commodity, the proposed weights, the
project type and the sample size. No client, owner or contractor names are
needed and none should be included.

By contributing you agree that your contributions are licensed under the
Apache License 2.0.
