from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zipfile import ZIP_DEFLATED, ZipFile
import re
import unicodedata

if TYPE_CHECKING:
    from job_store_gcs import GCSFileStore


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from automation_engine.config.categories import CATEGORIES, get_category  # noqa: E402

JOBS_ROOT = Path(os.getenv("AUTOMATIZACION_GIF_JOBS_ROOT") or PROJECT_ROOT / "outputs" / "jobs")
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
    sync_job_state_file_to_gcs(path)


def _read_json_or_none(path: Path) -> dict | None:
    if not path.exists():
        restore_job_state_file_from_gcs(path)
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
    files = []
    if paths["generated_dir"].exists():
        files = sorted(path.name for path in paths["generated_dir"].glob("*.docx"))
    if files:
        return files
    return sorted(Path(path).name for path in list_files_in_gcs(job_id, "generated") if path.lower().endswith(".docx"))


def list_especializacion_files(job_id: str) -> list[dict[str, str]]:
    return list_material_files(job_id)


def list_material_files(job_id: str) -> list[dict[str, str]]:
    paths = get_job_paths(job_id)
    category = get_category(get_job_category(job_id))
    materiales_dir = get_materials_dir(job_id)
    files = []
    if materiales_dir.exists():
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
    if files:
        return files
    for gcs_path in list_files_in_gcs(job_id, "materials"):
        if not gcs_path.lower().endswith(".docx"):
            continue
        relative = Path(gcs_path)
        parts = relative.parts[1:] if relative.parts and relative.parts[0] == "materials" else relative.parts
        if not parts:
            continue
        files.append({
            "granule": parts[0] if len(parts) > 1 else "",
            "name": parts[-1],
            "relative_path": f"{category.materials_dir}/{'/'.join(parts)}",
        })
    return files


def list_especializacion_relative_files(job_id: str) -> list[str]:
    return list_material_relative_files(job_id)


def list_material_relative_files(job_id: str) -> list[str]:
    return [item["relative_path"] for item in list_material_files(job_id)]


def list_pipeline_local_files(job_id: str) -> list[Path]:
    paths = get_job_paths(job_id)
    pipeline_dir = paths["pipeline_local_dir"]
    files = []
    if pipeline_dir.exists():
        files = sorted(
            [path for path in pipeline_dir.iterdir() if path.is_file() and path.suffix.lower() in {".docx", ".txt"}],
            key=lambda item: item.name.lower(),
        )
    if files:
        return files
    return sorted(
        [pipeline_dir / Path(path).name for path in list_files_in_gcs(job_id, "pipeline_local") if Path(path).suffix.lower() in {".docx", ".txt"}],
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
        if status in {"completed", "failed", "skipped", "cancelled"}:
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
    restore_job_content_from_gcs(job_id, ("generated",))
    paths = get_job_paths(job_id)
    docx_files = sorted(paths["generated_dir"].glob("*.docx"))
    with ZipFile(paths["zip_path"], "w", compression=ZIP_DEFLATED) as zip_file:
        for file_path in docx_files:
            zip_file.write(file_path, arcname=file_path.name)
    return paths["zip_path"]


def create_full_outputs_zip(job_id: str) -> Path:
    restore_job_content_from_gcs(job_id)
    paths = get_job_paths(job_id)
    zip_path = paths["content_root"] / "full_outputs.zip"
    package_files = _collect_academic_package_files(paths)

    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zip_file:
        for file_path, arcname in package_files:
            zip_file.write(file_path, arcname=arcname)

    return zip_path


def _unique_zip_name(used: set[str], arcname: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_./-]+", "_", arcname).replace("-", "_")
    folder, name = safe.rsplit("/", 1) if "/" in safe else ("", safe)
    stem = Path(name).stem
    suffix = Path(name).suffix
    candidate = f"{folder}/{stem}{suffix}" if folder else f"{stem}{suffix}"
    counter = 2
    while candidate in used:
        numbered = f"{stem}_{counter}{suffix}"
        candidate = f"{folder}/{numbered}" if folder else numbered
        counter += 1
    used.add(candidate)
    return candidate


def _granule_code_from_name(path: Path, fallback_index: int) -> str:
    match = re.search(r"\bG([1-5])\b|^G([1-5])[_\-. ]", path.stem, re.IGNORECASE)
    if match:
        return f"G{match.group(1) or match.group(2)}".upper()
    return f"G{fallback_index}"


def _short_pipeline_arcname(path: Path, fallback_index: int) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", path.stem.upper()).strip("_")
    granule_match = re.search(r"\bG([1-5])\b", normalized)
    granule = f"G{granule_match.group(1)}" if granule_match else f"G{fallback_index}"
    if "PDA" in normalized:
        kind = "PDA"
    elif "QUIZ" in normalized:
        quiz_match = re.search(r"QUIZ_?([1-3])", normalized)
        kind = f"QUIZ{quiz_match.group(1)}" if quiz_match else "QUIZ"
    elif "PRESENT" in normalized:
        kind = "PRESENTACION"
    elif "FORO" in normalized:
        kind = "FORO"
    elif "ACA" in normalized:
        kind = "ACA"
    else:
        kind = f"ARCHIVO{fallback_index}"
    return f"TXT_DOCX/{granule}_{kind}{path.suffix.lower()}"


def _short_material_arcname(path: Path, fallback_index: int) -> str:
    parts = path.parts
    haystack = "_".join(parts).upper()
    granule_match = re.search(r"\bG([1-5])\b|G([1-5])_", haystack)
    material_match = re.search(r"(?:^|_)(0[2-7])(?:_|\b)", path.name.upper())
    granule = f"G{granule_match.group(1) or granule_match.group(2)}" if granule_match else f"G{fallback_index}"
    material = material_match.group(1) if material_match else f"{fallback_index:02d}"
    return f"Materiales/{granule}_{material}{path.suffix.lower()}"


def create_local_full_outputs_zip(job_id: str) -> Path:
    """ZIP local compatible con Windows: nombres internos cortos, sin tocar archivos originales ni Drive."""
    restore_job_content_from_gcs(job_id)
    paths = get_job_paths(job_id)
    zip_path = paths["content_root"] / "full_outputs_local_safe.zip"
    used: set[str] = set()

    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zip_file:
        syllabus_path = paths["input_dir"] / "syllabus.docx"
        if syllabus_path.is_file():
            zip_file.write(syllabus_path, arcname=_unique_zip_name(used, "Syllabus/syllabus.docx"))

        for index, docx_file in enumerate(sorted(paths["generated_dir"].glob("*.docx"), key=lambda item: item.name.lower()), start=1):
            code = _granule_code_from_name(docx_file, index)
            zip_file.write(docx_file, arcname=_unique_zip_name(used, f"Granulos/{code}.docx"))

        for index, output_file in enumerate(list_pipeline_local_files(job_id), start=1):
            zip_file.write(output_file, arcname=_unique_zip_name(used, _short_pipeline_arcname(output_file, index)))

        materials_dir = get_materials_dir(job_id)
        if materials_dir.exists():
            material_files = sorted(materials_dir.rglob("*.docx"), key=lambda item: str(item.relative_to(materials_dir)).lower())
            for index, material_file in enumerate(material_files, start=1):
                rel = material_file.relative_to(materials_dir)
                zip_file.write(material_file, arcname=_unique_zip_name(used, _short_material_arcname(rel, index)))

    return zip_path


def collect_academic_package_files(job_id: str) -> list[tuple[Path, str]]:
    restore_job_content_from_gcs(job_id)
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
    restore_job_content_from_gcs(job_id)
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
    if phase == "granules":
        restore_job_content_from_gcs(job_id, ("generated",))
    elif phase == "pipeline_local":
        restore_job_content_from_gcs(job_id, ("pipeline_local",))
    elif phase in {"materiales_especializacion", "materials"}:
        restore_job_content_from_gcs(job_id, ("materials",))
    paths = get_job_paths(job_id)
    zip_path = paths["content_root"] / f"{phase}.zip"
    used: set[str] = set()

    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zip_file:
        if phase == "granules":
            for index, docx_file in enumerate(sorted(paths["generated_dir"].glob("*.docx"), key=lambda item: item.name.lower()), start=1):
                code = _granule_code_from_name(docx_file, index)
                zip_file.write(docx_file, arcname=_unique_zip_name(used, f"Granulos/{code}.docx"))
        elif phase == "pipeline_local":
            for index, output_file in enumerate(sorted(paths["pipeline_local_dir"].iterdir(), key=lambda item: item.name.lower()) if paths["pipeline_local_dir"].exists() else [], start=1):
                if output_file.is_file() and output_file.suffix.lower() in {".docx", ".txt"}:
                    zip_file.write(output_file, arcname=_unique_zip_name(used, _short_pipeline_arcname(output_file, index)))
        elif phase in {"materiales_especializacion", "materials"}:
            materials_dir = get_materials_dir(job_id)
            material_files = sorted(materials_dir.rglob("*.docx"), key=lambda item: str(item.relative_to(materials_dir)).lower()) if materials_dir.exists() else []
            for index, docx_file in enumerate(material_files, start=1):
                rel = docx_file.relative_to(materials_dir)
                zip_file.write(docx_file, arcname=_unique_zip_name(used, _short_material_arcname(rel, index)))
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


# ──────────────────────────────────────────────
# GCS Sync helpers (Fase 2: persistencia opcional)
# ──────────────────────────────────────────────

_gcs_store_cache: GCSFileStore | None = None


def _get_gcs_store() -> GCSFileStore:
    global _gcs_store_cache
    if _gcs_store_cache is None:
        from job_store_factory import get_gcs_store
        _gcs_store_cache = get_gcs_store()
    return _gcs_store_cache


def _job_state_gcs_path(path: Path) -> tuple[str, str] | None:
    try:
        relative = path.resolve().relative_to(JOBS_ROOT.resolve())
    except ValueError:
        return None
    if len(relative.parts) < 2:
        return None
    job_id = relative.parts[0]
    state_path = "/".join(("state", *relative.parts[1:]))
    return job_id, state_path


def sync_job_state_file_to_gcs(path: Path) -> str | None:
    """Persist runtime state files (metadata, phase status, logs) in GCS."""
    mapping = _job_state_gcs_path(path)
    if mapping is None or not path.exists() or not path.is_file():
        return None
    gcs = _get_gcs_store()
    if not gcs.is_available:
        return None
    job_id, gcs_path = mapping
    return gcs.upload_file(job_id, path, gcs_path)


def restore_job_state_file_from_gcs(path: Path) -> bool:
    """Restore one runtime state file from GCS if this instance lacks it."""
    mapping = _job_state_gcs_path(path)
    if mapping is None:
        return False
    gcs = _get_gcs_store()
    if not gcs.is_available:
        return False
    job_id, gcs_path = mapping
    return gcs.download_file(job_id, gcs_path, path)


def sync_phase_files_to_gcs(job_id: str, phase_key: str) -> list[str]:
    """Sube archivos de una fase completada a GCS.

    Retorna lista de URLs subidas (vacia si GCS no esta disponible).
    """
    gcs = _get_gcs_store()
    if not gcs.is_available:
        LOGGER.info("GCS sync phase %s: GCS no disponible (GCS_BUCKET no configurado)", phase_key)
        return []

    LOGGER.info("GCS sync phase %s: iniciado para job %s", phase_key, job_id)
    paths = get_job_paths(job_id)
    uploaded = []

    if phase_key == "granules":
        local_dir = paths["generated_dir"]
        gcs_prefix = "generated"
    elif phase_key == "pipelineLocal":
        local_dir = paths["pipeline_local_dir"]
        gcs_prefix = "pipeline_local"
    elif phase_key == "specializationMaterials":
        local_dir = get_materials_dir(job_id)
        gcs_prefix = "materials"
    else:
        LOGGER.warning("GCS sync phase %s: fase no soportada", phase_key)
        return []

    if local_dir is None or not local_dir.exists():
        LOGGER.warning("GCS sync phase %s: directorio local no existe: %s", phase_key, local_dir)
        return []

    LOGGER.info("GCS sync phase %s: directorio local encontrado: %s", phase_key, local_dir)

    uploaded = gcs.upload_directory(job_id, local_dir, gcs_prefix)
    if uploaded:
        LOGGER.info("GCS sync phase %s: %d archivos subidos para job %s", phase_key, len(uploaded), job_id)
    else:
        LOGGER.warning("GCS sync phase %s: no se subieron archivos para job %s", phase_key, job_id)
    return uploaded


def sync_syllabus_to_gcs(job_id: str) -> str | None:
    """Sube el syllabus original a GCS."""
    gcs = _get_gcs_store()
    if not gcs.is_available:
        return None
    paths = get_job_paths(job_id)
    syllabus_path = paths["input_dir"] / "syllabus.docx"
    if not syllabus_path.exists():
        LOGGER.warning("GCS sync syllabus: archivo no existe: %s", syllabus_path)
        return None
    LOGGER.info("GCS sync syllabus: subiendo para job %s", job_id)
    url = gcs.upload_file(job_id, syllabus_path, "input/syllabus.docx")
    if url:
        LOGGER.info("GCS sync syllabus: subido exitosamente para job %s", job_id)
    return url


def sync_zip_to_gcs(job_id: str, zip_path: Path, zip_name: str) -> str | None:
    """Sube un ZIP generado a GCS."""
    gcs = _get_gcs_store()
    if not gcs.is_available:
        return None
    if not zip_path.exists():
        LOGGER.warning("GCS sync zip: archivo no existe: %s", zip_path)
        return None
    LOGGER.info("GCS sync zip: subiendo %s para job %s", zip_name, job_id)
    url = gcs.upload_file(job_id, zip_path, f"zips/{zip_name}")
    if url:
        LOGGER.info("GCS sync zip: subido exitosamente %s para job %s", zip_name, job_id)
    return url


def download_file_from_gcs(job_id: str, gcs_path: str, local_path: Path) -> bool:
    """Descarga un archivo desde GCS a ruta local (fallback para descargas)."""
    gcs = _get_gcs_store()
    if not gcs.is_available:
        return False
    LOGGER.info("GCS download fallback: intentando %s para job %s", gcs_path, job_id)
    result = gcs.download_file(job_id, gcs_path, local_path)
    if result:
        LOGGER.info("GCS download fallback: exitoso %s -> %s", gcs_path, local_path.name)
    else:
        LOGGER.warning("GCS download fallback: fallo %s para job %s", gcs_path, job_id)
    return result


def file_exists_in_gcs(job_id: str, gcs_path: str) -> bool:
    """Verifica si un archivo existe en GCS."""
    gcs = _get_gcs_store()
    return gcs.file_exists(job_id, gcs_path)


def list_files_in_gcs(job_id: str, prefix: str = "") -> list[str]:
    """Lista archivos persistidos en GCS para un job."""
    gcs = _get_gcs_store()
    return gcs.list_files(job_id, prefix)


def _content_local_path_for_gcs(job_id: str, gcs_path: str) -> Path | None:
    paths = get_job_paths(job_id)
    parts = Path(gcs_path).parts
    if not parts:
        return None
    prefix = parts[0]
    rest = Path(*parts[1:]) if len(parts) > 1 else None
    if rest is None:
        return None
    if prefix == "input":
        return paths["input_dir"] / rest
    if prefix == "generated":
        return paths["generated_dir"] / rest
    if prefix == "pipeline_local":
        return paths["pipeline_local_dir"] / rest
    if prefix == "materials":
        return get_materials_dir(job_id) / rest
    return None


def restore_job_content_from_gcs(
    job_id: str,
    prefixes: tuple[str, ...] = ("input", "generated", "pipeline_local", "materials"),
) -> list[Path]:
    """Descarga a /tmp los archivos del job que existan en GCS y falten localmente."""
    restored: list[Path] = []
    gcs = _get_gcs_store()
    if not gcs.is_available:
        return restored
    for prefix in prefixes:
        for gcs_path in gcs.list_files(job_id, prefix):
            local_path = _content_local_path_for_gcs(job_id, gcs_path)
            if local_path is None or local_path.exists():
                continue
            if gcs.download_file(job_id, gcs_path, local_path):
                restored.append(local_path)
    return restored
