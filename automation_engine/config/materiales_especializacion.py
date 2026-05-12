from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ENGINE_DIR.parent

ESPECIALIZACION_PROMPT_PATH = PROJECT_ROOT / "prompts" / "04_PROMPT_GENERACION_MATERIALES_ESPECIALIZACION.md"

MATERIALES_A_GENERAR = [
    {
        "nn": "02",
        "nombre": "FICHAS_DE_ESTUDIO_DE_EVIDENCIA",
        "seccion_prompt": "02. FICHAS DE ESTUDIO DE EVIDENCIA",
    },
    {
        "nn": "03",
        "nombre": "GLOSARIO_ESPECIALIZADO",
        "seccion_prompt": "03. GLOSARIO ESPECIALIZADO",
    },
    {
        "nn": "04",
        "nombre": "REVISTA_DOSSIER",
        "seccion_prompt": "04. REVISTA DOSSIER",
    },
    {
        "nn": "05",
        "nombre": "INFOGRAFIA_MODELO_O_RUTA",
        "seccion_prompt": "05. INFOGRAFÍA MODELO O RUTA",
    },
    {
        "nn": "06",
        "nombre": "PODCAST_DEBATE_EXPERTO",
        "seccion_prompt": "06. PODCAST DEBATE EXPERTO",
    },
    {
        "nn": "07",
        "nombre": "VIDEO_SOLUCION_O_PROCEDIMIENTO",
        "seccion_prompt": "07. VIDEO SOLUCIÓN O PROCEDIMIENTO",
    },
]

MATERIALES_RESERVADOS_FUTURO = [
    {
        "nn": "01",
        "nombre": "VIDEO_CASO_O_PROBLEMA",
        "seccion_prompt": "01. VIDEO CASO O PROBLEMA",
        "nota": "Fase futura: requiere guiones de presentadoras",
    },
]

VERSION_DEFECTO = "V01"
EXTENSION_DEFECTO = ".docx"


@dataclass
class MaterialConfig:
    nn: str
    nombre: str
    prompt_particular: str


@dataclass
class EspecializacionConfig:
    system_prompt: str
    materiales: list[MaterialConfig]
    version: str = VERSION_DEFECTO
    extension: str = EXTENSION_DEFECTO
