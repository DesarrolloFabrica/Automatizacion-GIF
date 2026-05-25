from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from job_store import JobStore
from storage import JOBS_ROOT, _write_json_atomic, _read_json_or_none


MAX_LOG_LINES = 1000


class LocalDiskJobStore(JobStore):
    """Implementacion de JobStore basada en disco local.

    Envuelve la logica actual de /tmp/automatizacion-gif/jobs,
    job_metadata.json, phase_status.json y job.log.
    """

    def create_job(self, job_id: str, metadata: dict[str, Any]) -> None:
        state_dir = JOBS_ROOT / job_id
        state_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "jobId": job_id,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        payload.update(metadata)
        _write_json_atomic(state_dir / "job_metadata.json", payload)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        mp = JOBS_ROOT / job_id / "job_metadata.json"
        data = _read_json_or_none(mp)
        if data is None:
            return None
        ps_path = JOBS_ROOT / job_id / "phase_status.json"
        phase_status = _read_json_or_none(ps_path)
        if phase_status:
            data["phase_status"] = phase_status
        return data

    def update_job(self, job_id: str, updates: dict[str, Any]) -> None:
        state_dir = JOBS_ROOT / job_id
        state_dir.mkdir(parents=True, exist_ok=True)
        base = self.get_job(job_id) or {}
        base.update(updates)
        base["updated_at"] = datetime.utcnow().isoformat()
        _write_json_atomic(state_dir / "job_metadata.json", base)

    def update_phase_status(self, job_id: str, phase: str, status: str, files: list[str] | None = None) -> None:
        from storage import read_phase_status, write_phase_status, _empty_phase, _utc_now

        payload = read_phase_status(job_id)
        payload.setdefault(phase, _empty_phase("pending"))
        phase_entry = payload[phase]
        phase_entry["status"] = status
        if status == "running":
            phase_entry["startedAt"] = _utc_now()
            phase_entry["finishedAt"] = None
        if status in {"completed", "failed", "skipped", "cancelled"}:
            phase_entry["finishedAt"] = _utc_now()
        if files is not None:
            phase_entry["files"] = files
        write_phase_status(job_id, payload)

    def append_log(self, job_id: str, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        log_path = JOBS_ROOT / job_id / "job.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")

    def get_logs(self, job_id: str, max_lines: int = MAX_LOG_LINES) -> list[str]:
        log_path = JOBS_ROOT / job_id / "job.log"
        if not log_path.exists():
            return []
        try:
            text = log_path.read_text(encoding="utf-8")
            return text.splitlines()[-max_lines:]
        except OSError:
            return []

    def set_expires_at(self, job_id: str, expires_at: datetime) -> None:
        self.update_job(job_id, {"expires_at": expires_at.isoformat()})

    def save_file_manifest(self, job_id: str, manifest: list[dict[str, Any]]) -> None:
        state_dir = JOBS_ROOT / job_id
        state_dir.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(state_dir / "file_manifest.json", manifest)

    def get_file_manifest(self, job_id: str) -> list[dict[str, Any]]:
        mp = JOBS_ROOT / job_id / "file_manifest.json"
        data = _read_json_or_none(mp)
        if data is None:
            return []
        if isinstance(data, list):
            return data
        return []
