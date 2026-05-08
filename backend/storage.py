from __future__ import annotations

import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import re


PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOBS_ROOT = PROJECT_ROOT / "outputs" / "jobs"


def get_job_paths(job_id: str) -> dict[str, Path]:
    base_dir = JOBS_ROOT / job_id
    input_dir = base_dir / "input"
    generated_dir = base_dir / "generated"
    pipeline_local_dir = base_dir / "pipeline_local"
    materiales_dir = base_dir / "materiales_especializacion"
    log_path = base_dir / "job.log"
    zip_path = base_dir / "generated_docs.zip"
    return {
        "base_dir": base_dir,
        "input_dir": input_dir,
        "generated_dir": generated_dir,
        "pipeline_local_dir": pipeline_local_dir,
        "materiales_dir": materiales_dir,
        "log_path": log_path,
        "zip_path": zip_path,
    }


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
    paths = get_job_paths(job_id)
    materiales_dir = paths["materiales_dir"]
    if not materiales_dir.exists():
        return []
    files = []
    for granule_dir in sorted(materiales_dir.iterdir()):
        if granule_dir.is_dir():
            for docx_file in sorted(granule_dir.glob("*.docx")):
                files.append({
                    "granule": granule_dir.name,
                    "name": docx_file.name,
                    "relative_path": f"materiales_especializacion/{granule_dir.name}/{docx_file.name}",
                })
    return files


def list_pipeline_local_files(job_id: str) -> list[Path]:
    paths = get_job_paths(job_id)
    pipeline_dir = paths["pipeline_local_dir"]
    if not pipeline_dir.exists():
        return []
    return sorted(
        [path for path in pipeline_dir.iterdir() if path.is_file() and path.suffix.lower() in {".docx", ".txt"}],
        key=lambda item: item.name.lower(),
    )


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

    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zip_file:
        for docx_file in sorted(paths["generated_dir"].glob("*.docx")):
            zip_file.write(docx_file, arcname=f"generated/{docx_file.name}")

        if paths["pipeline_local_dir"].exists():
            for output_file in sorted(paths["pipeline_local_dir"].iterdir()):
                if output_file.is_file() and output_file.suffix.lower() in {".docx", ".txt"}:
                    zip_file.write(output_file, arcname=f"pipeline_local/{output_file.name}")

        if paths["materiales_dir"].exists():
            for granule_dir in sorted(paths["materiales_dir"].iterdir()):
                if granule_dir.is_dir():
                    for docx_file in sorted(granule_dir.glob("*.docx")):
                        arcname = f"materiales_especializacion/{granule_dir.name}/{docx_file.name}"
                        zip_file.write(docx_file, arcname=arcname)

        for meta_file in ["manifest.json", "summary.json", "errors.json"]:
            meta_path = paths["base_dir"] / meta_file
            if meta_path.exists():
                zip_file.write(meta_path, arcname=meta_file)

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
