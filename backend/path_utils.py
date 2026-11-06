from pathlib import Path


class PathTraversalError(Exception):
    """Raised when a resolved filesystem path escapes its intended root directory or contains traversal characters."""
    pass


def resolve_safe_path(base_dir: Path, *parts: str) -> Path:
    """Resolve a target path strictly beneath base_dir, rejecting traversal, symlink escapes, or absolute paths."""
    base = base_dir.resolve()
    for part in parts:
        if not part or not isinstance(part, str):
            raise PathTraversalError("Path component must be a non-empty string")
        if "/" in part or "\\" in part or part in (".", ".."):
            raise PathTraversalError(f"Path component contains separators or traversal: {part!r}")

    target = base.joinpath(*parts).resolve()
    if not target.is_relative_to(base):
        raise PathTraversalError(f"Target path escapes base directory: {target} (base: {base})")
    return target
