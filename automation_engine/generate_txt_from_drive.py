import argparse
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
except ImportError:  # pragma: no cover
    Request = None
    Credentials = None
    InstalledAppFlow = None
    build = None
    MediaFileUpload = None
    MediaIoBaseDownload = None

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

from automation_engine.generate_guiones import generate_document, word_count
from automation_engine.generate_txt_from_guiones import (
    ENGINE_DIR,
    DEFAULT_PROMPT_PATH,
    build_corpus,
    build_user_prompt,
    extract_metadata_from_corpus,
    output_filename,
    parse_titles,
    save_txt,
)


ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent
SCOPES = ["https://www.googleapis.com/auth/drive"]
DEFAULT_CREDENTIALS_PATH = PROJECT_ROOT / "credentials.json"
DEFAULT_TOKEN_PATH = PROJECT_ROOT / "token_drive.json"
SUPPORTED_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}


def ensure_google_dependencies() -> None:
    if any(item is None for item in [Request, Credentials, InstalledAppFlow, build, MediaFileUpload, MediaIoBaseDownload]):
        raise RuntimeError("Faltan dependencias de Google Drive. Ejecuta: pip install -r requirements.txt")


def get_drive_service(credentials_path: Path, token_path: Path):
    ensure_google_dependencies()
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"No existe {credentials_path}. Descarga el OAuth client JSON de Google Cloud y guardalo con ese nombre."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("drive", "v3", credentials=creds)


def list_source_files(service, folder_id: str) -> List[Dict[str, str]]:
    query = (
        f"'{folder_id}' in parents and trashed = false and "
        "mimeType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'"
    )
    files = []
    page_token = None
    while True:
        response = (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
                orderBy="name",
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return files


def find_or_create_output_folder(service, parent_folder_id: str, folder_name: str) -> str:
    safe_name = folder_name.replace("'", "\\'")
    query = (
        f"'{parent_folder_id}' in parents and trashed = false and "
        f"mimeType = 'application/vnd.google-apps.folder' and name = '{safe_name}'"
    )
    response = (
        service.files()
        .list(
            q=query,
            spaces="drive",
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    folders = response.get("files", [])
    if folders:
        return folders[0]["id"]

    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_folder_id],
    }
    folder = service.files().create(body=metadata, fields="id", supportsAllDrives=True).execute()
    return folder["id"]


def download_drive_file(service, file_info: Dict[str, str], target_dir: Path) -> Path:
    mime_type = file_info["mimeType"]
    name = file_info["name"]

    extension = SUPPORTED_MIME_TYPES.get(mime_type)
    if not extension:
        raise ValueError(f"Tipo no soportado: {name} ({mime_type})")
    output_path = target_dir / (name if Path(name).suffix else f"{name}{extension}")
    request = service.files().get_media(fileId=file_info["id"], supportsAllDrives=True)

    with output_path.open("wb") as handle:
        downloader = MediaIoBaseDownload(handle, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    return output_path


def upload_txt(service, output_folder_id: str, local_path: Path) -> Dict[str, str]:
    safe_name = local_path.name.replace("'", "\\'")
    query = (
        f"'{output_folder_id}' in parents and trashed = false and "
        f"mimeType = 'text/plain' and name = '{safe_name}'"
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
        "parents": [output_folder_id],
        "mimeType": "text/plain",
    }
    media = MediaFileUpload(str(local_path), mimetype="text/plain", resumable=False)
    if existing:
        return (
            service.files()
            .update(
                fileId=existing[0]["id"],
                body={"name": local_path.name, "mimeType": "text/plain"},
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera TXT desde archivos en una carpeta de Google Drive usando OAuth de usuario."
    )
    parser.add_argument("--drive-folder-id", required=True, help="ID de la carpeta de Drive con los guiones fuente")
    parser.add_argument("--output-folder-name", default="contenido complementario", help="Nombre de la subcarpeta de salida en Drive")
    parser.add_argument("--credentials", default=str(DEFAULT_CREDENTIALS_PATH), help="Ruta al OAuth client JSON")
    parser.add_argument("--token", default=str(DEFAULT_TOKEN_PATH), help="Ruta donde se guarda el token OAuth")
    parser.add_argument("--prompt", default=str(DEFAULT_PROMPT_PATH), help="Prompt maestro para generar los TXT")
    parser.add_argument("--count", type=int, default=4, help="Cantidad de archivos TXT a generar")
    parser.add_argument("--titles", default="", help="Titulos/enfoques separados por punto y coma. Por defecto: PDA; QUIZ 1; QUIZ 2; QUIZ 3")
    parser.add_argument("--programa", default="", help="Programa que debe aparecer en el encabezado de cada TXT")
    parser.add_argument("--asignatura", default="", help="Asignatura que debe aparecer en el encabezado de cada TXT")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4o"), help="Modelo OpenAI")
    parser.add_argument("--max-tokens", type=int, default=3500, help="Maximo de tokens por TXT generado")
    parser.add_argument("--temperature", type=float, default=0.45, help="Creatividad de generacion")
    parser.add_argument("--max-chars-per-file", type=int, default=45000, help="Maximo de caracteres leidos por archivo fuente")
    parser.add_argument("--dry-run", action="store_true", help="Lista Drive y valida configuracion, sin llamar a OpenAI ni subir TXT")
    return parser.parse_args()


def main() -> None:
    if load_dotenv:
        load_dotenv()

    args = parse_args()
    credentials_path = Path(args.credentials)
    token_path = Path(args.token)
    prompt_path = Path(args.prompt)

    if not prompt_path.exists():
        raise FileNotFoundError(f"No existe el prompt: {prompt_path}")

    service = get_drive_service(credentials_path, token_path)
    files = list_source_files(service, args.drive_folder_id)
    print(f"Carpeta Drive fuente: {args.drive_folder_id}")
    print(f"Archivos fuente encontrados: {len(files)}")
    for file_info in files:
        print(f"  - {file_info['name']} ({file_info['mimeType']})")

    if not files:
        print("\nNo encontre archivos fuente soportados en esa carpeta.")
        return

    with tempfile.TemporaryDirectory(prefix="drive_guiones_") as temp_name:
        temp_dir = Path(temp_name)
        local_files = []
        print("\nDescargando fuentes temporales...")
        for file_info in files:
            local_path = download_drive_file(service, file_info, temp_dir)
            local_files.append(local_path)
            print(f"  - {file_info['name']} -> {local_path.name}")

        corpus = build_corpus(local_files, args.max_chars_per_file)
        detected_metadata = extract_metadata_from_corpus(corpus)
        programa = args.programa or detected_metadata["programa"]
        asignatura = args.asignatura or detected_metadata["asignatura"]
        if not programa or not asignatura:
            raise RuntimeError("No pude detectar PROGRAMA/ASIGNATURA. Usa --programa y --asignatura para indicarlos.")
        titles = parse_titles(args.titles, args.count)
        manifest = {
            "drive_folder_id": args.drive_folder_id,
            "output_folder_name": args.output_folder_name,
            "prompt": str(prompt_path),
            "count": args.count,
            "titles": titles,
            "programa": programa,
            "asignatura": asignatura,
            "sources": [file_info["name"] for file_info in files],
            "corpus_words": word_count(corpus),
        }
        print(f"\nPalabras fuente aproximadas: {manifest['corpus_words']}")
        print(json.dumps(manifest, ensure_ascii=False, indent=2))

        if args.dry_run:
            print("\nDry-run activo. No se llamo a OpenAI ni se subieron archivos.")
            return

        if OpenAI is None:
            raise RuntimeError("Falta instalar el paquete openai. Ejecuta: pip install -r requirements.txt")
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("Falta OPENAI_API_KEY en variables de entorno o en .env")

        output_folder_id = find_or_create_output_folder(service, args.drive_folder_id, args.output_folder_name)
        print(f"\nCarpeta Drive de salida: {args.output_folder_name} ({output_folder_id})")

        client = OpenAI()
        system_prompt = prompt_path.read_text(encoding="utf-8")
        previous_outputs = ""

        for index, title in enumerate(titles, start=1):
            print(f"\nGenerando TXT {index}/{args.count}: {title}")
            result = generate_document(
                client=client,
                model=args.model,
                system_prompt=system_prompt,
                user_prompt=build_user_prompt(
                    corpus=corpus,
                    title=title,
                    index=index,
                    count=args.count,
                    previous_outputs=previous_outputs,
                    programa=programa,
                    asignatura=asignatura,
                ),
                max_tokens=args.max_tokens,
                temperature=args.temperature,
            )
            local_output = temp_dir / output_filename(title, index)
            save_txt(result, local_output)
            uploaded = upload_txt(service, output_folder_id, local_output)
            previous_outputs = (previous_outputs + "\n\n" + result).strip()
            print(f"Subido: {uploaded['name']} ({uploaded.get('webViewLink', uploaded['id'])})")


if __name__ == "__main__":
    main()
