"""Entry point for ``python -m calm_generation``; delegates to :func:`calm_generation.cli.main`."""
"""Entry point for ``python -m calm_generation``; delegates to :func:`calm_generation.cli.main`."""
from calm_generation.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
