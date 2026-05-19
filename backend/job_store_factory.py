from __future__ import annotations

import os

from job_store import JobStore
from job_store_local import LocalDiskJobStore
from job_store_gcs import GCSFileStore


def get_job_store() -> JobStore:
    """Factory para obtener la implementacion de JobStore.

    Usa LocalDiskJobStore para desarrollo local.
    """
    return LocalDiskJobStore()


def get_gcs_store() -> GCSFileStore:
    """Factory para obtener el GCSFileStore.

    Si GCS_BUCKET no esta configurado, retorna un store no disponible
    que hace no-op en todas las operaciones.
    """
    bucket = os.getenv("GCS_BUCKET")
    return GCSFileStore(bucket_name=bucket)
