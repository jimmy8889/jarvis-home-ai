from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import tarfile
from typing import Any


SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 1_000_000


class ArchiveError(RuntimeError):
    pass


def file_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1_048_576):
            digest.update(chunk)
    return digest.hexdigest()


def create_backup(
    source: Path,
    archive: Path,
    owner_uid: int | None = None,
    owner_gid: int | None = None,
) -> dict[str, Any]:
    source = source.resolve()
    if not source.is_dir():
        raise ArchiveError("backup source is not a directory")
    entries = sorted(source.rglob("*"))
    for path in entries:
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ArchiveError(f"unsupported data entry: {path.relative_to(source)}")
    files = [path for path in entries if path.is_file()]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "files": [
            {
                "path": path.relative_to(source).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": file_digest(path),
            }
            for path in files
        ],
    }
    encoded_manifest = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode()
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        raise ArchiveError("backup archive already exists")
    temporary = archive.with_name(f".{archive.name}.{secrets.token_hex(8)}")
    try:
        with tarfile.open(
            temporary,
            "w:gz",
            format=tarfile.PAX_FORMAT,
            dereference=True,
        ) as bundle:
            manifest_info = tarfile.TarInfo("manifest.json")
            manifest_info.size = len(encoded_manifest)
            manifest_info.mode = 0o600
            manifest_info.mtime = int(datetime.now(UTC).timestamp())
            bundle.addfile(manifest_info, BytesIO(encoded_manifest))
            for path in entries:
                arcname = f"payload/{path.relative_to(source).as_posix()}"
                bundle.add(path, arcname=arcname, recursive=False)
        os.chmod(temporary, 0o600)
        if owner_uid is not None or owner_gid is not None:
            os.chown(
                temporary,
                owner_uid if owner_uid is not None else -1,
                owner_gid if owner_gid is not None else -1,
            )
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def _safe_member_name(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and not path.is_absolute()
        and ".." not in path.parts
        and "." not in path.parts
        and "\\" not in name
    )


def restore_backup(archive: Path, destination: Path) -> dict[str, Any]:
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    staging = destination / f".restore-{secrets.token_hex(8)}"
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            names: set[str] = set()
            for member in members:
                if (
                    member.name in names
                    or not _safe_member_name(member.name)
                    or not (member.isdir() or member.isfile())
                    or (
                        member.name != "manifest.json"
                        and not member.name.startswith("payload/")
                    )
                ):
                    raise ArchiveError("backup contains an unsafe archive entry")
                names.add(member.name)
            try:
                manifest_member = bundle.getmember("manifest.json")
            except KeyError as error:
                raise ArchiveError("backup manifest is missing") from error
            if not manifest_member.isfile() or manifest_member.size > MAX_MANIFEST_BYTES:
                raise ArchiveError("backup manifest is invalid")
            manifest_handle = bundle.extractfile(manifest_member)
            if manifest_handle is None:
                raise ArchiveError("backup manifest is unreadable")
            try:
                manifest = json.load(manifest_handle)
            except (UnicodeError, ValueError) as error:
                raise ArchiveError("backup manifest is invalid") from error
            if (
                not isinstance(manifest, dict)
                or manifest.get("schema_version") != SCHEMA_VERSION
                or not isinstance(manifest.get("files"), list)
            ):
                raise ArchiveError("backup manifest schema is unsupported")
            expected: dict[str, dict[str, Any]] = {}
            for item in manifest["files"]:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("path"), str)
                    or not _safe_member_name(item["path"])
                    or item["path"] in expected
                ):
                    raise ArchiveError("backup manifest file entry is invalid")
                expected[item["path"]] = item
            archived_files = {
                member.name.removeprefix("payload/")
                for member in members
                if member.isfile() and member.name.startswith("payload/")
            }
            if archived_files != set(expected):
                raise ArchiveError("backup payload does not match its manifest")

            payload_root = staging / "payload"
            payload_root.mkdir(parents=True)
            for member in members:
                if member.name == "manifest.json":
                    continue
                relative = member.name.removeprefix("payload/")
                target = payload_root / relative
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    os.chmod(target, member.mode & 0o777)
                    if os.geteuid() == 0:
                        os.chown(target, member.uid, member.gid)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise ArchiveError("backup payload file is unreadable")
                digest = sha256()
                size = 0
                with target.open("wb") as handle:
                    while chunk := source.read(1_048_576):
                        handle.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                details = expected[relative]
                if size != details.get("size_bytes") or digest.hexdigest() != details.get(
                    "sha256"
                ):
                    raise ArchiveError("backup payload integrity check failed")
                os.chmod(target, member.mode & 0o777)
                if os.geteuid() == 0:
                    os.chown(target, member.uid, member.gid)

        for child in destination.iterdir():
            if child == staging:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        for child in (staging / "payload").iterdir():
            shutil.move(str(child), destination / child.name)
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up or restore Pilot Core data")
    subparsers = parser.add_subparsers(dest="action", required=True)
    backup = subparsers.add_parser("backup")
    backup.add_argument("--source", type=Path, required=True)
    backup.add_argument("--archive", type=Path, required=True)
    backup.add_argument("--owner-uid", type=int)
    backup.add_argument("--owner-gid", type=int)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "backup":
        manifest = create_backup(
            args.source, args.archive, args.owner_uid, args.owner_gid
        )
    else:
        manifest = restore_backup(args.archive, args.destination)
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
