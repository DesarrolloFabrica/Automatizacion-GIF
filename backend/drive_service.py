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
    import google.auth
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError:  # pragma: no cover
    google = None
    service_account = None
    build = None
    MediaFileUpload = None

from automation_engine.generate_txt_from_drive import DEFAULT_CREDENTIALS_PATH, DEFAULT_TOKEN_PATH, get_drive_service

from drive_naming import resolve_drive_relative_path


DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_URL = "https://drive.google.com/drive/folders/{folder_id}"
# Layout local/ZIP sigue usando PAQUETE_ACADEMICO/...; en Drive la raíz es la carpeta del usuario.
DRIVE_STRIP_PACKAGE_PREFIX = "PAQUETE_ACADEMICO"


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


@dataclass
class DriveStructureSummary:
    """Raíz académica en Drive = carpeta pegada por el usuario (sin contenedor PAQUETE_ACADEMICO)."""
    user_folder_id: str
    user_folder_link: str
    folders_created: int
    folders_reused: int


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

    if google is not None:
        try:
            credentials, _ = google.auth.default(scopes=DRIVE_SCOPES)
            return build("drive", "v3", credentials=credentials)
        except Exception:
            pass

    raise FileNotFoundError(
        "No hay credenciales Drive configuradas. Define GOOGLE_SERVICE_ACCOUNT_FILE en .env, "
        "configura credentials.json + token_drive.json, o ejecuta en Cloud Run con una service account con acceso a Drive."
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


# Si el usuario pega el ID de una subcarpeta del paquete (p. ej. CONTENIDOS) como destino,
# volver a crear SYLLABUS/CONTENIDOS debajo duplica toda la estructura. Subimos al padre.
_ACADEMIC_PACKAGE_SUBFOLDER_NAMES = frozenset({"SYLLABUS", "CONTENIDOS", "ACTIVIDADES_MOODLE", "RECURSOS_COMPLEMENTARIOS"})


def resolve_academic_workspace_folder_id(
    service,
    folder_id: str,
    *,
    log_fn=None,
    _depth: int = 0,
) -> str:
    """Devuelve el ID de la carpeta raíz del curso (hermano de SYLLABUS), no una subcarpeta del paquete."""
    if _depth > 12:
        return (folder_id or "").strip()
    clean_id = (folder_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,}", clean_id):
        return clean_id
    try:
        meta = service.files().get(
            fileId=clean_id,
            fields="id,name,parents",
            supportsAllDrives=True,
        ).execute()
    except Exception:
        return clean_id
    name_upper = (meta.get("name") or "").strip().upper()
    parents = meta.get("parents") or []
    if name_upper in _ACADEMIC_PACKAGE_SUBFOLDER_NAMES and parents:
        parent_id = parents[0]
        if log_fn:
            log_fn(
                f"Drive: la carpeta destino era «{meta.get('name')}» (parte del paquete); "
                "se usa la carpeta padre como raíz para no anidar otra copia del mismo árbol."
            )
        return resolve_academic_workspace_folder_id(service, parent_id, log_fn=log_fn, _depth=_depth + 1)
    return clean_id


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


def drive_arcname_for_upload(arcname: str) -> str:
    """Convierte ruta de paquete local (PAQUETE_ACADEMICO/...) a ruta bajo la carpeta destino del usuario."""
    normalized = arcname.replace("\\", "/").strip("/")
    parts = [p for p in normalized.split("/") if p]
    if parts and parts[0] == DRIVE_STRIP_PACKAGE_PREFIX:
        parts = parts[1:]
    return "/".join(parts)


def ensure_folder_path(service, parent_id: str, parts: Iterable[str], log_fn=None) -> tuple[str, int, int]:
    current_id = parent_id
    created = 0
    reused = 0
    for part in parts:
        folder, was_created = find_or_create_child_folder(service, current_id, part)
        current_id = folder["id"]
        if was_created:
            created += 1
            if log_fn:
                log_fn(f"Drive upload: carpeta creada {part} ({current_id})")
        else:
            reused += 1
            if log_fn:
                log_fn(f"Drive upload: carpeta reutilizada {part} ({current_id})")
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


def ensure_drive_package_structure(*, parent_folder_id: str, log_fn=None) -> DriveStructureSummary:
    """Crea o reutiliza SYLLABUS, CONTENIDOS, ACTIVIDADES_MOODLE, RECURSOS_COMPLEMENTARIOS (subcarpetas G*_TEMA las crea cada sync)."""
    if log_fn:
        log_fn(f"Drive estructura: validando carpeta destino (raíz académica) {parent_folder_id}")
    service = get_authenticated_drive_service()
    parent_folder_id = resolve_academic_workspace_folder_id(service, parent_folder_id, log_fn=log_fn)
    validate_drive_folder(service, parent_folder_id)

    folders_created = 0
    folders_reused = 0

    for name in ("SYLLABUS", "CONTENIDOS", "ACTIVIDADES_MOODLE"):
        _, c, r = ensure_folder_path(service, parent_folder_id, (name,), log_fn=log_fn)
        folders_created += c
        folders_reused += r

    _, c, r = ensure_folder_path(service, parent_folder_id, ("RECURSOS_COMPLEMENTARIOS",), log_fn=log_fn)
    folders_created += c
    folders_reused += r

    link = FOLDER_URL.format(folder_id=parent_folder_id)
    if log_fn:
        log_fn(f"Drive estructura: carpetas base listas bajo {link}")
    return DriveStructureSummary(
        user_folder_id=parent_folder_id,
        user_folder_link=link,
        folders_created=folders_created,
        folders_reused=folders_reused,
    )


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
    log_fn=None,
    job_id: str | None = None,
) -> DriveUploadSummary:
    if log_fn:
        log_fn(f"Drive upload: conectando con Google Drive, parent={parent_folder_id}")
    service = get_authenticated_drive_service()
    parent_folder_id = resolve_academic_workspace_folder_id(service, parent_folder_id, log_fn=log_fn)
    parent = validate_drive_folder(service, parent_folder_id)
    if log_fn:
        log_fn(f"Drive upload: carpeta destino validada {parent.get('name', '')} ({parent_folder_id})")

    folders_created = 0
    folders_reused = 0
    files_uploaded = 0
    files_overwritten = 0
    files_skipped = 0
    uploaded_files: list[dict[str, str]] = []

    entries = list(package_files)
    if include_zip is not None:
        entries.append(include_zip)
    if log_fn:
        log_fn(f"Drive upload: entradas a sincronizar={len(entries)}")

    folder_cache: dict[tuple[str, ...], str] = {}
    for local_path, arcname in entries:
        if not local_path.exists() or not local_path.is_file() or local_path.stat().st_size <= 0:
            files_skipped += 1
            if log_fn:
                log_fn(f"Drive upload: omitido archivo inválido {arcname} <- {local_path}")
            continue
        rel = (
            resolve_drive_relative_path(job_id, local_path, arcname)
            if job_id
            else drive_arcname_for_upload(arcname)
        )
        if not rel:
            files_skipped += 1
            if log_fn:
                log_fn(f"Drive upload: omitida ruta vacía tras normalizar {arcname}")
            continue
        parts = [part for part in Path(rel).parts if part]
        if len(parts) < 1:
            files_skipped += 1
            if log_fn:
                log_fn(f"Drive upload: omitida ruta inválida {arcname}")
            continue
        drive_name = parts[-1]
        if len(parts) == 1:
            target_folder_id = parent_folder_id
        else:
            folder_parts = tuple(parts[:-1])
            if folder_parts in folder_cache:
                target_folder_id = folder_cache[folder_parts]
            else:
                target_folder_id, created, reused = ensure_folder_path(service, parent_folder_id, folder_parts, log_fn=log_fn)
                folder_cache[folder_parts] = target_folder_id
                folders_created += created
                folders_reused += reused
        uploaded, overwritten = upload_file_overwrite(service, target_folder_id, local_path, drive_name)
        if overwritten:
            files_overwritten += 1
            if log_fn:
                log_fn(f"Drive upload: archivo sobrescrito {rel} ({uploaded.get('id', '')})")
        else:
            files_uploaded += 1
            if log_fn:
                log_fn(f"Drive upload: archivo subido {rel} ({uploaded.get('id', '')})")
        uploaded_files.append({
            "name": uploaded.get("name", drive_name),
            "id": uploaded.get("id", ""),
            "link": uploaded.get("webViewLink", ""),
            "path": rel,
            "overwritten": str(overwritten).lower(),
        })

    root_folder_id = parent_folder_id
    root_folder_link = FOLDER_URL.format(folder_id=root_folder_id)
    if log_fn:
        log_fn(f"Drive upload: fin sincronización link={root_folder_link}")

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
