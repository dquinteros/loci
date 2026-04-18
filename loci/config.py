import os
from pathlib import Path

DB_PATH      = Path(os.environ.get("LOCI_DB_PATH", Path.home() / ".loci" / "memories.db"))
EMBED_MODEL  = "BAAI/bge-small-en-v1.5"
WATCH_FOLDER = Path.home() / "loci-docs"
TOP_K        = 5
DEDUP_COS    = 0.95
CHUNK_SIZE   = 1024

CODE_EXTENSIONS = {".py", ".ts", ".js", ".go", ".rs", ".java", ".tsx", ".jsx", ".rb", ".cpp", ".c", ".h"}
DOC_EXTENSIONS  = {".pdf", ".docx", ".md", ".txt"}
