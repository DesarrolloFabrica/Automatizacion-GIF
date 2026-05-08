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
