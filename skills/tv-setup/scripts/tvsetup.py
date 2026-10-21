#!/usr/bin/env python3
"""Stable skill-local entry point, also when the skill directory is a symlink."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tvsetup.cli import main
raise SystemExit(main())
