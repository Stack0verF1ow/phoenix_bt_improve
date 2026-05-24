from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FileEntry:
    path: Path
    relative_path: Path
    size: int


@dataclass(slots=True)
class ResourceDraft:
    source_path: Path
    title: str
    subtitle: str = ""
    description: str = ""
    category: str = "0"
    tags: list[str] = field(default_factory=list)
    files: list[FileEntry] = field(default_factory=list)
    confirmed_compliance: bool = False

    @property
    def total_size(self) -> int:
        return sum(entry.size for entry in self.files)

    @property
    def file_count(self) -> int:
        return len(self.files)

    @classmethod
    def from_path(cls, source_path: Path) -> "ResourceDraft":
        source_path = source_path.expanduser().resolve()
        files = scan_files(source_path)
        return cls(
            source_path=source_path,
            title=infer_title(source_path),
            description=build_description(source_path, files),
            files=files,
        )


def scan_files(source_path: Path) -> list[FileEntry]:
    if source_path.is_file():
        return [FileEntry(source_path, Path(source_path.name), source_path.stat().st_size)]

    entries: list[FileEntry] = []
    for path in sorted(p for p in source_path.rglob("*") if p.is_file()):
        entries.append(FileEntry(path, path.relative_to(source_path), path.stat().st_size))
    return entries


def infer_title(source_path: Path) -> str:
    return source_path.expanduser().resolve().stem if source_path.is_file() else source_path.expanduser().resolve().name


def build_description(source_path: Path, files: list[FileEntry]) -> str:
    total_size = sum(entry.size for entry in files)
    lines = [
        f"资源名称：{infer_title(source_path)}",
        f"文件数量：{len(files)}",
        f"总大小：{format_size(total_size)}",
        "",
        "资源说明：",
        "",
        "做种说明：由金凤本地助手生成并上传，请下载后尽量保持做种。",
    ]
    return "\n".join(lines)


def format_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    raise AssertionError("unreachable")


@dataclass(frozen=True, slots=True)
class UploadResult:
    success: bool
    message: str
    detail_url: str = ""
    torrent_url: str = ""
    final_torrent_path: Path | None = None
