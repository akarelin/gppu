from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field

@dataclass(frozen=True)
class FileArtifact:
    path: Path
    display_path: str
    disk_name: str
    file_name: str
    extension: str
    file_size: int
    file_type_id: str | None
    file_type_class_id: str | None
    file_id: int
    folder_id: int
    location_id: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FolderArtifact:
    path: Path | None
    display_path: str
    name: str
    relative_path: str
    folder_id: int
    location_id: int
    child_names: tuple[str, ...]
    child_session_ids: tuple[str, ...] = ()


class Handler:
    """Default no-op surface implemented by concrete handlers."""

    id: str

    def inspect_file(self, artifact: FileArtifact) -> HandlerResult | None:
        return None

    def inspect_folder(self, artifact: FolderArtifact) -> HandlerResult | None:
        return None
