"""Shared plumbing for the write tools.

Every write tool follows the same cycle: load a **fresh** copy of the source
project (never the registry's cached object, which read tools share), apply
the change with py_l5x, and write the result to a separate ``output_path``.
The source file is never modified.

A bare ``output_path`` file name is written to the registry's output folder
(``registry.output_dir``, default ``l5x-mcp-output`` under the root), which
auto-discovery skips; a path with a directory part is root-relative. Output
paths are confined to the registry root, must end in ``.L5X``, must
differ from the source, and refuse to replace an existing file. With
``overwrite=True`` only a file this server process wrote earlier (and that has
not changed since) may be replaced, so other projects in the root can never be
clobbered. Files are written atomically (temp file plus rename) so a reader
never sees a half-written project.

py_l5x reports bad edits with ``ValueError``, ``KeyError``, ``TypeError`` and
``IndexError``. :func:`edit_errors` turns those into :class:`L5XError` so the
model sees the message instead of a hidden internal error.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from py_l5x import load
from py_l5x.parsers.atomic_types import atomic_info
from py_l5x.parsers.layout import builtin_table
from py_l5x.parsers.project import Project

from l5x_mcp.registry import L5XError, ProjectRegistry


@contextmanager
def edit_errors(action: str = "") -> Iterator[None]:
    """Convert py_l5x edit exceptions into user-facing :class:`L5XError`.

    Args:
        action: Optional prefix describing what was attempted.

    Yields:
        Nothing; wraps the block.

    Raises:
        L5XError: For any ``ValueError``/``KeyError``/``TypeError``/
            ``IndexError`` raised inside the block.
    """
    prefix = f"{action}: " if action else ""
    try:
        yield
    except L5XError:
        raise
    except KeyError as exc:
        what = exc.args[0] if exc.args else ""
        raise L5XError(f"{prefix}not found: {what}") from exc
    except (ValueError, TypeError, IndexError) as exc:
        raise L5XError(f"{prefix}{exc}") from exc


def resolve_output(
    registry: ProjectRegistry,
    output_path: str,
    *,
    source: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Validate and resolve a write tool's ``output_path``.

    Args:
        registry: Registry whose root confines the output.
        output_path: A bare file name (written to ``registry.output_dir``), or
            an absolute or root-relative path (which must be inside the root).
        source: The project being edited; the output may not be this file.
        overwrite: Allow replacing an existing file, but only one that this
            server wrote earlier in this session and that is unchanged since
            (``registry.is_own_output``).

    Returns:
        The resolved absolute destination path.

    Raises:
        L5XError: If the path is empty, escapes the root, is not ``.L5X``, is
            the source file, names a directory, exists without ``overwrite``,
            or exists with ``overwrite`` but is not an unchanged output of
            this server.
    """
    if not output_path or not output_path.strip():
        raise L5XError("output_path is required")
    raw = Path(output_path).expanduser()
    if not raw.is_absolute():
        base = registry.output_dir if raw.parent == Path() else registry.root
        raw = base / raw
    out = raw.resolve()
    try:
        out.relative_to(registry.root)
    except ValueError:
        raise L5XError(
            f"output_path must be inside the server root {registry.root}: {output_path}"
        ) from None
    if out.suffix.lower() != ".l5x":
        raise L5XError(f"output_path must end in .L5X: {output_path}")
    if source is not None and out == source.resolve():
        raise L5XError(
            "output_path must differ from the source file; write tools never "
            "modify their input. Choose a new file name."
        )
    if out.is_dir():
        raise L5XError(f"output_path is a directory: {output_path}")
    if out.exists() and not overwrite:
        raise L5XError(
            f"{registry.relpath(out)} already exists. Pass overwrite=true to "
            "replace it, or choose another output_path."
        )
    if out.exists() and not registry.is_own_output(out):
        raise L5XError(
            f"{registry.relpath(out)} exists and was not written by a write tool "
            "in this server session (or it changed since). overwrite only "
            "replaces this session's own outputs; choose a new output_path."
        )
    return out


def load_fresh(registry: ProjectRegistry, path: str | None) -> tuple[Path, Project]:
    """Load an uncached, editable copy of a project.

    Args:
        registry: Registry used to resolve ``path``.
        path: Project path (``None`` for auto-discovery).

    Returns:
        The resolved source path and a newly parsed project.

    Raises:
        L5XError: If the file cannot be found or parsed.
    """
    source = registry.resolve(path)
    try:
        return source, load(str(source))
    except ValueError as exc:
        raise L5XError(f"Failed to parse L5X file {source}: {exc}") from exc


def write_project(registry: ProjectRegistry, project: Project, out: Path) -> None:
    """Write a project atomically.

    The temp file is created by py_l5x (a normal ``open``), not with
    ``mkstemp``, so the result gets the usual umask permissions rather than
    0600.

    Args:
        registry: Registry that records the written file as this server's output.
        project: The project (or component export) to write.
        out: Destination path; parent directories are created.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.{uuid.uuid4().hex}.tmp")
    try:
        project.write(str(tmp))
        os.replace(tmp, out)
        registry.record_output(out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


#: Built-in types that py_l5x resolves without listing them in its type tables
#: (mirrors py_l5x's export resolver; keep in step with py_l5x).
_SPECIAL_TYPES = frozenset(
    {"MESSAGE", "MOTION_GROUP", "ALARM_ANALOG", "ALARM_DIGITAL", "COORDINATE_SYSTEM"}
    | {"HMIBC"}
)
_SPECIAL_PREFIXES = ("AXIS_", "ENERGY_")


def check_data_type(project: Project, name: str) -> None:
    """Raise unless ``name`` is a type this project can use for a tag.

    py_l5x writes a tag's ``DataType`` as given, so a misspelled type would
    produce a file that Studio rejects on import.

    Args:
        project: The project the tag is added to (its UDTs and AOIs count,
            source-protected AOIs included).
        name: The data type name (case-sensitive, as in Logix).

    Raises:
        L5XError: If the type is not atomic, built-in, special, a UDT or an AOI.
    """
    if (
        atomic_info(name) is not None
        or name in builtin_table()
        or name in _SPECIAL_TYPES
        or name.startswith(_SPECIAL_PREFIXES)
        or name in project.data_types
        or name in project.aois
        or name in project.protected_aois
    ):
        return
    raise L5XError(
        f"unknown data type {name!r}: use an atomic type (BOOL, DINT, REAL, ...), "
        "a built-in (TIMER, COUNTER, STRING, ...), or a UDT or AOI in this project"
    )


class Edit:
    """One load-edit-write cycle on a project.

    Usage::

        edit = Edit.open(registry, path, output_path, overwrite)
        with edit_errors("add tag"):
            edit.project.controller_tags.add(...)
        return edit.save({"added": [...]})
    """

    def __init__(
        self, registry: ProjectRegistry, source: Path, project: Project, out: Path
    ) -> None:
        self.registry = registry
        self.source = source
        self.project = project
        self.out = out

    @classmethod
    def open(
        cls,
        registry: ProjectRegistry,
        path: str | None,
        output_path: str,
        overwrite: bool = False,
    ) -> Edit:
        """Load the source and validate the output before any change is made.

        Args:
            registry: The project registry.
            path: Source project path (``None`` for auto-discovery).
            output_path: Destination path.
            overwrite: Allow replacing a destination this server wrote earlier.

        Returns:
            The edit session.
        """
        source = registry.resolve(path)
        out = resolve_output(registry, output_path, source=source, overwrite=overwrite)
        _, project = load_fresh(registry, str(source))
        return cls(registry, source, project, out)

    def save(self, summary: dict) -> dict:
        """Write the edited project and build the tool result.

        Args:
            summary: Tool-specific result fields.

        Returns:
            ``{"file": <output>, "source": <input>, **summary}``.
        """
        write_project(self.registry, self.project, self.out)
        return {
            "file": self.registry.relpath(self.out),
            "source": self.registry.relpath(self.source),
            **summary,
        }
