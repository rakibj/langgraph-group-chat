"""Env loading and shared paths/constants."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

# Force UTF-8 stdout/stderr so non-ASCII glyphs in print()s don't crash on
# Windows' default console codepage. Reconfigure here, the first app.*
# module everything else imports, before any prints can run.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

PROJECT_DIR = str(Path.cwd().resolve())

DATA_DIR = Path.cwd() / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
