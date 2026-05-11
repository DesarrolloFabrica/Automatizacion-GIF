"""
Nombres descriptivos exclusivos para Google Drive.

Los collectors y ZIP locales siguen usando rutas cortas (PAQUETE_ACADEMICO/...).
Aquí solo se transforma la ruta relativa que se usa al subir a Drive.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from storage import ACADEMIC_PACKAGE_ROOT, get_job_paths, read_job_metadata


def sanitize_drive_label(text: str) -> str:
    """Mayúsculas, sin tildes, Ñ→N, espacios/guiones→_, sin caracteres raros."""
    if not text or not str(text).strip():
        return ""
    s = unicodedata.normalize("NFKD", str(text))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("ñ", "N").replace("Ñ", "N")
    s = s.upper()
    s = re.sub(r"[^A-Z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "DOCUMENTO"


def sanitize_drive_filename_from_path(local_path: Path) -> str:
    """Nombre de archivo para Drive a partir del archivo real en disco."""
    stem = sanitize_drive_label(local_path.stem)
    ext = local_path.suffix.lower() or ""
    return f"{stem}{ext}"


def _strip_paquete_prefix(arcname: str) -> str:
    normalized = arcname.replace("\\", "/").strip("/")
    parts = [p for p in normalized.split("/") if p]
    if parts and parts[0] == ACADEMIC_PACKAGE_ROOT:
        parts = parts[1:]
    return "/".join(parts)


def load_plan_temas(job_id: str) -> list[str]:
    paths = get_job_paths(job_id)
    plan_path = paths["generated_dir"] / "plan_curso.json"
    if not plan_path.exists():
        return []
    try:
        data = json.loads(plan_path.read_text(encoding="utf-8"))
        temas = data.get("temas")
        if isinstance(temas, list):
            return [str(t) for t in temas]
    except (OSError, json.JSONDecodeError):
        pass
    return []


def granule_code_to_title(job_id: str) -> dict[str, str]:
    """G1..G5 -> etiqueta descriptiva (sin prefijo G en el título)."""
    temas = load_plan_temas(job_id)
    out: dict[str, str] = {}
    for i in range(1, 6):
        code = f"G{i}"
        tema = temas[i - 1] if i - 1 < len(temas) else ""
        label = sanitize_drive_label(tema) if tema and str(tema).strip() else ""
        out[code] = label
    return out


def drive_syllabus_display_name(job_id: str, local_path: Path) -> str:
    meta = read_job_metadata(job_id)
    raw = meta.get("syllabusOriginalName") or "syllabus.docx"
    stem = Path(str(raw)).stem
    ext = Path(str(raw)).suffix or local_path.suffix or ".docx"
    if not ext.startswith("."):
        ext = f".{ext}"
    body = sanitize_drive_label(stem)
    return f"{body}{ext.lower()}"


def drive_granule_display_basename(job_id: str, code: str, local_path: Path) -> str:
    gmap = granule_code_to_title(job_id)
    title = (gmap.get(code) or "").strip()
    if not title:
        m = re.match(rf"^{re.escape(code)}_(.+)\.docx$", local_path.name, re.IGNORECASE)
        if m:
            title = sanitize_drive_label(m.group(1).replace("-", " ").replace("_", " "))
    if not title:
        title = "GRANULO"
    return f"{code}_{title}.docx"


def drive_resource_folder_segment(code: str, job_id: str) -> str:
    gmap = granule_code_to_title(job_id)
    title = (gmap.get(code) or "").strip()
    if not title:
        title = "TEMA"
    return f"{code}_{title}"


def resolve_drive_relative_path(job_id: str, local_path: Path, package_arcname: str) -> str:
    """
    Convierte arcname del paquete local (con PAQUETE_ACADEMICO) en ruta relativa bajo la carpeta del usuario en Drive.
    """
    rel = _strip_paquete_prefix(package_arcname)
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    if not parts:
        return ""

    top = parts[0].upper()

    if top == "SYLLABUS":
        if local_path.suffix.lower() == ".docx":
            return f"SYLLABUS/{drive_syllabus_display_name(job_id, local_path)}"
        return f"SYLLABUS/{sanitize_drive_filename_from_path(local_path)}"

    if top == "CONTENIDOS" and len(parts) >= 2:
        fn = parts[-1]
        m = re.match(r"^(G[1-5])\.docx$", fn, re.IGNORECASE)
        if m:
            code = m.group(1).upper()
        else:
            m2 = re.match(r"^(G[1-5])_", fn, re.IGNORECASE)
            code = m2.group(1).upper() if m2 else "G1"
        return f"CONTENIDOS/{drive_granule_display_basename(job_id, code, local_path)}"

    if top == "ACTIVIDADES_MOODLE" and len(parts) >= 2:
        return f"ACTIVIDADES_MOODLE/{sanitize_drive_filename_from_path(local_path)}"

    if top == "RECURSOS_COMPLEMENTARIOS":
        rest = parts[1:]
        if not rest:
            return rel
        dir_parts = rest[:-1]

        if not dir_parts:
            return f"RECURSOS_COMPLEMENTARIOS/{sanitize_drive_filename_from_path(local_path)}"

        first = dir_parts[0]
        m_simple = re.fullmatch(r"(G[1-5])", first, re.IGNORECASE)
        if m_simple:
            code = m_simple.group(1).upper()
            folder_seg = drive_resource_folder_segment(code, job_id)
            fname = sanitize_drive_filename_from_path(local_path)
            if len(dir_parts) > 1:
                inner = "/".join(sanitize_drive_label(p) for p in dir_parts[1:])
                return f"RECURSOS_COMPLEMENTARIOS/{folder_seg}/{inner}/{fname}"
            return f"RECURSOS_COMPLEMENTARIOS/{folder_seg}/{fname}"

        safe_dirs = [sanitize_drive_label(d) for d in dir_parts]
        fname = sanitize_drive_filename_from_path(local_path)
        return f"RECURSOS_COMPLEMENTARIOS/{'/'.join(safe_dirs)}/{fname}"

    return rel
