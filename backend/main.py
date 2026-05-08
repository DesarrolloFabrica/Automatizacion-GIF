from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from jobs import create_job, get_job, start_job_thread
from schemas import (
    DriveUploadLink,
    JobCreateResponse,
    JobStatusResponse,
    LocalGeneratedFile,
    ScriptsLocalJobCreateResponse,
    ScriptsLocalJobStatusResponse,
    ScriptsJobCreateResponse,
    ScriptsJobStatusResponse,
    SyllabusPreviewResponse,
)
from storage import (
    PROJECT_ROOT,
    create_docs_zip,
    create_outputs_zip,
    ensure_job_dirs,
    get_job_paths,
    list_generated_files,
    save_local_granules,
    save_syllabus_file,
)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from automation_engine.generate_guiones import extract_course_plan  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")


ALLOWED_LEVELS = {"pregrado", "especializacion", "diplomado", "maestria"}

DRIVE_ID_REGEX = re.compile(r"(?:/folders/|id=)([A-Za-z0-9_-]{10,})")

SCRIPTS_PROGRESS_MAP = {
    "autenticando con google drive": "conectando con drive",
    "carpeta drive fuente": "leyendo granulo",
    "descargando fuentes a directorio temporal": "leyendo granulo",
    "[infer]": "validando datos",
    "fase 1: generacion de txt": "generando materiales",
    "fase 2: generacion de docx": "generando materiales",
    "subido:": "subiendo archivos",
    "=== resumen ===": "finalizado",
}

LOCAL_GRANULES_MIN = 4
LOCAL_GRANULES_MAX = 5
LOCAL_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024

SCRIPTS_LOCAL_PROGRESS_MAP = {
    "[infer]": "validando estructura",
    "leyendo granulos locales": "leyendo granulos",
    "=== fase 1: generacion de txt ===": "generando txt",
    "=== fase 2: generacion de docx ===": "generando docx",
    "guardado:": "preparando descargas",
    "=== resumen ===": "finalizado",
}


def extract_drive_folder_id(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Falta el link o ID de Drive")
    match = DRIVE_ID_REGEX.search(value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", value):
        return value
    raise HTTPException(status_code=400, detail="Formato de link/ID de Drive invalido")

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


def detect_media_type(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if lower.endswith(".txt"):
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


def get_upload_size(upload: UploadFile) -> int:
    try:
        upload.file.seek(0, 2)
        size = upload.file.tell()
        upload.file.seek(0)
        return int(size)
    except Exception:
        return 0


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


@app.post("/api/scripts/jobs", response_model=ScriptsJobCreateResponse)
async def create_scripts_job(
    driveFolderInput: str = Form(...),
    asignatura: str = Form(...),
    programa: str = Form(...),
) -> ScriptsJobCreateResponse:
    validate_required_api_key()

    if not (PROJECT_ROOT / "credentials.json").exists():
        raise HTTPException(
            status_code=400,
            detail="Falta credentials.json en la raiz del proyecto.",
        )
    if not (PROJECT_ROOT / "token_drive.json").exists():
        raise HTTPException(
            status_code=400,
            detail=(
                "Falta token_drive.json. Genera el token ejecutando una vez por CLI: "
                "python -m automation_engine.generate_txt_from_drive --drive-folder-id <ID> --dry-run"
            ),
        )

    if not asignatura.strip() or not programa.strip():
        raise HTTPException(status_code=400, detail="Asignatura y programa son obligatorios.")

    folder_id = extract_drive_folder_id(driveFolderInput)

    job_id = uuid.uuid4().hex[:12]
    paths = ensure_job_dirs(job_id)
    create_job(job_id, paths["log_path"], paths["generated_dir"], job_kind="scripts")

    command = [
        sys.executable,
        "-m",
        "automation_engine.generate_pipeline_drive",
        "--drive-folder-id",
        folder_id,
        "--asignatura",
        asignatura.strip(),
        "--programa",
        programa.strip(),
    ]
    start_job_thread(
        job_id=job_id,
        command=command,
        cwd=PROJECT_ROOT,
        env_vars=os.environ.copy(),
        initial_progress_step="conectando con drive",
        progress_map=SCRIPTS_PROGRESS_MAP,
        parse_drive_uploads=True,
        job_kind="scripts",
    )
    return ScriptsJobCreateResponse(jobId=job_id, status="queued")


@app.get("/api/scripts/jobs/{job_id}", response_model=ScriptsJobStatusResponse)
def get_scripts_job_status(job_id: str) -> ScriptsJobStatusResponse:
    job = get_job(job_id)
    if not job or job.job_kind != "scripts":
        raise HTTPException(status_code=404, detail="Job no encontrado.")

    links = [
        DriveUploadLink(name=d["name"], link=d["link"], kind=d["kind"])
        for d in job.drive_links
        if d.get("kind") in ("txt", "docx")
    ]

    return ScriptsJobStatusResponse(
        jobId=job.job_id,
        status=job.status,
        progressStep=job.progress_step,
        logs=job.logs,
        driveLinks=links,
    )


@app.post("/api/scripts/local/jobs", response_model=ScriptsLocalJobCreateResponse)
async def create_scripts_local_job(
    granules: list[UploadFile] = File(...),
    asignatura: str = Form(...),
    programa: str = Form(...),
) -> ScriptsLocalJobCreateResponse:
    validate_required_api_key()

    if not asignatura.strip() or not programa.strip():
        raise HTTPException(status_code=400, detail="Asignatura y programa son obligatorios.")

    if not (LOCAL_GRANULES_MIN <= len(granules) <= LOCAL_GRANULES_MAX):
        if len(granules) < LOCAL_GRANULES_MIN:
            raise HTTPException(
                status_code=400,
                detail=f"Faltan gránulos: sube al menos {LOCAL_GRANULES_MIN} archivos .docx.",
            )
        raise HTTPException(
            status_code=400,
            detail=f"Demasiados gránulos: máximo {LOCAL_GRANULES_MAX} archivos .docx.",
        )

    for granule in granules:
        filename = granule.filename or ""
        validate_docx_filename(filename)
        size = get_upload_size(granule)
        if size > LOCAL_MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"El archivo {filename} supera el límite de 10 MB.",
            )

    job_id = uuid.uuid4().hex[:12]
    paths = ensure_job_dirs(job_id)
    save_local_granules(job_id, granules)
    create_job(job_id, paths["log_path"], paths["generated_dir"], job_kind="scripts_local")

    command = [
        sys.executable,
        "-m",
        "automation_engine.generate_pipeline_local",
        "--input-dir",
        str(paths["input_dir"]),
        "--output-dir",
        str(paths["generated_dir"]),
        "--asignatura",
        asignatura.strip(),
        "--programa",
        programa.strip(),
    ]
    start_job_thread(
        job_id=job_id,
        command=command,
        cwd=PROJECT_ROOT,
        env_vars=os.environ.copy(),
        initial_progress_step="leyendo granulos",
        progress_map=SCRIPTS_LOCAL_PROGRESS_MAP,
        parse_drive_uploads=False,
        job_kind="scripts_local",
        files_listing_fn=lambda j: [p.name for p in list_generated_files(j)],
    )
    return ScriptsLocalJobCreateResponse(jobId=job_id, status="queued")


@app.get("/api/scripts/local/jobs/{job_id}", response_model=ScriptsLocalJobStatusResponse)
def get_scripts_local_job_status(job_id: str) -> ScriptsLocalJobStatusResponse:
    job = get_job(job_id)
    if not job or job.job_kind != "scripts_local":
        raise HTTPException(status_code=404, detail="Job no encontrado.")

    files = []
    for path in list_generated_files(job_id):
        kind = "txt" if path.suffix.lower() == ".txt" else "docx"
        files.append(LocalGeneratedFile(name=path.name, kind=kind, sizeBytes=path.stat().st_size))

    return ScriptsLocalJobStatusResponse(
        jobId=job.job_id,
        status=job.status,
        progressStep=job.progress_step,
        logs=job.logs,
        files=files,
    )


@app.get("/api/scripts/local/jobs/{job_id}/files/{filename}")
def download_scripts_local_file(job_id: str, filename: str) -> FileResponse:
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido.")

    job = get_job(job_id)
    if not job or job.job_kind != "scripts_local":
        raise HTTPException(status_code=404, detail="Job no encontrado.")

    file_path = get_job_paths(job_id)["generated_dir"] / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")

    return FileResponse(path=file_path, filename=filename, media_type=detect_media_type(filename))


@app.get("/api/scripts/local/jobs/{job_id}/download-all")
def download_all_scripts_local_files(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if not job or job.job_kind != "scripts_local":
        raise HTTPException(status_code=404, detail="Job no encontrado.")

    files = list_generated_files(job_id)
    if not files:
        raise HTTPException(status_code=404, detail="No hay archivos para descargar.")

    zip_path = create_outputs_zip(job_id)
    return FileResponse(path=zip_path, filename=f"materiales_local_{job_id}.zip", media_type="application/zip")


@app.get("/api/jobs/{job_id}/download-all")
def download_all_generated_files(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")

    if not job.files:
        raise HTTPException(status_code=404, detail="No hay archivos para descargar.")

    zip_path = create_docs_zip(job_id)
    return FileResponse(path=zip_path, filename=f"granulos_{job_id}.zip", media_type="application/zip")
