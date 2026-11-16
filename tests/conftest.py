import sys
from pathlib import Path

# Permite hacer "from fakes import ..." en los tests
sys.path.insert(0, str(Path(__file__).parent))
