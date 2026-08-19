"""Support ``python -m etabs_extractor``."""
from .cli import main
import sys

if __name__ == "__main__":
    sys.exit(main())
