import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_DIR = DATA_DIR / "db"
MARKDOWN_DIR = BASE_DIR / "data/markdown_files"

# Persistent File Paths
DB_PATH = DB_DIR / "faros_context.db"
MACRO_YAML_PATH = BASE_DIR / "macro_context.yaml"

# Ensure directories exist upon import
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_DIR.mkdir(parents=True, exist_ok=True)
MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)
