"""Ensure backend/ is importable as the root for `import database`, `import main`, etc.,
and use an isolated on-disk test database so tests never touch procura.db."""

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Tests must be hermetic: never make a real LLM network call even if the
# developer's real .env has a key configured. This forces every /ask test
# through the deterministic offline_extractive path.
for _key in ("GROQ_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
    os.environ.pop(_key, None)

import database  # noqa: E402

database.DB_PATH = BACKEND_DIR / "tests" / "test_procura.db"

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    database.reset_db()
    yield
    if database.DB_PATH.exists():
        database.DB_PATH.unlink()
