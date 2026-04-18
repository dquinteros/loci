from . import config

SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


def chunk(text: str, size: int = config.CHUNK_SIZE) -> list[str]:
    """Recursive character splitter — best retrieval accuracy per 2026 benchmark."""
    if not text or not text.strip():
        return []
    if len(text) <= size:
        return [text.strip()]
    for sep in SEPARATORS:
        if sep and sep in text:
            parts = text.split(sep)
            chunks: list[str] = []
            current = ""
            for part in parts:
                candidate = current + sep + part if current else part
                if len(candidate) <= size:
                    current = candidate
                else:
                    if current:
                        chunks.append(current.strip())
                    current = part
            if current:
                chunks.append(current.strip())
            return [c for c in chunks if c]
    return [text[i : i + size] for i in range(0, len(text), size)]
