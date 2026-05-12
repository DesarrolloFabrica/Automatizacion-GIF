"""
Pipeline local unificado del proyecto Automatizacion-GIF.

Lee 4 o 5 archivos .docx o .pdf desde una carpeta local, genera en una sola
ejecucion los 4 TXT (PDA + QUIZ 1-3) y los 3 DOCX (ACA, PRESENTACION, FORO),
y guarda todo en una carpeta local de salida.
"""

from __future__ import annotations

import argparse
import os
import sys
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
    build_corpus,
    build_user_prompt as build_user_prompt_txt,
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
    read_all_inputs,
    render_docx,
    split_response,
    validate_blocks,
)


LOCAL_GRANULES_MIN = 4
LOCAL_GRANULES_MAX = 5
SUPPORTED_SOURCE_EXTENSIONS = {".docx", ".pdf"}


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
    if load_dotenv:
        load_dotenv()

    args = parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    prompt_txt_path = Path(args.prompt_txt)
    prompt_docx_path = Path(args.prompt_docx)

    if not args.skip_txt and not prompt_txt_path.exists():
        raise FileNotFoundError(f"No existe el prompt TXT: {prompt_txt_path}")
    if not args.skip_docx and not prompt_docx_path.exists():
        raise FileNotFoundError(f"No existe el prompt DOCX: {prompt_docx_path}")

    local_files = collect_local_source_files(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("leyendo granulos locales")
    print(f"Carpeta local fuente: {input_dir}")
    print(f"Archivos fuente encontrados: {len(local_files)}")
    for path in local_files:
        print(f"  - {path.name}")

    asignatura, programa = infer_metadata_from_files(
        local_files=local_files,
        cli_asignatura=args.asignatura,
        cli_programa=args.programa,
    )

    corpus = build_corpus(local_files, args.max_chars_per_file)
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
    }
    print("\nManifest:")
    for key, value in manifest.items():
        print(f"- {key}: {value}")

    if args.dry_run:
        print("\nDry-run activo. No se llamo a OpenAI.")
        return

    if OpenAI is None:
        raise RuntimeError("Falta instalar openai. Ejecuta: pip install -r requirements.txt")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Falta OPENAI_API_KEY en variables de entorno o en .env")

    client = OpenAI()
    txt_error = ""
    docx_error = ""
    validation_warnings: List[str] = []

    if not args.skip_txt:
        print("\n=== FASE 1: GENERACION DE TXT ===")
        txt_system_prompt = prompt_txt_path.read_text(encoding="utf-8")
        previous_outputs = ""
        try:
            for index, title in enumerate(titles, start=1):
                print(f"\nGenerando TXT {index}/{len(titles)}: {title}")
                result = generate_document(
                    client=client,
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
                print(f"Guardado: {local_output.name} -> {local_output}")
                try:
                    from automation_engine.incremental_drive_upload import upload_package_file_if_configured

                    upload_package_file_if_configured(
                        local_output,
                        f"PAQUETE_ACADEMICO/ACTIVIDADES_MOODLE/{local_output.name}",
                    )
                except Exception as sync_exc:
                    print(f"Drive incremental: aviso TXT — {sync_exc}")
        except Exception as exc:  # pragma: no cover
            txt_error = str(exc)
            print(f"\nERROR en fase TXT: {exc}", file=sys.stderr)
    else:
        print("\nFASE 1 (TXT) saltada por --skip-txt.")

    if not args.skip_docx:
        print("\n=== FASE 2: GENERACION DE DOCX ===")
        try:
            combined_text = read_all_inputs(local_files)
            docx_system_prompt = prompt_docx_path.read_text(encoding="utf-8")
            docx_user_prompt = build_user_prompt_docx(
                combined_text=combined_text,
                subject=asignatura,
                program=programa,
            )
            print(f"Llamando al modelo {args.model} para los 3 documentos...")
            response = call_openai(
                client=client,
                model=args.model,
                system_prompt=docx_system_prompt,
                user_prompt=docx_user_prompt,
                max_tokens=args.max_tokens_docx,
                temperature=args.temperature_docx,
            )
            blocks = split_response(response)
            validation_warnings = validate_blocks(blocks)
            for doc_type in DOCUMENT_TYPES:
                filename = build_output_filename(doc_type, asignatura, programa)
                local_path = output_dir / filename
                title = f"{DOCUMENT_TITLES[doc_type]} - {asignatura.upper()}"
                render_docx(blocks[doc_type], local_path, title)
                print(f"Guardado: {local_path.name} -> {local_path}")
                try:
                    from automation_engine.incremental_drive_upload import upload_package_file_if_configured

                    upload_package_file_if_configured(
                        local_path,
                        f"PAQUETE_ACADEMICO/ACTIVIDADES_MOODLE/{local_path.name}",
                    )
                except Exception as sync_exc:
                    print(f"Drive incremental: aviso DOCX — {sync_exc}")
        except Exception as exc:  # pragma: no cover
            docx_error = str(exc)
            print(f"\nERROR en fase DOCX: {exc}", file=sys.stderr)
    else:
        print("\nFASE 2 (DOCX) saltada por --skip-docx.")

    print("\n=== RESUMEN ===")
    generated = sorted([p.name for p in output_dir.glob("*.txt")] + [p.name for p in output_dir.glob("*.docx")])
    for name in generated:
        print(f"  - {name}")

    if validation_warnings:
        print("\n=== ADVERTENCIAS DE VALIDACION (DOCX) ===")
        for warning in validation_warnings:
            print(f"  ! {warning}")
        print("=== FIN DE ADVERTENCIAS ===")

    if txt_error or docx_error:
        print("\nGeneracion finalizada con errores.")
        sys.exit(2)

    print("\nGeneracion completa.")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
