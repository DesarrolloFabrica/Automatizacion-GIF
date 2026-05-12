from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
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
    if OpenAI is None:
        raise RuntimeError("Falta instalar el paquete openai. Ejecuta: pip install -r requirements.txt")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Falta OPENAI_API_KEY en variables de entorno.")

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
    if disable_drive_upload:
        print("Drive incremental desactivado para esta ejecucion.")
    if debug_dir:
        print(f"Debug de respuestas activo: {debug_dir}")
    if category.reserved_materials:
        reserved = ", ".join(f"{m.nn} - {m.nombre}" for m in category.reserved_materials)
        print(f"Materiales reservados/no generados: {reserved}")

    prompt_text = load_materials_prompt(category)
    print(f"\nPrompt cargado: {category.materials_prompt_path}")
    system_prompt = extract_system_prompt(prompt_text)
    print("System prompt extraido correctamente.")

    missing_prompts = validate_material_prompts(prompt_text, materials_to_generate)
    if missing_prompts:
        raise ValueError(
            f"Faltan {len(missing_prompts)} bloques de prompt para {category.label}. "
            f"Secciones no encontradas: {', '.join(missing_prompts)}."
        )
    print(f"Validacion de prompts: {len(materials_to_generate)}/{len(materials_to_generate)} bloques encontrados.")

    material_prompts = {}
    for material in materials_to_generate:
        prompt_particular = extract_material_prompt(prompt_text, material.seccion_prompt)
        material_prompts[material.nn] = prompt_particular
        print(f"  Material configurado: {material.nn} - {material.nombre}")

    granules = discover_granules(generated_dir)
    print(f"\nGranulos encontrados: {len(granules)}")
    for granule in granules:
        print(f"  - {granule['code']}: {granule['tema']}")
    if len(granules) != category.expected_granules:
        print(f"ADVERTENCIA: Se encontraron {len(granules)} granulos, se esperaban {category.expected_granules}.")

    client = OpenAI()
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

    for granule in granules:
        granule_code = granule["code"]
        tema = granule["tema"]
        tema_corto = granule["tema_corto"]
        granule_path = granule["path"]
        print(f"\n{'-' * 50}")
        print(f"--- Procesando {granule_code}: {tema} ---")
        print(f"{'-' * 50}")

        try:
            guion_text = extract_docx_text(granule_path)
            print(f"  Contenido del granulo leido: {len(guion_text)} caracteres")
        except Exception as exc:
            error_msg = f"Error leyendo {granule_path}: {exc}"
            print(f"  ERROR: {error_msg}")
            errors.append({"granule": granule_code, "error": error_msg})
            summary["granules"][granule_code] = {"status": "error_lectura", "materiales": {}}
            summary["total_errores"] += 1
            continue

        granule_output_dir = output_base if flat_output else output_base / build_granule_folder_name(granule_code, tema)
        granule_output_dir.mkdir(parents=True, exist_ok=True)
        print(f"  Carpeta de salida: {granule_output_dir}")

        granule_summary = {"status": "ok", "materiales": {}}
        granule_errors = []
        granule_warnings_count = 0

        for material in materials_to_generate:
            material_filename = build_material_filename(
                material.nn, granule_code, material.nombre, tema_corto, category.version, category.extension
            )
            material_output_path = granule_output_dir / material_filename
            print(f"  Generando material: {material.nn} {granule_code} {material.nombre}")
            print(f"    Archivo: {material_filename}")

            try:
                user_prompt = build_user_prompt(
                    category=category,
                    material=material,
                    prompt_particular=material_prompts[material.nn],
                    guion_maestro_text=guion_text,
                    granule_code=granule_code,
                    tema=tema,
                    tema_corto=tema_corto,
                    version=category.version,
                )
                raw_content = generate_material_content(
                    client=client,
                    model=model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                content = clean_ai_response(raw_content)
                debug_stats = write_material_debug(debug_dir, granule_code, material.nn, raw_content, content)
                print(
                    "    Debug contenido: "
                    f"raw={debug_stats['raw_chars']} chars, "
                    f"cleaned={debug_stats['cleaned_chars']} chars, "
                    f"tablas={debug_stats['parsed_tables']}, "
                    f"escenas={debug_stats['scene_rows']}"
                )
                if not content or len(content) < MIN_RESPONSE_CHARS:
                    raise ValueError(f"Respuesta insuficiente ({len(content)} chars). Minimo: {MIN_RESPONSE_CHARS}.")

                layout_nn = resolve_layout_renderer_key(category.key, material.nn, material.nombre)
                if not layout_nn:
                    raise ValueError(
                        f"No hay plantilla DOCX definida para categoría {category.key!r} "
                        f"material nn={material.nn!r} ({material.nombre})."
                    )
                val_status, val_warnings = validate_material_content(layout_nn, content)
                if val_warnings:
                    for warning in val_warnings:
                        print(f"    ADVERTENCIA: {warning}")
                    granule_warnings_count += len(val_warnings)

                save_docx_with_structure(
                    content=content,
                    output_path=material_output_path,
                    material_nombre=material.nombre,
                    granule_code=granule_code,
                    tema=tema,
                    category_key=category.key,
                    material_nn=material.nn,
                )
                if not material_output_path.exists() or material_output_path.stat().st_size == 0:
                    raise ValueError("El archivo se guardo vacio o no se creo.")

                file_size = material_output_path.stat().st_size
                print(f"    DOCX final: {file_size} bytes")
                print(f"    Material guardado: {material_filename} ({file_size} bytes)")
                if not disable_drive_upload:
                    try:
                        from automation_engine.incremental_drive_upload import upload_material_file_if_configured

                        upload_material_file_if_configured(material_output_path)
                    except Exception as sync_exc:
                        print(f"    Drive incremental: aviso — {sync_exc}")
                granule_summary["materiales"][material.nn] = {
                    "nombre": material.nombre,
                    "archivo": material_filename,
                    "status": "ok",
                    "validation_status": val_status,
                    "warnings": val_warnings,
                    "size_bytes": file_size,
                    "debug": debug_stats,
                }
                summary["total_materiales_generados"] += 1
                manifest_entries.append({
                    "category": category.key,
                    "granule_code": granule_code,
                    "granule_topic": tema,
                    "material_number": material.nn,
                    "material_name": material.nombre,
                    "filename": material_filename,
                    "path": str(material_output_path),
                    "validation_status": val_status,
                    "warnings": val_warnings,
                    "debug": debug_stats,
                })
            except Exception as exc:
                error_msg = f"Error material {material.nn} {granule_code} ({material.nombre}): {exc}"
                print(f"    ERROR: {error_msg}")
                granule_errors.append({
                    "granule": granule_code,
                    "material": material.nn,
                    "nombre": material.nombre,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                })
                granule_summary["materiales"][material.nn] = {
                    "nombre": material.nombre,
                    "status": "error",
                    "error": str(exc),
                }
                summary["total_errores"] += 1

        if granule_errors:
            granule_summary["status"] = "parcial"
            errors.extend(granule_errors)
        if granule_warnings_count > 0:
            summary["total_advertencias"] += granule_warnings_count
        summary["granules"][granule_code] = granule_summary
        print(f"  {granule_code} completado: estado={granule_summary['status']}, advertencias={granule_warnings_count}")

    return {
        "summary": summary,
        "manifest": {
            "job_id": job_id,
            "category": category.key,
            "fecha": datetime.now(timezone.utc).isoformat(),
            "materiales": manifest_entries,
        },
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Genera materiales academicos por categoria derivados de granulos G1-G5.")
    parser.add_argument("--job-id", required=True, help="ID del job")
    parser.add_argument("--category", required=True, help="Categoria academica")
    parser.add_argument("--generated-dir", required=True, help="Directorio con granulos G1-G5")
    parser.add_argument("--output-dir", required=True, help="Directorio base para materiales")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4o"), help="Modelo OpenAI")
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
