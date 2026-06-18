"""
Add the validators directory to sys.path so tests can import validators
directly without package-relative imports.

Also add the project root so `from scripts.automation.lib.X import ...`
works for the automation subsystem (scripts/ is a namespace package).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Allow `import schema`, `import rn_calculator`, etc. from tests
VALIDATORS_DIR = ROOT / "scripts" / "oversight" / "validators"
OVERSIGHT_DIR  = ROOT / "scripts" / "oversight"
for p in (str(VALIDATORS_DIR), str(OVERSIGHT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Allow `from scripts.automation.lib.X import ...`
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
