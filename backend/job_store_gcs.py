from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger(__name__)


class GCSFileStore:
    """Manejo de archivos de jobs en Google Cloud Storage.

    Si GCS_BUCKET no esta configurado, todas las operaciones son no-op
    y el sistema usa el almacenamiento local existente.
    """

    def __init__(self, bucket_name: str | None = None):
        self._bucket_name = bucket_name or os.getenv("GCS_BUCKET")
        self._client = None
        self._bucket = None
        if self._bucket_name:
            self._init_client()

    @property
    def is_available(self) -> bool:
        return self._bucket is not None

    def _init_client(self) -> None:
        try:
            from google.cloud import storage
            self._client = storage.Client()
            self._bucket = self._client.bucket(self._bucket_name)
            LOGGER.info("GCS_BUCKET detectado: %s — GCSFileStore inicializado", self._bucket_name)
        except Exception as exc:
            LOGGER.warning("No se pudo inicializar GCSFileStore para bucket %s: %s", self._bucket_name, exc)
            self._client = None
            self._bucket = None

    def _blob_path(self, job_id: str, gcs_path: str) -> str:
        return f"jobs/{job_id}/{gcs_path.lstrip('/')}"

    def upload_file(self, job_id: str, local_path: Path | str, gcs_path: str) -> str | None:
        """Sube un archivo local a GCS.

        Returns:
            URL publica del blob o None si GCS no esta disponible.
        """
        if not self.is_available:
            return None
        try:
            local = Path(local_path)
            if not local.exists():
                LOGGER.warning("GCS upload: archivo local no existe: %s", local)
                return None
            blob_path = self._blob_path(job_id, gcs_path)
            blob = self._bucket.blob(blob_path)
            blob.upload_from_filename(str(local))
            LOGGER.info("GCS upload: %s -> gs://%s/%s", local.name, self._bucket_name, blob_path)
            return f"gs://{self._bucket_name}/{blob_path}"
        except Exception as exc:
            LOGGER.error("GCS upload error para %s: %s", gcs_path, exc)
            return None

    def download_file(self, job_id: str, gcs_path: str, local_path: Path | str) -> bool:
        """Descarga un archivo desde GCS a ruta local.

        Returns:
            True si la descarga fue exitosa.
        """
        if not self.is_available:
            return False
        try:
            local = Path(local_path)
            local.parent.mkdir(parents=True, exist_ok=True)
            blob_path = self._blob_path(job_id, gcs_path)
            blob = self._bucket.blob(blob_path)
            if not blob.exists():
                LOGGER.warning("GCS download: blob no existe: %s", blob_path)
                return False
            blob.download_to_filename(str(local))
            LOGGER.info("GCS download: gs://%s/%s -> %s", self._bucket_name, blob_path, local.name)
            return True
        except Exception as exc:
            LOGGER.error("GCS download error: %s", exc)
            return False

    def list_files(self, job_id: str, prefix: str = "") -> list[str]:
        """Lista archivos en GCS para un job con un prefijo dado.

        Returns:
            Lista de nombres de archivo (sin el prefijo completo).
        """
        if not self.is_available:
            return []
        try:
            search_prefix = self._blob_path(job_id, prefix)
            blobs = self._bucket.list_blobs(prefix=search_prefix)
            result = []
            for blob in blobs:
                if blob.name.endswith("/"):
                    continue
                relative = blob.name[len(self._blob_path(job_id, "")):]
                result.append(relative)
            return sorted(result)
        except Exception as exc:
            LOGGER.error("GCS list files error: %s", exc)
            return []

    def file_exists(self, job_id: str, gcs_path: str) -> bool:
        """Verifica si un archivo existe en GCS."""
        if not self.is_available:
            return False
        try:
            blob_path = self._blob_path(job_id, gcs_path)
            blob = self._bucket.blob(blob_path)
            return blob.exists()
        except Exception as exc:
            LOGGER.error("GCS file_exists error: %s", exc)
            return False

    def delete_job_files(self, job_id: str) -> bool:
        """Elimina todos los archivos de un job en GCS.

        Returns:
            True si la eliminacion fue exitosa.
        """
        if not self.is_available:
            return False
        try:
            prefix = self._blob_path(job_id, "")
            blobs = list(self._bucket.list_blobs(prefix=prefix))
            if blobs:
                self._bucket.delete_blobs(blobs)
                LOGGER.info("GCS delete: %d archivos eliminados para job %s", len(blobs), job_id)
            return True
        except Exception as exc:
            LOGGER.error("GCS delete job files error: %s", exc)
            return False

    def create_signed_url(self, job_id: str, gcs_path: str, expiration_minutes: int = 15) -> str | None:
        """Genera una URL firmada para acceso temporal a un archivo.

        Returns:
            URL firmada o None si GCS no esta disponible.
        """
        if not self.is_available:
            return None
        try:
            from datetime import timedelta
            blob_path = self._blob_path(job_id, gcs_path)
            blob = self._bucket.blob(blob_path)
            if not blob.exists():
                return None
            url = blob.generate_signed_url(
                expiration=timedelta(minutes=expiration_minutes),
                method="GET",
            )
            return url
        except Exception as exc:
            LOGGER.error("GCS signed URL error: %s", exc)
            return None

    def upload_directory(self, job_id: str, local_dir: Path | str, gcs_prefix: str) -> list[str]:
        """Sube todos los archivos de un directorio local a GCS.

        Returns:
            Lista de URLs de los archivos subidos.
            No falla toda la operacion si un archivo individual falla.
        """
        if not self.is_available:
            return []
        local = Path(local_dir)
        if not local.exists() or not local.is_dir():
            return []
        uploaded = []
        failed = []
        for file_path in sorted(local.rglob("*")):
            if file_path.is_file():
                relative = file_path.relative_to(local)
                gcs_path = f"{gcs_prefix}/{relative.as_posix()}"
                url = self.upload_file(job_id, file_path, gcs_path)
                if url:
                    uploaded.append(url)
                else:
                    failed.append(gcs_path)
        if failed:
            LOGGER.warning("GCS upload_directory: %d archivos fallaron para job %s: %s", len(failed), job_id, failed[:5])
        return uploaded
