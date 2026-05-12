from __future__ import annotations

import re
import unicodedata


def normalize_for_filename(value: str) -> str:
    value = value.strip().upper()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.replace("Ñ", "N").replace("ñ", "N")
    value = re.sub(r"[^A-Z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value)
    value = value.strip("_")
    return value or "TEMA"


def build_material_filename(nn: str, granule_code: str, tema: str, version: str, extension: str) -> str:
    tema_clean = normalize_for_filename(tema)
    return f"{nn}_{granule_code}_{tema_clean}_{version}{extension}"


def build_granule_folder_name(granule_code: str, tema: str) -> str:
    tema_clean = normalize_for_filename(tema)
    return f"{granule_code}_{tema_clean}"
