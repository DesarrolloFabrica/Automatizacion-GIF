from __future__ import annotations

import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import re
import unicodedata


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from automation_engine.config.categories import get_category  # noqa: E402

JOBS_ROOT = PROJECT_ROOT / "outputs" / "jobs"
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


def get_job_paths(job_id: str) -> dict[str, Path]:
    base_dir = JOBS_ROOT / job_id
    input_dir = base_dir / "input"
    generated_dir = base_dir / "generated"
    pipeline_local_dir = base_dir / "pipeline_local"
    materiales_dir = base_dir / "materiales_especializacion"
    log_path = base_dir / "job.log"
    phase_status_path = base_dir / "phase_status.json"
    metadata_path = base_dir / "job_metadata.json"
    zip_path = base_dir / "generated_docs.zip"
    return {
        "base_dir": base_dir,
        "input_dir": input_dir,
        "generated_dir": generated_dir,
        "pipeline_local_dir": pipeline_local_dir,
        "materiales_dir": materiales_dir,
        "log_path": log_path,
        "phase_status_path": phase_status_path,
        "metadata_path": metadata_path,
        "zip_path": zip_path,
    }


def save_job_metadata(job_id: str, *, category: str) -> dict:
    paths = ensure_job_dirs(job_id)
    payload = {"jobId": job_id, "category": category}
    paths["metadata_path"].write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_job_metadata(job_id: str) -> dict:
    paths = get_job_paths(job_id)
    if not paths["metadata_path"].exists():
        return {"jobId": job_id, "category": "especializacion"}
    return json.loads(paths["metadata_path"].read_text(encoding="utf-8"))


def get_job_category(job_id: str) -> str:
    return str(read_job_metadata(job_id).get("category") or "especializacion")


def get_materials_dir(job_id: str) -> Path:
    paths = get_job_paths(job_id)
    category = get_category(get_job_category(job_id))
    return paths["base_dir"] / category.materials_dir


def ensure_job_dirs(job_id: str) -> dict[str, Path]:
    paths = get_job_paths(job_id)
    paths["input_dir"].mkdir(parents=True, exist_ok=True)
    paths["generated_dir"].mkdir(parents=True, exist_ok=True)
    paths["pipeline_local_dir"].mkdir(parents=True, exist_ok=True)
    return paths


def save_syllabus_file(job_id: str, source_file) -> Path:
    paths = ensure_job_dirs(job_id)
    target_path = paths["input_dir"] / "syllabus.docx"
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
    paths["phase_status_path"].write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_phase_status(job_id: str) -> dict:
    paths = get_job_paths(job_id)
    if not paths["phase_status_path"].exists():
        return init_phase_status(job_id)
    payload = json.loads(paths["phase_status_path"].read_text(encoding="utf-8"))
    payload.setdefault("uploadDrive", _empty_phase("pending"))
    return payload


def write_phase_status(job_id: str, payload: dict) -> dict:
    paths = get_job_paths(job_id)
    paths["base_dir"].mkdir(parents=True, exist_ok=True)
    paths["phase_status_path"].write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


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
    zip_path = paths["base_dir"] / "full_outputs.zip"
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
    job_id = paths["base_dir"].name
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
    zip_path = paths["base_dir"] / f"{phase}.zip"

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
        if not target_name.lower().endswith(".docx"):
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
