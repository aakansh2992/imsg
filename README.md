# algotrader

A confluence-based, multi-market algorithmic paper-trading system —
strategies vote, regime-aware confluence gates the vote, and a hard risk
layer enforces daily loss limits and end-of-day flat. Pure Python ≥ 3.10,
zero dependencies, with a browser control panel that works on any device.

**All documentation lives in [`algotrader/README.md`](algotrader/README.md).**

Quick start:

```bash
cd algotrader
python3 -m unittest discover -s tests   # test suite
python3 -m algotrader web               # control panel at http://localhost:8899/
```

> ⚠️ Paper trading and research tooling only. Nothing here guarantees
> profits, and synthetic-data results validate machinery, not edge. See the
> full disclaimer in `algotrader/README.md`.

*(This repository previously contained the `imsg` Swift iMessage CLI; it was
removed at the owner's request and remains available in git history.)*
