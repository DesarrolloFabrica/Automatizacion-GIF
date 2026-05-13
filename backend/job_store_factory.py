from __future__ import annotations

import os

from job_store import JobStore
from job_store_local import LocalDiskJobStore
from job_store_gcs import GCSFileStore


def get_job_store() -> JobStore:
    """Factory para obtener la implementacion de JobStore.

    Por defecto usa LocalDiskJobStore.
    Si USE_FIRESTORE=1 en el futuro, retornara FirestoreJobStore.
    """
    if os.getenv("USE_FIRESTORE") == "1":
        raise NotImplementedError(
            "FirestoreJobStore no esta implementado aun. "
            "Configura USE_FIRESTORE=0 o deja la variable sin definir."
        )
    return LocalDiskJobStore()


def get_gcs_store() -> GCSFileStore:
    """Factory para obtener el GCSFileStore.

    Si GCS_BUCKET no esta configurado, retorna un store no disponible
    que hace no-op en todas las operaciones.
    """
    bucket = os.getenv("GCS_BUCKET")
    return GCSFileStore(bucket_name=bucket)
