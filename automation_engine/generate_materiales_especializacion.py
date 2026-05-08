from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import List

from docx import Document

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

from automation_engine.config.materiales_especializacion import (
    ESPECIALIZACION_PROMPT_PATH,
    MATERIALES_A_GENERAR,
    MATERIALES_RESERVADOS_FUTURO,
    VERSION_DEFECTO,
    EspecializacionConfig,
    MaterialConfig,
)
from automation_engine.utils.naming import (
    build_granule_folder_name,
    build_material_filename,
    normalize_for_filename,
)


def extract_docx_text(path: Path) -> str:
    doc = Document(path)
    parts = []
    for paragraph in doc.paragraphs:
        text = (paragraph.text or "").strip()
        if text:
            parts.append(text)
    for table in doc.tables:
        for row in table.rows:
            cells = [(cell.text or "").strip() for cell in row.cells if (cell.text or "").strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def load_especializacion_prompt() -> str:
    if not ESPECIALIZACION_PROMPT_PATH.exists():
        raise FileNotFoundError(f"No se encontro el prompt: {ESPECIALIZACION_PROMPT_PATH}")
    return ESPECIALIZACION_PROMPT_PATH.read_text(encoding="utf-8")


def extract_system_prompt(prompt_text: str) -> str:
    match = re.search(r"# PROMPT SISTEMA\s*\n\s*```text\s*\n(.*?)```", prompt_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    raise ValueError("No se encontro la seccion PROMPT SISTEMA en el archivo de prompt")


def extract_material_prompt(prompt_text: str, seccion_nombre: str) -> str:
    pattern = rf"## {re.escape(seccion_nombre)}\s*\n.*?### Prompt\s*\n\s*```text\s*\n(.*?)```"
    match = re.search(pattern, prompt_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    raise ValueError(f"No se encontro la seccion de prompt para: {seccion_nombre}")


def build_user_prompt(
    material: MaterialConfig,
    guion_maestro_text: str,
    granule_code: str,
    tema: str,
    tema_corto: str,
    version: str,
) -> str:
    return f"""Quiero generar un material derivado para ESPECIALIZACION.

Pego a continuacion el GUION MAESTRO aprobado del tema:

{guion_maestro_text}

Datos del material:
- Codigo GX: {granule_code}
- Nombre exacto del tema: {tema}
- Nombre corto para archivo: {tema_corto}
- Version: {version}
- Material a generar: {material.nombre.replace("_", " ")}
- Formato esperado: DOCX (contenido en tabla)
- Cierre integrado ira en: NO APLICA
- Restricciones adicionales: Generar contenido en formato tabla listo para DOCX.

Genera unicamente el material solicitado.
No generes los demas materiales.
No agregues informacion que no este en el GUION MAESTRO.
Entrega el contenido en formato tabla como se indica en las instrucciones del material.
""".strip()


def generate_material_content(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()


def save_docx_from_tables(content: str, output_path: Path) -> None:
    doc = Document()
    table_lines = []
    in_table = False

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            if in_table and table_lines:
                _add_table_to_docx(doc, table_lines)
                table_lines = []
                in_table = False
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            in_table = True
            table_lines.append(stripped)
        else:
            if in_table and table_lines:
                _add_table_to_docx(doc, table_lines)
                table_lines = []
                in_table = False
            doc.add_paragraph(stripped)

    if in_table and table_lines:
        _add_table_to_docx(doc, table_lines)

    doc.save(output_path)


def _add_table_to_docx(doc: Document, lines: List[str]) -> None:
    if not lines:
        return
    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.split("|") if cell.strip()]
        if cells:
            rows.append(cells)
    if not rows:
        return
    num_cols = max(len(row) for row in rows)
    table = doc.add_table(rows=len(rows), cols=num_cols)
    for row_idx, row_data in enumerate(rows):
        for col_idx, cell_text in enumerate(row_data):
            if col_idx < num_cols:
                table.rows[row_idx].cells[col_idx].text = cell_text


def discover_granules(generated_dir: Path) -> List[dict]:
    granules = []
    docx_files = sorted(generated_dir.glob("G*.docx"))
    for docx_path in docx_files:
        match = re.match(r"(G\d+)_", docx_path.stem)
        if match:
            granule_code = match.group(1)
            tema = docx_path.stem.replace(granule_code + "_", "", 1)
            granules.append({
                "code": granule_code,
                "tema": tema,
                "tema_corto": normalize_for_filename(tema),
                "path": docx_path,
            })
    return granules


def generate_all_materiales(
    job_id: str,
    generated_dir: Path,
    output_base: Path,
    model: str,
    max_tokens: int,
    temperature: float,
) -> dict:
    if OpenAI is None:
        raise RuntimeError("Falta instalar el paquete openai. Ejecuta: pip install -r requirements.txt")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Falta OPENAI_API_KEY en variables de entorno.")

    prompt_text = load_especializacion_prompt()
    system_prompt = extract_system_prompt(prompt_text)

    materiales_config = []
    for mat in MATERIALES_A_GENERAR:
        try:
            prompt_particular = extract_material_prompt(prompt_text, mat["seccion_prompt"])
            materiales_config.append(MaterialConfig(
                nn=mat["nn"],
                nombre=mat["nombre"],
                prompt_particular=prompt_particular,
            ))
        except ValueError as e:
            print(f"ADVERTENCIA: {e}")

    granules = discover_granules(generated_dir)
    if not granules:
        raise ValueError(f"No se encontraron gránulos en {generated_dir}")

    print(f"\n=== FASE: GENERACION DE MATERIALES DE ESPECIALIZACION ===")
    print(f"Gránulos encontrados: {len(granules)}")
    print(f"Materiales por gránulo: {len(materiales_config)}")
    print(f"Total de materiales a generar: {len(granules) * len(materiales_config)}")

    client = OpenAI()
    errors = []
    summary = {
        "job_id": job_id,
        "fecha": datetime.utcnow().isoformat(),
        "total_granules": len(granules),
        "total_materiales_esperados": len(granules) * len(materiales_config),
        "total_materiales_generados": 0,
        "total_errores": 0,
        "granules": {},
    }

    for granule in granules:
        granule_code = granule["code"]
        tema = granule["tema"]
        tema_corto = granule["tema_corto"]
        granule_path = granule["path"]

        print(f"\n--- Procesando {granule_code}: {tema} ---")

        try:
            guion_text = extract_docx_text(granule_path)
        except Exception as e:
            error_msg = f"Error leyendo {granule_path}: {e}"
            print(f"  ERROR: {error_msg}")
            errors.append({"granule": granule_code, "error": error_msg})
            summary["granules"][granule_code] = {"status": "error_lectura", "materiales": {}}
            continue

        folder_name = build_granule_folder_name(granule_code, tema)
        granule_output_dir = output_base / folder_name
        granule_output_dir.mkdir(parents=True, exist_ok=True)

        granule_summary = {"status": "ok", "materiales": {}}
        granule_errors = []

        for material in materiales_config:
            material_filename = build_material_filename(
                material.nn, granule_code, tema_corto, VERSION_DEFECTO, ".docx"
            )
            material_output_path = granule_output_dir / material_filename

            print(f"  Generando material: {material.nn} {granule_code} ({material.nombre})")

            try:
                user_prompt = build_user_prompt(
                    material=material,
                    guion_maestro_text=guion_text,
                    granule_code=granule_code,
                    tema=tema,
                    tema_corto=tema_corto,
                    version=VERSION_DEFECTO,
                )

                content = generate_material_content(
                    client=client,
                    model=model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

                save_docx_from_tables(content, material_output_path)
                print(f"  Material guardado: {material_filename}")

                granule_summary["materiales"][material.nn] = {
                    "nombre": material.nombre,
                    "archivo": material_filename,
                    "status": "ok",
                }
                summary["total_materiales_generados"] += 1

            except Exception as e:
                error_msg = f"Error material {material.nn} {granule_code}: {e}"
                print(f"  ERROR: {error_msg}")
                granule_errors.append({
                    "material": material.nn,
                    "nombre": material.nombre,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                })
                granule_summary["materiales"][material.nn] = {
                    "nombre": material.nombre,
                    "status": "error",
                    "error": str(e),
                }
                summary["total_errores"] += 1

        if granule_errors:
            granule_summary["status"] = "parcial"
            errors.extend(granule_errors)

        summary["granules"][granule_code] = granule_summary

    manifest = {
        "job_id": job_id,
        "fecha": datetime.utcnow().isoformat(),
        "materiales": [],
    }
    for granule in granules:
        granule_code = granule["code"]
        tema_corto = granule["tema_corto"]
        folder_name = build_granule_folder_name(granule_code, tema_corto)
        granule_dir = output_base / folder_name
        if granule_dir.exists():
            for docx_file in sorted(granule_dir.glob("*.docx")):
                manifest["materiales"].append({
                    "granule": granule_code,
                    "archivo": docx_file.name,
                    "ruta_relativa": f"materiales_especializacion/{folder_name}/{docx_file.name}",
                })

    return {
        "summary": summary,
        "manifest": manifest,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera materiales de especializacion derivados de gránulos."
    )
    parser.add_argument("--job-id", required=True, help="ID del job")
    parser.add_argument("--generated-dir", required=True, help="Directorio con gránulos generados")
    parser.add_argument("--output-dir", required=True, help="Directorio base para materiales")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4o"), help="Modelo OpenAI")
    parser.add_argument("--max-tokens", type=int, default=8000, help="Maximo de tokens por material")
    parser.add_argument("--temperature", type=float, default=0.5, help="Creatividad de generación")
    return parser.parse_args()


def main() -> None:
    if load_dotenv:
        load_dotenv()

    args = parse_args()
    generated_dir = Path(args.generated_dir)
    output_base = Path(args.output_dir)
    output_base.mkdir(parents=True, exist_ok=True)

    result = generate_all_materiales(
        job_id=args.job_id,
        generated_dir=generated_dir,
        output_base=output_base,
        model=args.model,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )

    summary_path = output_base.parent / "summary.json"
    summary_path.write_text(
        json.dumps(result["summary"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nSummary guardado: {summary_path}")

    manifest_path = output_base.parent / "manifest.json"
    manifest_path.write_text(
        json.dumps(result["manifest"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Manifest guardado: {manifest_path}")

    errors_path = output_base.parent / "errors.json"
    errors_path.write_text(
        json.dumps(result["errors"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Errors guardado: {errors_path}")

    print(f"\n=== RESUMEN ===")
    print(f"Gránulos procesados: {result['summary']['total_granules']}")
    print(f"Materiales generados: {result['summary']['total_materiales_generados']}")
    print(f"Errores: {result['summary']['total_errores']}")
    print(f"Total esperado: {result['summary']['total_materiales_esperados']}")

    if result["errors"]:
        print(f"\nErrores encontrados:")
        for err in result["errors"]:
            print(f"  - {err.get('granule', '?')} {err.get('material', '?')}: {err.get('error', '?')}")


if __name__ == "__main__":
    main()
