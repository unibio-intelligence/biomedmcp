#!/usr/bin/env python3
"""Live qualification; importing the definitions does not run the probes."""

from biomedmcp.canary import CASES, main, run

__all__ = ["CASES", "main", "run"]

if __name__ == "__main__":
    raise SystemExit(main())
