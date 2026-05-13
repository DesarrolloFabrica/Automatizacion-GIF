from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from storage import get_job_paths, list_generated_docx, read_job_metadata, read_phase_status, write_phase_status


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
# Subprocesos activos (granulos / fases) para poder cancelar sin reiniciar el servidor.
_ACTIVE_SUBPROCESSES: dict[str, subprocess.Popen] = {}
_CANCEL_REQUESTED: set[str] = set()


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


def hydrate_job_from_disk(job_id: str) -> JobRecord | None:
    """Reconstruye el JobRecord tras reinicio del servidor o pérdida de memoria, desde disco."""
    paths = get_job_paths(job_id)
    if not paths["metadata_path"].exists() or not paths["phase_status_path"].exists():
        return None
    logs: list[str] = []
    if paths["log_path"].exists():
        try:
            text = paths["log_path"].read_text(encoding="utf-8")
            logs = text.splitlines()[-MAX_LOG_LINES:]
        except OSError:
            logs = []
    phase_status = read_phase_status(job_id)
    running_phases = [
        phase_key
        for phase_key in ("granules", "pipelineLocal", "specializationMaterials", "uploadDrive")
        if phase_status.get(phase_key, {}).get("status") == "running"
    ]
    if running_phases:
        now = datetime.utcnow().isoformat()
        started_at = phase_status[running_phases[0]].get("startedAt")
        is_orphaned = False
        if started_at:
            try:
                started_dt = datetime.fromisoformat(started_at)
                elapsed = (datetime.utcnow() - started_dt).total_seconds()
                if elapsed > 3600:
                    is_orphaned = True
            except (ValueError, TypeError):
                is_orphaned = True
        for phase_key in running_phases:
            phase_status[phase_key]["status"] = "failed"
            phase_status[phase_key]["finishedAt"] = now
        write_phase_status(job_id, phase_status)
        if is_orphaned:
            logs.append("=== El proceso quedo incompleto por reinicio o perdida de instancia (mas de 1 hora sin actividad). ===")
        else:
            logs.append("=== Job marcado como fallido: el servidor se reinicio mientras habia una fase en ejecucion ===")

    phases = [phase_status.get(key, {}) for key in ("granules", "pipelineLocal", "specializationMaterials", "uploadDrive")]
    status = "failed" if running_phases or any(phase.get("status") == "failed" for phase in phases) else "completed"
    progress_step = "error" if status == "failed" else "finalizado"

    record = JobRecord(
        job_id=job_id,
        status=status,
        progress_step=progress_step,
        log_path=paths["log_path"],
        generated_dir=paths["generated_dir"],
        job_kind="granules_academic_package",
        logs=logs,
    )
    with _LOCK:
        if job_id in _JOBS:
            return _JOBS[job_id]
        _JOBS[job_id] = record
    return record


def get_job(job_id: str) -> JobRecord | None:
    with _LOCK:
        cached = _JOBS.get(job_id)
    if cached is not None:
        return cached
    return hydrate_job_from_disk(job_id)


def terminate_job_subprocess(job_id: str) -> bool:
    """Intenta detener el proceso del job (SIGTERM). Devuelve True si había proceso activo."""
    _CANCEL_REQUESTED.add(job_id)
    proc = _ACTIVE_SUBPROCESSES.get(job_id)
    if proc is None:
        with _LOCK:
            record = _JOBS.get(job_id)
            if record is not None:
                record.status = "cancelled"
                record.progress_step = "cancelado"
                record.finished_at = datetime.utcnow().isoformat()
        return False
    try:
        proc.terminate()
        return True
    except Exception:
        return False


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
        was_cancelled = job_id in _CANCEL_REQUESTED
        record.status = "cancelled" if was_cancelled else "completed" if success else "failed"
        record.progress_step = "cancelado" if was_cancelled else "finalizado" if success else "error"
        if files_listing_fn is not None:
            record.files = files_listing_fn(job_id)
        elif record.job_kind == "granules":
            record.files = list_generated_docx(job_id)
        else:
            record.files = []
        record.finished_at = datetime.utcnow().isoformat()
    if was_cancelled:
        phase_status = read_phase_status(job_id)
        for phase_key in ("granules", "pipelineLocal", "specializationMaterials", "uploadDrive"):
            if phase_status.get(phase_key, {}).get("status") in {"running", "failed"}:
                phase_status[phase_key]["status"] = "cancelled"
                phase_status[phase_key]["finishedAt"] = datetime.utcnow().isoformat()
        write_phase_status(job_id, phase_status)
    _CANCEL_REQUESTED.discard(job_id)


def set_job_failed_with_message(job_id: str, message: str) -> None:
    append_log(job_id, message)
    with _LOCK:
        kind = _JOBS[job_id].job_kind
    if kind == "granules":
        set_job_finished(job_id, success=False)
    else:
        set_job_finished(job_id, success=False, files_listing_fn=lambda _: [])


def _merge_subprocess_env(env_vars: dict[str, str] | None) -> dict[str, str]:
    merged = os.environ.copy()
    if env_vars:
        merged.update(env_vars)
    merged.setdefault("PYTHONUTF8", "1")
    merged.setdefault("PYTHONIOENCODING", "utf-8")
    return merged


def _process_subprocess_line(
    job_id: str,
    line: str,
    *,
    progress_map: dict[str, str] | None,
    parse_drive_uploads: bool,
) -> None:
    append_log(job_id, line)
    if parse_drive_uploads:
        parsed = parse_drive_upload_line(line)
        if parsed:
            with _LOCK:
                _JOBS[job_id].drive_links.append(parsed)
    update_progress_from_log(job_id, line, progress_map)


def _write_subprocess_failure_artifacts(
    job_id: str,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    return_code: int,
    stdout_text: str,
    stderr_text: str,
    host_traceback: str | None = None,
) -> Path:
    """Guarda stdout/stderr completos y un error.log con contexto (comando, cwd, env filtrado)."""
    paths = get_job_paths(job_id)
    logs_dir = paths["state_dir"] / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "stdout.log").write_text(stdout_text, encoding="utf-8")
    (logs_dir / "stderr.log").write_text(stderr_text, encoding="utf-8")

    def mask_secret(val: str) -> str:
        s = str(val)
        if len(s) <= 6:
            return "***"
        return s[:3] + "***" + s[-2:]

    safe_env: dict[str, str] = {}
    for key, val in sorted(env.items()):
        ku = key.upper()
        if any(x in ku for x in ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL")):
            safe_env[key] = mask_secret(val) if val else ""
        elif key.startswith(("OPENAI", "PYTHON", "AUTOMATIZACION", "PATH", "VIRTUAL_ENV", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR")):
            safe_env[key] = str(val)[:800]

    parts = [
        f"job_id={job_id}",
        f"return_code={return_code}",
        f"cwd={cwd}",
        f"command={json.dumps(command, ensure_ascii=False)}",
        "",
        "=== environment (filtered / masked) ===",
        json.dumps(safe_env, ensure_ascii=False, indent=2),
        "",
        "=== stderr (full) ===",
        stderr_text,
        "",
        "=== stdout (full) ===",
        stdout_text,
    ]
    if host_traceback:
        parts.extend(["", "=== host-side exception ===", host_traceback])
    err_path = logs_dir / "error.log"
    err_path.write_text("\n".join(parts), encoding="utf-8")
    return err_path


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
    merged_env = _merge_subprocess_env(env_vars)
    append_log(job_id, f"Ejecutando comando: {' '.join(command)}")
    append_log(job_id, f"cwd={cwd}")
    append_log(
        job_id,
        f"Entorno subprocess: PYTHONUTF8={merged_env.get('PYTHONUTF8', '')} PYTHONIOENCODING={merged_env.get('PYTHONIOENCODING', '')}",
    )
    host_tb: str | None = None
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    def read_stdout() -> None:
        try:
            assert process.stdout is not None
            for line in process.stdout:
                stdout_chunks.append(line)
                _process_subprocess_line(job_id, line, progress_map=progress_map, parse_drive_uploads=parse_drive_uploads)
        except Exception as exc:
            stdout_chunks.append(f"[jobs.py reader stdout] {exc!r}\n")

    def read_stderr() -> None:
        try:
            assert process.stderr is not None
            for line in process.stderr:
                stderr_chunks.append(line)
                _process_subprocess_line(job_id, line, progress_map=progress_map, parse_drive_uploads=parse_drive_uploads)
        except Exception as exc:
            stderr_chunks.append(f"[jobs.py reader stderr] {exc!r}\n")

    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=merged_env,
    )
    _ACTIVE_SUBPROCESSES[job_id] = process
    try:
        tout = threading.Thread(target=read_stdout, daemon=True)
        terr = threading.Thread(target=read_stderr, daemon=True)
        tout.start()
        terr.start()
        tout.join()
        terr.join()
        return_code = process.wait()
        append_log(job_id, f"Proceso finalizado con código: {return_code}")
        stdout_text = "".join(stdout_chunks)
        stderr_text = "".join(stderr_chunks)
        if return_code != 0:
            err_path = _write_subprocess_failure_artifacts(
                job_id,
                command,
                cwd,
                merged_env,
                return_code,
                stdout_text,
                stderr_text,
                host_traceback=host_tb,
            )
            append_log(
                job_id,
                f"=== Subprocess falló (código {return_code}). Diagnóstico: outputs/jobs/{job_id}/logs/error.log (y stdout.log / stderr.log) ===",
            )
            if stderr_text.strip():
                append_log(job_id, "=== Últimas líneas de stderr (error / traceback del hijo) ===")
                for tail_line in stderr_text.strip().splitlines()[-50:]:
                    append_log(job_id, tail_line)
        return return_code
    except Exception as exc:
        host_tb = traceback.format_exc()
        append_log(job_id, f"Error ejecutando subprocess: {exc}")
        append_log(job_id, host_tb)
        stdout_text = "".join(stdout_chunks)
        stderr_text = "".join(stderr_chunks)
        try:
            if process.poll() is None:
                process.terminate()
        except Exception:
            pass
        _write_subprocess_failure_artifacts(
            job_id,
            command,
            cwd,
            merged_env,
            process.poll() if process.poll() is not None else -1,
            stdout_text,
            stderr_text,
            host_traceback=host_tb,
        )
        return -1
    finally:
        _ACTIVE_SUBPROCESSES.pop(job_id, None)


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
