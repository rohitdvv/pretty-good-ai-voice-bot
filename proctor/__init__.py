"""
Proctor — Conversational AI Quality & Safety Assurance platform (starting-level MVP).

A local, runnable implementation of the full product loop described in ../docs:
    connect a target  ->  generate a test suite  ->  run it  ->  score it
    with real statistics  ->  produce an evidence-backed report  ->  gate regressions.

This package is deliberately structured to mirror the target architecture (docs/02),
so each module maps onto a future distributed service without being rewritten.
"""

__version__ = "0.1.0"
