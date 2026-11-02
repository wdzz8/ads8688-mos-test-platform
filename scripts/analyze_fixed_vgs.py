"""Compatibility entry point for single-curve and family output analysis."""
import sys

if __package__:
    from .analyze_fixed_vgs_family import main
else:
    from analyze_fixed_vgs_family import main

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
