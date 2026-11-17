"""Registry for managing L5X project files with discovery and caching."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from pathlib import Path

from py_l5x import load
from py_l5x.parsers.project import Project

#: Folder (relative to the root) where write tools put bare output file names.
DEFAULT_OUTPUT_DIR = "l5x-mcp-output"


class L5XError(ValueError):
    """Base exception for all user-facing L5X errors."""

    pass


class ProjectNotFoundError(L5XError):
    """Raised when a project file cannot be found."""

    pass


class AmbiguousProjectError(L5XError):
    """Raised when multiple project files match the query."""

    pass


class ItemNotFoundError(L5XError):
    """Raised when an item is not found in a collection."""

    pass


def lookup[T](collection: Mapping[str, T], name: str, kind: str) -> T:
    """Look up an item in a collection with exact or case-insensitive matching.

    Args:
        collection: Mapping of names to items.
        name: Item name to look up.
        kind: Description of item type (e.g. "Program", "Tag").

    Returns:
        The matched item.

    Raises:
        ItemNotFoundError: If no exact or unique case-insensitive match found.
    """
    # Try exact match first
    if name in collection:
        return collection[name]

    # Try case-insensitive match
    lower_name = name.lower()
    matches = [key for key in collection if key.lower() == lower_name]

    if len(matches) == 1:
        return collection[matches[0]]

    # No match or ambiguous
    if not collection:
        raise ItemNotFoundError(
            f"{kind} '{name}' not found. This project has no {kind.lower()}s."
        )

    # Build available names list
    available = sorted(collection.keys())
    if len(available) <= 50:
        available_str = ", ".join(available)
    else:
        more = len(available) - 50
        available_str = ", ".join(available[:50]) + f", ... ({more} more)"

    raise ItemNotFoundError(f"{kind} '{name}' not found. Available: {available_str}")


class ProjectRegistry:
    """Registry for discovering and caching L5X project files."""

    def __init__(
        self, root: str | Path | None = None, output_dir: str | Path | None = None
    ) -> None:
        """Initialize the registry with a root directory.

        Args:
            root: Root directory for searching. Defaults to current working directory.
            output_dir: Folder for bare output file names (see
                ``editing.resolve_output``); relative to the root, or absolute
                inside it. Defaults to :data:`DEFAULT_OUTPUT_DIR`. Not created
                until a file is written.

        Raises:
            L5XError: If root is not a directory, or output_dir is outside the
                root or is the root itself.
        """
        if root is None:
            self.root = Path.cwd().resolve()
        else:
            self.root = Path(root).resolve()

        if not self.root.is_dir():
            raise L5XError(f"Root directory does not exist: {self.root}")

        out = Path(output_dir or DEFAULT_OUTPUT_DIR).expanduser()
        if not out.is_absolute():
            out = self.root / out
        out = out.resolve()
        if out == self.root or not out.is_relative_to(self.root):
            raise L5XError(
                f"Output directory must be a folder inside the server root "
                f"{self.root}: {output_dir or DEFAULT_OUTPUT_DIR}"
            )
        self.output_dir = out

        self._cache: dict[Path, tuple[int, int, Project]] = {}
        self._lock = threading.Lock()
        self._outputs: dict[Path, tuple[int, int]] = {}

    def record_output(self, path: Path) -> None:
        """Remember a file this server just wrote (see :meth:`is_own_output`).

        Args:
            path: The written file.
        """
        path = Path(path).resolve()
        stat = path.stat()
        with self._lock:
            self._outputs[path] = (stat.st_mtime_ns, stat.st_size)

    def is_own_output(self, path: Path) -> bool:
        """Return whether ``path`` was written by this server and is unchanged.

        Args:
            path: The file to check.

        Returns:
            ``True`` only if the file was recorded by :meth:`record_output` and
            its mtime and size still match; ``False`` for a missing file.
        """
        path = Path(path).resolve()
        with self._lock:
            recorded = self._outputs.get(path)
        try:
            stat = path.stat()
        except OSError:
            return False
        return recorded == (stat.st_mtime_ns, stat.st_size)

    def is_output(self, path: Path) -> bool:
        """Return whether ``path`` is inside the output folder.

        Args:
            path: A file path.

        Returns:
            ``True`` if the path is under ``output_dir``.
        """
        return Path(path).resolve().is_relative_to(self.output_dir)

    def discover(self, subdir: str | None = None) -> list[Path]:
        """Recursively discover .L5X files under root directory.

        Args:
            subdir: Optional subdirectory to search within root.

        Returns:
            Sorted list of absolute resolved paths to .L5X files.

        Raises:
            L5XError: If subdir escapes root or other path issues.
        """
        if subdir:
            search_root = (self.root / subdir).resolve()
            # Verify subdir is within root
            try:
                search_root.relative_to(self.root)
            except ValueError:
                raise L5XError(f"Subdirectory escapes root: {subdir}") from None
        else:
            search_root = self.root

        l5x_files = []

        def _walk(current_dir: Path) -> None:
            """Recursively walk directory, skipping hidden and cache dirs."""
            try:
                for entry in current_dir.iterdir():
                    # Skip hidden directories
                    if entry.name.startswith("."):
                        continue
                    # Skip cache/venv directories
                    if entry.name in ("node_modules", "__pycache__", "venv"):
                        continue

                    if entry.is_dir():
                        _walk(entry)
                    elif entry.is_file() and entry.suffix.lower() == ".l5x":
                        l5x_files.append(entry.resolve())
            except (OSError, PermissionError):
                # Skip directories we can't read
                pass

        _walk(search_root)
        return sorted(l5x_files)

    def resolve(self, path: str | None = None) -> Path:
        """Resolve a project file path.

        Args:
            path: File path (absolute, relative to root, or None for
                auto-discovery, which ignores files in the output folder).

        Returns:
            Resolved absolute path to the project file.

        Raises:
            ProjectNotFoundError: If file not found or auto-discovery fails.
            AmbiguousProjectError: If multiple files discovered and no path given.
        """
        if path is None or path == "":
            # Auto-discovery mode
            everything = self.discover()
            discovered = [p for p in everything if not self.is_output(p)]
            if len(discovered) == 0 and everything:
                raise ProjectNotFoundError(
                    f"No source .L5X files found under {self.root}. The outputs in "
                    f"{self.relpath(self.output_dir)}/ are skipped by "
                    "auto-discovery; pass `path` to the file you want."
                )
            if len(discovered) == 0:
                raise ProjectNotFoundError(
                    f"No .L5X files found under {self.root}. "
                    "Pass an explicit `path` to an .L5X file."
                )
            if len(discovered) > 1:
                rel_paths = [self.relpath(p) for p in discovered]
                raise AmbiguousProjectError(
                    f"Multiple .L5X files found under {self.root}. "
                    "Pass the `path` argument with one of:\n" + "\n".join(rel_paths)
                )
            return discovered[0]

        # Resolve given path
        resolved = Path(path).expanduser()

        # If relative, make it relative to root
        if not resolved.is_absolute():
            resolved = self.root / resolved

        resolved = resolved.resolve()

        # Check if file exists
        if not resolved.is_file():
            discovered = self.discover()
            if discovered:
                rel_paths = [self.relpath(p) for p in discovered]
                raise ProjectNotFoundError(
                    f"File not found: {path}\n"
                    f"Available .L5X files:\n" + "\n".join(rel_paths)
                )
            else:
                raise ProjectNotFoundError(f"File not found: {path}")

        return resolved

    def get(self, path: str | None = None) -> Project:
        """Get a project with optional caching.

        Args:
            path: File path (None for auto-discovery).

        Returns:
            The loaded Project object.

        Raises:
            ProjectNotFoundError: If file not found.
            AmbiguousProjectError: If multiple files found.
            L5XError: If XML parsing fails.
        """
        return self.get_with_path(path)[1]

    def get_with_path(self, path: str | None = None) -> tuple[Path, Project]:
        """Get a project with its resolved path.

        Args:
            path: File path (None for auto-discovery).

        Returns:
            Tuple of (resolved path, Project object).

        Raises:
            ProjectNotFoundError: If file not found.
            AmbiguousProjectError: If multiple files found.
            L5XError: If XML parsing fails.
        """
        resolved_path = self.resolve(path)

        with self._lock:
            # Check cache
            try:
                stat = resolved_path.stat()
                mtime_ns = stat.st_mtime_ns
                size = stat.st_size

                if resolved_path in self._cache:
                    cached_mtime, cached_size, cached_project = self._cache[
                        resolved_path
                    ]
                    if cached_mtime == mtime_ns and cached_size == size:
                        return resolved_path, cached_project

            except OSError as e:
                raise ProjectNotFoundError(f"Cannot stat file: {resolved_path}") from e

            # Load or reload
            try:
                project = load(str(resolved_path))
            except FileNotFoundError as e:
                raise ProjectNotFoundError(str(e)) from e
            except ValueError as e:
                raise L5XError(f"Failed to parse L5X file {resolved_path}: {e}") from e

            # Update cache
            self._cache[resolved_path] = (mtime_ns, size, project)
            return resolved_path, project

    def relpath(self, path: Path) -> str:
        """Get relative path to file if inside root, else absolute.

        Args:
            path: The path to convert.

        Returns:
            Relative path string (posix-style) or absolute string.
        """
        path = path.resolve()
        try:
            rel = path.relative_to(self.root)
            return rel.as_posix()
        except ValueError:
            # Path is outside root
            return str(path)
