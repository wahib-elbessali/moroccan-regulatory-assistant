"""Command line interface for document ingestion and corpus seeding (P1-33)."""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from src.core.contracts.enums import DocStatus
from src.core.contracts.errors import Conflict
from src.core.contracts.ids import make_doc_id
from src.core.contracts.models import DocumentMeta
from src.ingestion.pipeline import short_reason

if TYPE_CHECKING:
    from src.core.contracts.protocols import DocumentRights, Ingestion

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".docx",
        ".html",
        ".htm",
        ".md",
        ".txt",
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
    }
)


def _build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m src.ingestion.cli",
        description="Ingestion and corpus seeding tool (P1-33).",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Subcommand: ingest
    ingest_parser = subparsers.add_parser("ingest", help="Ingest a file or directory.")
    ingest_parser.add_argument("path", help="Path to file or folder to ingest.")
    ingest_parser.add_argument(
        "--roles",
        help="Comma-separated roles for publication (e.g. 'lecteur,editeur'). Defaults to empty.",
    )
    ingest_parser.add_argument(
        "--owner",
        help="Owner UUID for private uploads.",
    )
    ingest_parser.add_argument(
        "--title",
        help="Document title override.",
    )
    ingest_parser.add_argument(
        "--source",
        help="Source URL or origin.",
    )
    ingest_parser.add_argument(
        "--date",
        help="Document date (YYYY-MM-DD).",
    )

    # Subcommand: seed
    seed_parser = subparsers.add_parser("seed", help="Seed corpus from manifest.csv.")
    seed_parser.add_argument(
        "--owner",
        help="Owner UUID for upload rows.",
    )
    seed_parser.add_argument(
        "--raw-dir",
        default="data/raw",
        help="Path to raw corpus directory (default: data/raw).",
    )

    return parser


def _ingest_file(
    file_path: Path,
    meta: DocumentMeta,
    roles: list[str],
    owner_id: UUID | None,
    rights: DocumentRights,
    ingestion: Ingestion,
    counts: dict[str, int],
) -> None:
    """Process and ingest a single file with idempotence and retry support."""
    try:
        file_bytes = file_path.read_bytes()
    except Exception as exc:
        counts["failed"] += 1
        print(f"file={file_path.name} status=failed reason={short_reason(exc)}")
        return

    doc_id = make_doc_id(file_bytes, owner_id)

    try:
        _, stored_path = rights.create_document(
            file_bytes,
            file_path.name,
            meta,
            owner_id,
            None,
        )
        target_path = stored_path if stored_path.is_file() else file_path
        ingestion.ingest(doc_id, target_path, meta, roles, owner_id)
    except Conflict:
        try:
            status = rights.get_status(doc_id)
        except Exception:
            status = DocStatus.FAILED

        if status == DocStatus.FAILED:
            # Retry with original file (P1-28, P1-33)
            try:
                ingestion.ingest(doc_id, file_path, meta, roles, owner_id)
            except Exception as exc:
                counts["failed"] += 1
                print(f"doc_id={doc_id} status=failed reason={short_reason(exc)}")
                return
        else:
            # Ready or in progress -> skip
            counts["ignored"] += 1
            print(f"doc_id={doc_id} status=ignored")
            return
    except Exception as exc:
        counts["failed"] += 1
        print(f"doc_id={doc_id} status=failed reason={short_reason(exc)}")
        return

    try:
        final_status = rights.get_status(doc_id)
    except Exception:
        final_status = DocStatus.FAILED

    if final_status == DocStatus.FAILED:
        counts["failed"] += 1
        print(f"doc_id={doc_id} status=failed")
    else:
        counts["ingested"] += 1
        print(f"doc_id={doc_id} status=ingested")


def main(
    argv: list[str] | None = None,
    rights: DocumentRights | None = None,
    ingestion: Ingestion | None = None,
) -> int:
    """CLI main entry point (P1-33)."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    # Resolve collaborators via registry if not provided (P1-31)
    if rights is None:
        try:
            from src.core.contracts.registry import get_document_rights

            rights = get_document_rights()
        except Exception as exc:
            sys.stderr.write(f"Registry error: {type(exc).__name__}\n")
            return 3

    if ingestion is None:
        try:
            from src.ingestion import real_ingestion

            ingestion = real_ingestion(rights=rights)
        except Exception as exc:
            sys.stderr.write(f"Registry error: {type(exc).__name__}\n")
            return 3

    owner_id: UUID | None = None
    if getattr(args, "owner", None):
        try:
            owner_id = UUID(args.owner)
        except ValueError:
            sys.stderr.write("Usage error: invalid UUID for --owner\n")
            return 2

    counts = {"ingested": 0, "ignored": 0, "failed": 0}

    if args.subcommand == "ingest":
        path = Path(args.path)
        if not path.exists():
            sys.stderr.write(f"Path not found: {path}\n")
            return 1

        roles = [r.strip() for r in args.roles.split(",") if r.strip()] if args.roles else []

        if path.is_file():
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                counts["failed"] += 1
                print(f"file={path.name} status=failed reason=unsupported format")
                print(
                    f"Summary: ingested={counts['ingested']} ignored={counts['ignored']} failed={counts['failed']}"
                )
                return 1

            meta = DocumentMeta(
                title=args.title or path.stem,
                source_file=path.name,
                source=args.source,
                date=args.date,
            )
            _ingest_file(path, meta, roles, owner_id, rights, ingestion, counts)

        elif path.is_dir():
            items = sorted(path.iterdir(), key=lambda p: p.name)
            for item in items:
                if not item.is_file():
                    continue
                if item.name.startswith(".") or item.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    counts["ignored"] += 1
                    continue

                meta = DocumentMeta(
                    title=args.title or item.stem,
                    source_file=item.name,
                    source=args.source,
                    date=args.date,
                )
                _ingest_file(item, meta, roles, owner_id, rights, ingestion, counts)
        else:
            sys.stderr.write(f"Invalid path type: {path}\n")
            return 1

    elif args.subcommand == "seed":
        raw_dir = Path(args.raw_dir)
        manifest_path = raw_dir / "manifest.csv"
        if not manifest_path.is_file():
            sys.stderr.write(f"Manifest not found: {manifest_path}\n")
            return 2

        try:
            with open(manifest_path, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except Exception as exc:
            sys.stderr.write(f"Error reading manifest: {short_reason(exc)}\n")
            return 2

        # Pre-flight check: upload rows require --owner (P1-33)
        has_upload = any(row.get("visibility", "").strip().lower() == "upload" for row in rows)
        if has_upload and owner_id is None:
            sys.stderr.write(
                "Usage error: --owner is required when manifest contains upload rows\n"
            )
            return 2

        for row in rows:
            file_rel = row.get("file", "").strip()
            if not file_rel:
                continue

            file_path = raw_dir / file_rel
            if not file_path.is_file():
                counts["failed"] += 1
                print(f"file={file_rel} status=failed reason=file not found")
                continue

            vis = row.get("visibility", "").strip().lower()
            if vis == "public":
                row_roles = ["lecteur", "editeur"]
                row_owner = None
            elif vis == "internal":
                row_roles = ["editeur"]
                row_owner = None
            elif vis == "upload":
                row_roles = []
                row_owner = owner_id
            else:
                row_roles = []
                row_owner = None

            meta_title = row.get("title", "").strip() or file_path.stem
            meta_source = row.get("source_url", "").strip() or None
            meta_date = row.get("date", "").strip() or None

            meta = DocumentMeta(
                title=meta_title,
                source_file=file_path.name,
                source=meta_source,
                date=meta_date,
            )

            _ingest_file(file_path, meta, row_roles, row_owner, rights, ingestion, counts)

    print(
        f"Summary: ingested={counts['ingested']} ignored={counts['ignored']} failed={counts['failed']}"
    )
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
