"""
Add the validators directory to sys.path so tests can import validators
directly without package-relative imports.
"""
import sys
from pathlib import Path

# Allow `import schema`, `import rn_calculator`, etc. from tests
VALIDATORS_DIR = Path(__file__).parent.parent / "scripts" / "oversight" / "validators"
OVERSIGHT_DIR  = Path(__file__).parent.parent / "scripts" / "oversight"
for p in (str(VALIDATORS_DIR), str(OVERSIGHT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)
