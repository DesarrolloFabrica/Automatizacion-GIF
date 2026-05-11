from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from jobs import append_log, create_job, get_job, start_job_thread, terminate_job_subprocess
from schemas import (
    DetectedCourse,
    DrivePackageUploadResponse,
    DriveUploadLink,
    JobCancelResponse,
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
    AcademicPackageError,
    PROJECT_ROOT,
    academic_package_filename,
    cleanup_drive_job_content_root,
    collect_academic_package_files,
    collect_partial_package_files_for_drive_phase,
    create_docs_zip,
    create_full_outputs_zip,
    create_outputs_zip,
    create_phase_zip,
    default_drive_phase_status,
    ensure_job_dirs,
    get_available_next_action,
    get_current_phase,
    get_drive_sync_snapshot,
    get_job_paths,
    get_job_category,
    get_materials_dir,
    init_phase_status,
    list_all_job_files,
    list_generated_docx,
    list_generated_files,
    list_material_files,
    list_pipeline_local_files,
    merge_job_metadata,
    read_job_metadata,
    read_phase_status,
    refresh_phase_files,
    reset_job_phases_from,
    accumulate_drive_counters,
    save_job_metadata,
    save_granule_source_file,
    save_local_granules,
    save_syllabus_file,
    set_drive_phase_record,
    update_phase_status,
)
from drive_service import (  # noqa: E402
    ensure_drive_package_structure,
    get_authenticated_drive_service,
    resolve_academic_workspace_folder_id,
    upload_academic_package_to_drive,
)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from automation_engine.generate_guiones import extract_course_plan, parse_syllabus_docx  # noqa: E402
from automation_engine.config.categories import CATEGORIES, get_category, public_categories_payload, validate_category_prompts  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")


ALLOWED_LEVELS = set(CATEGORIES.keys())

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

GRANULES_PROGRESS_MAP = {
    "plan detectado": "detectando estructura temática",
    "prompt seleccionado": "preparando prompts",
    "nivel seleccionado": "preparando prompts",
    "generando documento": "generando documentos",
    "guardado:": "generando gránulos",
}

ESPECIALIZACION_PROGRESS_MAP = {
    "=== fase 1: generación de gránulos ===": "generando gránulos",
    "=== fase 2: pipeline local txt/docx ===": "generando txt",
    "=== fase 3: materiales de especialización ===": "generando materiales especialización",
    "plan detectado": "detectando estructura temática",
    "prompt seleccionado": "preparando prompts",
    "nivel seleccionado": "preparando prompts",
    "=== fase 1: generacion de txt ===": "generando txt",
    "generando txt": "generando txt",
    "=== fase 2: generacion de docx ===": "generando docx",
    "llamando al modelo": "generando docx",
    "=== fase: generacion de materiales": "generando materiales especialización",
    "generando material:": "generando materiales especialización",
    "material guardado:": "generando materiales especialización",
    "error material": "generando materiales especialización",
    "generando documento": "generando documentos",
    "summary guardado:": "organizando archivos",
    "manifest guardado:": "organizando archivos",
    "errors guardado:": "organizando archivos",
    "=== resumen ===": "finalizado",
    "gránulos procesados:": "finalizado",
    "materiales generados:": "finalizado",
}

ACADEMIC_PACKAGE_PROGRESS_MAP = {
    **ESPECIALIZACION_PROGRESS_MAP,
    "=== fase 3: generacion de materiales": "generando materiales",
    "generando material:": "generando materiales",
    "material guardado:": "generando materiales",
    "error material": "generando materiales",
}


def list_generated_docx_with_materiales(job_id: str) -> list[str]:
    return list_all_job_files(job_id)


def _build_pipeline_local_command(paths: dict[str, Path]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "automation_engine.generate_pipeline_local",
        "--input-dir",
        str(paths["generated_dir"]),
        "--output-dir",
        str(paths["pipeline_local_dir"]),
    ]


def _build_materiales_command(job_id: str, category_key: str, paths: dict[str, Path]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "automation_engine.generate_materiales_categoria",
        "--job-id",
        job_id,
        "--category",
        category_key,
        "--generated-dir",
        str(paths["generated_dir"]),
        "--output-dir",
        str(get_materials_dir(job_id)),
    ]


def _phase_start_callback(phase_key: str):
    def _callback(job_id: str) -> None:
        labels = {
            "granules": "=== FASE 1: GENERACIÓN DE GRÁNULOS ===",
            "pipelineLocal": "=== FASE 2: PIPELINE LOCAL TXT/DOCX ===",
            "specializationMaterials": "=== FASE 3: GENERACIÓN DE MATERIALES ===",
        }
        if phase_key != "granules":
            append_log(job_id, labels[phase_key])
        update_phase_status(job_id, phase_key, status="running")

    return _callback


def run_phased_drive_sync(job_id: str, drive_phase: str) -> None:
    """Sincroniza una fase con Drive si el job tiene drivePhasedSync y carpeta padre."""
    meta = read_job_metadata(job_id)
    if not meta.get("drivePhasedSync") or not meta.get("driveParentFolderId"):
        return
    parent = str(meta.get("driveWorkspaceFolderId") or meta["driveParentFolderId"])
    p = drive_phase.lower().strip()
    log_fn = lambda m: append_log(job_id, m)

    if p == "structure":
        try:
            st = ensure_drive_package_structure(parent_folder_id=parent, log_fn=log_fn)
            merge_job_metadata(
                job_id,
                {
                    "driveWorkspaceFolderId": st.user_folder_id,
                    "driveParentFolderId": st.user_folder_id,
                    "drivePackageFolderId": st.user_folder_id,
                    "drivePackageUrl": st.user_folder_link,
                    "driveRootFolderId": st.user_folder_id,
                },
            )
            accumulate_drive_counters(
                job_id,
                folders_created=st.folders_created,
                folders_reused=st.folders_reused,
            )
            set_drive_phase_record(job_id, "structure", status="completed", error=None)
        except Exception as exc:
            set_drive_phase_record(job_id, "structure", status="failed", error=str(exc))
            append_log(job_id, f"Drive sync (estructura) error: {exc}")
        return

    phase_status_map = {
        "syllabus": "syllabus",
        "granules": "granules",
        "activities": "activities",
        "resources": "resources",
    }
    collect_key = phase_status_map.get(p)
    if not collect_key:
        return

    try:
        files = collect_partial_package_files_for_drive_phase(job_id, collect_key)
        if not files:
            append_log(job_id, f"Drive sync ({p}): sin archivos locales para subir")
            set_drive_phase_record(job_id, collect_key, status="completed", error=None)
            return
        summary = upload_academic_package_to_drive(
            parent_folder_id=parent,
            package_files=files,
            include_zip=None,
            log_fn=log_fn,
            job_id=job_id,
        )
        merge_job_metadata(
            job_id,
            {
                "drivePackageFolderId": summary.root_folder_id,
                "drivePackageUrl": summary.root_folder_link,
                "driveRootFolderId": parent,
            },
        )
        accumulate_drive_counters(
            job_id,
            folders_created=summary.folders_created,
            folders_reused=summary.folders_reused,
            files_uploaded=summary.files_uploaded,
            files_overwritten=summary.files_overwritten,
        )
        set_drive_phase_record(job_id, collect_key, status="completed", error=None)
        if collect_key == "resources" and files:
            cleanup_drive_job_content_root(job_id)
    except Exception as exc:
        set_drive_phase_record(job_id, collect_key, status="failed", error=str(exc))
        append_log(job_id, f"Drive sync ({p}) error: {exc}")


def _phase_complete_callback(phase_key: str, files_fn):
    """Tras terminar la generación local de una fase: sube a Drive y luego marca la fase completada.

    Así los archivos solo aparecen en Drive cuando esa fase ya terminó de generarse (no durante el proceso).
    """

    def _callback(job_id: str, success: bool) -> None:
        refresh_phase_files(job_id)
        if success:
            append_log(job_id, "=== Sincronización con Drive: la subida ocurre solo después de terminar esta fase en local ===")
            if phase_key == "granules":
                run_phased_drive_sync(job_id, "granules")
            elif phase_key == "pipelineLocal":
                run_phased_drive_sync(job_id, "activities")
            elif phase_key == "specializationMaterials":
                run_phased_drive_sync(job_id, "resources")
        update_phase_status(job_id, phase_key, status="completed" if success else "failed", files=files_fn(job_id))

    return _callback


def _ensure_job_exists(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    return job


def _ensure_not_running(job_id: str) -> None:
    job = _ensure_job_exists(job_id)
    phase_status = read_phase_status(job_id)
    phases = [phase_status["granules"], phase_status["pipelineLocal"], phase_status["specializationMaterials"], phase_status.get("uploadDrive", {"status": "pending"})]
    if job.status == "running" or any(phase["status"] == "running" for phase in phases):
        raise HTTPException(status_code=409, detail="Ya hay una fase en ejecución para este job.")


def _ensure_drive_job_metadata(job_id: str, parent_folder_id: str) -> None:
    """Registra carpeta Drive en metadata y fases por defecto si aún no existen."""
    meta = read_job_metadata(job_id)
    raw = parent_folder_id.strip()
    try:
        svc = get_authenticated_drive_service()
        resolved = resolve_academic_workspace_folder_id(svc, raw)
    except Exception:
        resolved = raw
    patch: dict = {
        "driveParentFolderId": resolved,
        "driveWorkspaceFolderId": resolved,
        "drivePhasedSync": True,
    }
    if "drivePhaseStatus" not in meta:
        patch["drivePhaseStatus"] = default_drive_phase_status()
    for key in ("driveFoldersCreated", "driveFoldersReused", "driveFilesUploaded", "driveFilesOverwritten"):
        if key not in meta:
            patch[key] = 0
    merge_job_metadata(job_id, patch)


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


def infer_program_name_for_package(job_id: str) -> str:
    syllabus_path = get_job_paths(job_id)["input_dir"] / "syllabus.docx"
    if not syllabus_path.exists():
        return "ESPECIALIZACION"
    try:
        parsed = parse_syllabus_docx(syllabus_path)
        if parsed.program:
            return parsed.program
        if parsed.selectedCourse and parsed.selectedCourse.programa:
            return parsed.selectedCourse.programa
        course = extract_course_plan(syllabus_path)
        return course.programa or "ESPECIALIZACION"
    except Exception:
        return "ESPECIALIZACION"


app = FastAPI(title="Automatizacion GIF API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/categories")
def list_categories() -> list[dict]:
    return public_categories_payload()


def validate_docx_filename(file_name: str) -> None:
    if not file_name.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="El archivo debe ser .docx")


def validate_required_api_key() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=400, detail="Falta configurar la API key en el .env (OPENAI_API_KEY).")


def _env_for_academic_subprocess(job_id: str) -> dict[str, str]:
    """Expone el job_id a generate_* para subida incremental a Drive (solo si el job usa carpeta Drive por fases)."""
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    meta = read_job_metadata(job_id)
    if meta.get("drivePhasedSync") and meta.get("driveParentFolderId"):
        env["AUTOMATIZACION_GIF_JOB_ID"] = job_id
    return env


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

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        shutil.copyfileobj(syllabus.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        parsed = parse_syllabus_docx(tmp_path)
        courses = parsed.coursesDetected
        plan_tables = extract_course_plan(tmp_path)
        primary_course = parsed.selectedCourse if parsed.selectedCourse else plan_tables
        program_merged = (
            (parsed.program or "").strip()
            or (getattr(primary_course, "programa", None) or "").strip()
            or (getattr(plan_tables, "programa", None) or "").strip()
        )

        print(f"[preview] Programa global detectado: {program_merged}")
        print(f"[preview] Total coursesDetected: {len(courses)}")
        for index, course in enumerate(courses, start=1):
            first_topic = course.temas[0] if course.temas else ""
            print(
                f"[preview] Curso {index}: subject={course.asignatura} | "
                f"semester={course.semestre} | topics_count={len(course.temas)} | first_topic={first_topic}"
            )

        topics = [{"index": index, "title": topic} for index, topic in enumerate(primary_course.temas, start=1)]

        courses_detected = [
            DetectedCourse(
                asignatura=c.asignatura,
                programa=(c.programa or "").strip() or program_merged,
                escuela=c.escuela,
                semestre=c.semestre,
                temas=c.temas,
            )
            for c in courses
        ]

        return SyllabusPreviewResponse(
            fileName=file_name,
            subjectName=primary_course.asignatura or "",
            programName=program_merged,
            detectedTopics=topics,
            totalGranules=len(topics),
            coursesDetected=courses_detected,
            selectedCourse=DetectedCourse(
                asignatura=primary_course.asignatura,
                programa=program_merged,
                escuela=parsed.school or primary_course.escuela,
                semestre=primary_course.semestre,
                temas=primary_course.temas,
            ),
        )
    finally:
        tmp_path.unlink(missing_ok=True)


@app.post("/api/jobs", response_model=JobCreateResponse)
async def create_generation_job(
    syllabus: UploadFile = File(...),
    nivel: str = Form(...),
    driveFolderId: str | None = Form(None),
) -> JobCreateResponse:
    if nivel not in ALLOWED_LEVELS:
        raise HTTPException(status_code=400, detail="Nivel no válido.")
    category = get_category(nivel)
    if not category.enabled_for_package:
        raise HTTPException(status_code=400, detail=category.disabled_reason or f"{category.label} no tiene prompt de materiales configurado.")
    try:
        validate_category_prompts(category)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    file_name = syllabus.filename or ""
    validate_docx_filename(file_name)
    validate_required_api_key()

    job_id = uuid.uuid4().hex[:12]

    drive_parent: str | None = None
    if driveFolderId and str(driveFolderId).strip():
        drive_parent = extract_drive_folder_id(str(driveFolderId).strip())
        try:
            svc = get_authenticated_drive_service()
            drive_parent = resolve_academic_workspace_folder_id(svc, drive_parent)
        except Exception:
            pass

    save_job_metadata(
        job_id,
        category=category.key,
        syllabus_original_name=file_name,
        drive_parent_folder_id=drive_parent,
    )
    paths = ensure_job_dirs(job_id)
    save_syllabus_file(job_id, syllabus.file)

    job_kind = "granules_academic_package"

    create_job(job_id=job_id, log_path=paths["log_path"], generated_dir=paths["generated_dir"], job_kind=job_kind)
    init_phase_status(job_id)

    if drive_parent:
        run_phased_drive_sync(job_id, "structure")
        run_phased_drive_sync(job_id, "syllabus")

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

    progress_map = ACADEMIC_PACKAGE_PROGRESS_MAP
    files_listing_fn = lambda j: list_generated_docx_with_materiales(j)

    start_job_thread(
        job_id=job_id,
        command=command,
        cwd=PROJECT_ROOT,
        env_vars=_env_for_academic_subprocess(job_id),
        initial_progress_step="leyendo syllabus",
        progress_map=progress_map,
        parse_drive_uploads=False,
        job_kind=job_kind,
        files_listing_fn=files_listing_fn,
        on_start=_phase_start_callback("granules"),
        on_complete=_phase_complete_callback("granules", lambda j: list_generated_docx(j)),
    )

    return JobCreateResponse(jobId=job_id, status="queued")


@app.post("/api/jobs/{job_id}/retry-granules", response_model=JobCreateResponse)
def retry_granules_generation(job_id: str) -> JobCreateResponse:
    """Reinicia la Fase 1 (gránulos) en un job existente con syllabus ya guardado; invalida fases posteriores en disco."""
    validate_required_api_key()
    _ensure_not_running(job_id)
    job = _ensure_job_exists(job_id)
    if job.job_kind != "granules_academic_package":
        raise HTTPException(status_code=400, detail="Este endpoint solo aplica para jobs de paquete académico.")

    paths = get_job_paths(job_id)
    syllabus_path = paths["input_dir"] / "syllabus.docx"
    if not syllabus_path.is_file():
        raise HTTPException(status_code=400, detail="No hay syllabus guardado en este job; crea un job nuevo con el archivo.")

    phase_status = read_phase_status(job_id)
    granule_state = phase_status.get("granules", {}).get("status", "pending")
    if granule_state == "running":
        raise HTTPException(status_code=409, detail="La fase de gránulos está en ejecución. Cancela o espera a que termine.")
    if granule_state not in ("failed", "completed"):
        raise HTTPException(
            status_code=400,
            detail=f"Solo se puede reintentar gránulos si la fase falló o ya terminó (estado actual: {granule_state}).",
        )

    reset_job_phases_from(job_id, "granules")
    category_key = get_job_category(job_id)
    category = get_category(category_key)
    if not category.enabled_for_package:
        raise HTTPException(status_code=400, detail=category.disabled_reason or f"{category.label} no tiene prompt de materiales configurado.")

    command = [
        sys.executable,
        "-m",
        "automation_engine.generate_guiones",
        "--syllabus",
        str(paths["input_dir"] / "syllabus.docx"),
        "--nivel",
        category_key,
        "--output-dir",
        str(paths["generated_dir"]),
    ]
    progress_map = ACADEMIC_PACKAGE_PROGRESS_MAP
    files_listing_fn = lambda j: list_generated_docx_with_materiales(j)

    append_log(job_id, "=== REINTENTO: FASE 1 GENERACIÓN DE GRÁNULOS (mismo job) ===")
    start_job_thread(
        job_id=job_id,
        command=command,
        cwd=PROJECT_ROOT,
        env_vars=_env_for_academic_subprocess(job_id),
        initial_progress_step="leyendo syllabus",
        progress_map=progress_map,
        parse_drive_uploads=False,
        job_kind="granules_academic_package",
        files_listing_fn=files_listing_fn,
        on_start=_phase_start_callback("granules"),
        on_complete=_phase_complete_callback("granules", lambda j: list_generated_docx(j)),
    )
    return JobCreateResponse(jobId=job_id, status="queued")


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str) -> JobStatusResponse:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")

    phase_status = refresh_phase_files(job_id) if job.job_kind == "granules_academic_package" else read_phase_status(job_id)
    files = list_all_job_files(job_id) if job.job_kind == "granules_academic_package" else job.files

    drive_sync = get_drive_sync_snapshot(job.job_id) if job.job_kind == "granules_academic_package" else None
    category_key = get_job_category(job.job_id) if job.job_kind == "granules_academic_package" else None

    return JobStatusResponse(
        jobId=job.job_id,
        status=job.status,
        progressStep=job.progress_step,
        logs=job.logs,
        files=files,
        granulesStatus=phase_status["granules"]["status"],
        pipelineLocalStatus=phase_status["pipelineLocal"]["status"],
        specializationMaterialsStatus=phase_status["specializationMaterials"]["status"],
        uploadDriveStatus=phase_status.get("uploadDrive", {"status": "pending"})["status"],
        currentPhase=get_current_phase(phase_status),
        availableNextAction=get_available_next_action(phase_status, job.status),
        phaseStatus=phase_status,
        driveSync=drive_sync,
        categoryKey=category_key,
    )


@app.post("/api/jobs/{job_id}/cancel", response_model=JobCancelResponse)
def cancel_generation_job(job_id: str) -> JobCancelResponse:
    """Intenta detener el subproceso del job. Las fases ya completadas y los archivos en Drive no se borran."""
    validate_required_api_key()
    job = _ensure_job_exists(job_id)
    if job.job_kind != "granules_academic_package":
        raise HTTPException(status_code=400, detail="Este endpoint solo aplica a jobs de paquete académico.")
    terminated = terminate_job_subprocess(job_id)
    append_log(job_id, "=== Cancelación solicitada por el usuario ===")
    msg = (
        "Proceso local detenido. Puedes reanudar más tarde desde la misma carpeta del job si las fases siguen pendientes."
        if terminated
        else "No había proceso activo en este momento (quizá ya había terminado o fallado)."
    )
    return JobCancelResponse(jobId=job_id, processTerminated=terminated, message=msg)


@app.post("/api/jobs/{job_id}/pipeline-local", response_model=JobCreateResponse)
def start_pipeline_local_phase(job_id: str) -> JobCreateResponse:
    validate_required_api_key()
    _ensure_not_running(job_id)
    job = _ensure_job_exists(job_id)
    if job.job_kind != "granules_academic_package":
        raise HTTPException(status_code=400, detail="Este endpoint solo aplica para jobs de paquete académico.")

    paths = get_job_paths(job_id)
    if len(list_generated_docx(job_id)) == 0:
        raise HTTPException(status_code=400, detail="No hay gránulos generados. Ejecuta primero la Fase 1.")

    phase_status = read_phase_status(job_id)
    if phase_status["granules"]["status"] != "completed":
        raise HTTPException(status_code=400, detail="La Fase 1 debe estar completada antes de generar TXT/DOCX académicos.")

    start_job_thread(
        job_id=job_id,
        command=_build_pipeline_local_command(paths),
        cwd=PROJECT_ROOT,
        env_vars=_env_for_academic_subprocess(job_id),
        initial_progress_step="generando txt",
        progress_map=ACADEMIC_PACKAGE_PROGRESS_MAP,
        parse_drive_uploads=False,
        job_kind="academic_package_phase",
        files_listing_fn=lambda j: list_all_job_files(j),
        on_start=_phase_start_callback("pipelineLocal"),
        on_complete=_phase_complete_callback("pipelineLocal", lambda j: [f"pipeline_local/{p.name}" for p in list_pipeline_local_files(j)]),
    )
    return JobCreateResponse(jobId=job_id, status="queued")


@app.post("/api/jobs/{job_id}/retry-pipeline-local", response_model=JobCreateResponse)
def retry_pipeline_local_phase(job_id: str) -> JobCreateResponse:
    """Reinicia la Fase 2 (TXT/DOCX) invalidando materiales y subida posteriores en el estado del job."""
    validate_required_api_key()
    _ensure_not_running(job_id)
    job = _ensure_job_exists(job_id)
    if job.job_kind != "granules_academic_package":
        raise HTTPException(status_code=400, detail="Este endpoint solo aplica para jobs de paquete académico.")

    paths = get_job_paths(job_id)
    if len(list_generated_docx(job_id)) == 0:
        raise HTTPException(status_code=400, detail="No hay gránulos generados. Ejecuta primero la Fase 1.")

    phase_status = read_phase_status(job_id)
    if phase_status["granules"]["status"] != "completed":
        raise HTTPException(status_code=400, detail="La Fase 1 debe estar completada antes de regenerar actividades.")

    pl_status = phase_status.get("pipelineLocal", {}).get("status", "pending")
    if pl_status == "running":
        raise HTTPException(status_code=409, detail="La fase de actividades está en ejecución.")
    if pl_status not in ("failed", "completed"):
        raise HTTPException(
            status_code=400,
            detail=f"Solo se puede reiniciar actividades si la fase falló o ya terminó (estado actual: {pl_status}).",
        )

    reset_job_phases_from(job_id, "pipelineLocal")
    append_log(job_id, "=== REINTENTO: FASE 2 PIPELINE LOCAL (mismo job) ===")
    start_job_thread(
        job_id=job_id,
        command=_build_pipeline_local_command(paths),
        cwd=PROJECT_ROOT,
        env_vars=_env_for_academic_subprocess(job_id),
        initial_progress_step="generando txt",
        progress_map=ACADEMIC_PACKAGE_PROGRESS_MAP,
        parse_drive_uploads=False,
        job_kind="academic_package_phase",
        files_listing_fn=lambda j: list_all_job_files(j),
        on_start=_phase_start_callback("pipelineLocal"),
        on_complete=_phase_complete_callback("pipelineLocal", lambda j: [f"pipeline_local/{p.name}" for p in list_pipeline_local_files(j)]),
    )
    return JobCreateResponse(jobId=job_id, status="queued")


@app.post("/api/jobs/{job_id}/materiales-especializacion", response_model=JobCreateResponse)
def start_materiales_especializacion_phase(job_id: str) -> JobCreateResponse:
    return start_materiales_phase(job_id)


@app.post("/api/jobs/{job_id}/materials", response_model=JobCreateResponse)
def start_materiales_phase(job_id: str) -> JobCreateResponse:
    validate_required_api_key()
    _ensure_not_running(job_id)
    job = _ensure_job_exists(job_id)
    if job.job_kind != "granules_academic_package":
        raise HTTPException(status_code=400, detail="Este endpoint solo aplica para jobs de paquete académico.")
    category_key = get_job_category(job_id)
    category = get_category(category_key)
    if not category.enabled_for_package:
        raise HTTPException(status_code=400, detail=category.disabled_reason or f"{category.label} no tiene prompt de materiales configurado.")

    paths = get_job_paths(job_id)
    if len(list_generated_docx(job_id)) == 0:
        raise HTTPException(status_code=400, detail="No hay gránulos generados. Ejecuta primero la Fase 1.")

    phase_status = read_phase_status(job_id)
    if phase_status["pipelineLocal"]["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"La Fase 2 debe estar completada antes de generar materiales de {category.label}.")

    start_job_thread(
        job_id=job_id,
        command=_build_materiales_command(job_id, category.key, paths),
        cwd=PROJECT_ROOT,
        env_vars=_env_for_academic_subprocess(job_id),
        initial_progress_step="generando materiales",
        progress_map=ACADEMIC_PACKAGE_PROGRESS_MAP,
        parse_drive_uploads=False,
        job_kind="academic_package_phase",
        files_listing_fn=lambda j: list_all_job_files(j),
        on_start=_phase_start_callback("specializationMaterials"),
        on_complete=_phase_complete_callback("specializationMaterials", lambda j: [f["relative_path"] for f in list_material_files(j)]),
    )
    return JobCreateResponse(jobId=job_id, status="queued")


@app.post("/api/jobs/{job_id}/retry-materials", response_model=JobCreateResponse)
def retry_materials_phase_endpoint(job_id: str) -> JobCreateResponse:
    """Reinicia la Fase 3 (materiales) invalidando la subida final en el estado del job."""
    validate_required_api_key()
    _ensure_not_running(job_id)
    job = _ensure_job_exists(job_id)
    if job.job_kind != "granules_academic_package":
        raise HTTPException(status_code=400, detail="Este endpoint solo aplica para jobs de paquete académico.")

    category_key = get_job_category(job_id)
    category = get_category(category_key)
    if not category.enabled_for_package:
        raise HTTPException(status_code=400, detail=category.disabled_reason or f"{category.label} no tiene prompt de materiales configurado.")

    paths = get_job_paths(job_id)
    if len(list_generated_docx(job_id)) == 0:
        raise HTTPException(status_code=400, detail="No hay gránulos generados. Ejecuta primero la Fase 1.")

    phase_status = read_phase_status(job_id)
    if phase_status["pipelineLocal"]["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"La Fase 2 debe estar completada antes de regenerar materiales de {category.label}.")

    mat_status = phase_status.get("specializationMaterials", {}).get("status", "pending")
    if mat_status == "running":
        raise HTTPException(status_code=409, detail="La fase de materiales está en ejecución.")
    if mat_status not in ("failed", "completed"):
        raise HTTPException(
            status_code=400,
            detail=f"Solo se puede reiniciar materiales si la fase falló o ya terminó (estado actual: {mat_status}).",
        )

    reset_job_phases_from(job_id, "specializationMaterials")
    append_log(job_id, "=== REINTENTO: FASE 3 MATERIALES (mismo job) ===")
    start_job_thread(
        job_id=job_id,
        command=_build_materiales_command(job_id, category.key, paths),
        cwd=PROJECT_ROOT,
        env_vars=_env_for_academic_subprocess(job_id),
        initial_progress_step="generando materiales",
        progress_map=ACADEMIC_PACKAGE_PROGRESS_MAP,
        parse_drive_uploads=False,
        job_kind="academic_package_phase",
        files_listing_fn=lambda j: list_all_job_files(j),
        on_start=_phase_start_callback("specializationMaterials"),
        on_complete=_phase_complete_callback("specializationMaterials", lambda j: [f["relative_path"] for f in list_material_files(j)]),
    )
    return JobCreateResponse(jobId=job_id, status="queued")


@app.get("/api/jobs/{job_id}/files/{filename}")
def download_generated_file(job_id: str, filename: str) -> FileResponse:
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido.")

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")

    paths = get_job_paths(job_id)
    file_path = paths["generated_dir"] / filename
    if not file_path.exists() and (paths["pipeline_local_dir"] / filename).exists():
        file_path = paths["pipeline_local_dir"] / filename
    materials_dir = get_materials_dir(job_id)
    if not file_path.exists() and materials_dir.exists():
        matches = [path for path in materials_dir.glob(f"*/{filename}") if path.is_file()]
        if matches:
            file_path = matches[0]
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")

    return FileResponse(path=file_path, filename=filename, media_type=detect_media_type(filename))


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


@app.post("/api/materials/local/jobs", response_model=JobCreateResponse)
async def create_local_materials_job(
    granule: UploadFile = File(...),
    nivel: str = Form(...),
) -> JobCreateResponse:
    validate_required_api_key()
    if nivel not in ALLOWED_LEVELS:
        raise HTTPException(status_code=400, detail="Nivel no válido.")
    category = get_category(nivel)
    if not category.enabled_for_package:
        raise HTTPException(status_code=400, detail=category.disabled_reason or f"{category.label} no tiene prompt de materiales configurado.")
    try:
        validate_category_prompts(category)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    file_name = granule.filename or ""
    validate_docx_filename(file_name)

    job_id = uuid.uuid4().hex[:12]
    paths = ensure_job_dirs(job_id)
    save_job_metadata(job_id, category=category.key, syllabus_original_name=file_name)
    saved_granule = save_granule_source_file(job_id, granule.file, file_name)

    create_job(job_id=job_id, log_path=paths["log_path"], generated_dir=paths["generated_dir"], job_kind="single_granule_materials")
    init_phase_status(job_id)
    update_phase_status(job_id, "granules", status="completed", files=[saved_granule.name])

    start_job_thread(
        job_id=job_id,
        command=_build_materiales_command(job_id, category.key, paths),
        cwd=PROJECT_ROOT,
        env_vars=os.environ.copy(),
        initial_progress_step="generando materiales",
        progress_map=ACADEMIC_PACKAGE_PROGRESS_MAP,
        parse_drive_uploads=False,
        job_kind="single_granule_materials",
        files_listing_fn=lambda j: list_all_job_files(j),
        on_start=_phase_start_callback("specializationMaterials"),
        on_complete=_phase_complete_callback("specializationMaterials", lambda j: [f["relative_path"] for f in list_material_files(j)]),
    )

    return JobCreateResponse(jobId=job_id, status="queued")


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

    available_files = list_all_job_files(job_id) if job.job_kind == "granules_academic_package" else job.files
    if not available_files:
        raise HTTPException(status_code=404, detail="No hay archivos para descargar.")

    if job.job_kind == "granules_academic_package":
        try:
            zip_path = create_full_outputs_zip(job_id)
        except AcademicPackageError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        package_name = academic_package_filename(infer_program_name_for_package(job_id))
        return FileResponse(path=zip_path, filename=package_name, media_type="application/zip")

    zip_path = create_docs_zip(job_id)
    return FileResponse(path=zip_path, filename=f"granulos_{job_id}.zip", media_type="application/zip")


def _drive_upload_response_from_snapshot(job_id: str) -> DrivePackageUploadResponse:
    snap = get_drive_sync_snapshot(job_id)
    return DrivePackageUploadResponse(
        jobId=job_id,
        status="completed",
        folderId=snap.get("drivePackageFolderId") or "",
        folderLink=snap.get("drivePackageUrl") or "",
        filesUploaded=int(snap.get("driveFilesUploaded") or 0),
        filesOverwritten=int(snap.get("driveFilesOverwritten") or 0),
        filesSkipped=0,
        foldersCreated=int(snap.get("driveFoldersCreated") or 0),
        foldersReused=int(snap.get("driveFoldersReused") or 0),
    )


@app.post("/api/jobs/{job_id}/upload-drive", response_model=DrivePackageUploadResponse)
def upload_package_to_drive(
    job_id: str,
    driveFolderId: str = Form(...),
    includeZip: bool = Form(True),
    phase: str = Form("all"),
) -> DrivePackageUploadResponse:
    job = _ensure_job_exists(job_id)
    if job.job_kind != "granules_academic_package":
        raise HTTPException(status_code=400, detail="Este endpoint solo aplica para jobs de paquete académico.")

    parent_folder_id = extract_drive_folder_id(driveFolderId)
    _ensure_drive_job_metadata(job_id, parent_folder_id)

    phase_norm = (phase or "all").strip().lower()
    allowed_partial = {"structure", "syllabus", "granules", "activities", "resources"}
    if phase_norm in allowed_partial:
        _ensure_not_running(job_id)
        append_log(job_id, f"=== Drive: sincronización manual fase={phase_norm} ===")
        sync_map = {
            "structure": "structure",
            "syllabus": "syllabus",
            "granules": "granules",
            "activities": "activities",
            "resources": "resources",
        }
        run_phased_drive_sync(job_id, sync_map[phase_norm])
        return _drive_upload_response_from_snapshot(job_id)

    if phase_norm != "all":
        raise HTTPException(status_code=400, detail=f"Fase Drive inválida: {phase}")

    _ensure_not_running(job_id)
    phase_status = refresh_phase_files(job_id)
    if phase_status["granules"]["status"] != "completed" or phase_status["pipelineLocal"]["status"] != "completed" or phase_status["specializationMaterials"]["status"] != "completed":
        raise HTTPException(status_code=400, detail="El paquete debe estar completo antes de subirlo a Drive (fase=all).")

    update_phase_status(job_id, "uploadDrive", status="running")
    append_log(job_id, "=== FASE 4: SUBIDA A GOOGLE DRIVE (completa) ===")
    try:
        append_log(job_id, f"Drive upload: folder id recibido={parent_folder_id}")
        local_files = list_all_job_files(job_id)
        append_log(job_id, f"Drive upload: archivos locales visibles antes de empaquetar={len(local_files)}")
        for relative_path in local_files[:12]:
            append_log(job_id, f"Drive upload: local disponible {relative_path}")
        if len(local_files) > 12:
            append_log(job_id, f"Drive upload: {len(local_files) - 12} archivos locales adicionales disponibles")
        package_files = collect_academic_package_files(job_id)
        append_log(job_id, f"Drive upload: archivos detectados para paquete={len(package_files)}")
        for local_path, arcname in package_files[:12]:
            append_log(job_id, f"Drive upload: archivo listo {arcname} <- {local_path}")
        if len(package_files) > 12:
            append_log(job_id, f"Drive upload: {len(package_files) - 12} archivos adicionales listos")
        zip_entry = None
        if includeZip:
            zip_path = create_full_outputs_zip(job_id)
            zip_entry = (zip_path, f"PAQUETE_ACADEMICO/{zip_path.name}")
            append_log(job_id, f"Drive upload: ZIP incluido {zip_entry[1]} <- {zip_path}")
        append_log(job_id, "Drive upload: iniciando autenticación y sincronización con Google Drive")
        summary = upload_academic_package_to_drive(
            parent_folder_id=parent_folder_id,
            package_files=package_files,
            include_zip=zip_entry,
            log_fn=lambda message: append_log(job_id, message),
            job_id=job_id,
        )
        merge_job_metadata(
            job_id,
            {
                "drivePackageFolderId": summary.root_folder_id,
                "drivePackageUrl": summary.root_folder_link,
                "driveRootFolderId": parent_folder_id,
            },
        )
        accumulate_drive_counters(
            job_id,
            folders_created=summary.folders_created,
            folders_reused=summary.folders_reused,
            files_uploaded=summary.files_uploaded,
            files_overwritten=summary.files_overwritten,
        )
        files = [item["path"] for item in summary.uploaded_files]
        update_phase_status(job_id, "uploadDrive", status="completed", files=files)
        append_log(job_id, f"Drive folder: {summary.root_folder_link}")
        append_log(job_id, f"Drive upload completado: archivos nuevos={summary.files_uploaded}, sobrescritos={summary.files_overwritten}, carpetas creadas={summary.folders_created}, reutilizadas={summary.folders_reused}")
        set_drive_phase_record(job_id, "structure", status="completed", error=None)
        set_drive_phase_record(job_id, "syllabus", status="completed", error=None)
        set_drive_phase_record(job_id, "granules", status="completed", error=None)
        set_drive_phase_record(job_id, "activities", status="completed", error=None)
        set_drive_phase_record(job_id, "resources", status="completed", error=None)
        cleanup_drive_job_content_root(job_id)
        return DrivePackageUploadResponse(
            jobId=job_id,
            status="completed",
            folderId=summary.root_folder_id,
            folderLink=summary.root_folder_link,
            filesUploaded=summary.files_uploaded,
            filesOverwritten=summary.files_overwritten,
            filesSkipped=summary.files_skipped,
            foldersCreated=summary.folders_created,
            foldersReused=summary.folders_reused,
        )
    except Exception as exc:
        update_phase_status(job_id, "uploadDrive", status="failed", files=[])
        append_log(job_id, f"Error subiendo paquete a Drive: {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}/download/granules")
def download_granules_phase(job_id: str) -> FileResponse:
    _ensure_job_exists(job_id)
    if not list_generated_docx(job_id):
        raise HTTPException(status_code=404, detail="No hay gránulos para descargar.")
    zip_path = create_phase_zip(job_id, "granules")
    return FileResponse(path=zip_path, filename=f"granulos_{job_id}.zip", media_type="application/zip")


@app.get("/api/jobs/{job_id}/download/pipeline-local")
def download_pipeline_local_phase(job_id: str) -> FileResponse:
    _ensure_job_exists(job_id)
    if not list_pipeline_local_files(job_id):
        raise HTTPException(status_code=404, detail="No hay archivos TXT/DOCX académicos para descargar.")
    zip_path = create_phase_zip(job_id, "pipeline_local")
    return FileResponse(path=zip_path, filename=f"pipeline_local_{job_id}.zip", media_type="application/zip")


@app.get("/api/jobs/{job_id}/download/materiales-especializacion")
def download_materiales_especializacion_phase(job_id: str) -> FileResponse:
    return download_materials_phase(job_id)


@app.get("/api/jobs/{job_id}/download/materials")
def download_materials_phase(job_id: str) -> FileResponse:
    _ensure_job_exists(job_id)
    category = get_category(get_job_category(job_id))
    if not list_material_files(job_id):
        raise HTTPException(status_code=404, detail=f"No hay materiales de {category.label} para descargar.")
    zip_path = create_phase_zip(job_id, "materials")
    return FileResponse(path=zip_path, filename=f"{category.materials_dir}_{job_id}.zip", media_type="application/zip")
