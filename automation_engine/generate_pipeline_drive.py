"""
Orquestador unificado del proyecto Automatizacion-GIF.

Descarga 5 archivos .docx desde una carpeta de Google Drive, genera en una sola
ejecucion los 4 TXT del flujo del companero (PDA + QUIZ 1-3) y los 3 DOCX del
flujo de documentos academicos (ACA, PRESENTACION, FORO), y sube todo a Drive
dentro de `contenido complementario/` en la carpeta fuente:

    <carpeta fuente>/
    └── contenido complementario/
        ├── txt/
        │   ├── PDA.txt
        │   ├── QUIZ 1.txt
        │   ├── QUIZ 2.txt
        │   └── QUIZ 3.txt
        ├── ACA_<ASIGNATURA>_<PROGRAMA>.docx
        ├── PRESENTACION_<ASIGNATURA>_<PROGRAMA>.docx
        └── FORO_<ASIGNATURA>_<PROGRAMA>.docx

No modifica los scripts existentes: importa y reutiliza sus helpers.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

try:
    from googleapiclient.http import MediaFileUpload
except ImportError:  # pragma: no cover
    MediaFileUpload = None

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

from automation_engine.generate_guiones import (
    extract_docx_text,
    extract_pdf_text,
    generate_document,
    word_count,
)

from automation_engine.generate_txt_from_drive import (
    DEFAULT_CREDENTIALS_PATH,
    DEFAULT_TOKEN_PATH,
    download_drive_file,
    find_or_create_output_folder,
    get_drive_service,
    list_source_files,
    upload_txt,
)

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
    EXPECTED_FILE_COUNT,
    build_output_filename,
    build_user_prompt as build_user_prompt_docx,
    call_openai,
    read_all_inputs,
    render_docx,
    split_response,
    validate_blocks,
)


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

ASIGNATURA_MAX_LENGTH = 120
PROGRAMA_MAX_LENGTH = 180
DEFAULT_ASIGNATURA = "Asignatura"
DEFAULT_PROGRAMA = "Programa"

LABEL_BREAK_PATTERN = re.compile(
    r"\b(?:ASIGNATURA|PROGRAMA|CICLO|SEMESTRE|ESCUELA|MODALIDAD|CR[E\u00C9]DITOS?|CONTENIDO|NIVEL|JORNADA|MODALIDAD\s+DEL\s+PROGRAMA)\s*[:\-]",
    re.IGNORECASE,
)


def _upload_docx(service, parent_folder_id: str, local_path: Path) -> Dict[str, str]:
    """Sube o reemplaza un archivo .docx en una carpeta de Drive.

    Es un espejo del helper `upload_txt` del companero pero con MIME de Word,
    sin modificar el helper original.
    """
    if MediaFileUpload is None:
        raise RuntimeError(
            "Faltan dependencias de Google Drive. Ejecuta: pip install -r requirements.txt"
        )

    safe_name = local_path.name.replace("'", "\\'")
    query = (
        f"'{parent_folder_id}' in parents and trashed = false and "
        f"mimeType = '{DOCX_MIME}' and name = '{safe_name}'"
    )
    existing = (
        service.files()
        .list(
            q=query,
            spaces="drive",
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
        .get("files", [])
    )
    metadata = {
        "name": local_path.name,
        "parents": [parent_folder_id],
        "mimeType": DOCX_MIME,
    }
    media = MediaFileUpload(str(local_path), mimetype=DOCX_MIME, resumable=False)
    if existing:
        return (
            service.files()
            .update(
                fileId=existing[0]["id"],
                body={"name": local_path.name, "mimeType": DOCX_MIME},
                media_body=media,
                fields="id, name, webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
    return (
        service.files()
        .create(
            body=metadata,
            media_body=media,
            fields="id, name, webViewLink",
            supportsAllDrives=True,
        )
        .execute()
    )


def _read_raw_text_for_inference(path: Path) -> str:
    """Lee un archivo preservando saltos de linea para que el regex pueda
    cortar en fin de linea. Reusa los lectores ya existentes del proyecto.
    """
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return extract_docx_text(path)
    if suffix == ".pdf":
        return extract_pdf_text(path)
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def _sanitize_field_value(raw: str, max_length: int) -> str:
    """Sanitiza un valor capturado tras una etiqueta `LABEL: ...`.

    Reglas en orden:
    1. Colapsa espacios y saltos.
    2. Quita basura de bordes (`:`, `.`, espacios, guiones, pipes, tabs).
    3. Si encuentra otra etiqueta conocida embebida, corta antes.
    4. Si el valor restante contiene un punto y es excesivamente largo,
       conserva solo la primera oracion.
    5. Limpia bordes residuales otra vez.
    6. Si supera `max_length`, retorna cadena vacia para forzar fallback.
    """
    if not raw:
        return ""

    cleaned = re.sub(r"\s+", " ", raw).strip()
    cleaned = cleaned.strip(":. \t-|")

    parts = LABEL_BREAK_PATTERN.split(cleaned, maxsplit=1)
    if parts:
        cleaned = parts[0].strip()

    if "." in cleaned:
        first_segment = cleaned.split(".")[0].strip()
        if first_segment and len(first_segment) >= 3:
            cleaned = first_segment

    cleaned = cleaned.strip(" .,:;-\t|")

    if not cleaned:
        return ""
    if len(cleaned) > max_length:
        return ""
    return cleaned


def _extract_label_value(text: str, label: str) -> str:
    """Devuelve el valor que sigue a `label:` (o `label |`) hasta fin de linea.

    Acepta dos estilos:
    - `LABEL: valor` (encabezado en una linea).
    - `LABEL | valor` (fila de tabla extraida con extract_docx_text).
    """
    inline_pattern = rf"\b{label}\s*:\s*([^\r\n|]+)"
    match = re.search(inline_pattern, text, re.IGNORECASE)
    if match and match.group(1).strip():
        return match.group(1)

    table_pattern = rf"\b{label}\b\s*\|\s*([^\r\n|]+)"
    match_table = re.search(table_pattern, text, re.IGNORECASE)
    if match_table and match_table.group(1).strip():
        return match_table.group(1)

    return ""


def infer_metadata_from_files(
    local_files: List[Path],
    cli_asignatura: str,
    cli_programa: str,
) -> Tuple[str, str]:
    """Inferencia robusta de asignatura y programa.

    Lee directamente los archivos locales (preservando saltos de linea) y
    aplica sanitizacion estricta. Respeta los overrides CLI sin tocarlos.
    Imprime logs en formato `[INFER] ...` y aplica fallback seguro si los
    candidatos exceden el limite o no aparecen.
    """
    asignatura = (cli_asignatura or "").strip()
    programa = (cli_programa or "").strip()

    if asignatura and programa:
        print(f"[INFER] Asignatura (override CLI): {asignatura}")
        print(f"[INFER] Programa (override CLI): {programa}")
        return asignatura, programa

    raw_texts: List[str] = []
    for path in local_files:
        try:
            raw_texts.append(_read_raw_text_for_inference(path))
        except Exception as exc:
            print(f"[INFER] WARNING: no pude leer {path.name} para inferir metadatos ({exc}).")
    combined = "\n\n".join(raw_texts)

    if not asignatura:
        raw = _extract_label_value(combined, "ASIGNATURA")
        candidate = _sanitize_field_value(raw, ASIGNATURA_MAX_LENGTH)
        if candidate and 3 <= len(candidate) <= ASIGNATURA_MAX_LENGTH:
            asignatura = candidate
        else:
            if raw:
                print(
                    f"[INFER] WARNING: candidato de asignatura no paso sanitizacion "
                    f"(longitud original {len(raw)}, limite {ASIGNATURA_MAX_LENGTH}). "
                    f"Fallback: '{DEFAULT_ASIGNATURA}'."
                )
            asignatura = DEFAULT_ASIGNATURA

    if not programa:
        raw = _extract_label_value(combined, "PROGRAMA")
        candidate = _sanitize_field_value(raw, PROGRAMA_MAX_LENGTH)
        if candidate and 3 <= len(candidate) <= PROGRAMA_MAX_LENGTH:
            programa = candidate
        else:
            if raw:
                print(
                    f"[INFER] WARNING: candidato de programa no paso sanitizacion "
                    f"(longitud original {len(raw)}, limite {PROGRAMA_MAX_LENGTH}). "
                    f"Fallback: '{DEFAULT_PROGRAMA}'."
                )
            programa = DEFAULT_PROGRAMA

    print("[INFER]")
    print(f"Asignatura detectada: {asignatura}")
    print(f"Programa detectado: {programa}")
    return asignatura, programa


def _print_uploads(label: str, uploads: List[Dict[str, str]]) -> None:
    print(f"\n{label}: {len(uploads)} archivo(s)")
    for item in uploads:
        link = item.get("webViewLink") or item.get("id")
        print(f"  - {item.get('name', '?')}: {link}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Pipeline unificado: descarga 5 .docx desde Drive y genera "
            "PDA + QUIZ 1-3 (TXT) y ACA + PRESENTACION + FORO (DOCX) en "
            "`contenido complementario/` dentro de la carpeta fuente."
        )
    )
    parser.add_argument(
        "--drive-folder-id",
        required=True,
        help="ID de la carpeta de Google Drive con los 5 archivos fuente .docx",
    )
    parser.add_argument(
        "--output-folder-name",
        default="contenido complementario",
        help="Nombre de la carpeta de salida en Drive (se crea si no existe)",
    )
    parser.add_argument(
        "--txt-subfolder-name",
        default="txt",
        help="Nombre de la subcarpeta para los TXT dentro de la carpeta de salida",
    )
    parser.add_argument(
        "--asignatura",
        default="",
        help="Override del nombre de la asignatura. Si se omite se intenta inferir",
    )
    parser.add_argument(
        "--programa",
        default="",
        help="Override del nombre del programa. Si se omite se intenta inferir",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=4,
        help="Cantidad de archivos TXT a generar (default 4: PDA + QUIZ 1-3)",
    )
    parser.add_argument(
        "--titles",
        default="",
        help="Titulos/enfoques de los TXT separados por punto y coma. Default: PDA; QUIZ 1; QUIZ 2; QUIZ 3",
    )
    parser.add_argument(
        "--prompt-txt",
        default=str(DEFAULT_TXT_PROMPT_PATH),
        help="Ruta al prompt maestro de los TXT",
    )
    parser.add_argument(
        "--prompt-docx",
        default=str(DEFAULT_DOCX_PROMPT_PATH),
        help="Ruta al prompt maestro de los documentos academicos",
    )
    parser.add_argument(
        "--credentials",
        default=str(DEFAULT_CREDENTIALS_PATH),
        help="Ruta al OAuth client JSON de Google",
    )
    parser.add_argument(
        "--token",
        default=str(DEFAULT_TOKEN_PATH),
        help="Ruta al token OAuth persistente",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_MODEL", "gpt-4o"),
        help="Modelo OpenAI a utilizar para ambas fases",
    )
    parser.add_argument(
        "--max-tokens-txt",
        type=int,
        default=3500,
        help="Maximo de tokens por TXT generado",
    )
    parser.add_argument(
        "--max-tokens-docx",
        type=int,
        default=6000,
        help="Maximo de tokens en la respuesta unica del flujo DOCX",
    )
    parser.add_argument(
        "--temperature-txt",
        type=float,
        default=0.45,
        help="Creatividad para la fase TXT",
    )
    parser.add_argument(
        "--temperature-docx",
        type=float,
        default=0.6,
        help="Creatividad para la fase DOCX",
    )
    parser.add_argument(
        "--max-chars-per-file",
        type=int,
        default=45000,
        help="Maximo de caracteres leidos por archivo fuente para el corpus TXT",
    )
    parser.add_argument(
        "--skip-txt",
        action="store_true",
        help="Salta la fase de TXT (util para regenerar solo los DOCX)",
    )
    parser.add_argument(
        "--skip-docx",
        action="store_true",
        help="Salta la fase de DOCX (util para regenerar solo los TXT)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Lista Drive, descarga, valida y muestra el manifest sin llamar a OpenAI ni subir nada",
    )
    return parser.parse_args()


def main() -> None:
    if load_dotenv:
        load_dotenv()

    args = parse_args()

    prompt_txt_path = Path(args.prompt_txt)
    prompt_docx_path = Path(args.prompt_docx)

    if not args.skip_txt and not prompt_txt_path.exists():
        raise FileNotFoundError(f"No existe el prompt TXT: {prompt_txt_path}")
    if not args.skip_docx and not prompt_docx_path.exists():
        raise FileNotFoundError(f"No existe el prompt DOCX: {prompt_docx_path}")

    credentials_path = Path(args.credentials)
    token_path = Path(args.token)

    print("Autenticando con Google Drive...")
    service = get_drive_service(credentials_path, token_path)

    files = list_source_files(service, args.drive_folder_id)
    print(f"\nCarpeta Drive fuente: {args.drive_folder_id}")
    print(f"Archivos fuente encontrados: {len(files)}")
    for file_info in files:
        print(f"  - {file_info['name']} ({file_info['mimeType']})")

    if len(files) != EXPECTED_FILE_COUNT:
        raise ValueError(
            f"Se esperan exactamente {EXPECTED_FILE_COUNT} archivos .docx en la "
            f"carpeta fuente, se encontraron {len(files)}. Ajusta la carpeta o "
            f"verifica que todos los archivos sean .docx."
        )

    with tempfile.TemporaryDirectory(prefix="pipeline_drive_") as temp_name:
        temp_dir = Path(temp_name)
        local_files: List[Path] = []
        print("\nDescargando fuentes a directorio temporal...")
        for file_info in files:
            local_path = download_drive_file(service, file_info, temp_dir)
            local_files.append(local_path)
            print(f"  - {file_info['name']} -> {local_path.name}")

        asignatura, programa = infer_metadata_from_files(
            local_files=local_files,
            cli_asignatura=args.asignatura,
            cli_programa=args.programa,
        )
        if asignatura == DEFAULT_ASIGNATURA or programa == DEFAULT_PROGRAMA:
            print(
                "[INFER] Aviso: se uso fallback en al menos un campo. "
                "Si necesitas valores especificos pasa --asignatura y/o --programa."
            )

        corpus = build_corpus(local_files, args.max_chars_per_file)

        titles = parse_titles(args.titles, args.count)

        parent_id = find_or_create_output_folder(
            service, args.drive_folder_id, args.output_folder_name
        )
        txt_id = find_or_create_output_folder(
            service, parent_id, args.txt_subfolder_name
        )

        manifest = {
            "drive_folder_id": args.drive_folder_id,
            "output_folder_name": args.output_folder_name,
            "output_folder_id": parent_id,
            "txt_subfolder_name": args.txt_subfolder_name,
            "txt_subfolder_id": txt_id,
            "asignatura": asignatura,
            "programa": programa,
            "titles": titles,
            "sources": [file_info["name"] for file_info in files],
            "corpus_words": word_count(corpus),
            "skip_txt": args.skip_txt,
            "skip_docx": args.skip_docx,
        }
        print(f"\nPalabras fuente aproximadas: {manifest['corpus_words']}")
        print("\nManifest:")
        print(json.dumps(manifest, ensure_ascii=False, indent=2))

        if args.dry_run:
            print(
                "\nDry-run activo. No se llamo a OpenAI ni se subieron archivos. "
                "Las carpetas de Drive ya quedaron creadas (`contenido complementario/` y `txt/`)."
            )
            return

        if OpenAI is None:
            raise RuntimeError(
                "Falta instalar el paquete openai. Ejecuta: pip install -r requirements.txt"
            )
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("Falta OPENAI_API_KEY en variables de entorno o en .env")

        client = OpenAI()

        txt_uploads: List[Dict[str, str]] = []
        docx_uploads: List[Dict[str, str]] = []
        validation_warnings: List[str] = []
        txt_error: str = ""
        docx_error: str = ""

        if not args.skip_txt:
            print("\n=== FASE 1: GENERACION DE TXT (PDA + QUIZ 1-3) ===")
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
                    local_output = temp_dir / output_filename(title, index)
                    save_txt(result, local_output)
                    uploaded = upload_txt(service, txt_id, local_output)
                    txt_uploads.append(uploaded)
                    previous_outputs = (previous_outputs + "\n\n" + result).strip()
                    link = uploaded.get("webViewLink") or uploaded.get("id", "")
                    print(f"  Subido: {uploaded['name']} -> {link}")
            except Exception as exc:  # pragma: no cover
                txt_error = str(exc)
                print(f"\nERROR en fase TXT: {exc}", file=sys.stderr)
        else:
            print("\nFASE 1 (TXT) saltada por --skip-txt.")

        if not args.skip_docx:
            print("\n=== FASE 2: GENERACION DE DOCX (ACA, PRESENTACION, FORO) ===")
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
                    local_path = temp_dir / filename
                    title = f"{DOCUMENT_TITLES[doc_type]} - {asignatura.upper()}"
                    render_docx(blocks[doc_type], local_path, title)
                    uploaded = _upload_docx(service, parent_id, local_path)
                    docx_uploads.append(uploaded)
                    link = uploaded.get("webViewLink") or uploaded.get("id", "")
                    print(f"  Subido: {uploaded['name']} -> {link}")
            except Exception as exc:  # pragma: no cover
                docx_error = str(exc)
                print(f"\nERROR en fase DOCX: {exc}", file=sys.stderr)
        else:
            print("\nFASE 2 (DOCX) saltada por --skip-docx.")

        print("\n=== RESUMEN ===")
        _print_uploads("TXT subidos", txt_uploads)
        _print_uploads("DOCX subidos", docx_uploads)

        if validation_warnings:
            print("\n=== ADVERTENCIAS DE VALIDACION (DOCX) ===")
            for warning in validation_warnings:
                print(f"  ! {warning}")
            print("=== FIN DE ADVERTENCIAS ===")
        elif not args.skip_docx and docx_uploads:
            print("\nValidacion DOCX OK: los 3 documentos cumplen los requisitos minimos.")

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
