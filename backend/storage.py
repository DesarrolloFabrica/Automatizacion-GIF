from __future__ import annotations

import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOBS_ROOT = PROJECT_ROOT / "outputs" / "jobs"


def get_job_paths(job_id: str) -> dict[str, Path]:
    base_dir = JOBS_ROOT / job_id
    input_dir = base_dir / "input"
    generated_dir = base_dir / "generated"
    log_path = base_dir / "job.log"
    zip_path = base_dir / "generated_docs.zip"
    return {
        "base_dir": base_dir,
        "input_dir": input_dir,
        "generated_dir": generated_dir,
        "log_path": log_path,
        "zip_path": zip_path,
    }


def ensure_job_dirs(job_id: str) -> dict[str, Path]:
    paths = get_job_paths(job_id)
    paths["input_dir"].mkdir(parents=True, exist_ok=True)
    paths["generated_dir"].mkdir(parents=True, exist_ok=True)
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


def create_docs_zip(job_id: str) -> Path:
    paths = get_job_paths(job_id)
    docx_files = sorted(paths["generated_dir"].glob("*.docx"))
    with ZipFile(paths["zip_path"], "w", compression=ZIP_DEFLATED) as zip_file:
        for file_path in docx_files:
            zip_file.write(file_path, arcname=file_path.name)
    return paths["zip_path"]
