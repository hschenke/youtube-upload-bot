"""Löst `.github/workflows/upload_videos.yaml` über die GitHub Actions REST API aus."""

from __future__ import annotations

import logging

import requests

from src.config.constants import GITHUB_API_TIMEOUT_SECONDS
from src.config.settings import AppSettings
from src.domain.exceptions import DispatchError

logger = logging.getLogger(__name__)


class GitHubActionsDispatcher:
    """Startet bei Bedarf sofortige Cloud-Läufe via `workflow_dispatch`."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def trigger_upload_run(
        self,
        *,
        profile: str = "",
        dry_run: bool = False,
        privacy: str = "",
        max_uploads: int = 0,
        video_id: str = "",
    ) -> None:
        """Sendet einen `workflow_dispatch`-Request an GitHub Actions."""
        if not self._settings.has_github_worker_configured:
            raise DispatchError(
                "GitHub-Worker ist nicht konfiguriert (GITHUB_TOKEN oder GITHUB_REPO fehlt)."
            )

        repo = self._settings.github_repo.strip("/")
        workflow = self._settings.github_workflow_file.strip()
        endpoint = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
        headers = {
            "Authorization": f"Bearer {self._settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "YouTubeUploadBot/0.1",
        }

        try:
            resp = requests.post(
                endpoint,
                headers=headers,
                json={
                    "ref": self._settings.github_branch,
                    "inputs": {
                        "profile": profile.strip(),
                        "dry_run": "true" if dry_run else "false",
                        "privacy": privacy.strip(),
                        "max_uploads": str(max(0, int(max_uploads))),
                        "video_id": video_id.strip(),
                    },
                },
                timeout=GITHUB_API_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise DispatchError(f"GitHub Actions API nicht erreichbar: {exc}") from exc

        if resp.status_code != 204:
            raise DispatchError(
                f"GitHub Actions Dispatch abgelehnt (HTTP {resp.status_code}). "
                "Bitte Berechtigung `Actions: Read and write` prüfen."
            )
        logger.info("GitHub Actions Workflow '%s' ausgelöst (profile='%s').", workflow, profile or "all")
