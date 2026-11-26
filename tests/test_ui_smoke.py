"""Import- & Smoke-Tests für CLI, Formatter und Streamlit-UI-Module."""

from __future__ import annotations

from src.domain.enums import RunStatus, VideoQueueStatus
from src.ui import app as ui_app
from src.ui import auth_view, formatters, styles
from src.ui.views import (
    history_view,
    picker_import_view,
    profiles_view,
    queue_view,
    settings_view,
)
from src.worker.cli_worker import build_arg_parser


def test_ui_modules_and_formatters_smoke() -> None:
    assert formatters.format_bytes(0) == "0 B"
    assert formatters.format_bytes(1536) == "1.5 KB"
    assert formatters.format_duration(65.0) == "1:05"
    assert formatters.format_resolution(1080, 1920) == "1080×1920"
    assert "Hochgeladen" in formatters.format_status_badge(VideoQueueStatus.UPLOADED)
    assert "Erfolg" in formatters.format_run_status_badge(RunStatus.SUCCESS)

    assert callable(ui_app.run_streamlit_app)
    assert callable(auth_view.enforce_authentication)
    assert callable(styles.inject_global_styles)
    assert callable(picker_import_view.render_picker_import_view)
    assert callable(queue_view.render_queue_view)
    assert callable(profiles_view.render_profiles_view)
    assert callable(history_view.render_history_view)
    assert callable(settings_view.render_settings_view)


def test_cli_arg_parser() -> None:
    parser = build_arg_parser()
    parsed = parser.parse_args(["--profile", "shorts", "--dry-run", "--max-uploads", "2"])
    assert parsed.profile == "shorts"
    assert parsed.dry_run is True
    assert parsed.max_uploads == 2
