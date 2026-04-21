import os
from pathlib import Path

DB_PATH      = Path(os.environ.get("LOCI_DB_PATH", Path.home() / ".loci" / "memories.db"))
EMBED_MODEL  = "BAAI/bge-small-en-v1.5"
WATCH_FOLDER = Path.home() / "loci-docs"
TOP_K        = 5
DEDUP_THRESHOLD       = 0.95
DEDUP_THRESHOLD_INTRA = 0.99
REF_WEIGHT   = 0.7
FILE_BOOST   = 0.5
SOURCE_BOOST = {
    "manual": 1.5,
    "session": 1.3,
    "code": 1.0,
    "web": 1.0,
    "pdf": 1.0,
}
RECENCY_DECAY = 0.0001
CHUNK_SIZE   = 1024

SKIP_DIRS: frozenset[str] = frozenset({
    "node_modules", "__pycache__", ".git", ".hg", ".svn",
    ".venv", "venv", ".env", "env",
    "vendor", "target", "build", "dist",
    ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".next", ".nuxt", ".output", ".turbo",
    "coverage", ".coverage", "htmlcov",
    ".idea", ".vscode",
    "site-packages",
})

CODE_EXTENSIONS = {".py", ".ts", ".js", ".go", ".rs", ".java", ".tsx", ".jsx", ".rb", ".cpp", ".c", ".h"}
DOC_EXTENSIONS  = {".pdf", ".docx", ".md", ".txt"}
