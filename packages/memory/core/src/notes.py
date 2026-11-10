"""User-owned Markdown scoped to the tenant and agent or session."""
import os
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock

MAX_NOTE_CHARS = 6000


class MemoryNotes:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._lock = Lock()

    def _path(self, tenant_id: int, scope: str, identity: str) -> Path:
        digest = sha256(identity.encode()).hexdigest()
        filename = "MEMORY.md" if scope == "agent" else "SESSION.md"
        path = self.root / str(tenant_id) / scope / digest / filename
        if path.resolve() != path:
            raise OSError("Memory note path is outside the configured memory directory")
        return path

    def read(self, tenant_id: int, scope: str, identity: str) -> str:
        try:
            with self._lock, self._path(tenant_id, scope, identity).open(encoding="utf-8") as file:
                return file.read(MAX_NOTE_CHARS)
        except FileNotFoundError:
            return ""

    def write(self, tenant_id: int, scope: str, identity: str, content: str) -> None:
        if len(content) > MAX_NOTE_CHARS:
            raise ValueError("Markdown 笔记超过长度上限")
        path = self._path(tenant_id, scope, identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        file = NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False)
        temporary = Path(file.name)
        try:
            with file:
                file.write(content)
            with self._lock:
                os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
