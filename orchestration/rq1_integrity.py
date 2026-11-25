"""Strict read-only verification of nested RQ1 raw-evidence manifests.

This outer utility does not change the frozen experiment harness. It verifies
manifest coverage as well as the hashes already checked by the report writer.
Python 3.6+.
"""
import hashlib
from pathlib import Path, PurePosixPath, PureWindowsPath
import re


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _files(root):
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("evidence symlink is not permitted: " + str(path))
        if path.is_file():
            files.append(path)
    return files


def _relative(value, manifest):
    name = value.replace("\\", "/")
    parts = name.split("/")
    if (not name or PurePosixPath(name).is_absolute()
            or PureWindowsPath(name).drive
            or any(part in ("", ".", "..") for part in parts)
            or "\x00" in name):
        raise ValueError("unsafe evidence path in %s: %r" % (manifest, value))
    return name


def verify_tree(root):
    """Verify every manifest and its complete recursive file coverage.

    Files outside any manifest subtree are intentionally outside this check;
    the caller must separately validate session/protocol identities. A parent
    manifest must include all nested manifests, excluding only its own file.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("evidence root is not a directory: " + str(root))
    files = _files(root)
    manifests = [path for path in files if path.name == "SHA256SUMS"]
    if not manifests:
        raise ValueError("no SHA256SUMS found under: " + str(root))
    counts = []
    total = 0
    for manifest in manifests:
        directory = manifest.parent.resolve()
        entries = {}
        try:
            lines = manifest.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as error:
            raise ValueError("cannot read manifest %s: %s" % (manifest, error))
        if not lines:
            raise ValueError("empty evidence manifest: " + str(manifest))
        for number, line in enumerate(lines, 1):
            match = re.match(r"^([0-9a-f]{64})  (.+)$", line)
            if match is None:
                raise ValueError("malformed SHA256 line %d in %s" % (number, manifest))
            expected, raw_name = match.groups()
            name = _relative(raw_name, manifest)
            if name in entries:
                raise ValueError("duplicate evidence path in %s: %s" % (manifest, name))
            path = directory.joinpath(*name.split("/"))
            resolved = path.resolve()
            if directory not in resolved.parents or path == manifest:
                raise ValueError("unsafe/self evidence path in %s: %s" % (manifest, name))
            if not path.is_file():
                raise ValueError("missing evidence file listed by %s: %s" % (manifest, path))
            if digest(path) != expected:
                raise ValueError("SHA256 mismatch listed by %s: %s" % (manifest, path))
            entries[name] = expected
        actual = {path.relative_to(directory).as_posix()
                  for path in _files(directory) if path != manifest}
        uncovered = sorted(actual - set(entries))
        if uncovered:
            raise ValueError("unlisted evidence file(s) under %s: %s" % (
                manifest, ", ".join(uncovered)))
        counts.append({"manifest": manifest.relative_to(root).as_posix(), "entries": len(entries)})
        total += len(entries)
    return {"status": "PASS", "root": str(root), "manifests": len(manifests),
            "entries": total, "manifest_counts": counts}


def seal_tree(root):
    """Create one new complete manifest, preserving all existing evidence."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("evidence root is not a directory: " + str(root))
    manifest = root / "SHA256SUMS"
    files = [path for path in _files(root) if path != manifest]
    if not files:
        raise ValueError("cannot seal empty evidence directory: " + str(root))
    lines = [digest(path) + "  " + path.relative_to(root).as_posix() for path in files]
    with manifest.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines) + "\n")
    return manifest
