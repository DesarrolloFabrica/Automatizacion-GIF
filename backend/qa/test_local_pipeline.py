"""QA Local Pipeline - Prueba automatizada del flujo local principal.

Usa 'Cátedra de Pensamiento Cunista I.docx' como fixture de entrada.
"""
from __future__ import annotations

import os
import sys
import time
import shutil
import uuid
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND = PROJECT_ROOT / "backend"
FIXTURE = PROJECT_ROOT / "Cátedra de Pensamiento Cunista I.docx"
JOBS_ROOT = PROJECT_ROOT / "outputs" / "jobs"

sys.path.insert(0, str(BACKEND))

from storage import (
    ensure_job_dirs, save_syllabus_file, save_local_granules,
    list_generated_docx, list_pipeline_local_files, list_material_files,
    get_job_paths, read_job_metadata, read_phase_status, init_phase_status,
    update_phase_status, refresh_phase_files, get_job_category,
    get_materials_dir, save_granule_source_file,
)
from automation_engine.generate_guiones import parse_syllabus_docx
from automation_engine.config.categories import CATEGORIES, get_category

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"

results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = ""):
    results.append((name, condition, detail))
    icon = PASS if condition else FAIL
    print(f"  {icon} {name}" + (f" — {detail}" if detail and not condition else ""))


def run_subprocess(cmd: list[str], cwd: Path, job_id: str) -> int:
    import subprocess
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env)
    stdout, stderr = proc.communicate()
    return proc.returncode


def cleanup_job(job_id: str):
    job_dir = JOBS_ROOT / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)


def test_preview_syllabus() -> str:
    print("\n[1] Preview / parsing del syllabus")
    if not FIXTURE.exists():
        check("Fixture existe", False, f"No se encontró {FIXTURE}")
        return ""
    check("Fixture existe", True)

    parsed = parse_syllabus_docx(FIXTURE)
    check("Detecta asignatura", bool(parsed.selectedCourse and parsed.selectedCourse.asignatura),
          f"asignatura='{parsed.selectedCourse.asignatura if parsed.selectedCourse else None}'")
    check("Detecta programa", bool(parsed.program or (parsed.selectedCourse and parsed.selectedCourse.programa)),
          f"programa='{parsed.program or (parsed.selectedCourse.programa if parsed.selectedCourse else None)}'")

    topics = parsed.selectedCourse.temas if parsed.selectedCourse else []
    check("Detecta 5 contenidos/gránulos", len(topics) == 5, f"temas detectados: {len(topics)}")

    single_word = [t for t in topics if len(t.strip().split()) == 1]
    check("No se pierden contenidos de una sola palabra", len(single_word) == 0,
          f"contenidos de 1 palabra: {single_word}")

    return parsed.selectedCourse.asignatura if parsed.selectedCourse else ""


def test_generate_granules(subject: str) -> str:
    print("\n[2] Generación de gránulos")
    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_ROOT / job_id

    ensure_job_dirs(job_id)
    save_syllabus_file(job_id, open(FIXTURE, "rb"))
    init_phase_status(job_id)
    update_phase_status(job_id, "granules", status="running")

    paths = get_job_paths(job_id)
    cmd = [
        sys.executable, "-m", "automation_engine.generate_guiones",
        "--syllabus", str(paths["input_dir"] / "syllabus.docx"),
        "--nivel", "especializacion",
        "--output-dir", str(paths["generated_dir"]),
    ]
    rc = run_subprocess(cmd, PROJECT_ROOT, job_id)
    update_phase_status(job_id, "granules", status="completed" if rc == 0 else "failed",
                        files=list_generated_docx(job_id))

    check("Proceso terminó sin error", rc == 0, f"return_code={rc}")

    granules = list_generated_docx(job_id)
    check("Se crearon 5 DOCX", len(granules) == 5, f"archivos: {granules}")

    plan_path = paths["generated_dir"] / "plan_curso.json"
    check("plan_curso.json existe", plan_path.exists())

    meta = read_job_metadata(job_id)
    check("job_metadata.json existe", bool(meta))

    ps = read_phase_status(job_id)
    check("phase_status.json existe", bool(ps))
    check("phaseStatus.granules = completed", ps.get("granules", {}).get("status") == "completed")

    return job_id


def test_pipeline_local(granules_job_id: str):
    print("\n[3] Generación TXT/DOCX desde gránulos")
    job_id = uuid.uuid4().hex[:12]
    paths = get_job_paths(job_id)
    ensure_job_dirs(job_id)

    src_paths = get_job_paths(granules_job_id)
    granule_files = sorted(src_paths["generated_dir"].glob("*.docx"))
    for gf in granule_files:
        shutil.copy(gf, paths["input_dir"] / gf.name)

    init_phase_status(job_id)

    cmd = [
        sys.executable, "-m", "automation_engine.generate_pipeline_local",
        "--input-dir", str(paths["input_dir"]),
        "--output-dir", str(paths["generated_dir"]),
        "--asignatura", "Pensamiento Cunista I",
        "--programa", "Especialización",
    ]
    rc = run_subprocess(cmd, PROJECT_ROOT, job_id)
    update_phase_status(job_id, "pipelineLocal", status="completed" if rc == 0 else "failed",
                        files=[p.name for p in list_pipeline_local_files(job_id)])

    check("Proceso terminó sin error", rc == 0, f"return_code={rc}")

    pipeline_files = list_pipeline_local_files(job_id)
    names = [p.name.upper() for p in pipeline_files]

    check("PDA.txt existe", any("PDA" in n and n.endswith(".TXT") for n in names))
    check("QUIZ1.txt existe", any("QUIZ" in n and "1" in n and n.endswith(".TXT") for n in names))
    check("QUIZ2.txt existe", any("QUIZ" in n and "2" in n and n.endswith(".TXT") for n in names))
    check("QUIZ3.txt existe", any("QUIZ" in n and "3" in n and n.endswith(".TXT") for n in names))
    check("ACA.docx existe", any("ACA" in n and n.endswith(".DOCX") for n in names))
    check("PRESENTACION.docx existe", any("PRESENTACION" in n and n.endswith(".DOCX") for n in names))
    check("FORO.docx existe", any("FORO" in n and n.endswith(".DOCX") for n in names))

    ps = read_phase_status(job_id)
    check("phaseStatus.pipelineLocal = completed", ps.get("pipelineLocal", {}).get("status") == "completed")

    return job_id


def test_materials_by_granule(granules_job_id: str):
    print("\n[4] Materiales por gránulo")
    job_id = uuid.uuid4().hex[:12]
    paths = get_job_paths(job_id)
    ensure_job_dirs(job_id)

    src_paths = get_job_paths(granules_job_id)
    granule_files = sorted(src_paths["generated_dir"].glob("G1*.docx"))
    if not granule_files:
        granule_files = sorted(src_paths["generated_dir"].glob("*.docx"))
    granule_file = granule_files[0] if granule_files else None

    if not granule_file:
        check("Gránulo G1 disponible", False, "No se encontró gránulo G1")
        return job_id

    check("Gránulo G1 disponible", True, granule_file.name)

    category = get_category("especializacion")
    save_job_metadata_local(job_id, category=category.key)
    saved = save_granule_source_file(job_id, open(granule_file, "rb"), granule_file.name)
    init_phase_status(job_id)
    update_phase_status(job_id, "granules", status="completed", files=[saved.name])

    cmd = [
        sys.executable, "-m", "automation_engine.generate_materiales",
        "--input-dir", str(paths["input_dir"]),
        "--output-dir", str(paths["generated_dir"]),
        "--nivel", "especializacion",
    ]
    rc = run_subprocess(cmd, PROJECT_ROOT, job_id)
    update_phase_status(job_id, "specializationMaterials", status="completed" if rc == 0 else "failed",
                        files=[f["relative_path"] for f in list_material_files(job_id)])

    check("Proceso terminó sin error", rc == 0, f"return_code={rc}")

    materials = list_material_files(job_id)
    check("Se crearon materiales", len(materials) > 0, f"materiales: {len(materials)}")

    ps = read_phase_status(job_id)
    check("phaseStatus.specializationMaterials = completed",
          ps.get("specializationMaterials", {}).get("status") == "completed")

    return job_id


def save_job_metadata_local(job_id: str, **kwargs):
    from storage import _write_json_atomic
    state_dir = JOBS_ROOT / job_id
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {"jobId": job_id}
    payload.update(kwargs)
    _write_json_atomic(state_dir / "job_metadata.json", payload)


def test_zip_names(granules_job_id: str):
    print("\n[5] Descargas / ZIP local — nombres seguros para Windows")
    paths = get_job_paths(granules_job_id)
    granules = list_generated_docx(granules_job_id)
    check("Hay gránulos para ZIP", len(granules) > 0)

    from storage import create_local_full_outputs_zip
    try:
        zip_path = create_local_full_outputs_zip(granules_job_id)
        check("ZIP creado", zip_path.exists(), str(zip_path))

        from zipfile import ZipFile
        with ZipFile(zip_path) as zf:
            names = zf.namelist()
            long_names = [n for n in names if len(n) > 100]
            check("Nombres internos < 100 chars", len(long_names) == 0,
                  f"nombres largos: {long_names[:3]}")

            invalid_chars = [n for n in names if any(c in n for c in '<>:"|?*')]
            check("Sin caracteres inválidos Windows", len(invalid_chars) == 0,
                  f"inválidos: {invalid_chars[:3]}")
    except Exception as exc:
        check("ZIP creado", False, str(exc))


def main():
    print("=" * 60)
    print("  QA LOCAL PIPELINE")
    print("=" * 60)
    print("\n  [INFO] QA real con OpenAI desactivado por defecto.")
    print("  Para ejecutar manualmente: RUN_REAL_QA=1 python backend/qa/test_local_pipeline.py")
    print("\n  Pruebas ligeras disponibles:")
    print("    - python -m py_compile backend/main.py")
    print("    - python -m py_compile backend/storage.py")
    print("    - python -m py_compile backend/jobs.py")
    print("    - python -m py_compile backend/schemas.py")
    print("    - npm run build")
    print("\n  [EXIT] QA real desactivado. Sin llamadas a OpenAI.")
    sys.exit(0)


if __name__ == "__main__":
    main()
