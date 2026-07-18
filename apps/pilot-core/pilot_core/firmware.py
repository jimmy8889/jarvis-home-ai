from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any


_VERSION = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_TARGET = re.compile(r"^[a-z0-9][a-z0-9.-]{0,127}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class FirmwareReleaseError(RuntimeError):
    pass


def _version_key(version: str) -> tuple[int, int, int, tuple[tuple[int, int | str], ...] | None]:
    match = _VERSION.fullmatch(version)
    if match is None:
        raise ValueError("invalid semantic version")
    prerelease = match.group("prerelease")
    prerelease_key = None
    if prerelease is not None:
        prerelease_key = tuple(
            (0, int(identifier))
            if identifier.isdigit()
            else (1, identifier)
            for identifier in prerelease.split(".")
        )
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        prerelease_key,
    )


def is_newer_version(candidate: str, current: str) -> bool:
    """Return whether candidate is a valid SemVer upgrade from current.

    An empty current version represents an unversioned factory image. Invalid
    non-empty versions fail closed so a malformed request cannot authorize a
    downgrade.
    """

    try:
        candidate_key = _version_key(candidate)
    except ValueError:
        return False
    if not current:
        return True
    try:
        current_key = _version_key(current)
    except ValueError:
        return False

    candidate_core = candidate_key[:3]
    current_core = current_key[:3]
    if candidate_core != current_core:
        return candidate_core > current_core
    candidate_prerelease = candidate_key[3]
    current_prerelease = current_key[3]
    if candidate_prerelease is None:
        return current_prerelease is not None
    if current_prerelease is None:
        return False
    return candidate_prerelease > current_prerelease


@dataclass(frozen=True)
class FirmwareRelease:
    target: str
    version: str
    filename: str
    sha256: str
    size_bytes: int
    mandatory: bool
    path: Path

    def manifest(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "version": self.version,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "mandatory": self.mandatory,
        }


class FirmwareReleases:
    """Validates immutable firmware binaries against a release manifest."""

    def __init__(self, root: str | Path, max_bytes: int) -> None:
        self.root = Path(root)
        self.max_bytes = max_bytes

    def latest(self, target: str) -> FirmwareRelease | None:
        if not _TARGET.fullmatch(target):
            raise FirmwareReleaseError("invalid firmware target")
        manifest_path = self.root / target / "latest.json"
        if not manifest_path.is_file():
            return None
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise FirmwareReleaseError("firmware manifest is unreadable") from error
        if not isinstance(value, dict):
            raise FirmwareReleaseError("firmware manifest must be an object")

        version = str(value.get("version", ""))
        filename = str(value.get("filename", ""))
        expected_sha256 = str(value.get("sha256", "")).lower()
        mandatory = value.get("mandatory", False)
        if not _VERSION.fullmatch(version):
            raise FirmwareReleaseError("firmware version is invalid")
        if (
            not filename
            or filename != Path(filename).name
            or not filename.endswith(".bin")
        ):
            raise FirmwareReleaseError("firmware filename is invalid")
        if not _SHA256.fullmatch(expected_sha256):
            raise FirmwareReleaseError("firmware SHA-256 is invalid")
        if not isinstance(mandatory, bool):
            raise FirmwareReleaseError("firmware mandatory flag is invalid")

        image_path = manifest_path.parent / filename
        try:
            size = image_path.stat().st_size
        except OSError as error:
            raise FirmwareReleaseError("firmware image is missing") from error
        if size < 1 or size > self.max_bytes:
            raise FirmwareReleaseError("firmware image size is invalid")
        digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        if digest != expected_sha256:
            raise FirmwareReleaseError("firmware image checksum does not match")
        return FirmwareRelease(
            target=target,
            version=version,
            filename=filename,
            sha256=digest,
            size_bytes=size,
            mandatory=mandatory,
            path=image_path,
        )
