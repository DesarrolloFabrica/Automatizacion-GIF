"""
Pipeline local unificado del proyecto Automatizacion-GIF.

Lee 4 o 5 archivos .docx o .pdf desde una carpeta local, genera en una sola
ejecucion los 4 TXT (PDA + QUIZ 1-3) y los 3 DOCX (ACA, PRESENTACION, FORO),
y guarda todo en una carpeta local de salida.

Soporta modo paralelo via PIPELINE_LOCAL_PARALLEL=1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

from automation_engine.generate_guiones import generate_document
from automation_engine.generate_pipeline_drive import infer_metadata_from_files
from automation_engine.generate_txt_from_guiones import (
    DEFAULT_PROMPT_PATH as DEFAULT_TXT_PROMPT_PATH,
    TXT_TASKS,
    build_corpus,
    build_user_prompt as build_user_prompt_txt,
    generate_single_txt,
    output_filename,
    parse_titles,
    save_txt,
)
from automation_engine.generate_documentos_academicos import (
    DEFAULT_PROMPT_PATH as DEFAULT_DOCX_PROMPT_PATH,
    DOCUMENT_TITLES,
    DOCUMENT_TYPES,
    build_output_filename,
    build_user_prompt as build_user_prompt_docx,
    call_openai,
    classify_warnings,
    generate_single_docx,
    read_all_inputs,
    render_docx,
    split_response,
    validate_blocks,
)


LOCAL_GRANULES_MIN = 4
LOCAL_GRANULES_MAX = 5
SUPPORTED_SOURCE_EXTENSIONS = {".docx", ".pdf"}


def is_parallel_mode() -> bool:
    return os.getenv("PIPELINE_LOCAL_PARALLEL", "0") == "1"


def get_pipeline_max_workers(limit: int) -> int:
    raw = os.getenv("PIPELINE_LOCAL_MAX_WORKERS", "4")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 4
    return max(1, min(value, limit))


def _log(msg: str) -> None:
    """Print with immediate flush for real-time UI visibility."""
    print(msg, flush=True)


def _log_pipeline_mode() -> None:
    """Log explicit pipeline mode diagnostics at startup."""
    parallel_val = os.getenv("PIPELINE_LOCAL_PARALLEL", "NOT_SET")
    workers_val = os.getenv("PIPELINE_LOCAL_MAX_WORKERS", "NOT_SET")
    mode = "PARALELO" if is_parallel_mode() else "SECUENCIAL"
    _log(f"[PipelineLocal] PIPELINE_LOCAL_PARALLEL={parallel_val}")
    _log(f"[PipelineLocal] PIPELINE_LOCAL_MAX_WORKERS={workers_val}")
    _log(f"[PipelineLocal] Modo pipelineLocal: {mode}")
    if is_parallel_mode():
        _log("[PipelineLocal] >> Activando ejecucion paralela con ThreadPoolExecutor")
    else:
        _log("[PipelineLocal] >> Ejecucion secuencial (establezca PIPELINE_LOCAL_PARALLEL=1 en .env para activar paralelo)")


def generate_blueprint(output_dir: Path, corpus: str, asignatura: str, programa: str) -> Dict[str, object]:
    plan_evaluacion = {
        "asignatura": asignatura,
        "programa": programa,
        "txt_tasks": {
            "PDA": {"role": "diagnostic", "questions": 10, "sources": "all_5_documents", "cognitive_level": "recordar_comprender"},
            "QUIZ 1": {"role": "fundamentals", "questions": 15, "sources": "documents_1_2", "cognitive_level": "comprender_diferenciar"},
            "QUIZ 2": {"role": "application", "questions": 15, "sources": "documents_3_4", "cognitive_level": "aplicar_analizar"},
            "QUIZ 3": {"role": "critical_thinking", "questions": 15, "sources": "document_5_plus_integration", "cognitive_level": "evaluar_integrar"},
        },
        "docx_tasks": {
            "ACA": {"type": "proyecto_final", "structure": "6_sections", "bibliography_min": 6},
            "PRESENTACION": {"type": "presentacion_asignatura", "structure": "6_sections", "axes": 4},
            "FORO": {"type": "foro_academico", "structure": "4_sections", "interaction_min": 5, "references_min": 3},
        },
        "corpus_preview": corpus[:500] + "..." if len(corpus) > 500 else corpus,
    }
    blueprint_path = output_dir / "plan_evaluacion.json"
    blueprint_path.write_text(json.dumps(plan_evaluacion, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan_evaluacion


def execute_txt_parallel(
    client: OpenAI,
    model: str,
    corpus: str,
    programa: str,
    asignatura: str,
    max_tokens: int,
    temperature: float,
    output_dir: Path,
) -> List[Dict[str, object]]:
    results = []
    max_workers = get_pipeline_max_workers(len(TXT_TASKS))
    task_keys = list(TXT_TASKS.keys())
    _log(f"[PipelineLocal] Lanzando tareas TXT paralelas: {', '.join(task_keys)} (workers={max_workers})")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                generate_single_txt,
                OpenAI(),
                model,
                task_key,
                corpus,
                programa,
                asignatura,
                max_tokens,
                temperature,
                output_dir,
            ): task_key
            for task_key in task_keys
        }
        for task_key in task_keys:
            _log(f"  [{task_key}] iniciado")
        for future in as_completed(futures):
            task_key = futures[future]
            try:
                result = future.result()
                results.append(result)
                status_icon = "OK" if result["status"] == "success" else "ERR"
                _log(f"  [{status_icon}] {task_key}: {result.get('output_file', result.get('error', ''))} ({result['duration_seconds']}s)")
            except Exception as exc:
                _log(f"  [ERR] {task_key}: {exc}")
                results.append({"task": task_key, "status": "error", "error": str(exc), "duration_seconds": 0})
    return results


def execute_docx_parallel(
    client: OpenAI,
    model: str,
    combined_text: str,
    subject: str,
    program: str,
    max_tokens: int,
    temperature: float,
    output_dir: Path,
) -> List[Dict[str, object]]:
    results = []
    max_workers = get_pipeline_max_workers(len(DOCUMENT_TYPES))
    _log(f"\n=== FASE 2: PIPELINE LOCAL TXT/DOCX ===")
    _log(f"Iniciando generacion paralela de {len(DOCUMENT_TYPES)} documentos DOCX...")
    _log(f"[PipelineLocal] Lanzando tareas DOCX paralelas: {', '.join(DOCUMENT_TYPES)} (workers={max_workers})")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                generate_single_docx,
                client,
                model,
                doc_type,
                combined_text,
                subject,
                program,
                max_tokens,
                temperature,
                output_dir,
            ): doc_type
            for doc_type in DOCUMENT_TYPES
        }
        for doc_type in DOCUMENT_TYPES:
            _log(f"  [{doc_type}] iniciado")
        for future in as_completed(futures):
            doc_type = futures[future]
            try:
                result = future.result()
                results.append(result)
                status_icon = "OK" if result["status"] == "success" else "ERR"
                repair_info = ""
                if result.get("repair_attempts", 0) > 0:
                    repair_info = f" [repairs: {result['repair_attempts']}, success: {result.get('repaired_successfully', False)}]"
                critical_count = len(result.get("warnings_critical", []))
                minor_count = len(result.get("warnings_minor", []))
                warning_info = ""
                if critical_count > 0 or minor_count > 0:
                    warning_info = f" [warnings: {critical_count} critical, {minor_count} minor]"
                _log(f"  [{status_icon}] {doc_type}: {result.get('output_file', result.get('error', ''))} ({result['duration_seconds']}s){repair_info}{warning_info}")
            except Exception as exc:
                _log(f"  [ERR] {doc_type}: {exc}")
                results.append({"task": doc_type, "status": "error", "error": str(exc), "duration_seconds": 0})
    return results


def save_metrics(output_dir: Path, txt_results: List[Dict], docx_results: List[Dict], total_duration: float) -> None:
    docx_phase_metrics = {
        "tasks": [],
        "total_duration": round(sum(r.get("duration_seconds", 0) for r in docx_results), 2),
        "total_repair_duration": round(sum(r.get("repair_duration_seconds", 0) for r in docx_results), 2),
        "success_count": sum(1 for r in docx_results if r.get("status") == "success"),
        "error_count": sum(1 for r in docx_results if r.get("status") == "error"),
        "total_warnings": sum(len(r.get("warnings", [])) for r in docx_results),
        "total_critical_warnings": sum(len(r.get("warnings_critical", [])) for r in docx_results),
        "total_minor_warnings": sum(len(r.get("warnings_minor", [])) for r in docx_results),
        "total_repair_attempts": sum(r.get("repair_attempts", 0) for r in docx_results),
        "repaired_successfully_count": sum(1 for r in docx_results if r.get("repaired_successfully")),
    }
    for r in docx_results:
        docx_phase_metrics["tasks"].append({
            "task": r.get("task"),
            "status": r.get("status"),
            "output_file": r.get("output_file", ""),
            "word_count": r.get("word_count", 0),
            "duration_seconds": r.get("duration_seconds", 0),
            "warnings_count": len(r.get("warnings", [])),
            "warnings_critical": r.get("warnings_critical", []),
            "warnings_minor": r.get("warnings_minor", []),
            "repair_attempts": r.get("repair_attempts", 0),
            "repaired_successfully": r.get("repaired_successfully", False),
            "repair_duration_seconds": r.get("repair_duration_seconds", 0),
            "error": r.get("error", ""),
        })

    metrics = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "parallel_mode": is_parallel_mode(),
        "total_duration_seconds": round(total_duration, 2),
        "txt_phase": {
            "tasks": txt_results,
            "total_duration": round(sum(r.get("duration_seconds", 0) for r in txt_results), 2),
            "success_count": sum(1 for r in txt_results if r.get("status") == "success"),
            "error_count": sum(1 for r in txt_results if r.get("status") == "error"),
        },
        "docx_phase": docx_phase_metrics,
    }
    metrics_path = output_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"\nMetricas guardadas en: {metrics_path}")


def collect_local_source_files(input_dir: Path) -> List[Path]:
    if not input_dir.exists() or not input_dir.is_dir():
        raise FileNotFoundError(f"No existe la carpeta de entrada: {input_dir}")
    files = sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SOURCE_EXTENSIONS and not path.name.startswith("~$")
    )
    if not (LOCAL_GRANULES_MIN <= len(files) <= LOCAL_GRANULES_MAX):
        raise ValueError(
            f"Se esperan entre {LOCAL_GRANULES_MIN} y {LOCAL_GRANULES_MAX} archivos .docx o .pdf "
            f"en {input_dir}, se encontraron {len(files)}."
        )
    return files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Pipeline local unificado: toma 4 o 5 .docx o .pdf locales y genera "
            "PDA + QUIZ 1-3 (TXT) y ACA + PRESENTACION + FORO (DOCX)."
        )
    )
    parser.add_argument("--input-dir", required=True, help="Carpeta local con 4 o 5 .docx o .pdf")
    parser.add_argument("--output-dir", required=True, help="Carpeta local donde se guardaran TXT y DOCX")
    parser.add_argument("--asignatura", default="", help="Nombre de la asignatura (si se omite intenta inferir)")
    parser.add_argument("--programa", default="", help="Nombre del programa (si se omite intenta inferir)")
    parser.add_argument("--count", type=int, default=4, help="Cantidad de TXT a generar")
    parser.add_argument(
        "--titles",
        default="",
        help="Titulos de TXT separados por ';'. Default: PDA; QUIZ 1; QUIZ 2; QUIZ 3",
    )
    parser.add_argument("--prompt-txt", default=str(DEFAULT_TXT_PROMPT_PATH), help="Ruta al prompt TXT")
    parser.add_argument("--prompt-docx", default=str(DEFAULT_DOCX_PROMPT_PATH), help="Ruta al prompt DOCX")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4o"), help="Modelo OpenAI")
    parser.add_argument("--max-tokens-txt", type=int, default=3500, help="Maximo de tokens por TXT")
    parser.add_argument("--max-tokens-docx", type=int, default=6000, help="Maximo de tokens fase DOCX")
    parser.add_argument("--temperature-txt", type=float, default=0.45, help="Creatividad fase TXT")
    parser.add_argument("--temperature-docx", type=float, default=0.6, help="Creatividad fase DOCX")
    parser.add_argument("--max-chars-per-file", type=int, default=45000, help="Maximo de caracteres por fuente")
    parser.add_argument("--skip-txt", action="store_true", help="Salta la fase de TXT")
    parser.add_argument("--skip-docx", action="store_true", help="Salta la fase de DOCX")
    parser.add_argument("--dry-run", action="store_true", help="No llama OpenAI, solo valida y muestra manifest")
    return parser.parse_args()


def main() -> None:
    _log("[PipelineLocal] main() iniciado")

    if load_dotenv:
        load_dotenv()
    _log_pipeline_mode()

    args = parse_args()
    _log(f"[PipelineLocal] args recibidos: input-dir={args.input_dir}, output-dir={args.output_dir}")

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    prompt_txt_path = Path(args.prompt_txt)
    prompt_docx_path = Path(args.prompt_docx)

    if not args.skip_txt and not prompt_txt_path.exists():
        raise FileNotFoundError(f"No existe el prompt TXT: {prompt_txt_path}")
    if not args.skip_docx and not prompt_docx_path.exists():
        raise FileNotFoundError(f"No existe el prompt DOCX: {prompt_docx_path}")

    _log(f"[PipelineLocal] input-dir existe: {input_dir.exists()}")
    local_files = collect_local_source_files(input_dir)
    _log(f"[PipelineLocal] cantidad archivos fuente: {len(local_files)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    _log(f"[PipelineLocal] output-dir preparado: {output_dir}")

    _log("[PipelineLocal] leyendo corpus")
    asignatura, programa = infer_metadata_from_files(
        local_files=local_files,
        cli_asignatura=args.asignatura,
        cli_programa=args.programa,
    )
    corpus = build_corpus(local_files, args.max_chars_per_file)
    _log("[PipelineLocal] corpus leido")

    titles = parse_titles(args.titles, args.count)
    manifest: Dict[str, object] = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "sources": [p.name for p in local_files],
        "asignatura": asignatura,
        "programa": programa,
        "titles": titles,
        "skip_txt": args.skip_txt,
        "skip_docx": args.skip_docx,
        "parallel_mode": is_parallel_mode(),
    }
    _log("\nManifest:")
    for key, value in manifest.items():
        _log(f"- {key}: {value}")

    if args.dry_run:
        _log("\nDry-run activo. No se llamo a OpenAI.")
        return

    if OpenAI is None:
        raise RuntimeError("Falta instalar openai. Ejecuta: pip install -r requirements.txt")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Falta OPENAI_API_KEY en variables de entorno o en .env")

    pipeline_start = time.time()
    txt_error = ""
    docx_error = ""
    validation_warnings: List[str] = []
    txt_results: List[Dict[str, object]] = []
    docx_results: List[Dict[str, object]] = []

    if not args.skip_txt:
        _log("\n=== FASE 1: GENERACION DE TXT ===")
        _log("[PipelineLocal] iniciando generacion TXT")
        try:
            if is_parallel_mode():
                _log("Modo PARALELO activado para TXT")
                generate_blueprint(output_dir, corpus, asignatura, programa)
                client = OpenAI()
                txt_results = execute_txt_parallel(
                    client=client,
                    model=args.model,
                    corpus=corpus,
                    programa=programa,
                    asignatura=asignatura,
                    max_tokens=args.max_tokens_txt,
                    temperature=args.temperature_txt,
                    output_dir=output_dir,
                )
            else:
                _log("Modo SECUENCIAL para TXT")
                txt_system_prompt = prompt_txt_path.read_text(encoding="utf-8")
                previous_outputs = ""
                for index, title in enumerate(titles, start=1):
                    _log(f"\nGenerando TXT {index}/{len(titles)}: {title}")
                    result = generate_document(
                        client=OpenAI(),
                        model=args.model,
                        system_prompt=txt_system_prompt,
                        user_prompt=build_user_prompt_txt(
                            corpus=corpus,
                            title=title,
                            index=index,
                            count=args.count,
                            previous_outputs=previous_outputs,
                            programa=programa,
                            asignatura=asignatura,
                        ),
                        max_tokens=args.max_tokens_txt,
                        temperature=args.temperature_txt,
                    )
                    local_output = output_dir / output_filename(title, index)
                    save_txt(result, local_output)
                    previous_outputs = (previous_outputs + "\n\n" + result).strip()
                    _log(f"Guardado: {local_output.name} -> {local_output}")
                    try:
                        from automation_engine.incremental_drive_upload import upload_package_file_if_configured

                        upload_package_file_if_configured(
                            local_output,
                            f"PAQUETE_ACADEMICO/ACTIVIDADES_MOODLE/{local_output.name}",
                        )
                    except Exception as sync_exc:
                        _log(f"Drive incremental: aviso TXT — {sync_exc}")
        except Exception as exc:  # pragma: no cover
            txt_error = str(exc)
            _log(f"\n[PipelineLocal][ERROR] fase TXT: {exc}")
            _log(traceback.format_exc())
    else:
        _log("\nFASE 1 (TXT) saltada por --skip-txt.")

    if not args.skip_docx:
        _log("\n=== FASE 2: GENERACION DE DOCX ===")
        _log("[PipelineLocal] iniciando generacion DOCX")
        try:
            combined_text = read_all_inputs(local_files)
            if is_parallel_mode():
                _log("Modo PARALELO activado para DOCX")
                client = OpenAI()
                docx_results = execute_docx_parallel(
                    client=client,
                    model=args.model,
                    combined_text=combined_text,
                    subject=asignatura,
                    program=programa,
                    max_tokens=args.max_tokens_docx,
                    temperature=args.temperature_docx,
                    output_dir=output_dir,
                )
                for r in docx_results:
                    if r.get("warnings_critical"):
                        validation_warnings.extend(r["warnings_critical"])
                    if r.get("warnings_minor"):
                        validation_warnings.extend(r["warnings_minor"])
            else:
                _log("Modo SECUENCIAL para DOCX")
                docx_system_prompt = prompt_docx_path.read_text(encoding="utf-8")
                docx_user_prompt = build_user_prompt_docx(
                    combined_text=combined_text,
                    subject=asignatura,
                    program=programa,
                )
                _log(f"Llamando al modelo {args.model} para los 3 documentos...")
                response = call_openai(
                    client=OpenAI(),
                    model=args.model,
                    system_prompt=docx_system_prompt,
                    user_prompt=docx_user_prompt,
                    max_tokens=args.max_tokens_docx,
                    temperature=args.temperature_docx,
                )
                blocks = split_response(response)
                all_warnings = validate_blocks(blocks)
                for doc_type in DOCUMENT_TYPES:
                    doc_warnings = [w for w in all_warnings if w.startswith(f"[{doc_type}]")]
                    critical, minor = classify_warnings(doc_type, doc_warnings)
                    if critical:
                        _log(f"  [{doc_type}] validation failed - {len(critical)} critical issues")
                    filename = build_output_filename(doc_type, asignatura, programa)
                    local_path = output_dir / filename
                    title = f"{DOCUMENT_TITLES[doc_type]} - {asignatura.upper()}"
                    render_docx(blocks[doc_type], local_path, title)
                    _log(f"  [OK] {doc_type}: {local_path.name} [warnings: {len(critical)} critical, {len(minor)} minor]")
                    docx_results.append({
                        "task": doc_type,
                        "status": "success",
                        "output_file": filename,
                        "warnings": all_warnings,
                        "warnings_critical": critical,
                        "warnings_minor": minor,
                        "duration_seconds": 0,
                        "word_count": 0,
                        "repair_attempts": 0,
                        "repaired_successfully": False,
                        "repair_duration_seconds": 0,
                        "error": "",
                    })
                    try:
                        from automation_engine.incremental_drive_upload import upload_package_file_if_configured

                        upload_package_file_if_configured(
                            local_path,
                            f"PAQUETE_ACADEMICO/ACTIVIDADES_MOODLE/{local_path.name}",
                        )
                    except Exception as sync_exc:
                        _log(f"Drive incremental: aviso DOCX — {sync_exc}")
        except Exception as exc:  # pragma: no cover
            docx_error = str(exc)
            _log(f"\n[PipelineLocal][ERROR] fase DOCX: {exc}")
            _log(traceback.format_exc())
    else:
        _log("\nFASE 2 (DOCX) saltada por --skip-docx.")

    total_duration = time.time() - pipeline_start

    if is_parallel_mode():
        save_metrics(output_dir, txt_results, docx_results, total_duration)

    _log("\n=== RESUMEN ===")
    generated = sorted([p.name for p in output_dir.glob("*.txt")] + [p.name for p in output_dir.glob("*.docx")])
    for name in generated:
        _log(f"  - {name}")

    if validation_warnings:
        _log("\n=== ADVERTENCIAS DE VALIDACION (DOCX) ===")
        for warning in validation_warnings:
            _log(f"  ! {warning}")
        _log("=== FIN DE ADVERTENCIAS ===")

    if txt_error or docx_error:
        _log("\nGeneracion finalizada con errores.")
        sys.exit(2)

    _log(f"\nGeneracion completa en {round(total_duration, 2)}s.")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        _log(f"[PipelineLocal][ERROR] {error}")
        _log(traceback.format_exc())
        sys.exit(1)
    except Exception as error:
        _log(f"[PipelineLocal][ERROR] Unexpected: {error}")
        _log(traceback.format_exc())
        sys.exit(1)
