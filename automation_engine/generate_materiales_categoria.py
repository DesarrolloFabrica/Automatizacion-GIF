from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import traceback
import concurrent.futures
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Tuple

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from automation_engine.config.categories import CategoryConfig, MaterialDefinition, get_category, validate_category_prompts
from automation_engine.generate_materiales_especializacion import (
    ARTIFACT_PATTERNS,
    MIN_RESPONSE_CHARS,
    build_material_filename,
    clean_ai_response,
    discover_granules,
    extract_docx_text,
    extract_material_prompt,
    extract_system_prompt,
    generate_material_content,
    _parse_markdown_tables,
    resolve_layout_renderer_key,
    save_docx_with_structure,
    validate_material_content,
)
from automation_engine.utils.naming import build_granule_folder_name
from automation_engine.utils.openai_client import get_openai_client, get_openai_model


def _log(msg: str) -> None:
    print(msg, flush=True)


def safe_int_env(name: str, default: int, min_value: int, max_value: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        _log(f"[Materials][WARN] {name} invalido={raw!r}; usando default={default}")
        return default
    if value < min_value or value > max_value:
        clamped = max(min_value, min(value, max_value))
        _log(f"[Materials][WARN] {name} fuera de rango={value}; usando {clamped}")
        return clamped
    return value


MATERIALS_PARALLEL = os.getenv("MATERIALS_PARALLEL", "0") == "1"
MATERIALS_MAX_WORKERS = safe_int_env("MATERIALS_MAX_WORKERS", 4, 1, 8)
MATERIALS_API_RETRIES = safe_int_env("MATERIALS_API_RETRIES", 2, 0, 5)
MATERIALS_REPAIR_ATTEMPTS = safe_int_env("MATERIALS_REPAIR_ATTEMPTS", 1, 0, 3)


def build_material_blueprint(
    category: CategoryConfig,
    materials_to_generate: tuple[MaterialDefinition, ...],
    granules: list[dict],
    prompt_text: str,
    output_base: Path,
    flat_output: bool,
) -> dict:
    system_prompt = extract_system_prompt(prompt_text)
    material_prompts = {}
    for material in materials_to_generate:
        material_prompts[material.nn] = extract_material_prompt(prompt_text, material.seccion_prompt)

    granule_texts = {}
    for granule in granules:
        try:
            granule_texts[granule["code"]] = extract_docx_text(granule["path"])
        except Exception as exc:
            granule_texts[granule["code"]] = None

    tasks = []
    for granule in granules:
        granule_code = granule["code"]
        tema = granule["tema"]
        tema_corto = granule["tema_corto"]
        granule_output_dir = output_base if flat_output else output_base / build_granule_folder_name(granule_code, tema)
        granule_output_dir.mkdir(parents=True, exist_ok=True)

        for material in materials_to_generate:
            material_filename = build_material_filename(
                material.nn, granule_code, material.nombre, tema_corto, category.version, category.extension
            )
            tasks.append({
                "granule_code": granule_code,
                "tema": tema,
                "tema_corto": tema_corto,
                "material_nn": material.nn,
                "material_nombre": material.nombre,
                "material_filename": material_filename,
                "material_output_path": str(granule_output_dir / material_filename),
                "prompt_particular": material_prompts[material.nn],
                "guion_text": granule_texts.get(granule_code),
                "guion_error": granule_texts.get(granule_code) is None,
            })

    return {
        "system_prompt": system_prompt,
        "material_prompts": material_prompts,
        "granule_texts": granule_texts,
        "tasks": tasks,
        "category_key": category.key,
        "category_label": category.label,
        "category_version": category.version,
        "category_extension": category.extension,
    }


def build_material_tasks(blueprint: dict) -> list[dict]:
    return blueprint["tasks"]


def _call_openai_with_retry(client, model, system_prompt, user_prompt, max_tokens, temperature, max_retries=MATERIALS_API_RETRIES):
    import httpx
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=120.0,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            last_exc = exc
            status_code = getattr(exc, "status_code", None)
            if status_code in (429, 500, 502, 503, 504) or isinstance(exc, (httpx.TimeoutException, httpx.RemoteProtocolError, OSError)):
                if attempt < max_retries:
                    backoff = 2 ** (attempt + 1)
                    time.sleep(backoff)
                    continue
            else:
                raise
    raise last_exc


def generate_single_material(
    task: dict,
    blueprint: dict,
    model: str,
    max_tokens: int,
    temperature: float,
    disable_drive_upload: bool,
    debug_dir: Path | None,
) -> dict:
    granule_code = task["granule_code"]
    material_nn = task["material_nn"]
    material_nombre = task["material_nombre"]
    material_filename = task["material_filename"]
    material_output_path = Path(task["material_output_path"])
    tema = task["tema"]

    if task["guion_error"] or not task["guion_text"]:
        return {
            "granule_code": granule_code,
            "material_nn": material_nn,
            "material_nombre": material_nombre,
            "status": "error",
            "error": f"Error leyendo granulo {granule_code}",
            "duration": 0.0,
            "warnings": [],
            "repair_attempts": 0,
        }

    system_prompt = blueprint["system_prompt"]
    prompt_particular = task["prompt_particular"]
    guion_text = task["guion_text"]
    tema_corto = task["tema_corto"]
    category_key = blueprint["category_key"]
    category_label = blueprint["category_label"]
    category_version = blueprint["category_version"]
    category_extension = blueprint["category_extension"]
    layout_nn = resolve_layout_renderer_key(category_key, material_nn, material_nombre)
    client = get_openai_client()

    user_prompt = f"""Quiero generar un material derivado para {category_label.upper()}.

Pego a continuacion el GUION MAESTRO aprobado del tema:

{guion_text}

Datos del material:
- Categoria academica: {category_label}
- Codigo GX: {granule_code}
- Nombre exacto del tema: {tema}
- Nombre corto para archivo: {tema_corto}
- Version: {category_version}
- Material a generar: {material_nombre.replace("_", " ")}
- Formato esperado: DOCX (contenido en tabla)
- Cierre integrado ira en: NO APLICA

Instrucciones especificas para este material:

{prompt_particular}

REGLAS CRITICAS DE SALIDA:
1. NO incluyas la frase "Datos recibidos" ni ninguna frase de confirmacion de instrucciones.
2. NO confirmes que entendiste las instrucciones. Entrega directamente el contenido final.
3. NO uses markdown fences (```text, ```, ```markdown).
4. NO inventes fuentes, terminos, casos, tecnologias ni datos que no esten en el GUION MAESTRO.
5. Si una informacion no esta en el guion maestro, marca como "Informacion faltante" en una tabla.
6. Entrega unicamente el contenido del material solicitado en formato tabla markdown.
7. No generes los demas materiales. Solo este.

REGLAS EDITORIALES MINIMAS:
1. Aunque la estructura tecnica se entregue en tabla markdown para validacion, redacta cada celda con lenguaje editorial profesional.
2. Evita fragmentos frios o telegraficos: usa parrafos naturales, legibles y listos para maquetacion academica.
3. Cada recurso debe sentirse autentico para la categoria {category_label}, no como otra categoria con nombre cambiado.
4. Las referencias, fuentes y conexiones de ruta deben mantenerse claras, pero sin saturar el texto principal.
5. Si el material incluye un bloque llamado "Conceptos clave", no lo resumas como glosario. Desarrollalo como seccion editorial con apertura general y conceptos explicados en profundidad, respetando la extension indicada en el prompt particular.

Genera unicamente el material solicitado.
""".strip()

    start = time.time()
    raw_content = None
    content = None
    val_warnings = []
    repair_attempts = 0
    error_msg = None

    try:
        raw_content = _call_openai_with_retry(client, model, system_prompt, user_prompt, max_tokens, temperature)
        content = clean_ai_response(raw_content)
        if not content or len(content) < MIN_RESPONSE_CHARS:
            raise ValueError(f"Respuesta insuficiente ({len(content)} chars). Minimo: {MIN_RESPONSE_CHARS}.")

        if not layout_nn:
            raise ValueError(
                f"No hay plantilla DOCX definida para categoría {category_key!r} "
                f"material nn={material_nn!r} ({material_nombre})."
            )

        for repair_attempt in range(MATERIALS_REPAIR_ATTEMPTS + 1):
            val_status, val_warnings = validate_material_content(layout_nn, content, category_key, material_nn)
            critical_warnings = [w for w in val_warnings if any(kw in w.lower() for kw in ["incompleto", "insuficiente", "esperaban"])]
            if critical_warnings and repair_attempt < MATERIALS_REPAIR_ATTEMPTS:
                repair_attempts += 1
                repair_temp = min(temperature, 0.3)
                repair_prompt = f"{user_prompt}\n\nADVERTENCIA CRITICA DETECTADA: {'; '.join(critical_warnings)}\n\nRepara el contenido cumpliendo estrictamente los requisitos faltantes."
                raw_content = _call_openai_with_retry(client, model, system_prompt, repair_prompt, max_tokens, repair_temp)
                content = clean_ai_response(raw_content)
            else:
                break

        debug_stats = write_material_debug(debug_dir, granule_code, material_nn, raw_content or "", content)

        save_docx_with_structure(
            content=content,
            output_path=material_output_path,
            material_nombre=material_nombre,
            granule_code=granule_code,
            tema=tema,
            category_key=category_key,
            material_nn=material_nn,
        )
        if not material_output_path.exists() or material_output_path.stat().st_size == 0:
            raise ValueError("El archivo se guardo vacio o no se creo.")

        file_size = material_output_path.stat().st_size
        if not disable_drive_upload:
            try:
                from automation_engine.incremental_drive_upload import upload_material_file_if_configured
                upload_material_file_if_configured(material_output_path)
            except Exception as sync_exc:
                pass

        duration = time.time() - start
        return {
            "granule_code": granule_code,
            "material_nn": material_nn,
            "material_nombre": material_nombre,
            "material_filename": material_filename,
            "status": "ok",
            "validation_status": val_status,
            "warnings": val_warnings,
            "size_bytes": file_size,
            "debug": debug_stats,
            "duration": duration,
            "repair_attempts": repair_attempts,
            "error": None,
        }
    except Exception as exc:
        duration = time.time() - start
        return {
            "granule_code": granule_code,
            "material_nn": material_nn,
            "material_nombre": material_nombre,
            "material_filename": material_filename,
            "status": "error",
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "duration": duration,
            "warnings": val_warnings,
            "repair_attempts": repair_attempts,
        }


def execute_materials_parallel(
    blueprint: dict,
    model: str,
    max_tokens: int,
    temperature: float,
    disable_drive_upload: bool,
    debug_dir: Path | None,
) -> list[dict]:
    tasks = build_material_tasks(blueprint)
    results = []
    mode = "PARALELO" if MATERIALS_PARALLEL else "SECUENCIAL"
    _log(f"[Materials] modo: {mode}")

    if MATERIALS_PARALLEL:
        with concurrent.futures.ThreadPoolExecutor(max_workers=MATERIALS_MAX_WORKERS) as executor:
            future_to_task = {
                executor.submit(
                    generate_single_material,
                    task,
                    blueprint,
                    model,
                    max_tokens,
                    temperature,
                    disable_drive_upload,
                    debug_dir,
                ): task
                for task in tasks
            }
            for future in concurrent.futures.as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    result = future.result()
                    if result["status"] == "ok":
                        _log(f"[Materials][{task['granule_code']}][{task['material_nn']}] completado en {result['duration']:.1f}s {task['material_nombre']}")
                    else:
                        _log(f"[Materials][{task['granule_code']}][{task['material_nn']}] error en {result['duration']:.1f}s {task['material_nombre']}: {result['error']}")
                    results.append(result)
                except Exception as exc:
                    _log(f"[Materials][{task['granule_code']}][{task['material_nn']}] excepcion: {exc}")
                    results.append({
                        "granule_code": task["granule_code"],
                        "material_nn": task["material_nn"],
                        "material_nombre": task["material_nombre"],
                        "material_filename": task["material_filename"],
                        "status": "error",
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                        "duration": 0.0,
                        "warnings": [],
                        "repair_attempts": 0,
                    })
    else:
        for task in tasks:
            _log(f"[Materials][{task['granule_code']}][{task['material_nn']}] iniciado {task['material_nombre']}")
            result = generate_single_material(
                task,
                blueprint,
                model,
                max_tokens,
                temperature,
                disable_drive_upload,
                debug_dir,
            )
            if result["status"] == "ok":
                _log(f"[Materials][{task['granule_code']}][{task['material_nn']}] completado en {result['duration']:.1f}s {task['material_nombre']}")
            else:
                _log(f"[Materials][{task['granule_code']}][{task['material_nn']}] error en {result['duration']:.1f}s {task['material_nombre']}: {result['error']}")
            results.append(result)

    return results


def load_materials_prompt(category: CategoryConfig) -> str:
    if not category.enabled_for_package:
        raise ValueError(category.disabled_reason or f"{category.label} no está habilitada para paquete completo.")
    validate_category_prompts(category)
    assert category.materials_prompt_path is not None
    return category.materials_prompt_path.read_text(encoding="utf-8")


def validate_material_prompts(prompt_text: str, materials: tuple[MaterialDefinition, ...]) -> list[str]:
    missing = []
    for material in materials:
        try:
            extract_material_prompt(prompt_text, material.seccion_prompt)
        except ValueError:
            missing.append(material.seccion_prompt)
    return missing


def parse_material_filter(value: str | None) -> set[str] | None:
    if not value:
        return None
    materials = {part.strip().zfill(2) for part in value.split(",") if part.strip()}
    return materials or None


def filter_materials(materials: Iterable[MaterialDefinition], only_materials: set[str] | None) -> tuple[MaterialDefinition, ...]:
    selected = tuple(material for material in materials if only_materials is None or material.nn in only_materials)
    if only_materials and not selected:
        raise ValueError(f"No hay materiales configurados para el filtro: {', '.join(sorted(only_materials))}")
    return selected


def write_material_debug(
    debug_dir: Path | None,
    granule_code: str,
    material_nn: str,
    raw_content: str,
    cleaned_content: str,
) -> dict:
    tables = _parse_markdown_tables(cleaned_content)
    scene_rows = 0
    for header, rows in tables:
        normalized_header = " | ".join(cell.lower() for cell in header)
        if "escena" in normalized_header:
            scene_rows += len(rows)

    stats = {
        "raw_chars": len(raw_content or ""),
        "cleaned_chars": len(cleaned_content or ""),
        "parsed_tables": len(tables),
        "scene_rows": scene_rows,
    }
    if not debug_dir:
        return stats

    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / f"debug_raw_{granule_code}_{material_nn}.md").write_text(raw_content or "", encoding="utf-8")
    (debug_dir / f"debug_cleaned_{granule_code}_{material_nn}.md").write_text(cleaned_content or "", encoding="utf-8")
    parsed_payload = {
        "stats": stats,
        "tables": [
            {"header": header, "row_count": len(rows), "rows_preview": rows[:3]}
            for header, rows in tables
        ],
    }
    (debug_dir / f"debug_parsed_{granule_code}_{material_nn}.json").write_text(
        json.dumps(parsed_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return stats


def build_user_prompt(
    category: CategoryConfig,
    material: MaterialDefinition,
    prompt_particular: str,
    guion_maestro_text: str,
    granule_code: str,
    tema: str,
    tema_corto: str,
    version: str,
) -> str:
    return f"""Quiero generar un material derivado para {category.label.upper()}.

Pego a continuacion el GUION MAESTRO aprobado del tema:

{guion_maestro_text}

Datos del material:
- Categoria academica: {category.label}
- Codigo GX: {granule_code}
- Nombre exacto del tema: {tema}
- Nombre corto para archivo: {tema_corto}
- Version: {version}
- Material a generar: {material.nombre.replace("_", " ")}
- Formato esperado: DOCX (contenido en tabla)
- Cierre integrado ira en: NO APLICA

Instrucciones especificas para este material:

{prompt_particular}

REGLAS CRITICAS DE SALIDA:
1. NO incluyas la frase "Datos recibidos" ni ninguna frase de confirmacion de instrucciones.
2. NO confirmes que entendiste las instrucciones. Entrega directamente el contenido final.
3. NO uses markdown fences (```text, ```, ```markdown).
4. NO inventes fuentes, terminos, casos, tecnologias ni datos que no esten en el GUION MAESTRO.
5. Si una informacion no esta en el guion maestro, marca como "Informacion faltante" en una tabla.
6. Entrega unicamente el contenido del material solicitado en formato tabla markdown.
7. No generes los demas materiales. Solo este.

REGLAS EDITORIALES MINIMAS:
1. Aunque la estructura tecnica se entregue en tabla markdown para validacion, redacta cada celda con lenguaje editorial profesional.
2. Evita fragmentos frios o telegraficos: usa parrafos naturales, legibles y listos para maquetacion academica.
3. Cada recurso debe sentirse autentico para la categoria {category.label}, no como otra categoria con nombre cambiado.
4. Las referencias, fuentes y conexiones de ruta deben mantenerse claras, pero sin saturar el texto principal.
5. Si el material incluye un bloque llamado "Conceptos clave", no lo resumas como glosario. Desarrollalo como seccion editorial con apertura general y conceptos explicados en profundidad, respetando la extension indicada en el prompt particular.

Genera unicamente el material solicitado.
""".strip()


def generate_all_materiales(
    job_id: str,
    category_key: str,
    generated_dir: Path,
    output_base: Path,
    model: str,
    max_tokens: int,
    temperature: float,
    only_materials: set[str] | None = None,
    flat_output: bool = False,
    disable_drive_upload: bool = False,
    debug_dir: Path | None = None,
) -> dict:
    if not model:
        model = get_openai_model("materials")

    category = get_category(category_key)
    if not category.enabled_for_package:
        raise ValueError(category.disabled_reason or f"{category.label} no tiene prompt de materiales configurado.")

    materials_to_generate = filter_materials(category.materials, only_materials)

    print(f"\n{'=' * 60}")
    print(f"=== FASE 3: GENERACION DE MATERIALES - {category.label.upper()} ===")
    print(f"{'=' * 60}")
    print(f"Job ID: {job_id}")
    print(f"Categoria: {category.key} ({category.label})")
    print(f"Directorio de granulos: {generated_dir}")
    print(f"Directorio de salida: {output_base}")
    print(f"Materiales por granulo: {len(materials_to_generate)}")
    if only_materials:
        print(f"Filtro de materiales activo: {', '.join(material.nn for material in materials_to_generate)}")
    if flat_output:
        print("Salida plana activa: los DOCX se guardaran directamente en el directorio de salida.")
    if debug_dir:
        print(f"Debug de respuestas activo: {debug_dir}")
    if category.reserved_materials:
        reserved = ", ".join(f"{m.nn} - {m.nombre}" for m in category.reserved_materials)
        print(f"Materiales reservados/no generados: {reserved}")
    _log(f"[Materials] modo: {'PARALELO' if MATERIALS_PARALLEL else 'SECUENCIAL'} (workers={MATERIALS_MAX_WORKERS})")
    if disable_drive_upload or MATERIALS_PARALLEL:
        print("Drive incremental desactivado para esta ejecucion.")

    prompt_text = load_materials_prompt(category)
    print(f"\nPrompt cargado: {category.materials_prompt_path}")

    missing_prompts = validate_material_prompts(prompt_text, materials_to_generate)
    if missing_prompts:
        raise ValueError(
            f"Faltan {len(missing_prompts)} bloques de prompt para {category.label}. "
            f"Secciones no encontradas: {', '.join(missing_prompts)}."
        )
    print(f"Validacion de prompts: {len(materials_to_generate)}/{len(materials_to_generate)} bloques encontrados.")

    granules = discover_granules(generated_dir)
    print(f"\nGranulos encontrados: {len(granules)}")
    for granule in granules:
        print(f"  - {granule['code']}: {granule['tema']}")
    if len(granules) != category.expected_granules:
        print(f"ADVERTENCIA: Se encontraron {len(granules)} granulos, se esperaban {category.expected_granules}.")

    blueprint = build_material_blueprint(
        category=category,
        materials_to_generate=materials_to_generate,
        granules=granules,
        prompt_text=prompt_text,
        output_base=output_base,
        flat_output=flat_output,
    )

    blueprint_path = output_base.parent / "materials_blueprint.json"
    blueprint_serializable = {
        "category_key": blueprint["category_key"],
        "category_label": blueprint["category_label"],
        "category_version": blueprint["category_version"],
        "category_extension": blueprint["category_extension"],
        "system_prompt_length": len(blueprint["system_prompt"]),
        "material_prompts_keys": list(blueprint["material_prompts"].keys()),
        "granule_texts_keys": list(blueprint["granule_texts"].keys()),
        "task_count": len(blueprint["tasks"]),
        "tasks": blueprint["tasks"],
    }
    blueprint_path.write_text(json.dumps(blueprint_serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Blueprint guardado: {blueprint_path}")

    effective_disable_drive = disable_drive_upload or MATERIALS_PARALLEL

    task_results = execute_materials_parallel(
        blueprint=blueprint,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        disable_drive_upload=effective_disable_drive,
        debug_dir=debug_dir,
    )

    errors = []
    manifest_entries = []
    summary = {
        "job_id": job_id,
        "category": category.key,
        "category_label": category.label,
        "fecha": datetime.now(timezone.utc).isoformat(),
        "total_granules": len(granules),
        "total_materiales_esperados": len(granules) * len(materials_to_generate),
        "total_materiales_generados": 0,
        "total_errores": 0,
        "total_advertencias": 0,
        "granules": {},
    }

    granule_summary_map = {}
    for result in task_results:
        granule_code = result["granule_code"]
        material_nn = result["material_nn"]
        if granule_code not in granule_summary_map:
            granule_summary_map[granule_code] = {"status": "ok", "materiales": {}}

        if result["status"] == "ok":
            granule_summary_map[granule_code]["materiales"][material_nn] = {
                "nombre": result["material_nombre"],
                "archivo": result["material_filename"],
                "status": "ok",
                "validation_status": result.get("validation_status", "ok"),
                "warnings": result.get("warnings", []),
                "size_bytes": result.get("size_bytes", 0),
                "debug": result.get("debug", {}),
                "duration": result.get("duration", 0.0),
                "repair_attempts": result.get("repair_attempts", 0),
            }
            summary["total_materiales_generados"] += 1
            manifest_entries.append({
                "category": category.key,
                "granule_code": granule_code,
                "granule_topic": result.get("tema", ""),
                "material_number": material_nn,
                "material_name": result["material_nombre"],
                "filename": result["material_filename"],
                "path": next((t["material_output_path"] for t in blueprint["tasks"] if t["granule_code"] == granule_code and t["material_nn"] == material_nn), ""),
                "validation_status": result.get("validation_status", "ok"),
                "warnings": result.get("warnings", []),
                "debug": result.get("debug", {}),
                "duration": result.get("duration", 0.0),
            })
        else:
            error_msg = f"Error material {material_nn} {granule_code} ({result['material_nombre']}): {result['error']}"
            errors.append({
                "granule": granule_code,
                "material": material_nn,
                "nombre": result["material_nombre"],
                "error": result["error"],
                "traceback": result.get("traceback", ""),
            })
            granule_summary_map[granule_code]["materiales"][material_nn] = {
                "nombre": result["material_nombre"],
                "status": "error",
                "error": result["error"],
                "duration": result.get("duration", 0.0),
            }
            summary["total_errores"] += 1

    for granule_code, granule_summary in granule_summary_map.items():
        has_errors = any(m.get("status") == "error" for m in granule_summary["materiales"].values())
        if has_errors:
            granule_summary["status"] = "parcial"
        total_warnings = sum(len(m.get("warnings", [])) for m in granule_summary["materiales"].values())
        summary["total_advertencias"] += total_warnings
        summary["granules"][granule_code] = granule_summary

    durations = [r.get("duration", 0.0) for r in task_results if r.get("duration", 0.0) > 0]
    total_duration = sum(durations)
    avg_duration = total_duration / len(durations) if durations else 0.0
    throughput = len(durations) / total_duration if total_duration > 0 else 0.0
    success_count = sum(1 for r in task_results if r["status"] == "ok")
    error_count = sum(1 for r in task_results if r["status"] == "error")
    total_warnings = sum(len(r.get("warnings", [])) for r in task_results)
    total_repair_attempts = sum(r.get("repair_attempts", 0) for r in task_results)

    materials_phase_metrics = {
        "mode": "parallel" if MATERIALS_PARALLEL else "sequential",
        "max_workers": MATERIALS_MAX_WORKERS if MATERIALS_PARALLEL else 1,
        "total_duration": round(total_duration, 2),
        "avg_duration": round(avg_duration, 2),
        "throughput": round(throughput, 2),
        "success_count": success_count,
        "error_count": error_count,
        "warnings": total_warnings,
        "repair_attempts": total_repair_attempts,
        "per_task": [
            {
                "granule_code": r["granule_code"],
                "material_nn": r["material_nn"],
                "material_nombre": r["material_nombre"],
                "status": r["status"],
                "duration": round(r.get("duration", 0.0), 2),
                "warnings": len(r.get("warnings", [])),
                "repair_attempts": r.get("repair_attempts", 0),
            }
            for r in task_results
        ],
    }

    return {
        "summary": summary,
        "manifest": {
            "job_id": job_id,
            "category": category.key,
            "fecha": datetime.now(timezone.utc).isoformat(),
            "materiales": manifest_entries,
        },
        "errors": errors,
        "materials_phase": materials_phase_metrics,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Genera materiales academicos por categoria derivados de granulos G1-G5.")
    parser.add_argument("--job-id", required=True, help="ID del job")
    parser.add_argument("--category", required=True, help="Categoria academica")
    parser.add_argument("--generated-dir", required=True, help="Directorio con granulos G1-G5")
    parser.add_argument("--output-dir", required=True, help="Directorio base para materiales")
    parser.add_argument("--model", default=None, help="Modelo (fallback: OPENAI_MODEL_MATERIALS > OPENAI_MODEL > gemini-2.5-flash)")
    parser.add_argument("--max-tokens", type=int, default=8000, help="Maximo de tokens por material")
    parser.add_argument("--temperature", type=float, default=0.5, help="Creatividad de generacion")
    parser.add_argument("--materials", "--only-material", dest="materials", help="Filtro de materiales por NN, ejemplo: 03 o 02,03")
    parser.add_argument("--flat-output", action="store_true", help="Guarda los DOCX directamente en output-dir, sin subcarpetas por granulo")
    parser.add_argument("--no-drive-upload", action="store_true", help="Desactiva el hook opcional de subida incremental a Drive")
    parser.add_argument("--debug-dir", help="Directorio para guardar raw, cleaned y tablas parseadas por material")
    return parser.parse_args()


def main() -> None:
    if load_dotenv:
        load_dotenv()
    args = parse_args()
    category = get_category(args.category)
    output_base = Path(args.output_dir)
    output_base.mkdir(parents=True, exist_ok=True)

    result = generate_all_materiales(
        job_id=args.job_id,
        category_key=category.key,
        generated_dir=Path(args.generated_dir),
        output_base=output_base,
        model=args.model,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        only_materials=parse_material_filter(args.materials),
        flat_output=args.flat_output,
        disable_drive_upload=args.no_drive_upload,
        debug_dir=Path(args.debug_dir) if args.debug_dir else None,
    )

    summary_path = output_base.parent / "summary.json"
    summary_path.write_text(json.dumps(result["summary"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSummary guardado: {summary_path}")
    manifest_path = output_base.parent / "manifest.json"
    manifest_path.write_text(json.dumps(result["manifest"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest guardado: {manifest_path}")
    errors_path = output_base.parent / "errors.json"
    errors_path.write_text(json.dumps(result["errors"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Errors guardado: {errors_path}")

    if "materials_phase" in result:
        metrics_path = output_base.parent / "metrics.json"
        metrics_path.write_text(json.dumps(result["materials_phase"], ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Materials phase metrics guardado: {metrics_path}")

    print(f"\n{'=' * 60}")
    print("=== RESUMEN FINAL ===")
    print(f"{'=' * 60}")
    print(f"Job ID: {result['summary']['job_id']}")
    print(f"Categoria: {category.label}")
    print(f"Granulos procesados: {result['summary']['total_granules']}")
    print(f"Materiales generados: {result['summary']['total_materiales_generados']}")
    print(f"Materiales esperados: {result['summary']['total_materiales_esperados']}")
    print(f"Errores: {result['summary']['total_errores']}")
    print(f"Advertencias: {result['summary'].get('total_advertencias', 0)}")
    if result["errors"]:
        print("\n--- Errores detectados ---")
        for err in result["errors"]:
            print(f"  [{err.get('granule', '?')}] Material {err.get('material', '?')} ({err.get('nombre', '?')}): {err.get('error', '?')}")
        print("--- Fin de errores ---")
    else:
        print("\nTodos los materiales se generaron sin errores.")
    print("\nGeneracion completa.")


if __name__ == "__main__":
    main()
