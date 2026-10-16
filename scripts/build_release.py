"""Package the current source and client manual without private runtime data."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

from dotenv import dotenv_values


BASE = Path(__file__).resolve().parent.parent
SOURCE_DIRECTORIES = {"apps", "config", "templates", "static", "deployment", "docs", "scripts", ".github"}
ROOT_FILES = {".env.example", ".gitignore", "manage.py", "requirements.txt", "requirements-dev.txt", "README.md", "PROJECT_DOCUMENTATION.md", "PROJECT_MANUAL.md"}
CLIENT_MANUAL = "docs/manuals/SikaFriend_Client_User_Manual.pdf"
BLOCKED_PARTS = {"__pycache__", ".git", ".venv", "media", "private-media", "staticfiles", "backups", "quotations", "credentials", "secrets", ".aws", ".ssh"}
BLOCKED_SUFFIXES = {".pyc", ".pyo", ".sql", ".db", ".sqlite", ".sqlite3", ".key", ".pem", ".log", ".dump", ".bak"}


def allowed(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or set(path.parts) & BLOCKED_PARTS:
        return False
    if path.suffix.lower() in BLOCKED_SUFFIXES or (path.name.startswith(".env") and name != ".env.example"):
        return False
    if path.name in {"db.txt", "restore_data.json", "data-export.json"}:
        return False
    return path.parts[0] in SOURCE_DIRECTORIES or name in ROOT_FILES


def private_values() -> set[bytes]:
    """Canary check only; these files and values never enter the archive."""
    paths = [BASE / ".env", *BASE.glob("backups/private/security-performance-*/before*.env")]
    values = set()
    for path in paths:
        if not path.is_file():
            continue
        for key, value in dotenv_values(path).items():
            if value and len(value) >= 8 and any(marker in key.upper() for marker in ("SECRET", "PASSWORD", "TOKEN", "KEY")):
                values.add(value.encode())
                if key == "MFA_ENCRYPTION_KEYS":
                    values.update(part.strip().encode() for part in value.split(",") if len(part.strip()) >= 8)
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=BASE / "backups" / f"sikafriend-update-{date.today():%Y%m%d}.zip")
    args = parser.parse_args()
    output = args.output.resolve()
    names = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=BASE).decode().split("\0")
    names = {name for name in names if name and allowed(name) and (BASE / name).is_file()}
    if not (BASE / CLIENT_MANUAL).is_file():
        raise SystemExit("Rebuild the client manual before packaging.")
    names.add(CLIENT_MANUAL)
    canaries = private_values()
    manifest = []
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            temporary.chmod(0o600)
            for name in sorted(names):
                path = BASE / name
                if path.is_symlink() or not path.resolve().is_relative_to(BASE):
                    raise SystemExit(f"Release source must be a regular project file: {name}")
                data = path.read_bytes()
                if path.suffix.lower() in {".py", ".txt", ".json", ".md", ".html", ".css", ".js", ".yml", ".yaml", ".example"} and any(value in data for value in canaries):
                    raise SystemExit(f"A private configuration value appears in release source: {name}")
                archive.writestr(name, data)
                manifest.append({"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
            archive.writestr("RELEASE_MANIFEST.json", json.dumps({"source": "current working tree", "files": manifest}, indent=2) + "\n")
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise SystemExit("Release ZIP integrity check failed.")
            if any(not allowed(name) for name in archive.namelist() if name != "RELEASE_MANIFEST.json"):
                raise SystemExit("Release ZIP contains an unexpected entry.")
        temporary.replace(output)
        output.chmod(0o600)
        print(json.dumps({"release": str(output.relative_to(BASE)) if output.is_relative_to(BASE) else str(output), "files": len(manifest), "bytes": output.stat().st_size, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "private_configuration_excluded": True}))
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
