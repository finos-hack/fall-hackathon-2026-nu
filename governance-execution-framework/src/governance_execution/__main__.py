"""Entry point for ``python -m governance_execution``; delegates to :func:`governance_execution.cli.main`."""
from governance_execution.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
