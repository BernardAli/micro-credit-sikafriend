"""Move legacy identity uploads outside the publicly mapped media directory."""
import hashlib
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Preview moving customer/workforce uploads into private storage; use --apply to move them."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        source_root = Path(settings.MEDIA_ROOT).resolve()
        target_root = Path(settings.PRIVATE_MEDIA_ROOT).resolve()
        if source_root == target_root or source_root in target_root.parents or target_root in source_root.parents:
            raise CommandError("Public and private media roots must be separate directories.")
        files = []
        for folder in ("borrowers", "agents"):
            base = source_root / folder
            if base.is_symlink():
                raise CommandError("Refusing to move a linked upload directory.")
            if base.exists():
                for source in base.rglob("*"):
                    if source.is_symlink():
                        raise CommandError("Refusing to move linked uploads.")
                    if source.is_file():
                        relative = source.relative_to(source_root)
                        target = target_root / relative
                        if target.exists():
                            if target.is_symlink() or not target.is_file():
                                raise CommandError("Private destination is not a regular file.")
                            with source.open("rb") as left, target.open("rb") as right:
                                if hashlib.file_digest(left, "sha256").digest() != hashlib.file_digest(right, "sha256").digest():
                                    raise CommandError("Different private copy exists; no files have been moved.")
                        files.append((source, target))
        # Validate every destination before changing any file.
        if options["apply"]:
            target_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            target_root.chmod(0o700)
            for source, target in files:
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                for directory in target.parent.parents:
                    if directory == target_root:
                        break
                    if target_root in directory.parents:
                        directory.chmod(0o700)
                target.parent.chmod(0o700)
                if target.exists():
                    source.unlink()  # Identical private copy was verified above.
                else:
                    shutil.move(str(source), str(target))
                target.chmod(0o600)
        label = "Moved" if options["apply"] else "Dry run: would move"
        self.stdout.write(f"{label} {len(files)} private upload(s). Public company media is unchanged.")
