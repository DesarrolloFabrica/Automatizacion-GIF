from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


ENGINE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ENGINE_DIR.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"


@dataclass(frozen=True)
class MaterialDefinition:
    nn: str
    nombre: str
    seccion_prompt: str


@dataclass(frozen=True)
class CategoryConfig:
    key: str
    label: str
    guion_prompt_file: str
    materials_prompt_file: str | None
    materials_dir: str
    materials_route: str
    enabled_for_package: bool
    disabled_reason: str = ""
    expected_granules: int = 5
    version: str = "V01"
    extension: str = ".docx"
    reserved_materials: tuple[MaterialDefinition, ...] = ()
    materials: tuple[MaterialDefinition, ...] = ()

    @property
    def guion_prompt_path(self) -> Path:
        return PROMPTS_DIR / self.guion_prompt_file

    @property
    def materials_prompt_path(self) -> Path | None:
        if not self.materials_prompt_file:
            return None
        return PROMPTS_DIR / self.materials_prompt_file


def _material(nn: str, label: str) -> MaterialDefinition:
    normalized = label.upper()
    normalized = re.sub(r"[^A-ZÁÉÍÓÚÜÑ0-9]+", "_", normalized).strip("_")
    return MaterialDefinition(nn=nn, nombre=normalized, seccion_prompt=f"{nn}. {label}")


CATEGORIES: dict[str, CategoryConfig] = {
    "curso_rapido": CategoryConfig(
        key="curso_rapido",
        label="Curso rápido",
        guion_prompt_file="pregrado.md",
        materials_prompt_file="01_PROMPT_GENERACION_MATERIALES_CURSO_RAPIDO.md",
        materials_dir="materiales_curso_rapido",
        materials_route="materials",
        enabled_for_package=True,
        materials=(
            _material("01", "INFOGRAFÍA GUÍA RÁPIDA"),
            _material("02", "PODCAST INVITACIÓN"),
            _material("03", "VIDEO PRESENTACIÓN BREVE"),
            _material("04", "GLOSARIO BÁSICO"),
            _material("05", "VIDEO CORTO POR TEMA"),
            _material("06", "REVISTA GUÍA RÁPIDA"),
            _material("07", "FICHAS DE ESTUDIO RÁPIDAS"),
        ),
    ),
    "pregrado": CategoryConfig(
        key="pregrado",
        label="Pregrado",
        guion_prompt_file="pregrado.md",
        materials_prompt_file="02_PROMPT_GENERACION_MATERIALES_PREGRADO.md",
        materials_dir="materiales_pregrado",
        materials_route="materials",
        enabled_for_package=True,
        materials=(
            _material("01", "PODCAST INVITACIÓN"),
            _material("02", "INFOGRAFÍA UNA PÁGINA"),
            _material("03", "VIDEO PRESENTACIÓN DEL PROBLEMA"),
            _material("04", "GLOSARIO POR TEMA"),
            _material("05", "VIDEO POR TEMA"),
            _material("06", "REVISTA DIGITAL POR TEMA"),
            _material("07", "FICHAS DE ESTUDIO SCORM"),
        ),
    ),
    "diplomado": CategoryConfig(
        key="diplomado",
        label="Diplomado",
        guion_prompt_file="diplomado.md",
        materials_prompt_file="03_PROMPT_GENERACION_MATERIALES_DIPLOMADO.md",
        materials_dir="materiales_diplomado",
        materials_route="materials",
        enabled_for_package=True,
        materials=(
            _material("01", "VIDEO PRESENTACIÓN DEL PROBLEMA"),
            _material("02", "GLOSARIO TÉCNICO"),
            _material("03", "REVISTA DIGITAL POR TEMA"),
            _material("04", "VIDEO POR TEMA"),
            _material("05", "INFOGRAFÍA APLICADA"),
            _material("06", "PODCAST DE ANÁLISIS"),
            _material("07", "FICHAS DE ESTUDIO SCORM"),
        ),
    ),
    "especializacion": CategoryConfig(
        key="especializacion",
        label="Especialización",
        guion_prompt_file="especializacion.md",
        materials_prompt_file="04_PROMPT_GENERACION_MATERIALES_ESPECIALIZACION.md",
        materials_dir="materiales_especializacion",
        materials_route="materiales-especializacion",
        enabled_for_package=True,
        reserved_materials=(
            _material("01", "VIDEO CASO O PROBLEMA"),
        ),
        materials=(
            _material("02", "FICHAS DE ESTUDIO DE EVIDENCIA"),
            _material("03", "GLOSARIO ESPECIALIZADO"),
            _material("04", "REVISTA DOSSIER"),
            _material("05", "INFOGRAFÍA MODELO O RUTA"),
            _material("06", "PODCAST DEBATE EXPERTO"),
            _material("07", "VIDEO SOLUCIÓN O PROCEDIMIENTO"),
        ),
    ),
    "curso_externos_profesional": CategoryConfig(
        key="curso_externos_profesional",
        label="Curso externos profesional",
        guion_prompt_file="diplomado.md",
        materials_prompt_file="05_PROMPT_GENERACION_MATERIALES_CURSO_EXTERNOS_PROFESIONAL.md",
        materials_dir="materiales_curso_externos_profesional",
        materials_route="materials",
        enabled_for_package=True,
        materials=(
            _material("01", "VIDEO APERTURA ESTRATÉGICA"),
            _material("02", "PODCAST EXPERTO O TEASER"),
            _material("03", "INFOGRAFÍA MAPA DE VALOR"),
            _material("04", "VIDEO DEMOSTRACIÓN"),
            _material("05", "REVISTA GUÍA PREMIUM"),
            _material("06", "GLOSARIO OPERATIVO"),
            _material("07", "FICHAS DE ESTUDIO O MATRIZ"),
        ),
    ),
    "maestria": CategoryConfig(
        key="maestria",
        label="Maestría",
        guion_prompt_file="maestria.md",
        materials_prompt_file=None,
        materials_dir="materiales_maestria",
        materials_route="materials",
        enabled_for_package=False,
        disabled_reason="Maestría aún no tiene prompt de materiales configurado.",
    ),
}


def get_category(key: str) -> CategoryConfig:
    normalized = (key or "").strip().lower()
    if normalized not in CATEGORIES:
        raise KeyError(f"Categoría no válida: {key}")
    return CATEGORIES[normalized]


def active_package_categories() -> list[str]:
    return [key for key, config in CATEGORIES.items() if config.enabled_for_package]


def validate_category_prompts(category: CategoryConfig) -> None:
    if not category.guion_prompt_path.exists():
        raise FileNotFoundError(f"No existe el prompt principal para {category.label}: {category.guion_prompt_path}")
    if category.enabled_for_package:
        if category.materials_prompt_path is None:
            raise FileNotFoundError(f"{category.label} no tiene prompt de materiales configurado.")
        if not category.materials_prompt_path.exists():
            raise FileNotFoundError(f"No existe el prompt de materiales para {category.label}: {category.materials_prompt_path}")


def public_categories_payload() -> list[dict]:
    return [
        {
            "key": config.key,
            "label": config.label,
            "enabledForPackage": config.enabled_for_package,
            "disabledReason": config.disabled_reason,
            "materialsDir": config.materials_dir,
            "materialsRoute": config.materials_route,
            "expectedGranules": config.expected_granules,
            "expectedMaterialsPerGranule": len(config.materials),
            "deliverables": [
                {"nn": material.nn, "name": material.nombre, "section": material.seccion_prompt}
                for material in config.materials
            ],
            "reservedDeliverables": [
                {"nn": material.nn, "name": material.nombre, "section": material.seccion_prompt}
                for material in config.reserved_materials
            ],
        }
        for config in CATEGORIES.values()
    ]
