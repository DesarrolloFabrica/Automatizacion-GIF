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
from automation_engine.generate_guiones import clean_text, extract_docx_text, extract_pdf_text, slugify, word_count
from automation_engine.utils.openai_client import get_openai_client, get_openai_model


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

TXT_MIN_OUTPUT_TOKENS = 16000
TXT_BLOCK_QUESTION_COUNT = 5


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

    question_blocks = extract_gift_question_blocks(normalized)
    questions_found = len(question_blocks)
    expected = TXT_TASKS.get(task_key, {}).get("questions", 0)
    if expected > 0 and questions_found != expected:
        warnings.append(f"[{task_key}] Preguntas detectadas: {questions_found}/{expected}. Debe contener exactamente {expected} bloques ::Pregunta.")
    for index, block in enumerate(question_blocks, start=1):
        for issue in validate_gift_question_block(block):
            warnings.append(f"[{task_key}] Pregunta {index} {issue}")
    if "```" in normalized:
        warnings.append(f"[{task_key}] Contiene bloques de codigo markdown (```)")
    return warnings


def extract_gift_question_blocks(text: str) -> List[str]:
    starts = list(re.finditer(r"(?m)^\s*::.+?::", text))
    blocks: List[str] = []
    for index, match in enumerate(starts):
        start = match.start()
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        blocks.append(text[start:end].strip())
    return blocks


def validate_gift_question_block(block: str) -> List[str]:
    issues: List[str] = []
    if "{" not in block or "}" not in block:
        issues.append("no contiene llaves de apertura/cierre.")
    body = block[block.find("{") + 1:block.rfind("}")] if "{" in block and "}" in block else block
    correct_count = len(re.findall(r"(?m)^\s*=", body))
    distractor_count = len(re.findall(r"(?m)^\s*~", body))
    if correct_count != 1:
        issues.append(f"debe tener exactamente 1 respuesta correcta con '='; detectadas {correct_count}.")
    if distractor_count < 3:
        issues.append(f"debe tener minimo 3 distractores con '~'; detectados {distractor_count}.")
    if not re.search(r"#[Cc]orrecto\.?|#[Ii]ncorrecto\.?,?", body):
        issues.append("no incluye retroalimentacion #Correcto/#Incorrecto.")
    return issues


def invalid_gift_question_numbers(text: str) -> List[int]:
    invalid: List[int] = []
    for index, block in enumerate(extract_gift_question_blocks(text), start=1):
        if validate_gift_question_block(block):
            invalid.append(index)
    return invalid


def _question_block_start(question_number: int) -> int:
    return ((question_number - 1) // TXT_BLOCK_QUESTION_COUNT) * TXT_BLOCK_QUESTION_COUNT + 1


def repair_txt_invalid_blocks(
    text: str,
    client,
    model: str,
    task_key: str,
    corpus: str,
    programa: str,
    asignatura: str,
    max_tokens: int,
    temperature: float,
) -> str:
    expected = TXT_TASKS.get(task_key, {}).get("questions", 0)
    blocks = extract_gift_question_blocks(text)
    if len(blocks) != expected:
        return generate_txt_by_blocks(client, model, task_key, corpus, programa, asignatura, max_tokens, temperature)

    first_match = re.search(r"(?m)^\s*::.+?::", text)
    header = text[: first_match.start()].strip() if first_match else f"PROGRAMA: {programa}\nASIGNATURA: {asignatura}\n\n{task_key}"
    repaired_blocks = list(blocks)

    invalid_questions = invalid_gift_question_numbers(text)
    block_starts = sorted({_question_block_start(question) for question in invalid_questions})
    for block_start in block_starts:
        print(f"[TXT][{task_key}] reparando bloque que contiene Pregunta {block_start}.")
        count = min(TXT_BLOCK_QUESTION_COUNT, expected - block_start + 1)
        replacement = generate_txt_question_block(
            client=client,
            model=model,
            task_key=task_key,
            corpus=corpus,
            programa=programa,
            asignatura=asignatura,
            max_tokens=max_tokens,
            temperature=temperature,
            start_question=block_start,
            count=count,
            total=expected,
        )
        replacement_blocks = extract_gift_question_blocks(replacement)
        repaired_blocks[block_start - 1:block_start - 1 + count] = replacement_blocks

    return (header + "\n\n" + "\n\n".join(repaired_blocks)).strip()


def call_txt_openai(client, model: str, system_prompt: str, user_prompt: str, max_tokens: int, temperature: float) -> str:
    effective_max_tokens = max(max_tokens, TXT_MIN_OUTPUT_TOKENS)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=effective_max_tokens,
    )
    if not response.choices:
        raise RuntimeError(f"La API devolvio choices vacio para TXT. model={model}")
    choice = response.choices[0]
    finish_reason = getattr(choice, "finish_reason", None)
    content = choice.message.content
    if finish_reason == "length":
        raise RuntimeError(f"finish_reason=length; salida TXT cortada. max_tokens={effective_max_tokens}")
    if content is None:
        refusal = getattr(choice.message, "refusal", None)
        raise RuntimeError(f"La API devolvio content=None para TXT. finish_reason={finish_reason!r}; refusal={refusal!r}")
    return content.strip()


def build_block_prompt(task_key: str, corpus: str, programa: str, asignatura: str, start_question: int, count: int, total: int) -> Tuple[str, str]:
    system_prompt, base_prompt = build_independent_prompt(task_key, corpus, programa, asignatura)
    block_prompt = f"""{base_prompt}

INSTRUCCION DE BLOQUE OBLIGATORIA:
Genera UNICAMENTE las preguntas {start_question} a {start_question + count - 1} de {total} para {task_key}.
Debes entregar exactamente {count} bloques GIFT.
Cada bloque debe iniciar con ::Pregunta {start_question}::, ::Pregunta {start_question + 1}::, etc.
Cada pregunta debe tener llaves {{ }}, exactamente una respuesta correcta con '=', minimo tres distractores con '~' y feedback #Correcto/#Incorrecto.
No incluyas explicaciones ni texto fuera de los bloques GIFT.
""".strip()
    return system_prompt, block_prompt


def generate_txt_by_blocks(
    client,
    model: str,
    task_key: str,
    corpus: str,
    programa: str,
    asignatura: str,
    max_tokens: int,
    temperature: float,
) -> str:
    expected = TXT_TASKS.get(task_key, {}).get("questions", 0)
    if expected <= 0:
        raise RuntimeError(f"No hay conteo esperado configurado para {task_key}")
    parts: List[str] = []
    start = 1
    while start <= expected:
        count = min(TXT_BLOCK_QUESTION_COUNT, expected - start + 1)
        print(f"[TXT][{task_key}] generando bloque preguntas {start}-{start + count - 1}/{expected}")
        part = generate_txt_question_block(
            client=client,
            model=model,
            task_key=task_key,
            corpus=corpus,
            programa=programa,
            asignatura=asignatura,
            max_tokens=max_tokens,
            temperature=temperature,
            start_question=start,
            count=count,
            total=expected,
        )
        parts.append(part)
        start += count
    header = f"PROGRAMA: {programa}\nASIGNATURA: {asignatura}\n\n{task_key}\n\n"
    return header + "\n\n".join(parts).strip()


def generate_txt_question_block(
    client,
    model: str,
    task_key: str,
    corpus: str,
    programa: str,
    asignatura: str,
    max_tokens: int,
    temperature: float,
    start_question: int,
    count: int,
    total: int,
) -> str:
    last_error = ""
    for attempt in range(1, 4):
        system_prompt, block_prompt = build_block_prompt(task_key, corpus, programa, asignatura, start_question, count, total)
        part = call_txt_openai(
            client=client,
            model=model,
            system_prompt=system_prompt,
            user_prompt=block_prompt,
            max_tokens=max_tokens,
            temperature=min(temperature, 0.3),
        )
        blocks = extract_gift_question_blocks(part)
        invalid = [idx for idx, block in enumerate(blocks, start=start_question) if validate_gift_question_block(block)]
        if len(blocks) == count and not invalid:
            return "\n\n".join(blocks)
        last_error = f"bloque {start_question}-{start_question + count - 1}: {len(blocks)}/{count} preguntas, invalidas={invalid}"
        print(f"[TXT][{task_key}] bloque invalido en intento {attempt}: {last_error}")
    raise RuntimeError(f"No se pudo reparar bloque TXT: {last_error}")


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
        try:
            response_text = call_txt_openai(
                client=client,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except RuntimeError as exc:
            if "finish_reason=length" not in str(exc):
                raise
            print(f"[TXT][{task_key}] finish_reason=length, regenerando por bloques")
            response_text = generate_txt_by_blocks(
                client=client,
                model=model,
                task_key=task_key,
                corpus=corpus,
                programa=programa,
                asignatura=asignatura,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        warnings = validate_gift_format(response_text, task_key)
        expected = TXT_TASKS.get(task_key, {}).get("questions", 0)
        found = len(extract_gift_question_blocks(response_text))
        print(f"[TXT][{task_key}] preguntas detectadas: {found}/{expected}")
        if warnings:
            invalid_questions = invalid_gift_question_numbers(response_text)
            if found == expected and invalid_questions:
                response_text = repair_txt_invalid_blocks(
                    text=response_text,
                    client=client,
                    model=model,
                    task_key=task_key,
                    corpus=corpus,
                    programa=programa,
                    asignatura=asignatura,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            else:
                print(f"[TXT][{task_key}] validacion fallo, regenerando por bloques")
                response_text = generate_txt_by_blocks(
                    client=client,
                    model=model,
                    task_key=task_key,
                    corpus=corpus,
                    programa=programa,
                    asignatura=asignatura,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            warnings = validate_gift_format(response_text, task_key)
            found = len(extract_gift_question_blocks(response_text))
            print(f"[TXT][{task_key}] preguntas detectadas tras bloques: {found}/{expected}")
        if warnings:
            raise RuntimeError("Validacion TXT final fallo: " + " | ".join(warnings[:8]))
        filename = output_filename(task_key, list(TXT_TASKS.keys()).index(task_key) + 1)
        output_path = output_dir / filename
        save_txt(response_text, output_path)
        result["status"] = "success"
        result["output_file"] = filename
        result["word_count"] = word_count(response_text)
        result["warnings"] = warnings
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
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
    parser.add_argument("--model", default=None, help="Modelo (fallback: OPENAI_MODEL_TXT > OPENAI_MODEL > gemini-2.5-flash)")
    parser.add_argument("--max-tokens", type=int, default=TXT_MIN_OUTPUT_TOKENS, help="Maximo de tokens por TXT generado")
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

    if not args.model:
        args.model = get_openai_model("txt")

    client = get_openai_client()
    system_prompt = prompt_path.read_text(encoding="utf-8")
    previous_outputs = ""

    for index, title in enumerate(titles, start=1):
        print(f"\nGenerando TXT {index}/{args.count}: {title}")
        task_key = title.upper()
        try:
            result = call_txt_openai(
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
        except RuntimeError as exc:
            if task_key not in TXT_TASKS or "finish_reason=length" not in str(exc):
                raise
            print(f"[TXT][{task_key}] finish_reason=length, regenerando por bloques")
            result = generate_txt_by_blocks(
                client=client,
                model=args.model,
                task_key=task_key,
                corpus=corpus,
                programa=programa,
                asignatura=asignatura,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
            )
        if task_key in TXT_TASKS:
            warnings = validate_gift_format(result, task_key)
            expected = TXT_TASKS[task_key]["questions"]
            found = len(extract_gift_question_blocks(result))
            print(f"[TXT][{task_key}] preguntas detectadas: {found}/{expected}")
            if warnings:
                invalid_questions = invalid_gift_question_numbers(result)
                if found == expected and invalid_questions:
                    result = repair_txt_invalid_blocks(
                        text=result,
                        client=client,
                        model=args.model,
                        task_key=task_key,
                        corpus=corpus,
                        programa=programa,
                        asignatura=asignatura,
                        max_tokens=args.max_tokens,
                        temperature=args.temperature,
                    )
                else:
                    print(f"[TXT][{task_key}] validacion fallo, regenerando por bloques")
                    result = generate_txt_by_blocks(
                        client=client,
                        model=args.model,
                        task_key=task_key,
                        corpus=corpus,
                        programa=programa,
                        asignatura=asignatura,
                        max_tokens=args.max_tokens,
                        temperature=args.temperature,
                    )
                warnings = validate_gift_format(result, task_key)
                found = len(extract_gift_question_blocks(result))
                print(f"[TXT][{task_key}] preguntas detectadas tras bloques: {found}/{expected}")
            if warnings:
                raise RuntimeError("Validacion TXT final fallo: " + " | ".join(warnings[:8]))
        output_path = output_dir / output_filename(title, index)
        save_txt(result, output_path)
        previous_outputs = (previous_outputs + "\n\n" + result).strip()
        print(f"Guardado: {output_path} ({word_count(result)} palabras aprox.)")


if __name__ == "__main__":
    main()
