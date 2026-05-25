from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any


class JobStore(ABC):
    """Interfaz abstracta para persistencia de metadata de jobs.

    Implementaciones:
    - LocalDiskJobStore: desarrollo local (JSON en disco)
    """

    @abstractmethod
    def create_job(self, job_id: str, metadata: dict[str, Any]) -> None:
        """Crea un registro de job con metadata inicial."""

    @abstractmethod
    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Obtiene la metadata completa de un job."""

    @abstractmethod
    def update_job(self, job_id: str, updates: dict[str, Any]) -> None:
        """Actualiza campos parciales de un job."""

    @abstractmethod
    def update_phase_status(self, job_id: str, phase: str, status: str, files: list[str] | None = None) -> None:
        """Actualiza el estado de una fase especifica."""

    @abstractmethod
    def append_log(self, job_id: str, line: str) -> None:
        """Agrega una linea al log del job."""

    @abstractmethod
    def get_logs(self, job_id: str, max_lines: int = 1000) -> list[str]:
        """Obtiene las ultimas N lineas del log."""

    @abstractmethod
    def set_expires_at(self, job_id: str, expires_at: datetime) -> None:
        """Define la fecha de expiracion del job."""

    @abstractmethod
    def save_file_manifest(self, job_id: str, manifest: list[dict[str, Any]]) -> None:
        """Guarda el manifiesto de archivos generados."""

    @abstractmethod
    def get_file_manifest(self, job_id: str) -> list[dict[str, Any]]:
        """Obtiene el manifiesto de archivos del job."""
