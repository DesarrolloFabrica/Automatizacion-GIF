"""Subida incremental a Google Drive desde procesos hijo (generate_*), vía env AUTOMATIZACION_GIF_JOB_ID."""

from __future__ import annotations

from pathlib import Path

from drive_service import upload_academic_package_to_drive
from storage import read_job_metadata


def sync_single_package_entry(job_id: str, local_path: Path, arcname: str) -> None:
    """Sube un archivo al paquete Drive si el job tiene drivePhasedSync. No actualiza contadores acumulados (evita duplicar con la sync por fase)."""
    meta = read_job_metadata(job_id)
    if not meta.get("drivePhasedSync") or not meta.get("driveParentFolderId"):
        return
    if not local_path.is_file() or local_path.stat().st_size <= 0:
        return
    parent = str(meta.get("driveWorkspaceFolderId") or meta["driveParentFolderId"])

    def log_print(msg: str) -> None:
        print(f"Drive incremental: {msg}")

    summary = upload_academic_package_to_drive(
        parent_folder_id=parent,
        package_files=[(local_path, arcname)],
        include_zip=None,
        log_fn=log_print,
        job_id=job_id,
    )
    for item in summary.uploaded_files:
        print(
            "Drive incremental: publicado "
            f"{item.get('path', arcname)} "
            f"link={item.get('link', '')}"
        )
