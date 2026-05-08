from __future__ import annotations

import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from storage import list_generated_docx


MAX_LOG_LINES = 1000

SUBIDO_PATTERN = re.compile(r"Subido:\s*(.+?)\s*->\s*(.+)", re.IGNORECASE)


def parse_drive_upload_line(line: str) -> dict[str, str] | None:
    """Parsea líneas tipo 'Subido: archivo.docx -> https://...' del pipeline Drive."""
    match = SUBIDO_PATTERN.search(line)
    if not match:
        return None
    name = match.group(1).strip()
    link = match.group(2).strip()
    lower = name.lower()
    if lower.endswith(".txt"):
        kind = "txt"
    elif lower.endswith(".docx"):
        kind = "docx"
    else:
        kind = "unknown"
    return {"name": name, "link": link, "kind": kind}


@dataclass
class JobRecord:
    job_id: str
    status: str
    progress_step: str
    log_path: Path
    generated_dir: Path
    job_kind: str = "granules"
    logs: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    drive_links: list[dict[str, str]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    finished_at: str | None = None


_JOBS: dict[str, JobRecord] = {}
_LOCK = threading.Lock()


def create_job(job_id: str, log_path: Path, generated_dir: Path, job_kind: str = "granules") -> JobRecord:
    record = JobRecord(
        job_id=job_id,
        status="queued",
        progress_step="pendiente",
        log_path=log_path,
        generated_dir=generated_dir,
        job_kind=job_kind,
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


def update_progress_from_log(job_id: str, line: str, progress_map: dict[str, str] | None = None) -> None:
    normalized = line.lower()

    if progress_map:
        for pattern, step in progress_map.items():
            if pattern in normalized:
                with _LOCK:
                    _JOBS[job_id].progress_step = step
                return
        return

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


def set_job_running(job_id: str, initial_progress_step: str = "leyendo syllabus") -> None:
    with _LOCK:
        record = _JOBS[job_id]
        record.status = "running"
        record.progress_step = initial_progress_step


def set_job_finished(job_id: str, success: bool, files_listing_fn: Callable[[str], list[str]] | None = None) -> None:
    with _LOCK:
        record = _JOBS[job_id]
        record.status = "completed" if success else "failed"
        record.progress_step = "finalizado" if success else "error"
        if files_listing_fn is not None:
            record.files = files_listing_fn(job_id)
        elif record.job_kind == "granules":
            record.files = list_generated_docx(job_id)
        else:
            record.files = []
        record.finished_at = datetime.utcnow().isoformat()


def set_job_failed_with_message(job_id: str, message: str) -> None:
    append_log(job_id, message)
    with _LOCK:
        kind = _JOBS[job_id].job_kind
    if kind == "granules":
        set_job_finished(job_id, success=False)
    else:
        set_job_finished(job_id, success=False, files_listing_fn=lambda _: [])


def run_subprocess_job(
    job_id: str,
    command: list[str],
    cwd: Path,
    env_vars: dict[str, str] | None = None,
    *,
    initial_progress_step: str = "leyendo syllabus",
    progress_map: dict[str, str] | None = None,
    parse_drive_uploads: bool = False,
    job_kind: str = "granules",
    files_listing_fn: Callable[[str], list[str]] | None = None,
    chain_command: list[str] | None = None,
    chain_commands: list[list[str]] | None = None,
    chain_labels: list[str] | None = None,
    on_start: Callable[[str], None] | None = None,
    on_complete: Callable[[str, bool], None] | None = None,
) -> None:
    set_job_running(job_id, initial_progress_step)
    if on_start is not None:
        on_start(job_id)

    try:
        if job_kind.startswith("granules"):
            append_log(job_id, "=== FASE 1: GENERACIÓN DE GRÁNULOS ===")
        return_code = _run_command_and_stream_logs(
            job_id=job_id,
            command=command,
            cwd=cwd,
            env_vars=env_vars,
            progress_map=progress_map,
            parse_drive_uploads=parse_drive_uploads,
        )
        success = return_code == 0

        commands_to_chain = chain_commands or ([chain_command] if chain_command else [])
        labels = chain_labels or []
        for index, chained in enumerate(commands_to_chain):
            if not success:
                break
            label = labels[index] if index < len(labels) else f"FASE ENCADENADA {index + 2}"
            append_log(job_id, label)
            try:
                chain_return = _run_command_and_stream_logs(
                    job_id=job_id,
                    command=chained,
                    cwd=cwd,
                    env_vars=env_vars,
                    progress_map=progress_map,
                    parse_drive_uploads=False,
                )
                append_log(job_id, f"Fase encadenada finalizada con código: {chain_return}")
                success = chain_return == 0
            except Exception as chain_exc:
                append_log(job_id, f"Error en fase encadenada: {chain_exc}")
                success = False

        if on_complete is not None:
            on_complete(job_id, success)

        if files_listing_fn is not None:
            set_job_finished(job_id, success=success, files_listing_fn=files_listing_fn)
        elif job_kind == "scripts":
            set_job_finished(job_id, success=success, files_listing_fn=lambda _: [])
        else:
            set_job_finished(job_id, success=success)
    except Exception as exc:
        if on_complete is not None:
            on_complete(job_id, False)
        set_job_failed_with_message(job_id, f"Error al ejecutar el proceso: {exc}")


def _run_command_and_stream_logs(
    job_id: str,
    command: list[str],
    cwd: Path,
    env_vars: dict[str, str] | None,
    progress_map: dict[str, str] | None,
    parse_drive_uploads: bool,
) -> int:
    append_log(job_id, f"Ejecutando comando: {' '.join(command)}")
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
        if parse_drive_uploads:
            parsed = parse_drive_upload_line(line)
            if parsed:
                with _LOCK:
                    _JOBS[job_id].drive_links.append(parsed)
        update_progress_from_log(job_id, line, progress_map)

    return_code = process.wait()
    append_log(job_id, f"Proceso finalizado con código: {return_code}")
    return return_code


def start_job_thread(
    job_id: str,
    command: list[str],
    cwd: Path,
    env_vars: dict[str, str] | None = None,
    *,
    initial_progress_step: str = "leyendo syllabus",
    progress_map: dict[str, str] | None = None,
    parse_drive_uploads: bool = False,
    job_kind: str = "granules",
    files_listing_fn: Callable[[str], list[str]] | None = None,
    chain_command: list[str] | None = None,
    chain_commands: list[list[str]] | None = None,
    chain_labels: list[str] | None = None,
    on_start: Callable[[str], None] | None = None,
    on_complete: Callable[[str, bool], None] | None = None,
) -> None:
    kwargs: dict[str, Any] = {
        "initial_progress_step": initial_progress_step,
        "progress_map": progress_map,
        "parse_drive_uploads": parse_drive_uploads,
        "job_kind": job_kind,
        "files_listing_fn": files_listing_fn,
        "chain_command": chain_command,
        "chain_commands": chain_commands,
        "chain_labels": chain_labels,
        "on_start": on_start,
        "on_complete": on_complete,
    }
    thread = threading.Thread(
        target=run_subprocess_job,
        args=(job_id, command, cwd, env_vars),
        kwargs=kwargs,
        daemon=True,
    )
    thread.start()
