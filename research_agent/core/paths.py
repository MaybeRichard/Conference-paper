"""Conservative path validation for trusted, single-user local workspaces.

This check does not defeat a hostile process swapping paths after validation.
Storage callers must enforce their own allowed root and transaction protocol.
"""
from pathlib import Path, PureWindowsPath

from research_agent.core.errors import PathViolation


def safe_child(root: Path, relative: str) -> Path:
    """Resolve an unambiguous relative child without creating or following links."""
    if not isinstance(relative, str) or not relative or "\\" in relative or "\x00" in relative:
        raise PathViolation("Invalid relative path")
    if Path(relative).is_absolute() or PureWindowsPath(relative).drive or ":" in relative:
        raise PathViolation("Absolute or platform-specific path is forbidden")
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PathViolation("Path traversal or ambiguous component is forbidden")
    try:
        root = Path(root).absolute()
        if root.is_symlink() or (root.exists() and not root.is_dir()):
            raise PathViolation("Root must not be a link or regular file")
        root = root.resolve()
        child = root
        for index, part in enumerate(parts):
            child = child / part
            if child.is_symlink():
                raise PathViolation("Symbolic links are forbidden")
            if index < len(parts) - 1 and child.exists() and not child.is_dir():
                raise PathViolation("A path parent is not a directory")
        if not child.is_relative_to(root):
            raise PathViolation("Path is outside the permitted root")
        return child
    except (OSError, RuntimeError, ValueError):
        raise PathViolation("Cannot safely resolve the requested path") from None
