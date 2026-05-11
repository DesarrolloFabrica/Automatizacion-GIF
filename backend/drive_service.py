from __future__ import annotations

import mimetypes
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError:  # pragma: no cover
    service_account = None
    build = None
    MediaFileUpload = None

from automation_engine.generate_txt_from_drive import DEFAULT_CREDENTIALS_PATH, DEFAULT_TOKEN_PATH, get_drive_service


DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_URL = "https://drive.google.com/drive/folders/{folder_id}"


@dataclass
class DriveUploadSummary:
    root_folder_id: str
    root_folder_link: str
    folders_created: int
    folders_reused: int
    files_uploaded: int
    files_overwritten: int
    files_skipped: int
    uploaded_files: list[dict[str, str]]


def _ensure_google_dependencies() -> None:
    if any(item is None for item in [build, MediaFileUpload]):
        raise RuntimeError("Faltan dependencias de Google Drive. Ejecuta: pip install -r requirements.txt")


def get_authenticated_drive_service():
    load_dotenv(PROJECT_ROOT / ".env")
    _ensure_google_dependencies()

    service_account_path = (
        os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        or os.getenv("DRIVE_SERVICE_ACCOUNT_FILE")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    )
    if service_account_path:
        path = Path(service_account_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists():
            raise FileNotFoundError(f"No existe el archivo de service account: {path}")
        if service_account is None:
            raise RuntimeError("Falta google-auth para service account. Ejecuta: pip install -r requirements.txt")
        credentials = service_account.Credentials.from_service_account_file(str(path), scopes=DRIVE_SCOPES)
        return build("drive", "v3", credentials=credentials)

    if DEFAULT_CREDENTIALS_PATH.exists() and DEFAULT_TOKEN_PATH.exists():
        return get_drive_service(DEFAULT_CREDENTIALS_PATH, DEFAULT_TOKEN_PATH)

    raise FileNotFoundError(
        "No hay credenciales Drive configuradas. Define GOOGLE_SERVICE_ACCOUNT_FILE en .env "
        "o configura credentials.json + token_drive.json."
    )


def validate_drive_folder(service, folder_id: str) -> dict[str, str]:
    clean_id = (folder_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,}", clean_id):
        raise ValueError("Folder ID de Drive inválido.")
    try:
        folder = service.files().get(
            fileId=clean_id,
            fields="id, name, mimeType, webViewLink",
            supportsAllDrives=True,
        ).execute()
    except Exception as exc:
        raise FileNotFoundError(f"No se pudo acceder a la carpeta Drive {clean_id}: {exc}") from exc
    if folder.get("mimeType") != DRIVE_FOLDER_MIME:
        raise ValueError(f"El ID de Drive no corresponde a una carpeta: {clean_id}")
    return folder


def _escape_drive_query(value: str) -> str:
    return value.replace("'", "\\'")


def find_child_folder(service, parent_id: str, name: str) -> dict[str, str] | None:
    safe_name = _escape_drive_query(name)
    query = (
        f"'{parent_id}' in parents and trashed = false and "
        f"mimeType = '{DRIVE_FOLDER_MIME}' and name = '{safe_name}'"
    )
    files = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name, webViewLink)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute().get("files", [])
    return files[0] if files else None


def find_or_create_child_folder(service, parent_id: str, name: str) -> tuple[dict[str, str], bool]:
    existing = find_child_folder(service, parent_id, name)
    if existing:
        return existing, False
    metadata = {"name": name, "mimeType": DRIVE_FOLDER_MIME, "parents": [parent_id]}
    folder = service.files().create(
        body=metadata,
        fields="id, name, webViewLink",
        supportsAllDrives=True,
    ).execute()
    return folder, True


def ensure_folder_path(service, parent_id: str, parts: Iterable[str]) -> tuple[str, int, int]:
    current_id = parent_id
    created = 0
    reused = 0
    for part in parts:
        folder, was_created = find_or_create_child_folder(service, current_id, part)
        current_id = folder["id"]
        if was_created:
            created += 1
        else:
            reused += 1
    return current_id, created, reused


def _mime_type(path: Path) -> str:
    lower = path.suffix.lower()
    if lower == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if lower == ".txt":
        return "text/plain"
    if lower == ".pdf":
        return "application/pdf"
    if lower == ".zip":
        return "application/zip"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def find_child_file(service, parent_id: str, name: str) -> dict[str, str] | None:
    safe_name = _escape_drive_query(name)
    query = (
        f"'{parent_id}' in parents and trashed = false and "
        f"mimeType != '{DRIVE_FOLDER_MIME}' and name = '{safe_name}'"
    )
    files = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name, webViewLink)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute().get("files", [])
    return files[0] if files else None


def upload_file_overwrite(service, parent_id: str, local_path: Path, drive_name: str) -> tuple[dict[str, str], bool]:
    if not local_path.exists() or not local_path.is_file():
        raise FileNotFoundError(f"Archivo no encontrado para subir a Drive: {local_path}")
    if local_path.stat().st_size <= 0:
        raise ValueError(f"Archivo vacío o corrupto, no se sube a Drive: {local_path}")
    mime_type = _mime_type(local_path)
    media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=False)
    existing = find_child_file(service, parent_id, drive_name)
    if existing:
        uploaded = service.files().update(
            fileId=existing["id"],
            body={"name": drive_name, "mimeType": mime_type},
            media_body=media,
            fields="id, name, webViewLink",
            supportsAllDrives=True,
        ).execute()
        return uploaded, True
    metadata = {"name": drive_name, "parents": [parent_id], "mimeType": mime_type}
    uploaded = service.files().create(
        body=metadata,
        media_body=media,
        fields="id, name, webViewLink",
        supportsAllDrives=True,
    ).execute()
    return uploaded, False


def upload_academic_package_to_drive(
    *,
    parent_folder_id: str,
    package_files: list[tuple[Path, str]],
    include_zip: tuple[Path, str] | None = None,
) -> DriveUploadSummary:
    service = get_authenticated_drive_service()
    validate_drive_folder(service, parent_folder_id)

    folders_created = 0
    folders_reused = 0
    files_uploaded = 0
    files_overwritten = 0
    files_skipped = 0
    uploaded_files: list[dict[str, str]] = []

    root_folder_id = ""
    root_folder_link = ""
    entries = list(package_files)
    if include_zip is not None:
        entries.append(include_zip)

    folder_cache: dict[tuple[str, ...], str] = {}
    for local_path, arcname in entries:
        if not local_path.exists() or not local_path.is_file() or local_path.stat().st_size <= 0:
            files_skipped += 1
            continue
        parts = [part for part in Path(arcname).parts if part]
        if len(parts) < 2:
            files_skipped += 1
            continue
        folder_parts = tuple(parts[:-1])
        drive_name = parts[-1]
        if folder_parts in folder_cache:
            target_folder_id = folder_cache[folder_parts]
        else:
            target_folder_id, created, reused = ensure_folder_path(service, parent_folder_id, folder_parts)
            folder_cache[folder_parts] = target_folder_id
            folders_created += created
            folders_reused += reused
            if folder_parts == ("PAQUETE_ACADEMICO",):
                root_folder_id = target_folder_id
        uploaded, overwritten = upload_file_overwrite(service, target_folder_id, local_path, drive_name)
        if overwritten:
            files_overwritten += 1
        else:
            files_uploaded += 1
        uploaded_files.append({
            "name": uploaded.get("name", drive_name),
            "id": uploaded.get("id", ""),
            "link": uploaded.get("webViewLink", ""),
            "path": "/".join(parts),
            "overwritten": str(overwritten).lower(),
        })

    if not root_folder_id:
        root, was_created = find_or_create_child_folder(service, parent_folder_id, "PAQUETE_ACADEMICO")
        root_folder_id = root["id"]
        folders_created += 1 if was_created else 0
        folders_reused += 0 if was_created else 1
    root_folder_link = FOLDER_URL.format(folder_id=root_folder_id)

    return DriveUploadSummary(
        root_folder_id=root_folder_id,
        root_folder_link=root_folder_link,
        folders_created=folders_created,
        folders_reused=folders_reused,
        files_uploaded=files_uploaded,
        files_overwritten=files_overwritten,
        files_skipped=files_skipped,
        uploaded_files=uploaded_files,
    )
