"""Hook opcional: si existe AUTOMATIZACION_GIF_JOB_ID y el job usa Drive por fases, sube cada archivo al terminar de guardarlo."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _PKG_ROOT / "backend"


def _ensure_backend_on_path() -> None:
    if str(_BACKEND) not in sys.path:
        sys.path.insert(0, str(_BACKEND))


PAQUETE = "PAQUETE_ACADEMICO"


def upload_package_file_if_configured(local_path: Path, arcname: str) -> None:
    job_id = (os.environ.get("AUTOMATIZACION_GIF_JOB_ID") or "").strip()
    if not job_id:
        return
    if not local_path.is_file():
        return
    _ensure_backend_on_path()
    try:
        from drive_incremental_sync import sync_single_package_entry

        sync_single_package_entry(job_id, local_path, arcname)
    except Exception as exc:
        print(f"Drive incremental: error al subir {local_path.name} — {exc}")


def upload_material_file_if_configured(material_output_path: Path) -> None:
    job_id = (os.environ.get("AUTOMATIZACION_GIF_JOB_ID") or "").strip()
    if not job_id:
        return
    _ensure_backend_on_path()
    try:
        from storage import get_materials_dir

        materials_root = get_materials_dir(job_id)
        rel = material_output_path.relative_to(materials_root).as_posix()
        arcname = f"{PAQUETE}/RECURSOS_COMPLEMENTARIOS/{rel}"
        upload_package_file_if_configured(material_output_path, arcname)
    except Exception as exc:
        print(f"Drive incremental: error material {material_output_path.name} — {exc}")
