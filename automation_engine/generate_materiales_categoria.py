from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import traceback
import concurrent.futures
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Tuple

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from automation_engine.config.categories import CategoryConfig, MaterialDefinition, get_category, validate_category_prompts
from automation_engine.generate_materiales_especializacion import (
    ARTIFACT_PATTERNS,
    MIN_RESPONSE_CHARS,
    build_material_filename,
    clean_ai_response,
    discover_granules,
    extract_docx_text,
    extract_material_prompt,
    extract_system_prompt,
    generate_material_content,
    _parse_markdown_tables,
    resolve_layout_renderer_key,
    save_docx_with_structure,
    validate_material_content,
)
from automation_engine.utils.naming import build_granule_folder_name
from automation_engine.utils.openai_client import get_openai_client, get_openai_model


def _log(msg: str) -> None:
    print(msg, flush=True)


def safe_int_env(name: str, default: int, min_value: int, max_value: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        _log(f"[Materials][WARN] {name} invalido={raw!r}; usando default={default}")
        return default
    if value < min_value or value > max_value:
        clamped = max(min_value, min(value, max_value))
        _log(f"[Materials][WARN] {name} fuera de rango={value}; usando {clamped}")
        return clamped
    return value


MATERIALS_PARALLEL = os.getenv("MATERIALS_PARALLEL", "0") == "1"
MATERIALS_MAX_WORKERS = safe_int_env("MATERIALS_MAX_WORKERS", 4, 1, 8)
MATERIALS_API_RETRIES = safe_int_env("MATERIALS_API_RETRIES", 2, 0, 5)
MATERIALS_REPAIR_ATTEMPTS = safe_int_env("MATERIALS_REPAIR_ATTEMPTS", 1, 0, 3)

FORBIDDEN_INTERNAL_ARTIFACTS = (
    "Pregunta para completar",
    "Sección donde debería estar",
    "Seccion donde deberia estar",
    "Recursos visuales sugeridos",
)

RESOURCE_PROFILES = {
    "podcast": {
        "words": "700-1200 palabras",
        "identity": "tono humano, conversacional y oral; storytelling; frases cortas; evita parrafos densos y tono de articulo academico",
    },
    "infografia": {
        "words": "350-500 palabras maximo",
        "identity": "sintesis visual; bullets cortos; frases de impacto; no desarrollar como revista ni ensayo",
    },
    "video_presentacion": {
        "words": "1200-1800 palabras maximo",
        "identity": "storytelling problema -> tension -> solucion; maximo 6-7 escenas utiles; no repetir teoria completa",
    },
    "video_tema": {
        "words": "900-1400 palabras maximo",
        "identity": "tutorial didactico; explica conceptos y ejemplos rapidos; mas pedagogico que emocional",
    },
    "glosario": {
        "words": "120-180 palabras maximo por termino",
        "identity": "ultra concreto; definicion + aplicacion; sin parrafos largos",
    },
    "revista": {
        "words": "1800-2600 palabras maximo",
        "identity": "profundidad conceptual; reflexion; aplicacion profesional; analisis amplio",
    },
    "fichas": {
        "words": "120 palabras maximo por lado de ficha",
        "identity": "formato resumido; memorizacion y aplicacion; no mini articulos",
    },
}

REPETITIVE_PHRASES = (
    "transformar datos en decisiones",
    "datos brutos",
    "toma de decisiones",
    "herramienta fundamental",
)


def _normalize_meta(value: str) -> str:
    value = (value or "").strip().lower()
    replacements = str.maketrans("áéíóúüñ", "aeiouun")
    value = value.translate(replacements)
    value = re.sub(r"\s+", " ", value)
    return value


def _extract_line_value(text: str, label: str) -> str:
    match = re.search(rf"{re.escape(label)}\s*:\s*([^\n\r.]+)", text or "", flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _find_plan_curso(generated_dir: Path, output_base: Path) -> Path | None:
    candidates = [
        generated_dir / "plan_curso.json",
        generated_dir.parent / "plan_curso.json",
        output_base / "plan_curso.json",
        output_base.parent / "plan_curso.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _load_plan_metadata(generated_dir: Path, output_base: Path) -> dict:
    plan_path = _find_plan_curso(generated_dir, output_base)
    if not plan_path:
        searched = [
            generated_dir / "plan_curso.json",
            generated_dir.parent / "plan_curso.json",
            output_base / "plan_curso.json",
            output_base.parent / "plan_curso.json",
        ]
        raise FileNotFoundError(
            "plan_curso.json es obligatorio para generar materiales. Buscado en: "
            + "; ".join(str(path) for path in searched)
        )
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    _log(f"plan keys={sorted(data.keys())}")
    return {
        "path": str(plan_path),
        "subject": data.get("asignatura", ""),
        "program": data.get("programa", ""),
        "category": data.get("nivel", data.get("categoria", "")),
        "topics": data.get("temas", []),
    }


def _validate_granule_metadata(plan_metadata: dict, category_key: str, granule: dict, guion_text: str) -> dict:
    subject = _extract_line_value(guion_text, "ASIGNATURA") or plan_metadata.get("subject", "")
    program = _extract_line_value(guion_text, "PROGRAMA") or plan_metadata.get("program", "")
    granule_code = granule["code"]
    topic_index = int(re.sub(r"\D", "", granule_code) or "0") - 1
    expected_topic = ""
    topics = plan_metadata.get("topics") or []
    if 0 <= topic_index < len(topics):
        expected_topic = topics[topic_index]

    if plan_metadata:
        if _normalize_meta(program) != _normalize_meta(plan_metadata.get("program", "")):
            raise ValueError(
                f"Metadata contaminada en {granule_code}: programa={program!r} no coincide con plan={plan_metadata.get('program')!r}"
            )
        if _normalize_meta(subject) != _normalize_meta(plan_metadata.get("subject", "")):
            raise ValueError(
                f"Metadata contaminada en {granule_code}: asignatura={subject!r} no coincide con plan={plan_metadata.get('subject')!r}"
            )
        expected_category = plan_metadata.get("category", "")
        if expected_category and _normalize_meta(category_key) != _normalize_meta(expected_category):
            raise ValueError(
                f"Metadata contaminada: categoria={category_key!r} no coincide con plan={expected_category!r}"
            )

    return {
        "subject": subject,
        "program": program,
        "category": category_key,
        "granule": granule_code,
        "topic": granule.get("tema", ""),
        "expected_topic": expected_topic,
    }


def _material_profile_key(material_nn: str, material_nombre: str) -> str:
    name = _normalize_meta(material_nombre)
    if "podcast" in name:
        return "podcast"
    if "infografia" in name:
        return "infografia"
    if "video presentacion" in name or material_nn == "03":
        return "video_presentacion"
    if "video por tema" in name or "video corto" in name or material_nn == "05":
        return "video_tema"
    if "glosario" in name:
        return "glosario"
    if "revista" in name:
        return "revista"
    if "fichas" in name or "scorm" in name:
        return "fichas"
    return ""


def _profile_instructions(material_nn: str, material_nombre: str) -> str:
    key = _material_profile_key(material_nn, material_nombre)
    profile = RESOURCE_PROFILES.get(key)
    if not profile:
        return ""
    return f"""IDENTIDAD PEDAGOGICA DEL RECURSO:
- {profile['identity']}.
- Longitud objetivo: {profile['words']}.
- Evita reutilizar introducciones, parrafos o frases de otros recursos.
- No repitas literalmente expresiones como: {', '.join(REPETITIVE_PHRASES)}.
""".strip()


def _count_words(text: str) -> int:
    return len(re.findall(r"\b[\wÁÉÍÓÚáéíóúÑñÜü]+\b", text or ""))


def _semantic_repetition_warnings(content: str, material_nombre: str) -> list[str]:
    warnings = []
    normalized = _normalize_meta(content)
    for phrase in REPETITIVE_PHRASES:
        count = normalized.count(_normalize_meta(phrase))
        if count >= 3:
            warnings.append(f"Repeticion frecuente en {material_nombre}: '{phrase}' aparece {count} veces")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content or "") if len(p.strip()) > 80]
    seen = set()
    for paragraph in paragraphs:
        key = _normalize_meta(paragraph[:180])
        if key in seen:
            warnings.append(f"Parrafo repetido o muy similar detectado en {material_nombre}")
            break
        seen.add(key)
    return warnings


def _identity_warnings(content: str, material_nn: str, material_nombre: str) -> list[str]:
    warnings = []
    key = _material_profile_key(material_nn, material_nombre)
    lines = [line.strip() for line in (content or "").splitlines() if line.strip()]
    long_lines = [line for line in lines if len(line.split()) > 45]
    bullet_lines = [line for line in lines if line.startswith(("-", "•", "*"))]
    word_count = _count_words(content)

    if key == "podcast" and len(long_lines) > max(3, len(lines) // 3):
        warnings.append("Podcast con exceso de parrafos academicos o densos; debe sentirse oral/conversacional")
    if key == "infografia":
        if word_count > 550:
            warnings.append(f"Infografia demasiado extensa: {word_count} palabras")
        if len(long_lines) > 3:
            warnings.append("Infografia contiene demasiados parrafos largos; debe usar bullets/bloques visuales")
    if key == "fichas" and len(long_lines) > 2:
        warnings.append("Fichas SCORM contienen bloques tipo ensayo; deben ser tarjetas cortas")
    if key == "glosario" and len(long_lines) > 4:
        warnings.append("Glosario demasiado extenso; cada termino debe ser definicion + aplicacion breve")
    if key == "revista" and word_count < 900:
        warnings.append(f"Revista posiblemente superficial: {word_count} palabras")
    if key in {"infografia", "fichas"} and len(bullet_lines) < 4:
        warnings.append(f"{material_nombre} necesita estructura mas esquematica con bullets/bloques")
    return warnings


def _metadata_contamination_warnings(content: str, metadata: dict) -> list[str]:
    warnings = []
    normalized = _normalize_meta(content)
    if "videojuegos" in normalized or all(token in normalized for token in ("diseno", "desarrollo", "videojuegos")):
        warnings.append("Contaminacion de metadata detectada: programa/asignatura ajena de videojuegos")
    expected_program = metadata.get("program", "")
    expected_subject = metadata.get("subject", "")
    if expected_program and _normalize_meta(expected_program) not in normalized[:3000]:
        warnings.append(f"Programa esperado no aparece de forma clara en el recurso: {expected_program}")
    if expected_subject and _normalize_meta(expected_subject) not in normalized[:3000]:
        warnings.append(f"Asignatura esperada no aparece de forma clara en el recurso: {expected_subject}")
    return warnings


def _contamination_excerpt(content: str) -> str:
    if not content:
        return ""
    normalized = _normalize_meta(content)
    index = normalized.find("videojuegos")
    if index < 0:
        index = normalized.find("diseno")
    if index < 0:
        return ""
    start = max(0, index - 100)
    end = min(len(content), index + 180)
    return re.sub(r"\s+", " ", content[start:end]).strip()


def _abort_metadata_contamination(content: str, metadata: dict, source: str, resource: str) -> None:
    warnings = _metadata_contamination_warnings(content, metadata)
    if not warnings:
        return
    _log("[Materials][Contamination]")
    _log(f"resource={resource}")
    _log("phrase=metadata ajena de videojuegos")
    _log(f"source={source}")
    _log(f"excerpt={_contamination_excerpt(content)}")
    raise ValueError(f"Contaminacion de metadata detectada en {source}; se aborta antes de guardar DOCX.")


def _post_generation_warnings(content: str, material_nn: str, material_nombre: str, metadata: dict) -> list[str]:
    warnings = []
    warnings.extend(_metadata_contamination_warnings(content, metadata))
    warnings.extend(_identity_warnings(content, material_nn, material_nombre))
    warnings.extend(_semantic_repetition_warnings(content, material_nombre))
    return warnings


def _remove_internal_artifact_lines(content: str) -> str:
    cleaned_lines = []
    artifact_patterns = [
        r"pregunta\s+para\s+completar",
        r"secci[oó]n\s+donde\s+deber[ií]a\s+estar",
        r"instrucciones?\s+internas?",
        r"placeholder",
        r"texto\s+pendiente",
        r"pendiente\s+por\s+completar",
        r"rellenar\s+aqu[ií]",
        r"\[\s*(?:completar|pendiente|insertar|agregar)[^\]]*\]",
    ]
    for raw_line in (content or "").splitlines():
        normalized = _normalize_meta(raw_line)
        if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in artifact_patterns):
            continue
        cleaned_lines.append(raw_line)
    return "\n".join(cleaned_lines).strip()


def _has_forbidden_visible_artifact(content: str) -> str | None:
    normalized = _normalize_meta(content)
    if "videojuegos" in normalized or all(token in normalized for token in ("diseno", "desarrollo", "videojuegos")):
        return "metadata ajena de videojuegos"
    for phrase in FORBIDDEN_INTERNAL_ARTIFACTS:
        if _normalize_meta(phrase) in normalized:
            return phrase
    return None


def _dedupe_repeated_lines(content: str) -> str:
    seen = set()
    lines = []
    for raw_line in (content or "").splitlines():
        key = _normalize_meta(raw_line)
        if key and len(key) > 40:
            if key in seen:
                continue
            seen.add(key)
        lines.append(raw_line)
    return "\n".join(lines).strip()


def _video_has_duplicate_table_and_development(content: str, material_nn: str, material_nombre: str) -> bool:
    profile = _material_profile_key(material_nn, material_nombre)
    if profile not in {"video_presentacion", "video_tema"}:
        return False
    normalized = _normalize_meta(content)
    table_scene_count = len(re.findall(r"\|[^\n]*(?:escena|tiempo|narracion|visual)[^\n]*\|", normalized))
    scene_heading_count = len(re.findall(r"(?:^|\n)\s*(?:escena|secuencia)\s+\d+", normalized))
    return table_scene_count >= 3 and scene_heading_count >= 3


def _prepare_material_for_save(content: str, material_nn: str, material_nombre: str) -> str:
    prepared = _remove_internal_artifact_lines(content)
    prepared = _dedupe_repeated_lines(prepared)
    forbidden = _has_forbidden_visible_artifact(prepared)
    if forbidden:
        raise ValueError(f"Artefacto prohibido visible antes de guardar: {forbidden}")
    if _video_has_duplicate_table_and_development(prepared, material_nn, material_nombre):
        raise ValueError(
            "Video contiene tabla de escenas y desarrollo duplicado; no se guarda recurso con estructura redundante."
        )
    return prepared


def build_material_blueprint(
    category: CategoryConfig,
    materials_to_generate: tuple[MaterialDefinition, ...],
    granules: list[dict],
    prompt_text: str,
    output_base: Path,
    flat_output: bool,
    plan_metadata: dict,
) -> dict:
    system_prompt = extract_system_prompt(prompt_text)
    material_prompts = {}
    for material in materials_to_generate:
        material_prompts[material.nn] = extract_material_prompt(prompt_text, material.seccion_prompt)

    granule_texts = {}
    granule_metadata = {}
    for granule in granules:
        try:
            text = extract_docx_text(granule["path"])
        except Exception as exc:
            granule_texts[granule["code"]] = None
            granule_metadata[granule["code"]] = {"error": str(exc)}
            continue
        granule_texts[granule["code"]] = text
        granule_metadata[granule["code"]] = _validate_granule_metadata(plan_metadata, category.key, granule, text)

    tasks = []
    for granule in granules:
        granule_code = granule["code"]
        tema = granule["tema"]
        tema_corto = granule["tema_corto"]
        granule_output_dir = output_base if flat_output else output_base / build_granule_folder_name(granule_code, tema)
        granule_output_dir.mkdir(parents=True, exist_ok=True)

        for material in materials_to_generate:
            material_filename = build_material_filename(
                material.nn, granule_code, material.nombre, tema_corto, category.version, category.extension
            )
            tasks.append({
                "granule_code": granule_code,
                "tema": tema,
                "tema_corto": tema_corto,
                "material_nn": material.nn,
                "material_nombre": material.nombre,
                "material_filename": material_filename,
                "material_output_path": str(granule_output_dir / material_filename),
                "prompt_particular": material_prompts[material.nn],
                "guion_text": granule_texts.get(granule_code),
                "guion_error": granule_texts.get(granule_code) is None,
                "metadata": granule_metadata.get(granule_code, {}),
            })

    return {
        "system_prompt": system_prompt,
        "material_prompts": material_prompts,
        "granule_texts": granule_texts,
        "granule_metadata": granule_metadata,
        "plan_metadata": plan_metadata,
        "tasks": tasks,
        "category_key": category.key,
        "category_label": category.label,
        "category_version": category.version,
        "category_extension": category.extension,
    }


def build_material_tasks(blueprint: dict) -> list[dict]:
    return blueprint["tasks"]


def _call_openai_with_retry(client, model, system_prompt, user_prompt, max_tokens, temperature, max_retries=MATERIALS_API_RETRIES):
    import httpx
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=120.0,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            last_exc = exc
            status_code = getattr(exc, "status_code", None)
            if status_code in (429, 500, 502, 503, 504) or isinstance(exc, (httpx.TimeoutException, httpx.RemoteProtocolError, OSError)):
                if attempt < max_retries:
                    backoff = 2 ** (attempt + 1)
                    time.sleep(backoff)
                    continue
            else:
                raise
    raise last_exc


def generate_single_material(
    task: dict,
    blueprint: dict,
    model: str,
    max_tokens: int,
    temperature: float,
    disable_drive_upload: bool,
    debug_dir: Path | None,
) -> dict:
    granule_code = task["granule_code"]
    material_nn = task["material_nn"]
    material_nombre = task["material_nombre"]
    material_filename = task["material_filename"]
    material_output_path = Path(task["material_output_path"])
    tema = task["tema"]

    if task["guion_error"] or not task["guion_text"]:
        return {
            "granule_code": granule_code,
            "material_nn": material_nn,
            "material_nombre": material_nombre,
            "status": "error",
            "error": f"Error leyendo granulo {granule_code}",
            "duration": 0.0,
            "warnings": [],
            "repair_attempts": 0,
        }

    system_prompt = blueprint["system_prompt"]
    prompt_particular = task["prompt_particular"]
    guion_text = task["guion_text"]
    tema_corto = task["tema_corto"]
    metadata = task.get("metadata", {})
    if metadata.get("error"):
        raise ValueError(f"Metadata invalida para {granule_code}: {metadata['error']}")
    category_key = blueprint["category_key"]
    category_label = blueprint["category_label"]
    category_version = blueprint["category_version"]
    category_extension = blueprint["category_extension"]
    layout_nn = resolve_layout_renderer_key(category_key, material_nn, material_nombre)
    client = get_openai_client()
    _log("[Materials][Metadata]")
    _log(f"program={metadata.get('program', '')}")
    _log(f"subject={metadata.get('subject', '')}")
    _log(f"granule={granule_code} {tema}")
    _log(f"granule from=filename/docx value={granule_code} {tema}")
    _log(f"category={category_key}")
    profile_rules = _profile_instructions(material_nn, material_nombre)

    user_prompt = f"""Programa oficial: {metadata.get('program', '')}
Asignatura oficial: {metadata.get('subject', '')}
Nivel oficial: {metadata.get('category', '')}
Granulo oficial: {granule_code} - {tema}

Esta prohibido mencionar cualquier programa, asignatura o especializacion distinta.

Quiero generar un material derivado para {category_label.upper()}.

Pego a continuacion el GUION MAESTRO aprobado del tema:

{guion_text}

Datos del material:
- Programa correcto: {metadata.get('program', '')}
- Asignatura correcta: {metadata.get('subject', '')}
- Categoria correcta: {category_key}
- Categoria academica: {category_label}
- Codigo GX: {granule_code}
- Nombre exacto del tema: {tema}
- Nombre corto para archivo: {tema_corto}
- Version: {category_version}
- Material a generar: {material_nombre.replace("_", " ")}
- Formato esperado: DOCX (contenido en tabla)
- Cierre integrado ira en: NO APLICA

Instrucciones especificas para este material:

{prompt_particular}

{profile_rules}

REGLAS CRITICAS DE SALIDA:
1. NO incluyas la frase "Datos recibidos" ni ninguna frase de confirmacion de instrucciones.
2. NO confirmes que entendiste las instrucciones. Entrega directamente el contenido final.
3. NO uses markdown fences (```text, ```, ```markdown).
4. NO inventes fuentes, terminos, casos, tecnologias ni datos que no esten en el GUION MAESTRO.
5. Si una informacion no esta en el guion maestro, marca como "Informacion faltante" en una tabla.
6. Entrega unicamente el contenido del material solicitado en formato tabla markdown.
7. No generes los demas materiales. Solo este.
8. No uses ni menciones metadata ajena al curso actual, otro programa académico, otra asignatura o una categoría distinta.
9. Antes de responder verifica internamente que programa, asignatura, categoria y granulo coinciden con los datos correctos indicados arriba.

REGLAS EDITORIALES MINIMAS:
1. Aunque la estructura tecnica se entregue en tabla markdown para validacion, redacta cada celda con lenguaje editorial profesional.
2. Evita fragmentos frios o telegraficos: usa parrafos naturales, legibles y listos para maquetacion academica.
3. Cada recurso debe sentirse autentico para la categoria {category_label}, no como otra categoria con nombre cambiado.
4. Las referencias, fuentes y conexiones de ruta deben mantenerse claras, pero sin saturar el texto principal.
5. Si el material incluye un bloque llamado "Conceptos clave", no lo resumas como glosario. Desarrollalo como seccion editorial con apertura general y conceptos explicados en profundidad, respetando la extension indicada en el prompt particular.

Genera unicamente el material solicitado.
""".strip()

    start = time.time()
    raw_content = None
    content = None
    val_warnings = []
    repair_attempts = 0
    error_msg = None

    try:
        raw_content = _call_openai_with_retry(client, model, system_prompt, user_prompt, max_tokens, temperature)
        resource_id = f"{granule_code} {material_nombre}"
        _abort_metadata_contamination(raw_content, metadata, "raw_content", resource_id)
        content = clean_ai_response(raw_content)
        _abort_metadata_contamination(content, metadata, "cleaned_content", resource_id)
        content = _prepare_material_for_save(content, material_nn, material_nombre)
        if not content or len(content) < MIN_RESPONSE_CHARS:
            raise ValueError(f"Respuesta insuficiente ({len(content)} chars). Minimo: {MIN_RESPONSE_CHARS}.")

        if not layout_nn:
            raise ValueError(
                f"No hay plantilla DOCX definida para categoría {category_key!r} "
                f"material nn={material_nn!r} ({material_nombre})."
            )

        for repair_attempt in range(MATERIALS_REPAIR_ATTEMPTS + 1):
            val_status, val_warnings = validate_material_content(layout_nn, content, category_key, material_nn)
            val_warnings.extend(_post_generation_warnings(content, material_nn, material_nombre, metadata))
            critical_warnings = [w for w in val_warnings if any(kw in w.lower() for kw in ["incompleto", "insuficiente", "esperaban"])]
            critical_warnings.extend([w for w in val_warnings if "contaminacion de metadata" in w.lower()])
            if critical_warnings and repair_attempt < MATERIALS_REPAIR_ATTEMPTS:
                repair_attempts += 1
                repair_temp = min(temperature, 0.3)
                repair_prompt = f"{user_prompt}\n\nADVERTENCIA CRITICA DETECTADA: {'; '.join(critical_warnings)}\n\nRepara el contenido desde cero, elimina cualquier metadata ajena y diferencia pedagogicamente este recurso."
                raw_content = _call_openai_with_retry(client, model, system_prompt, repair_prompt, max_tokens, repair_temp)
                _abort_metadata_contamination(raw_content, metadata, "raw_content tras repair", resource_id)
                content = clean_ai_response(raw_content)
                _abort_metadata_contamination(content, metadata, "cleaned_content tras repair", resource_id)
                content = _prepare_material_for_save(content, material_nn, material_nombre)
            else:
                break

        content = _prepare_material_for_save(content, material_nn, material_nombre)
        if any("contaminacion de metadata" in w.lower() for w in val_warnings):
            raise ValueError("Contaminacion de metadata persistente: " + "; ".join(val_warnings))

        debug_stats = write_material_debug(debug_dir, granule_code, material_nn, raw_content or "", content)

        save_docx_with_structure(
            content=content,
            output_path=material_output_path,
            material_nombre=material_nombre,
            granule_code=granule_code,
            tema=tema,
            category_key=category_key,
            material_nn=material_nn,
        )
        if not material_output_path.exists() or material_output_path.stat().st_size == 0:
            raise ValueError("El archivo se guardo vacio o no se creo.")

        file_size = material_output_path.stat().st_size
        if not disable_drive_upload:
            try:
                from automation_engine.incremental_drive_upload import upload_material_file_if_configured
                upload_material_file_if_configured(material_output_path)
            except Exception as sync_exc:
                pass

        duration = time.time() - start
        return {
            "granule_code": granule_code,
            "material_nn": material_nn,
            "material_nombre": material_nombre,
            "material_filename": material_filename,
            "status": "ok",
            "validation_status": val_status,
            "warnings": val_warnings,
            "word_count": _count_words(content),
            "size_bytes": file_size,
            "debug": debug_stats,
            "duration": duration,
            "repair_attempts": repair_attempts,
            "error": None,
        }
    except Exception as exc:
        duration = time.time() - start
        return {
            "granule_code": granule_code,
            "material_nn": material_nn,
            "material_nombre": material_nombre,
            "material_filename": material_filename,
            "status": "error",
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "duration": duration,
            "warnings": val_warnings,
            "repair_attempts": repair_attempts,
        }


def execute_materials_parallel(
    blueprint: dict,
    model: str,
    max_tokens: int,
    temperature: float,
    disable_drive_upload: bool,
    debug_dir: Path | None,
) -> list[dict]:
    tasks = build_material_tasks(blueprint)
    results = []
    mode = "PARALELO" if MATERIALS_PARALLEL else "SECUENCIAL"
    _log(f"[Materials] modo: {mode}")

    if MATERIALS_PARALLEL:
        with concurrent.futures.ThreadPoolExecutor(max_workers=MATERIALS_MAX_WORKERS) as executor:
            future_to_task = {
                executor.submit(
                    generate_single_material,
                    task,
                    blueprint,
                    model,
                    max_tokens,
                    temperature,
                    disable_drive_upload,
                    debug_dir,
                ): task
                for task in tasks
            }
            for future in concurrent.futures.as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    result = future.result()
                    if result["status"] == "ok":
                        _log(f"[Materials][{task['granule_code']}][{task['material_nn']}] completado en {result['duration']:.1f}s {task['material_nombre']}")
                    else:
                        _log(f"[Materials][{task['granule_code']}][{task['material_nn']}] error en {result['duration']:.1f}s {task['material_nombre']}: {result['error']}")
                    results.append(result)
                except Exception as exc:
                    _log(f"[Materials][{task['granule_code']}][{task['material_nn']}] excepcion: {exc}")
                    results.append({
                        "granule_code": task["granule_code"],
                        "material_nn": task["material_nn"],
                        "material_nombre": task["material_nombre"],
                        "material_filename": task["material_filename"],
                        "status": "error",
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                        "duration": 0.0,
                        "warnings": [],
                        "repair_attempts": 0,
                    })
    else:
        for task in tasks:
            _log(f"[Materials][{task['granule_code']}][{task['material_nn']}] iniciado {task['material_nombre']}")
            result = generate_single_material(
                task,
                blueprint,
                model,
                max_tokens,
                temperature,
                disable_drive_upload,
                debug_dir,
            )
            if result["status"] == "ok":
                _log(f"[Materials][{task['granule_code']}][{task['material_nn']}] completado en {result['duration']:.1f}s {task['material_nombre']}")
            else:
                _log(f"[Materials][{task['granule_code']}][{task['material_nn']}] error en {result['duration']:.1f}s {task['material_nombre']}: {result['error']}")
            results.append(result)

    return results


def load_materials_prompt(category: CategoryConfig) -> str:
    if not category.enabled_for_package:
        raise ValueError(category.disabled_reason or f"{category.label} no está habilitada para paquete completo.")
    validate_category_prompts(category)
    assert category.materials_prompt_path is not None
    return category.materials_prompt_path.read_text(encoding="utf-8")


def validate_material_prompts(prompt_text: str, materials: tuple[MaterialDefinition, ...]) -> list[str]:
    missing = []
    for material in materials:
        try:
            extract_material_prompt(prompt_text, material.seccion_prompt)
        except ValueError:
            missing.append(material.seccion_prompt)
    return missing


def parse_material_filter(value: str | None) -> set[str] | None:
    if not value:
        return None
    materials = {part.strip().zfill(2) for part in value.split(",") if part.strip()}
    return materials or None


def filter_materials(materials: Iterable[MaterialDefinition], only_materials: set[str] | None) -> tuple[MaterialDefinition, ...]:
    selected = tuple(material for material in materials if only_materials is None or material.nn in only_materials)
    if only_materials and not selected:
        raise ValueError(f"No hay materiales configurados para el filtro: {', '.join(sorted(only_materials))}")
    return selected


def write_material_debug(
    debug_dir: Path | None,
    granule_code: str,
    material_nn: str,
    raw_content: str,
    cleaned_content: str,
) -> dict:
    tables = _parse_markdown_tables(cleaned_content)
    scene_rows = 0
    for header, rows in tables:
        normalized_header = " | ".join(cell.lower() for cell in header)
        if "escena" in normalized_header:
            scene_rows += len(rows)

    stats = {
        "raw_chars": len(raw_content or ""),
        "cleaned_chars": len(cleaned_content or ""),
        "parsed_tables": len(tables),
        "scene_rows": scene_rows,
    }
    if not debug_dir:
        return stats

    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / f"debug_raw_{granule_code}_{material_nn}.md").write_text(raw_content or "", encoding="utf-8")
    (debug_dir / f"debug_cleaned_{granule_code}_{material_nn}.md").write_text(cleaned_content or "", encoding="utf-8")
    parsed_payload = {
        "stats": stats,
        "tables": [
            {"header": header, "row_count": len(rows), "rows_preview": rows[:3]}
            for header, rows in tables
        ],
    }
    (debug_dir / f"debug_parsed_{granule_code}_{material_nn}.json").write_text(
        json.dumps(parsed_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return stats


def build_user_prompt(
    category: CategoryConfig,
    material: MaterialDefinition,
    prompt_particular: str,
    guion_maestro_text: str,
    granule_code: str,
    tema: str,
    tema_corto: str,
    version: str,
) -> str:
    return f"""Quiero generar un material derivado para {category.label.upper()}.

Pego a continuacion el GUION MAESTRO aprobado del tema:

{guion_maestro_text}

Datos del material:
- Categoria academica: {category.label}
- Codigo GX: {granule_code}
- Nombre exacto del tema: {tema}
- Nombre corto para archivo: {tema_corto}
- Version: {version}
- Material a generar: {material.nombre.replace("_", " ")}
- Formato esperado: DOCX (contenido en tabla)
- Cierre integrado ira en: NO APLICA

Instrucciones especificas para este material:

{prompt_particular}

REGLAS CRITICAS DE SALIDA:
1. NO incluyas la frase "Datos recibidos" ni ninguna frase de confirmacion de instrucciones.
2. NO confirmes que entendiste las instrucciones. Entrega directamente el contenido final.
3. NO uses markdown fences (```text, ```, ```markdown).
4. NO inventes fuentes, terminos, casos, tecnologias ni datos que no esten en el GUION MAESTRO.
5. Si una informacion no esta en el guion maestro, marca como "Informacion faltante" en una tabla.
6. Entrega unicamente el contenido del material solicitado en formato tabla markdown.
7. No generes los demas materiales. Solo este.

REGLAS EDITORIALES MINIMAS:
1. Aunque la estructura tecnica se entregue en tabla markdown para validacion, redacta cada celda con lenguaje editorial profesional.
2. Evita fragmentos frios o telegraficos: usa parrafos naturales, legibles y listos para maquetacion academica.
3. Cada recurso debe sentirse autentico para la categoria {category.label}, no como otra categoria con nombre cambiado.
4. Las referencias, fuentes y conexiones de ruta deben mantenerse claras, pero sin saturar el texto principal.
5. Si el material incluye un bloque llamado "Conceptos clave", no lo resumas como glosario. Desarrollalo como seccion editorial con apertura general y conceptos explicados en profundidad, respetando la extension indicada en el prompt particular.

Genera unicamente el material solicitado.
""".strip()


def generate_all_materiales(
    job_id: str,
    category_key: str,
    generated_dir: Path,
    output_base: Path,
    model: str,
    max_tokens: int,
    temperature: float,
    only_materials: set[str] | None = None,
    flat_output: bool = False,
    disable_drive_upload: bool = False,
    debug_dir: Path | None = None,
) -> dict:
    if not model:
        model = get_openai_model("materials")

    category = get_category(category_key)
    if not category.enabled_for_package:
        raise ValueError(category.disabled_reason or f"{category.label} no tiene prompt de materiales configurado.")

    materials_to_generate = filter_materials(category.materials, only_materials)

    print(f"\n{'=' * 60}")
    print(f"=== FASE 3: GENERACION DE MATERIALES - {category.label.upper()} ===")
    print(f"{'=' * 60}")
    print(f"Job ID: {job_id}")
    print(f"Categoria: {category.key} ({category.label})")
    print(f"Directorio de granulos: {generated_dir}")
    print(f"Directorio de salida: {output_base}")
    print(f"Materiales por granulo: {len(materials_to_generate)}")
    if only_materials:
        print(f"Filtro de materiales activo: {', '.join(material.nn for material in materials_to_generate)}")
    if flat_output:
        print("Salida plana activa: los DOCX se guardaran directamente en el directorio de salida.")
    if debug_dir:
        print(f"Debug de respuestas activo: {debug_dir}")
    if category.reserved_materials:
        reserved = ", ".join(f"{m.nn} - {m.nombre}" for m in category.reserved_materials)
        print(f"Materiales reservados/no generados: {reserved}")
    _log(f"[Materials] modo: {'PARALELO' if MATERIALS_PARALLEL else 'SECUENCIAL'} (workers={MATERIALS_MAX_WORKERS})")
    if disable_drive_upload or MATERIALS_PARALLEL:
        print("Drive incremental desactivado para esta ejecucion.")

    plan_metadata = _load_plan_metadata(generated_dir, output_base)
    if plan_metadata:
        _log("[Materials][Metadata]")
        _log("[Materials][MetadataSource]")
        _log(f"program={plan_metadata.get('program', '')}")
        _log(f"program from=plan_curso.json value={plan_metadata.get('program', '')}")
        _log(f"subject={plan_metadata.get('subject', '')}")
        _log(f"subject from=plan_curso.json value={plan_metadata.get('subject', '')}")
        _log(f"category={plan_metadata.get('category', '')}")
        _log(f"level from=plan_curso.json value={plan_metadata.get('category', '')}")
        _log(f"plan={plan_metadata.get('path', '')}")

    prompt_text = load_materials_prompt(category)
    print(f"\nPrompt cargado: {category.materials_prompt_path}")

    missing_prompts = validate_material_prompts(prompt_text, materials_to_generate)
    if missing_prompts:
        raise ValueError(
            f"Faltan {len(missing_prompts)} bloques de prompt para {category.label}. "
            f"Secciones no encontradas: {', '.join(missing_prompts)}."
        )
    print(f"Validacion de prompts: {len(materials_to_generate)}/{len(materials_to_generate)} bloques encontrados.")

    granules = discover_granules(generated_dir)
    print(f"\nGranulos encontrados: {len(granules)}")
    for granule in granules:
        print(f"  - {granule['code']}: {granule['tema']}")
    if len(granules) != category.expected_granules:
        print(f"ADVERTENCIA: Se encontraron {len(granules)} granulos, se esperaban {category.expected_granules}.")

    blueprint = build_material_blueprint(
        category=category,
        materials_to_generate=materials_to_generate,
        granules=granules,
        prompt_text=prompt_text,
        output_base=output_base,
        flat_output=flat_output,
        plan_metadata=plan_metadata,
    )

    for stale_name in ("materials_blueprint.json", "manifest.json", "summary.json", "metrics.json"):
        stale_path = output_base.parent / stale_name
        if stale_path.exists():
            stale_path.unlink()
    blueprint_path = output_base.parent / "materials_blueprint.json"
    blueprint_serializable = {
        "category_key": blueprint["category_key"],
        "category_label": blueprint["category_label"],
        "category_version": blueprint["category_version"],
        "category_extension": blueprint["category_extension"],
        "system_prompt_length": len(blueprint["system_prompt"]),
        "material_prompts_keys": list(blueprint["material_prompts"].keys()),
        "granule_texts_keys": list(blueprint["granule_texts"].keys()),
        "task_count": len(blueprint["tasks"]),
        "tasks": blueprint["tasks"],
    }
    blueprint_path.write_text(json.dumps(blueprint_serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Blueprint guardado: {blueprint_path}")
    _log("blueprint regenerated=true")

    effective_disable_drive = disable_drive_upload or MATERIALS_PARALLEL

    task_results = execute_materials_parallel(
        blueprint=blueprint,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        disable_drive_upload=effective_disable_drive,
        debug_dir=debug_dir,
    )

    errors = []
    manifest_entries = []
    summary = {
        "job_id": job_id,
        "category": category.key,
        "category_label": category.label,
        "fecha": datetime.now(timezone.utc).isoformat(),
        "total_granules": len(granules),
        "total_materiales_esperados": len(granules) * len(materials_to_generate),
        "total_materiales_generados": 0,
        "total_errores": 0,
        "total_advertencias": 0,
        "granules": {},
    }

    granule_summary_map = {}
    for result in task_results:
        granule_code = result["granule_code"]
        material_nn = result["material_nn"]
        if granule_code not in granule_summary_map:
            granule_summary_map[granule_code] = {"status": "ok", "materiales": {}}

        if result["status"] == "ok":
            granule_summary_map[granule_code]["materiales"][material_nn] = {
                "nombre": result["material_nombre"],
                "archivo": result["material_filename"],
                "status": "ok",
                "validation_status": result.get("validation_status", "ok"),
                "warnings": result.get("warnings", []),
                "word_count": result.get("word_count", 0),
                "size_bytes": result.get("size_bytes", 0),
                "debug": result.get("debug", {}),
                "duration": result.get("duration", 0.0),
                "repair_attempts": result.get("repair_attempts", 0),
            }
            summary["total_materiales_generados"] += 1
            manifest_entries.append({
                "category": category.key,
                "granule_code": granule_code,
                "granule_topic": result.get("tema", ""),
                "material_number": material_nn,
                "material_name": result["material_nombre"],
                "filename": result["material_filename"],
                "path": next((t["material_output_path"] for t in blueprint["tasks"] if t["granule_code"] == granule_code and t["material_nn"] == material_nn), ""),
                "validation_status": result.get("validation_status", "ok"),
                "warnings": result.get("warnings", []),
                "word_count": result.get("word_count", 0),
                "debug": result.get("debug", {}),
                "duration": result.get("duration", 0.0),
            })
        else:
            error_msg = f"Error material {material_nn} {granule_code} ({result['material_nombre']}): {result['error']}"
            errors.append({
                "granule": granule_code,
                "material": material_nn,
                "nombre": result["material_nombre"],
                "error": result["error"],
                "traceback": result.get("traceback", ""),
            })
            granule_summary_map[granule_code]["materiales"][material_nn] = {
                "nombre": result["material_nombre"],
                "status": "error",
                "error": result["error"],
                "duration": result.get("duration", 0.0),
            }
            summary["total_errores"] += 1

    for granule_code, granule_summary in granule_summary_map.items():
        has_errors = any(m.get("status") == "error" for m in granule_summary["materiales"].values())
        if has_errors:
            granule_summary["status"] = "parcial"
        total_warnings = sum(len(m.get("warnings", [])) for m in granule_summary["materiales"].values())
        summary["total_advertencias"] += total_warnings
        summary["granules"][granule_code] = granule_summary

    durations = [r.get("duration", 0.0) for r in task_results if r.get("duration", 0.0) > 0]
    total_duration = sum(durations)
    avg_duration = total_duration / len(durations) if durations else 0.0
    throughput = len(durations) / total_duration if total_duration > 0 else 0.0
    success_count = sum(1 for r in task_results if r["status"] == "ok")
    error_count = sum(1 for r in task_results if r["status"] == "error")
    total_warnings = sum(len(r.get("warnings", [])) for r in task_results)
    total_repair_attempts = sum(r.get("repair_attempts", 0) for r in task_results)

    materials_phase_metrics = {
        "mode": "parallel" if MATERIALS_PARALLEL else "sequential",
        "max_workers": MATERIALS_MAX_WORKERS if MATERIALS_PARALLEL else 1,
        "total_duration": round(total_duration, 2),
        "avg_duration": round(avg_duration, 2),
        "throughput": round(throughput, 2),
        "success_count": success_count,
        "error_count": error_count,
        "warnings": total_warnings,
        "repair_attempts": total_repair_attempts,
        "per_task": [
            {
                "granule_code": r["granule_code"],
                "material_nn": r["material_nn"],
                "material_nombre": r["material_nombre"],
                "status": r["status"],
                "duration": round(r.get("duration", 0.0), 2),
                "warnings": len(r.get("warnings", [])),
                "word_count": r.get("word_count", 0),
                "repair_attempts": r.get("repair_attempts", 0),
            }
            for r in task_results
        ],
    }

    return {
        "summary": summary,
        "manifest": {
            "job_id": job_id,
            "category": category.key,
            "fecha": datetime.now(timezone.utc).isoformat(),
            "materiales": manifest_entries,
        },
        "errors": errors,
        "materials_phase": materials_phase_metrics,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Genera materiales academicos por categoria derivados de granulos G1-G5.")
    parser.add_argument("--job-id", required=True, help="ID del job")
    parser.add_argument("--category", required=True, help="Categoria academica")
    parser.add_argument("--generated-dir", required=True, help="Directorio con granulos G1-G5")
    parser.add_argument("--output-dir", required=True, help="Directorio base para materiales")
    parser.add_argument("--model", default=None, help="Modelo (fallback: OPENAI_MODEL_MATERIALS > OPENAI_MODEL > gemini-2.5-flash)")
    parser.add_argument("--max-tokens", type=int, default=8000, help="Maximo de tokens por material")
    parser.add_argument("--temperature", type=float, default=0.5, help="Creatividad de generacion")
    parser.add_argument("--materials", "--only-material", dest="materials", help="Filtro de materiales por NN, ejemplo: 03 o 02,03")
    parser.add_argument("--flat-output", action="store_true", help="Guarda los DOCX directamente en output-dir, sin subcarpetas por granulo")
    parser.add_argument("--no-drive-upload", action="store_true", help="Desactiva el hook opcional de subida incremental a Drive")
    parser.add_argument("--debug-dir", help="Directorio para guardar raw, cleaned y tablas parseadas por material")
    return parser.parse_args()


def main() -> None:
    if load_dotenv:
        load_dotenv()
    args = parse_args()
    category = get_category(args.category)
    output_base = Path(args.output_dir)
    output_base.mkdir(parents=True, exist_ok=True)

    result = generate_all_materiales(
        job_id=args.job_id,
        category_key=category.key,
        generated_dir=Path(args.generated_dir),
        output_base=output_base,
        model=args.model,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        only_materials=parse_material_filter(args.materials),
        flat_output=args.flat_output,
        disable_drive_upload=args.no_drive_upload,
        debug_dir=Path(args.debug_dir) if args.debug_dir else None,
    )

    summary_path = output_base.parent / "summary.json"
    summary_path.write_text(json.dumps(result["summary"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSummary guardado: {summary_path}")
    manifest_path = output_base.parent / "manifest.json"
    manifest_path.write_text(json.dumps(result["manifest"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest guardado: {manifest_path}")
    errors_path = output_base.parent / "errors.json"
    errors_path.write_text(json.dumps(result["errors"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Errors guardado: {errors_path}")

    if "materials_phase" in result:
        metrics_path = output_base.parent / "metrics.json"
        metrics_path.write_text(json.dumps(result["materials_phase"], ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Materials phase metrics guardado: {metrics_path}")

    print(f"\n{'=' * 60}")
    print("=== RESUMEN FINAL ===")
    print(f"{'=' * 60}")
    print(f"Job ID: {result['summary']['job_id']}")
    print(f"Categoria: {category.label}")
    print(f"Granulos procesados: {result['summary']['total_granules']}")
    print(f"Materiales generados: {result['summary']['total_materiales_generados']}")
    print(f"Materiales esperados: {result['summary']['total_materiales_esperados']}")
    print(f"Errores: {result['summary']['total_errores']}")
    print(f"Advertencias: {result['summary'].get('total_advertencias', 0)}")
    if result["errors"]:
        print("\n--- Errores detectados ---")
        for err in result["errors"]:
            print(f"  [{err.get('granule', '?')}] Material {err.get('material', '?')} ({err.get('nombre', '?')}): {err.get('error', '?')}")
        print("--- Fin de errores ---")
    else:
        print("\nTodos los materiales se generaron sin errores.")
    print("\nGeneracion completa.")


if __name__ == "__main__":
    main()
