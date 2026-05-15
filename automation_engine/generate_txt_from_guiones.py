import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

from automation_engine.config.categories import resolve_txt_prompt
from automation_engine.generate_guiones import clean_text, extract_docx_text, extract_pdf_text, generate_document, slugify, word_count


ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent
DEFAULT_INPUT_DIR = PROJECT_ROOT / "entrada_guiones_txt"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "salidas_txt"
DEFAULT_PROMPT_PATH = PROJECT_ROOT / "prompts" / "txt" / "txt_pda.md"
SUPPORTED_EXTENSIONS = {".docx", ".pdf"}

TXT_TASKS = {
    "PDA": {"prompt": "prompts/txt/txt_pda.md", "role": "diagnostic", "questions": 10},
    "QUIZ 1": {"prompt": "prompts/txt/txt_quiz1.md", "role": "fundamentals", "questions": 15},
    "QUIZ 2": {"prompt": "prompts/txt/txt_quiz2.md", "role": "application", "questions": 15},
    "QUIZ 3": {"prompt": "prompts/txt/txt_quiz3.md", "role": "critical_thinking", "questions": 15},
}


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def extract_file_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return extract_docx_text(path)
    if suffix == ".pdf":
        return extract_pdf_text(path)
    if suffix in {".txt", ".md"}:
        return read_text_file(path)
    raise ValueError(f"Formato no soportado: {path.name}")


def collect_input_files(input_dir: Path) -> List[Path]:
    return sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS and not path.name.startswith("~$")
    )


def build_corpus(files: List[Path], max_chars_per_file: int) -> str:
    blocks = []
    for index, path in enumerate(files, start=1):
        text = clean_text(extract_file_text(path))
        if max_chars_per_file > 0:
            text = text[:max_chars_per_file]
        blocks.append(
            "\n".join(
                [
                    f"===== DOCUMENTO {index}: {path.name} =====",
                    text,
                ]
            )
        )
    return "\n\n".join(blocks).strip()


def parse_titles(value: str, count: int) -> List[str]:
    titles = [clean_text(part) for part in value.split(";") if clean_text(part)]
    if not titles:
        titles = ["PDA", "QUIZ 1", "QUIZ 2", "QUIZ 3"]
    if len(titles) < count:
        titles.extend(f"QUIZ {index}" for index in range(len(titles), count))
    return titles[:count]


def extract_metadata_from_corpus(corpus: str) -> dict:
    programa_match = re.search(r"PROGRAMA\s*:\s*(.+)", corpus, flags=re.IGNORECASE)
    asignatura_match = re.search(r"ASIGNATURA\s*:\s*(.+)", corpus, flags=re.IGNORECASE)
    return {
        "programa": clean_text(programa_match.group(1)) if programa_match else "",
        "asignatura": clean_text(asignatura_match.group(1)) if asignatura_match else "",
    }


def strip_markdown_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:text|txt|gift)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = text.replace("```text", "").replace("```txt", "").replace("```gift", "").replace("```", "")
    return text.strip()


def build_user_prompt(
    corpus: str,
    title: str,
    index: int,
    count: int,
    previous_outputs: str,
    programa: str,
    asignatura: str,
) -> str:
    previous_note = previous_outputs[-5000:] if previous_outputs else "Aun no se ha generado ningun TXT en este flujo."
    return f"""
Genera el archivo TXT {index} de {count}.

Nombre o enfoque del TXT:
{title}

Datos obligatorios del encabezado:
PROGRAMA: {programa}
ASIGNATURA: {asignatura}

El archivo debe iniciar exactamente con:
PROGRAMA: {programa}
ASIGNATURA: {asignatura}

{title}

Contexto de TXT anteriores para evitar repeticiones:
{previous_note}

Documentos fuente:
{corpus}

Reglas de salida:
- Entrega unicamente el contenido final del archivo TXT solicitado.
- No uses bloques de codigo. No escribas ```text ni ```.
- No expliques el proceso.
- No incluyas markdown decorativo salvo que el prompt de sistema lo pida expresamente.
- Usa los documentos fuente como base principal.
- No menciones anexos, documentos fuente, G1, G2, G3, G4 ni G5.
- Evita repetir texto literal entre archivos TXT.
""".strip()


def output_filename(title: str, index: int) -> str:
    normalized = title.strip().upper()
    if normalized == "PDA":
        return "PDA.txt"
    if normalized.startswith("QUIZ"):
        return f"{normalized}.txt"
    return f"T{index}_{slugify(title)}.txt"


def load_txt_prompt(task_key: str, base_dir: Optional[Path] = None) -> str:
    try:
        prompt_path = resolve_txt_prompt(task_key, base_dir)
        return prompt_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # Last resort fallback: try txt_desde_guiones.md in any location
        fallback_candidates = [
            PROJECT_ROOT / "prompts" / "txt" / "txt_desde_guiones.md",
            PROJECT_ROOT / "prompts" / "guiones" / "txt_desde_guiones.md",
            PROJECT_ROOT / "prompts" / "txt_desde_guiones.md",
        ]
        for candidate in fallback_candidates:
            if candidate.exists():
                return candidate.read_text(encoding="utf-8")
        raise FileNotFoundError(
            f"No se encontro ningun prompt TXT para '{task_key}'. "
            f"Buscado en: {[str(c) for c in fallback_candidates]}"
        )


def build_independent_prompt(
    task_key: str,
    corpus: str,
    programa: str,
    asignatura: str,
) -> Tuple[str, str]:
    system_prompt = load_txt_prompt(task_key)
    prompt_template = system_prompt
    prompt_filled = prompt_template.replace("{programa}", programa).replace("{asignatura}", asignatura).replace("{corpus}", corpus)
    return system_prompt, prompt_filled


def validate_gift_format(text: str, task_key: str) -> List[str]:
    warnings = []
    normalized = text.strip()
    first_lines = normalized.split("\n")[:10]
    first_lines_text = "\n".join(first_lines)

    if not normalized.startswith("PROGRAMA:"):
        warnings.append(f"[{task_key}] No inicia con 'PROGRAMA:'")
    if "ASIGNATURA" not in first_lines_text:
        warnings.append(f"[{task_key}] No se encontro 'ASIGNATURA' en las primeras lineas del encabezado")

    question_pattern = re.compile(r"::.*?::\s*\n.*?\{", re.DOTALL)
    questions_found = len(question_pattern.findall(normalized))
    expected = TXT_TASKS.get(task_key, {}).get("questions", 0)
    if expected > 0 and questions_found < expected * 0.8:
        warnings.append(f"[{task_key}] Solo se detectaron {questions_found} preguntas GIFT, se esperaban ~{expected}")
    feedback_pattern = re.compile(r"#[Cc]orrecto\.|#[Ii]ncorrecto\.")
    feedback_count = len(feedback_pattern.findall(normalized))
    if expected > 0 and feedback_count < expected * 3:
        warnings.append(f"[{task_key}] Retroalimentacion insuficiente: {feedback_count} feedbacks para ~{expected} preguntas")
    if "```" in normalized:
        warnings.append(f"[{task_key}] Contiene bloques de codigo markdown (```)")
    return warnings


def generate_single_txt(
    client,
    model: str,
    task_key: str,
    corpus: str,
    programa: str,
    asignatura: str,
    max_tokens: int,
    temperature: float,
    output_dir: Path,
) -> Dict[str, object]:
    start_time = time.time()
    task_info = TXT_TASKS.get(task_key, {"role": "generic", "questions": 0})
    result = {
        "task": task_key,
        "role": task_info["role"],
        "status": "pending",
        "output_file": "",
        "warnings": [],
        "duration_seconds": 0,
        "word_count": 0,
        "error": "",
    }
    try:
        system_prompt, user_prompt = build_independent_prompt(task_key, corpus, programa, asignatura)
        response_text = generate_document(
            client=client,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        filename = output_filename(task_key, list(TXT_TASKS.keys()).index(task_key) + 1)
        output_path = output_dir / filename
        save_txt(response_text, output_path)
        result["status"] = "success"
        result["output_file"] = filename
        result["word_count"] = word_count(response_text)
        result["warnings"] = validate_gift_format(response_text, task_key)
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
    finally:
        result["duration_seconds"] = round(time.time() - start_time, 2)
    return result


def save_txt(text: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(strip_markdown_fences(text) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera archivos TXT usando como entrada una carpeta de guiones ya creados."
    )
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR), help="Carpeta con guiones .docx o .pdf")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Carpeta donde se guardan los .txt generados")
    parser.add_argument("--prompt", default=str(DEFAULT_PROMPT_PATH), help="Prompt maestro para generar los TXT")
    parser.add_argument("--count", type=int, default=4, help="Cantidad de archivos TXT a generar")
    parser.add_argument("--titles", default="", help="Titulos/enfoques separados por punto y coma para cada TXT")
    parser.add_argument("--programa", default="", help="Programa que debe aparecer en el encabezado de cada TXT")
    parser.add_argument("--asignatura", default="", help="Asignatura que debe aparecer en el encabezado de cada TXT")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4o"), help="Modelo OpenAI")
    parser.add_argument("--max-tokens", type=int, default=3500, help="Maximo de tokens por TXT generado")
    parser.add_argument("--temperature", type=float, default=0.45, help="Creatividad de generacion")
    parser.add_argument("--max-chars-per-file", type=int, default=45000, help="Maximo de caracteres leidos por archivo fuente")
    parser.add_argument("--dry-run", action="store_true", help="Solo lista entradas y valida configuracion, sin llamar a la API")
    return parser.parse_args()


def main() -> None:
    if load_dotenv:
        load_dotenv()

    args = parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    prompt_path = Path(args.prompt)

    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = collect_input_files(input_dir)
    print(f"Carpeta de entrada: {input_dir}")
    print(f"Carpeta de salida: {output_dir}")
    print(f"Prompt: {prompt_path}")
    print(f"Archivos fuente encontrados: {len(files)}")
    for path in files:
        print(f"  - {path.name}")

    if not files:
        print("\nNo hay archivos de entrada. Copia tus guiones .docx/.pdf/.txt/.md en la carpeta de entrada.")
        return

    if not prompt_path.exists():
        print(f"\nNo existe el prompt: {prompt_path}")
        print("Crea ese archivo en prompts o usa --prompt con otra ruta.")
        return

    corpus = build_corpus(files, args.max_chars_per_file)
    detected_metadata = extract_metadata_from_corpus(corpus)
    programa = args.programa or detected_metadata["programa"]
    asignatura = args.asignatura or detected_metadata["asignatura"]
    if not programa or not asignatura:
        raise RuntimeError("No pude detectar PROGRAMA/ASIGNATURA. Usa --programa y --asignatura para indicarlos.")
    titles = parse_titles(args.titles, args.count)
    manifest = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "prompt": str(prompt_path),
        "count": args.count,
        "titles": titles,
        "programa": programa,
        "asignatura": asignatura,
        "sources": [path.name for path in files],
        "corpus_words": word_count(corpus),
    }
    (output_dir / "plan_txt.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nPalabras fuente aproximadas: {manifest['corpus_words']}")
    print(f"Plan guardado en: {output_dir / 'plan_txt.json'}")

    if args.dry_run:
        print("\nDry-run activo. No se llamo a la API.")
        return

    if OpenAI is None:
        raise RuntimeError("Falta instalar el paquete openai. Ejecuta: pip install -r requirements.txt")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Falta OPENAI_API_KEY en variables de entorno o en .env")

    client = OpenAI()
    system_prompt = prompt_path.read_text(encoding="utf-8")
    previous_outputs = ""

    for index, title in enumerate(titles, start=1):
        print(f"\nGenerando TXT {index}/{args.count}: {title}")
        result = generate_document(
            client=client,
            model=args.model,
            system_prompt=system_prompt,
            user_prompt=build_user_prompt(
                corpus=corpus,
                title=title,
                index=index,
                count=args.count,
                previous_outputs=previous_outputs,
                programa=programa,
                asignatura=asignatura,
            ),
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        )
        output_path = output_dir / output_filename(title, index)
        save_txt(result, output_path)
        previous_outputs = (previous_outputs + "\n\n" + result).strip()
        print(f"Guardado: {output_path} ({word_count(result)} palabras aprox.)")


if __name__ == "__main__":
    main()
