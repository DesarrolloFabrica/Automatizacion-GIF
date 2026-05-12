from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import re
import unicodedata


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from automation_engine.config.categories import CATEGORIES, get_category  # noqa: E402

JOBS_ROOT = PROJECT_ROOT / "outputs" / "jobs"
DRIVE_JOB_CONTENT_ROOT = Path(
    os.getenv("AUTOMATIZACION_GIF_DRIVE_CONTENT_ROOT")
    or Path(tempfile.gettempdir()) / "automatizacion_gif_drive_content"
)
LOGGER = logging.getLogger(__name__)


class AcademicPackageError(ValueError):
    pass


ACADEMIC_PACKAGE_ROOT = "PAQUETE_ACADEMICO"
GRANULE_PATTERN = re.compile(r"^(G[1-5])(?:_|\b).+\.docx$", re.IGNORECASE)
MATERIAL_PATTERN = re.compile(r"^(02|03|04|05|06|07)_G([1-5])_.*\.docx$", re.IGNORECASE)
MATERIAL_SHORT_NAMES = {
    "02": "02_FICHAS.docx",
    "03": "03_GLOSARIO.docx",
    "04": "04_REVISTA.docx",
    "05": "05_INFOGRAFIA.docx",
    "06": "06_PODCAST.docx",
    "07": "07_VIDEO_SOLUCION.docx",
}


def _job_metadata_path(job_id: str) -> Path:
    return JOBS_ROOT / job_id / "job_metadata.json"


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def _read_json_or_none(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return None
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("No se pudo leer JSON runtime %s: %s", path, exc)
        return None


def job_uses_drive_temp_content(job_id: str) -> bool:
    """Si True, input/generated/pipeline/materiales viven en temp del SO, no en outputs/jobs."""
    mp = _job_metadata_path(job_id)
    data = _read_json_or_none(mp)
    return bool(data and data.get("drivePhasedSync"))


def get_job_paths(job_id: str) -> dict[str, Path]:
    state_dir = JOBS_ROOT / job_id
    content_root = (DRIVE_JOB_CONTENT_ROOT / job_id) if job_uses_drive_temp_content(job_id) else state_dir
    input_dir = content_root / "input"
    generated_dir = content_root / "generated"
    pipeline_local_dir = content_root / "pipeline_local"
    log_path = state_dir / "job.log"
    phase_status_path = state_dir / "phase_status.json"
    metadata_path = state_dir / "job_metadata.json"
    zip_path = content_root / "generated_docs.zip"
    return {
        "job_id": job_id,
        "state_dir": state_dir,
        "content_root": content_root,
        "base_dir": state_dir,
        "input_dir": input_dir,
        "generated_dir": generated_dir,
        "pipeline_local_dir": pipeline_local_dir,
        "log_path": log_path,
        "phase_status_path": phase_status_path,
        "metadata_path": metadata_path,
        "zip_path": zip_path,
    }


def _empty_drive_phase_entry(status: str = "pending") -> dict:
    return {"status": status, "error": None, "updatedAt": None}


def default_drive_phase_status() -> dict[str, dict]:
    return {
        "structure": _empty_drive_phase_entry(),
        "syllabus": _empty_drive_phase_entry(),
        "granules": _empty_drive_phase_entry(),
        "activities": _empty_drive_phase_entry(),
        "resources": _empty_drive_phase_entry(),
    }


def save_job_metadata(
    job_id: str,
    *,
    category: str,
    syllabus_original_name: str | None = None,
    drive_parent_folder_id: str | None = None,
    drive_phased_sync: bool | None = None,
) -> dict:
    state_dir = JOBS_ROOT / job_id
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {"jobId": job_id, "category": category}
    if syllabus_original_name:
        payload["syllabusOriginalName"] = syllabus_original_name
    if drive_parent_folder_id:
        pid = drive_parent_folder_id.strip()
        payload["driveParentFolderId"] = pid
        # Raíz estable del paquete en Drive (no sobrescribir con subcarpetas en merges posteriores).
        payload["driveWorkspaceFolderId"] = pid
    effective_sync = drive_phased_sync if drive_phased_sync is not None else bool(drive_parent_folder_id)
    if effective_sync and payload.get("driveParentFolderId"):
        payload["drivePhasedSync"] = True
        payload.setdefault("drivePhaseStatus", default_drive_phase_status())
        payload.setdefault("driveFoldersCreated", 0)
        payload.setdefault("driveFoldersReused", 0)
        payload.setdefault("driveFilesUploaded", 0)
        payload.setdefault("driveFilesOverwritten", 0)
    metadata_path = state_dir / "job_metadata.json"
    _write_json_atomic(metadata_path, payload)
    return payload


def merge_job_metadata(job_id: str, updates: dict) -> dict:
    state_dir = JOBS_ROOT / job_id
    state_dir.mkdir(parents=True, exist_ok=True)
    base = read_job_metadata(job_id)
    base.update(updates)
    if "driveWorkspaceFolderId" not in base and base.get("driveParentFolderId"):
        base["driveWorkspaceFolderId"] = str(base["driveParentFolderId"]).strip()
    _write_json_atomic(state_dir / "job_metadata.json", base)
    return base


def read_job_metadata(job_id: str) -> dict:
    mp = _job_metadata_path(job_id)
    data = _read_json_or_none(mp)
    if data is None:
        return {"jobId": job_id, "category": "especializacion"}
    if data.get("drivePhasedSync"):
        data.setdefault("drivePhaseStatus", default_drive_phase_status())
        for key in ("structure", "syllabus", "granules", "activities", "resources"):
            data["drivePhaseStatus"].setdefault(key, _empty_drive_phase_entry())
    return data


def accumulate_drive_counters(
    job_id: str,
    *,
    folders_created: int = 0,
    folders_reused: int = 0,
    files_uploaded: int = 0,
    files_overwritten: int = 0,
) -> dict:
    meta = read_job_metadata(job_id)
    meta["driveFoldersCreated"] = int(meta.get("driveFoldersCreated") or 0) + folders_created
    meta["driveFoldersReused"] = int(meta.get("driveFoldersReused") or 0) + folders_reused
    meta["driveFilesUploaded"] = int(meta.get("driveFilesUploaded") or 0) + files_uploaded
    meta["driveFilesOverwritten"] = int(meta.get("driveFilesOverwritten") or 0) + files_overwritten
    return merge_job_metadata(job_id, meta)


def set_drive_phase_record(job_id: str, phase_key: str, *, status: str, error: str | None = None) -> dict:
    meta = read_job_metadata(job_id)
    phases = meta.setdefault("drivePhaseStatus", default_drive_phase_status())
    entry = phases.setdefault(phase_key, _empty_drive_phase_entry())
    entry["status"] = status
    entry["error"] = error
    entry["updatedAt"] = datetime.utcnow().isoformat()
    if error:
        meta["driveLastError"] = error
    return merge_job_metadata(job_id, meta)


def get_drive_sync_snapshot(job_id: str) -> dict:
    """Subset of metadata for API responses (Drive polling)."""
    meta = read_job_metadata(job_id)
    phased = bool(meta.get("drivePhasedSync"))
    root_id = meta.get("driveRootFolderId") or meta.get("drivePackageFolderId") or meta.get("driveParentFolderId")
    out: dict = {
        "drivePhasedSync": phased,
        "driveParentFolderId": meta.get("driveParentFolderId"),
        "driveWorkspaceFolderId": meta.get("driveWorkspaceFolderId") or meta.get("driveParentFolderId"),
        "drivePackageFolderId": meta.get("drivePackageFolderId") or root_id,
        "driveRootFolderId": root_id,
        "drivePackageUrl": meta.get("drivePackageUrl"),
        "driveFoldersCreated": int(meta.get("driveFoldersCreated") or 0),
        "driveFoldersReused": int(meta.get("driveFoldersReused") or 0),
        "driveFilesUploaded": int(meta.get("driveFilesUploaded") or 0),
        "driveFilesOverwritten": int(meta.get("driveFilesOverwritten") or 0),
        "drivePhaseStatus": meta.get("drivePhaseStatus") if phased else None,
        "driveLastError": meta.get("driveLastError") if phased else None,
    }
    if phased and out["drivePhaseStatus"] is None:
        out["drivePhaseStatus"] = default_drive_phase_status()
    return out


def get_job_category(job_id: str) -> str:
    return str(read_job_metadata(job_id).get("category") or "especializacion")


def get_materials_dir(job_id: str) -> Path:
    paths = get_job_paths(job_id)
    category = get_category(get_job_category(job_id))
    return paths["content_root"] / category.materials_dir


def _cleanup_stale_content_shadow_under_state(state_dir: Path) -> None:
    """Elimina carpetas de contenido antiguas bajo outputs/jobs si el contenido pasó a temp (Drive)."""
    for name in ("input", "generated", "pipeline_local"):
        candidate = state_dir / name
        if candidate.is_dir():
            shutil.rmtree(candidate, ignore_errors=True)
    for cfg in CATEGORIES.values():
        candidate = state_dir / cfg.materials_dir
        if candidate.is_dir():
            shutil.rmtree(candidate, ignore_errors=True)


def cleanup_drive_job_content_root(job_id: str) -> None:
    """Borra el directorio temporal de contenido tras subida completa a Drive (modo drivePhasedSync)."""
    if not job_uses_drive_temp_content(job_id):
        return
    root = DRIVE_JOB_CONTENT_ROOT / job_id
    if not root.exists():
        return
    shutil.rmtree(root, ignore_errors=True)
    merge_job_metadata(job_id, {"driveTempContentCleanedAt": datetime.utcnow().isoformat()})


def ensure_job_dirs(job_id: str) -> dict[str, Path]:
    paths = get_job_paths(job_id)
    paths["state_dir"].mkdir(parents=True, exist_ok=True)
    paths["content_root"].mkdir(parents=True, exist_ok=True)
    paths["input_dir"].mkdir(parents=True, exist_ok=True)
    paths["generated_dir"].mkdir(parents=True, exist_ok=True)
    paths["pipeline_local_dir"].mkdir(parents=True, exist_ok=True)
    get_materials_dir(job_id).mkdir(parents=True, exist_ok=True)
    if job_uses_drive_temp_content(job_id):
        _cleanup_stale_content_shadow_under_state(paths["state_dir"])
    return paths


def save_syllabus_file(job_id: str, source_file) -> Path:
    paths = ensure_job_dirs(job_id)
    target_path = paths["input_dir"] / "syllabus.docx"
    with target_path.open("wb") as destination:
        shutil.copyfileobj(source_file, destination)
    return target_path


def _normalize_uploaded_stem(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", normalized).strip("_")
    return normalized.upper() or "GRANULO"


def save_granule_source_file(job_id: str, source_file, original_name: str) -> Path:
    paths = ensure_job_dirs(job_id)
    original = Path(original_name or "G1_GRANULO.docx").name
    if GRANULE_PATTERN.match(original):
        target_name = original
    else:
        target_name = f"G1_{_normalize_uploaded_stem(Path(original).stem)}.docx"
    target_path = paths["generated_dir"] / target_name
    with target_path.open("wb") as destination:
        shutil.copyfileobj(source_file, destination)
    return target_path


def list_generated_docx(job_id: str) -> list[str]:
    paths = get_job_paths(job_id)
    if not paths["generated_dir"].exists():
        return []
    return sorted(path.name for path in paths["generated_dir"].glob("*.docx"))


def list_especializacion_files(job_id: str) -> list[dict[str, str]]:
    return list_material_files(job_id)


def list_material_files(job_id: str) -> list[dict[str, str]]:
    paths = get_job_paths(job_id)
    category = get_category(get_job_category(job_id))
    materiales_dir = get_materials_dir(job_id)
    if not materiales_dir.exists():
        return []
    files = []
    for docx_file in sorted(materiales_dir.rglob("*.docx"), key=lambda item: str(item.relative_to(materiales_dir)).lower()):
        if not docx_file.is_file():
            continue
        relative_path = docx_file.relative_to(materiales_dir)
        granule_folder = relative_path.parts[0] if len(relative_path.parts) > 1 else ""
        files.append({
            "granule": granule_folder,
            "name": docx_file.name,
            "relative_path": f"{category.materials_dir}/{relative_path.as_posix()}",
        })
    return files


def list_especializacion_relative_files(job_id: str) -> list[str]:
    return list_material_relative_files(job_id)


def list_material_relative_files(job_id: str) -> list[str]:
    return [item["relative_path"] for item in list_material_files(job_id)]


def list_pipeline_local_files(job_id: str) -> list[Path]:
    paths = get_job_paths(job_id)
    pipeline_dir = paths["pipeline_local_dir"]
    if not pipeline_dir.exists():
        return []
    return sorted(
        [path for path in pipeline_dir.iterdir() if path.is_file() and path.suffix.lower() in {".docx", ".txt"}],
        key=lambda item: item.name.lower(),
    )


def list_pipeline_local_relative_files(job_id: str) -> list[str]:
    return [f"pipeline_local/{path.name}" for path in list_pipeline_local_files(job_id)]


def list_all_job_files(job_id: str) -> list[str]:
    return sorted(
        list_generated_docx(job_id)
        + list_pipeline_local_relative_files(job_id)
        + list_material_relative_files(job_id)
    )


def _utc_now() -> str:
    return datetime.utcnow().isoformat()


def _empty_phase(status: str = "pending") -> dict:
    return {
        "status": status,
        "startedAt": None,
        "finishedAt": None,
        "files": [],
    }


def init_phase_status(job_id: str) -> dict:
    paths = ensure_job_dirs(job_id)
    payload = {
        "jobId": job_id,
        "granules": _empty_phase("pending"),
        "pipelineLocal": _empty_phase("pending"),
        "specializationMaterials": _empty_phase("pending"),
        "uploadDrive": _empty_phase("pending"),
    }
    _write_json_atomic(paths["phase_status_path"], payload)
    return payload


def read_phase_status(job_id: str) -> dict:
    paths = get_job_paths(job_id)
    payload = _read_json_or_none(paths["phase_status_path"])
    if payload is None:
        payload = {
            "jobId": job_id,
            "granules": _empty_phase("pending"),
            "pipelineLocal": _empty_phase("pending"),
            "specializationMaterials": _empty_phase("pending"),
            "uploadDrive": _empty_phase("pending"),
        }
        write_phase_status(job_id, payload)
        return payload
    payload.setdefault("uploadDrive", _empty_phase("pending"))
    return payload


def write_phase_status(job_id: str, payload: dict) -> dict:
    paths = get_job_paths(job_id)
    paths["state_dir"].mkdir(parents=True, exist_ok=True)
    _write_json_atomic(paths["phase_status_path"], payload)
    return payload


def reset_job_phases_from(job_id: str, restart_from: str) -> dict:
    """Pone en pending la fase `restart_from` y todas las posteriores (p. ej. re-ejecutar gránulos invalida pipeline/materiales/subida)."""
    order = ("granules", "pipelineLocal", "specializationMaterials", "uploadDrive")
    if restart_from not in order:
        raise ValueError(f"restart_from inválido: {restart_from}")
    payload = read_phase_status(job_id)
    idx = order.index(restart_from)
    for key in order[idx:]:
        payload[key] = _empty_phase("pending")
    return write_phase_status(job_id, payload)


def update_phase_status(job_id: str, phase_key: str, *, status: str | None = None, files: list[str] | None = None) -> dict:
    payload = read_phase_status(job_id)
    payload.setdefault(phase_key, _empty_phase("pending"))
    phase = payload[phase_key]
    if status:
        phase["status"] = status
        if status == "running":
            phase["startedAt"] = _utc_now()
            phase["finishedAt"] = None
        if status in {"completed", "failed", "skipped"}:
            phase["finishedAt"] = _utc_now()
    if files is not None:
        phase["files"] = files
    return write_phase_status(job_id, payload)


def refresh_phase_files(job_id: str) -> dict:
    payload = read_phase_status(job_id)
    payload["granules"]["files"] = list_generated_docx(job_id)
    payload["pipelineLocal"]["files"] = list_pipeline_local_relative_files(job_id)
    payload["specializationMaterials"]["files"] = list_material_relative_files(job_id)
    payload["materials"] = payload["specializationMaterials"]
    payload.setdefault("uploadDrive", _empty_phase("pending"))
    return write_phase_status(job_id, payload)


def get_available_next_action(phase_status: dict, job_status: str) -> str:
    phases = [phase_status["granules"], phase_status["pipelineLocal"], phase_status["specializationMaterials"], phase_status.get("uploadDrive", _empty_phase())]
    if job_status == "running" or any(phase["status"] == "running" for phase in phases):
        return "none"
    if any(phase["status"] == "failed" for phase in phases):
        return "retry_current_phase"
    if phase_status["granules"]["status"] != "completed":
        return "generate_granules"
    if phase_status["pipelineLocal"]["status"] != "completed":
        return "generate_pipeline_local"
    if phase_status["specializationMaterials"]["status"] != "completed":
        return "generate_specialization_materials"
    return "download_package"


def get_current_phase(phase_status: dict) -> str:
    if phase_status.get("uploadDrive", {}).get("status") == "running":
        return "uploadDrive"
    if phase_status["specializationMaterials"]["status"] == "running":
        return "specializationMaterials"
    if phase_status["pipelineLocal"]["status"] == "running":
        return "pipelineLocal"
    if phase_status["granules"]["status"] == "running":
        return "granules"
    if phase_status["specializationMaterials"]["status"] == "completed":
        return "completed"
    if phase_status["pipelineLocal"]["status"] == "completed":
        return "pipelineLocal"
    if phase_status["granules"]["status"] == "completed":
        return "granules"
    return "pending"


def create_docs_zip(job_id: str) -> Path:
    paths = get_job_paths(job_id)
    docx_files = sorted(paths["generated_dir"].glob("*.docx"))
    with ZipFile(paths["zip_path"], "w", compression=ZIP_DEFLATED) as zip_file:
        for file_path in docx_files:
            zip_file.write(file_path, arcname=file_path.name)
    return paths["zip_path"]


def create_full_outputs_zip(job_id: str) -> Path:
    paths = get_job_paths(job_id)
    zip_path = paths["content_root"] / "full_outputs.zip"
    package_files = _collect_academic_package_files(paths)

    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zip_file:
        for file_path, arcname in package_files:
            zip_file.write(file_path, arcname=arcname)

    return zip_path


def collect_academic_package_files(job_id: str) -> list[tuple[Path, str]]:
    return _collect_academic_package_files(get_job_paths(job_id))


def _collect_academic_package_files(paths: dict[str, Path]) -> list[tuple[Path, str]]:
    missing: list[str] = []
    package_files: list[tuple[Path, str]] = []
    job_id = paths["job_id"]
    category = get_category(get_job_category(job_id))

    syllabus_path = paths["input_dir"] / "syllabus.docx"
    if syllabus_path.exists() and syllabus_path.is_file():
        package_files.append((syllabus_path, f"{ACADEMIC_PACKAGE_ROOT}/SYLLABUS/syllabus.docx"))
    else:
        missing.append("SYLLABUS/syllabus.docx")

    granules = _find_granule_docx(paths["generated_dir"])
    for index in range(1, 6):
        code = f"G{index}"
        granule_path = granules.get(code)
        if granule_path:
            package_files.append((granule_path, f"{ACADEMIC_PACKAGE_ROOT}/CONTENIDOS/{code}.docx"))
        else:
            missing.append(f"CONTENIDOS/{code}.docx")

    txt_files = _find_pipeline_txt(paths["pipeline_local_dir"])
    for short_name in ("PDA.txt", "QUIZ_1.txt", "QUIZ_2.txt", "QUIZ_3.txt"):
        txt_path = txt_files.get(short_name)
        if txt_path:
            package_files.append((txt_path, f"{ACADEMIC_PACKAGE_ROOT}/ACTIVIDADES_MOODLE/{short_name}"))
        else:
            missing.append(f"ACTIVIDADES_MOODLE/{short_name}")

    academic_docx = _find_pipeline_academic_docx(paths["pipeline_local_dir"])
    for short_name in ("ACA.docx", "FORO.docx", "PRESENTACION.docx"):
        docx_path = academic_docx.get(short_name)
        if docx_path:
            package_files.append((docx_path, f"{ACADEMIC_PACKAGE_ROOT}/ACTIVIDADES_MOODLE/{short_name}"))
        else:
            missing.append(f"ACTIVIDADES_MOODLE/{short_name}")

    materials_dir = get_materials_dir(job_id)
    if category.key == "especializacion":
        material_files = _find_specialization_materials(materials_dir)
        for index in range(1, 6):
            granule_code = f"G{index}"
            for material_number, short_name in MATERIAL_SHORT_NAMES.items():
                material_path = material_files.get((granule_code, material_number))
                if material_path:
                    package_files.append((
                        material_path,
                        f"{ACADEMIC_PACKAGE_ROOT}/RECURSOS_COMPLEMENTARIOS/{granule_code}/{short_name}",
                    ))
                else:
                    missing.append(f"RECURSOS_COMPLEMENTARIOS/{granule_code}/{short_name}")
    else:
        material_paths = sorted(materials_dir.rglob("*.docx"), key=lambda item: str(item.relative_to(materials_dir)).lower()) if materials_dir.exists() else []
        expected_materials = len(category.materials) * category.expected_granules
        if len(material_paths) < expected_materials:
            missing.append(f"RECURSOS_COMPLEMENTARIOS/{category.materials_dir}: {expected_materials - len(material_paths)} materiales")
        for material_path in material_paths:
            relative = material_path.relative_to(materials_dir).as_posix()
            package_files.append((material_path, f"{ACADEMIC_PACKAGE_ROOT}/RECURSOS_COMPLEMENTARIOS/{relative}"))

    if missing:
        message = "No se puede crear el paquete académico completo. Faltan archivos: " + ", ".join(missing)
        LOGGER.warning(message)
        raise AcademicPackageError(message)

    return package_files


def collect_partial_package_files_for_drive_phase(job_id: str, phase: str) -> list[tuple[Path, str]]:
    """Archivos locales existentes para una fase Drive (sin exigir paquete completo)."""
    paths = get_job_paths(job_id)
    phase_norm = (phase or "").strip().lower()
    package_files: list[tuple[Path, str]] = []
    category = get_category(get_job_category(job_id))

    if phase_norm == "syllabus":
        syllabus_path = paths["input_dir"] / "syllabus.docx"
        if syllabus_path.exists() and syllabus_path.is_file():
            package_files.append((syllabus_path, f"{ACADEMIC_PACKAGE_ROOT}/SYLLABUS/syllabus.docx"))
        return package_files

    if phase_norm == "granules":
        granules = _find_granule_docx(paths["generated_dir"])
        for index in range(1, 6):
            code = f"G{index}"
            granule_path = granules.get(code)
            if granule_path:
                package_files.append((granule_path, f"{ACADEMIC_PACKAGE_ROOT}/CONTENIDOS/{code}.docx"))
        return package_files

    if phase_norm == "activities":
        txt_files = _find_pipeline_txt(paths["pipeline_local_dir"])
        for short_name in ("PDA.txt", "QUIZ_1.txt", "QUIZ_2.txt", "QUIZ_3.txt"):
            txt_path = txt_files.get(short_name)
            if txt_path:
                package_files.append((txt_path, f"{ACADEMIC_PACKAGE_ROOT}/ACTIVIDADES_MOODLE/{short_name}"))
        academic_docx = _find_pipeline_academic_docx(paths["pipeline_local_dir"])
        for short_name in ("ACA.docx", "FORO.docx", "PRESENTACION.docx"):
            docx_path = academic_docx.get(short_name)
            if docx_path:
                package_files.append((docx_path, f"{ACADEMIC_PACKAGE_ROOT}/ACTIVIDADES_MOODLE/{short_name}"))
        return package_files

    if phase_norm == "resources":
        materials_dir = get_materials_dir(job_id)
        if category.key == "especializacion":
            material_files = _find_specialization_materials(materials_dir)
            for index in range(1, 6):
                granule_code = f"G{index}"
                for material_number, short_name in MATERIAL_SHORT_NAMES.items():
                    material_path = material_files.get((granule_code, material_number))
                    if material_path:
                        package_files.append((
                            material_path,
                            f"{ACADEMIC_PACKAGE_ROOT}/RECURSOS_COMPLEMENTARIOS/{granule_code}/{short_name}",
                        ))
        else:
            if materials_dir.exists():
                for material_path in sorted(materials_dir.rglob("*.docx"), key=lambda item: str(item.relative_to(materials_dir)).lower()):
                    if not material_path.is_file():
                        continue
                    relative = material_path.relative_to(materials_dir).as_posix()
                    package_files.append((material_path, f"{ACADEMIC_PACKAGE_ROOT}/RECURSOS_COMPLEMENTARIOS/{relative}"))
        return package_files

    return package_files


def _find_granule_docx(generated_dir: Path) -> dict[str, Path]:
    granules: dict[str, Path] = {}
    if not generated_dir.exists():
        return granules
    for docx_file in sorted(generated_dir.glob("*.docx"), key=lambda item: item.name.lower()):
        match = GRANULE_PATTERN.match(docx_file.name)
        if match:
            granules.setdefault(match.group(1).upper(), docx_file)
    return granules


def _find_pipeline_txt(pipeline_dir: Path) -> dict[str, Path]:
    txt_files: dict[str, Path] = {}
    if not pipeline_dir.exists():
        return txt_files
    for txt_file in sorted(pipeline_dir.rglob("*.txt"), key=lambda item: item.name.lower()):
        normalized = re.sub(r"[^A-Z0-9]+", "_", txt_file.stem.upper()).strip("_")
        if normalized == "PDA":
            txt_files.setdefault("PDA.txt", txt_file)
        else:
            quiz_match = re.match(r"QUIZ_?([1-3])$", normalized)
            if quiz_match:
                txt_files.setdefault(f"QUIZ_{quiz_match.group(1)}.txt", txt_file)
    return txt_files


def _find_pipeline_academic_docx(pipeline_dir: Path) -> dict[str, Path]:
    docx_files: dict[str, Path] = {}
    if not pipeline_dir.exists():
        return docx_files
    for docx_file in sorted(pipeline_dir.rglob("*.docx"), key=lambda item: item.name.lower()):
        normalized = re.sub(r"[^A-Z0-9]+", "_", docx_file.stem.upper()).strip("_")
        for prefix, short_name in (("ACA", "ACA.docx"), ("FORO", "FORO.docx"), ("PRESENTACION", "PRESENTACION.docx")):
            if normalized == prefix or normalized.startswith(f"{prefix}_"):
                docx_files.setdefault(short_name, docx_file)
    return docx_files


def _find_specialization_materials(materiales_dir: Path) -> dict[tuple[str, str], Path]:
    materials: dict[tuple[str, str], Path] = {}
    if not materiales_dir.exists():
        return materials
    for docx_file in sorted(materiales_dir.rglob("*.docx"), key=lambda item: str(item.relative_to(materiales_dir)).lower()):
        match = MATERIAL_PATTERN.match(docx_file.name)
        if not match:
            continue
        material_number = match.group(1)
        granule_code = f"G{match.group(2)}"
        materials.setdefault((granule_code, material_number), docx_file)
    return materials


def academic_package_filename(program_name: str | None = None) -> str:
    raw_name = (program_name or "ESPECIALIZACION").strip() or "ESPECIALIZACION"
    normalized = unicodedata.normalize("NFKD", raw_name.upper())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    safe_program = re.sub(r"[^A-Z0-9]+", "_", normalized).strip("_") or "ESPECIALIZACION"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    return f"PAQUETE_ACADEMICO_{safe_program}_{timestamp}.zip"


def create_phase_zip(job_id: str, phase: str) -> Path:
    paths = get_job_paths(job_id)
    zip_path = paths["content_root"] / f"{phase}.zip"

    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zip_file:
        if phase == "granules":
            for docx_file in sorted(paths["generated_dir"].glob("*.docx")):
                zip_file.write(docx_file, arcname=f"generated/{docx_file.name}")
        elif phase == "pipeline_local":
            for output_file in sorted(paths["pipeline_local_dir"].iterdir()) if paths["pipeline_local_dir"].exists() else []:
                if output_file.is_file() and output_file.suffix.lower() in {".docx", ".txt"}:
                    zip_file.write(output_file, arcname=f"pipeline_local/{output_file.name}")
        elif phase in {"materiales_especializacion", "materials"}:
            category = get_category(get_job_category(job_id))
            materials_dir = get_materials_dir(job_id)
            for granule_dir in sorted(materials_dir.iterdir()) if materials_dir.exists() else []:
                if granule_dir.is_dir():
                    for docx_file in sorted(granule_dir.glob("*.docx")):
                        zip_file.write(docx_file, arcname=f"{category.materials_dir}/{granule_dir.name}/{docx_file.name}")
        else:
            raise ValueError(f"Fase no soportada: {phase}")

    return zip_path


def _safe_local_name(name: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", (name or "").strip())
    cleaned = cleaned.replace("..", "_")
    return cleaned or "granule.docx"


def save_local_granules(job_id: str, upload_files) -> list[Path]:
    paths = ensure_job_dirs(job_id)
    saved_paths: list[Path] = []
    for index, upload in enumerate(upload_files, start=1):
        original = upload.filename or f"granule_{index}.docx"
        target_name = _safe_local_name(original)
        if Path(target_name).suffix.lower() not in {".docx", ".pdf"}:
            target_name = f"{Path(target_name).stem}.docx"
        target_path = paths["input_dir"] / target_name
        with target_path.open("wb") as destination:
            shutil.copyfileobj(upload.file, destination)
        saved_paths.append(target_path)
    return saved_paths


def list_generated_files(job_id: str, suffixes: tuple[str, ...] = (".docx", ".txt")) -> list[Path]:
    paths = get_job_paths(job_id)
    generated_dir = paths["generated_dir"]
    if not generated_dir.exists():
        return []
    normalized = tuple(s.lower() for s in suffixes)
    return sorted(
        [path for path in generated_dir.iterdir() if path.is_file() and path.suffix.lower() in normalized],
        key=lambda item: item.name.lower(),
    )


def create_outputs_zip(job_id: str, suffixes: tuple[str, ...] = (".docx", ".txt")) -> Path:
    paths = get_job_paths(job_id)
    files = list_generated_files(job_id, suffixes=suffixes)
    with ZipFile(paths["zip_path"], "w", compression=ZIP_DEFLATED) as zip_file:
        for file_path in files:
            zip_file.write(file_path, arcname=file_path.name)
    return paths["zip_path"]
