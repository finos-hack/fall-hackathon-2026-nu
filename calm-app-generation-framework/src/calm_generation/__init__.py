"""CALM app-generation framework: read, generate and validate CALM architectures."""

from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_VARIANTS_DIR = FRAMEWORK_ROOT / "fixtures" / "variants"
