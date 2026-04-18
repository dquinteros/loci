from __future__ import annotations
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

from .. import config, store
from . import code as code_ingest
from . import pdf as pdf_ingest
from . import docx as docx_ingest
from ..chunker import chunk


def _ingest_doc(path: Path, project: str = "") -> None:
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            pdf_ingest.ingest(path, project=project)
        elif suffix == ".docx":
            docx_ingest.ingest(path, project=project)
        elif suffix in {".md", ".txt"}:
            text = path.read_text(errors="replace")
            for idx, c in enumerate(chunk(text)):
                store.insert(c, tags=["doc", suffix.lstrip(".")],
                             project=project, source="file",
                             source_ref=str(path), chunk_idx=idx)
    except Exception as exc:
        print(f"[loci] watcher ingest error {path}: {exc}")


class DocWatcher(FileSystemEventHandler):
    def __init__(self, project: str = "") -> None:
        self.project = project

    def _handle(self, event: FileSystemEvent) -> None:
        path = Path(event.src_path)
        if path.suffix.lower() in config.DOC_EXTENSIONS:
            _ingest_doc(path, project=self.project)

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle(event)


class CodeWatcher(FileSystemEventHandler):
    _debounce: dict[str, float] = {}
    DEBOUNCE_SECS = 3.0

    def __init__(self, cwd: Path, project: str = "") -> None:
        self.cwd = cwd
        self.project = project
        self._patterns = code_ingest._load_gitignore(cwd)

    def on_modified(self, event: FileSystemEvent) -> None:
        path = Path(event.src_path)
        if path.suffix not in config.CODE_EXTENSIONS:
            return
        if code_ingest._is_ignored(path, self._patterns, self.cwd):
            return
        now = time.time()
        last = self._debounce.get(str(path), 0.0)
        if now - last < self.DEBOUNCE_SECS:
            return
        self._debounce[str(path)] = now
        store.mark_stale(str(path))
        code_ingest.ingest_file(path, project=self.project)
        store.delete_stale(str(path))


def start_daemon(project: str = "") -> None:
    """Blocks; run as background process via `loci watch`."""
    config.WATCH_FOLDER.mkdir(parents=True, exist_ok=True)
    cwd = Path.cwd()
    observer = Observer()
    observer.schedule(DocWatcher(project=project), str(config.WATCH_FOLDER), recursive=True)
    observer.schedule(CodeWatcher(cwd=cwd, project=project), str(cwd), recursive=True)
    observer.start()
    print(f"[loci] watching {config.WATCH_FOLDER} and {cwd}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
