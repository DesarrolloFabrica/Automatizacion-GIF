from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
import os
from pathlib import Path

from storage import list_generated_docx


MAX_LOG_LINES = 1000


@dataclass
class JobRecord:
    job_id: str
    status: str
    progress_step: str
    log_path: Path
    generated_dir: Path
    logs: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    finished_at: str | None = None


_JOBS: dict[str, JobRecord] = {}
_LOCK = threading.Lock()


def create_job(job_id: str, log_path: Path, generated_dir: Path) -> JobRecord:
    record = JobRecord(
        job_id=job_id,
        status="queued",
        progress_step="pendiente",
        log_path=log_path,
        generated_dir=generated_dir,
    )
    with _LOCK:
        _JOBS[job_id] = record
    return record


def get_job(job_id: str) -> JobRecord | None:
    with _LOCK:
        return _JOBS.get(job_id)


def append_log(job_id: str, line: str) -> None:
    line = line.rstrip()
    if not line:
        return

    with _LOCK:
        record = _JOBS[job_id]
        record.logs.append(line)
        if len(record.logs) > MAX_LOG_LINES:
            record.logs = record.logs[-MAX_LOG_LINES:]

    record.log_path.parent.mkdir(parents=True, exist_ok=True)
    with record.log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")


def update_progress_from_log(job_id: str, line: str) -> None:
    normalized = line.lower()
    progress_step = None

    if "plan detectado" in normalized:
        progress_step = "detectando estructura temática"
    elif "prompt seleccionado" in normalized or "nivel seleccionado" in normalized:
        progress_step = "preparando prompts"
    elif "generando documento" in normalized:
        progress_step = "generando documentos"

    if progress_step is None:
        return

    with _LOCK:
        _JOBS[job_id].progress_step = progress_step


def set_job_running(job_id: str) -> None:
    with _LOCK:
        record = _JOBS[job_id]
        record.status = "running"
        record.progress_step = "leyendo syllabus"


def set_job_finished(job_id: str, success: bool) -> None:
    with _LOCK:
        record = _JOBS[job_id]
        record.status = "completed" if success else "failed"
        record.progress_step = "finalizado" if success else "error"
        record.files = list_generated_docx(job_id)
        record.finished_at = datetime.utcnow().isoformat()


def set_job_failed_with_message(job_id: str, message: str) -> None:
    append_log(job_id, message)
    set_job_finished(job_id, success=False)


def run_generate_guiones(job_id: str, command: list[str], cwd: Path, env_vars: dict[str, str] | None = None) -> None:
    set_job_running(job_id)
    append_log(job_id, f"Ejecutando comando: {' '.join(command)}")

    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env_vars or os.environ.copy(),
        )

        assert process.stdout is not None
        for line in process.stdout:
            append_log(job_id, line)
            update_progress_from_log(job_id, line)

        return_code = process.wait()
        append_log(job_id, f"Proceso finalizado con código: {return_code}")
        set_job_finished(job_id, success=(return_code == 0))
    except Exception as exc:
        set_job_failed_with_message(job_id, f"Error al ejecutar generate_guiones.py: {exc}")


def start_job_thread(job_id: str, command: list[str], cwd: Path, env_vars: dict[str, str] | None = None) -> None:
    thread = threading.Thread(target=run_generate_guiones, args=(job_id, command, cwd, env_vars), daemon=True)
    thread.start()
