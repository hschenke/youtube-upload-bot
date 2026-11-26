"""Headless CLI-Worker für GitHub Actions Cron und lokale Ausführung."""

from __future__ import annotations

import argparse
import logging
import sys

from src.config.settings import load_app_settings
from src.domain.enums import PrivacyStatus, RunStatus, TriggerSource
from src.storage.repository import create_repository
from src.worker.pipeline import UploadPipelineService


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="youtube-upload-bot",
        description="Synchronisiert Google Drive Staging-Videos, analysiert per Gemini und lädt auf YouTube hoch.",
    )
    parser.add_argument(
        "--profile",
        default="",
        help="Name eines bestimmten Profils (leer = alle aktiven Profile).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simuliert Filterung und KI-Metadaten ohne YouTube-Upload und Drive-Löschung.",
    )
    parser.add_argument(
        "--privacy",
        choices=[p.value for p in PrivacyStatus],
        default="",
        help="Überschreibt die Sichtbarkeit des Profils (public, unlisted, private).",
    )
    parser.add_argument(
        "--max-uploads",
        type=int,
        default=0,
        help="Überschreibt das maximale Upload-Limit pro Profil in diesem Lauf.",
    )
    parser.add_argument(
        "--video-id",
        default="",
        help="Optional nur ein bestimmtes Video aus der Queue verarbeiten.",
    )
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Synchronisiert nur den Google Drive Staging-Ordner in die Datenbank.",
    )
    parser.add_argument(
        "--trigger-source",
        choices=[t.value for t in TriggerSource],
        default=TriggerSource.CLI.value,
        help="Herkunft des Laufs für das Audit-Protokoll.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = build_arg_parser().parse_args(argv)
    settings = load_app_settings()
    repository = create_repository(settings)

    try:
        pipeline = UploadPipelineService(settings, repository)
        if args.sync_only:
            scanned, missing = pipeline.sync_drive_queue()
            logging.info("Drive-Sync abgeschlossen: %d Dateien gescannt, %d fehlende übersprungen.", scanned, missing)
            return 0

        privacy_override = PrivacyStatus(args.privacy) if args.privacy else None
        run_record = pipeline.run_scheduled_upload(
            profile_name=args.profile,
            dry_run=args.dry_run,
            privacy_override=privacy_override,
            max_uploads_override=args.max_uploads if args.max_uploads > 0 else None,
            video_id=args.video_id,
            trigger_source=TriggerSource(args.trigger_source),
        )
        logging.info("Run %s (%s): %s", run_record.run_id, run_record.status.value, run_record.summary_message)
        return 1 if run_record.status == RunStatus.FAILED else 0
    finally:
        repository.close()


if __name__ == "__main__":
    sys.exit(main())
