from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from jobs import create_job, get_job, start_job_thread
from schemas import JobCreateResponse, JobStatusResponse, SyllabusPreviewResponse
from storage import PROJECT_ROOT, create_docs_zip, ensure_job_dirs, get_job_paths, save_syllabus_file

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from automation_engine.generate_guiones import extract_course_plan  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")


ALLOWED_LEVELS = {"pregrado", "especializacion", "diplomado", "maestria"}

app = FastAPI(title="Automatizacion GIF API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def validate_docx_filename(file_name: str) -> None:
    if not file_name.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="El archivo debe ser .docx")


def validate_required_api_key() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=400, detail="Falta configurar la API key en el .env (OPENAI_API_KEY).")


@app.post("/api/syllabus/preview", response_model=SyllabusPreviewResponse)
async def syllabus_preview(syllabus: UploadFile = File(...)) -> SyllabusPreviewResponse:
    file_name = syllabus.filename or "syllabus.docx"
    validate_docx_filename(file_name)

    preview_id = f"preview_{uuid.uuid4().hex[:10]}"
    saved_path = save_syllabus_file(preview_id, syllabus.file)
    plan = extract_course_plan(saved_path)

    topics = [{"index": index, "title": topic} for index, topic in enumerate(plan.temas, start=1)]

    return SyllabusPreviewResponse(
        fileName=file_name,
        subjectName=plan.asignatura or "",
        detectedTopics=topics,
        totalGranules=len(topics),
    )


@app.post("/api/jobs", response_model=JobCreateResponse)
async def create_generation_job(
    syllabus: UploadFile = File(...),
    nivel: str = Form(...),
) -> JobCreateResponse:
    if nivel not in ALLOWED_LEVELS:
        raise HTTPException(status_code=400, detail="Nivel no válido.")

    file_name = syllabus.filename or ""
    validate_docx_filename(file_name)
    validate_required_api_key()

    job_id = uuid.uuid4().hex[:12]
    paths = ensure_job_dirs(job_id)
    save_syllabus_file(job_id, syllabus.file)

    create_job(job_id=job_id, log_path=paths["log_path"], generated_dir=paths["generated_dir"])

    command = [
        sys.executable,
        "-m",
        "automation_engine.generate_guiones",
        "--syllabus",
        str(paths["input_dir"] / "syllabus.docx"),
        "--nivel",
        nivel,
        "--output-dir",
        str(paths["generated_dir"]),
    ]
    start_job_thread(job_id=job_id, command=command, cwd=PROJECT_ROOT, env_vars=os.environ.copy())

    return JobCreateResponse(jobId=job_id, status="queued")


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str) -> JobStatusResponse:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")

    return JobStatusResponse(
        jobId=job.job_id,
        status=job.status,
        progressStep=job.progress_step,
        logs=job.logs,
        files=job.files,
    )


@app.get("/api/jobs/{job_id}/files/{filename}")
def download_generated_file(job_id: str, filename: str) -> FileResponse:
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido.")

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")

    file_path = get_job_paths(job_id)["generated_dir"] / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")

    return FileResponse(path=file_path, filename=filename, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.get("/api/jobs/{job_id}/download-all")
def download_all_generated_files(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")

    if not job.files:
        raise HTTPException(status_code=404, detail="No hay archivos para descargar.")

    zip_path = create_docs_zip(job_id)
    return FileResponse(path=zip_path, filename=f"granulos_{job_id}.zip", media_type="application/zip")
