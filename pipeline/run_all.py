"""Run the whole pipeline: ASP + crosswalk -> hospital files -> comparison.

Run from the infusion-audit folder:  python -m pipeline.run_all
"""
import sys

from . import build_compare, load_asp, load_drug, parse_hpt

if __name__ == "__main__":
    for step in (load_asp, load_drug, parse_hpt, build_compare):
        print(f"\n=== {step.__name__.split('.')[-1]} ===")
        if step.main() != 0:
            sys.exit(1)
