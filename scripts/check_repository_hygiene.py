"""Fail CI when private runtime data is tracked; report paths without printing contents."""
from pathlib import PurePosixPath
import subprocess
import sys

paths = subprocess.check_output(["git", "ls-files", "-z"], text=True).split("\0")
blocked = []
for name in filter(None, paths):
    path = PurePosixPath(name)
    parts = path.parts
    private_directory = parts[0] in {"backups", "private-media", "media", "staticfiles", ".aws", ".ssh", "credentials", "secrets", ".venv"}
    private_file = (path.name.startswith(".env") and path.name != ".env.example") or path.suffix.lower() in {".sql", ".db", ".sqlite", ".sqlite3", ".key", ".pem"}
    legacy_dump = path.name in {"db.txt", "restore_data.json", "data-export.json"}
    commercial = name.startswith("docs/quotations/")
    if private_directory or private_file or legacy_dump or commercial:
        blocked.append(name)
if blocked:
    print("Private files are tracked; remove these from the release index:")
    print("\n".join(blocked))
    sys.exit(1)
print("Repository hygiene check passed.")
