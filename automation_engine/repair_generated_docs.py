import argparse
from pathlib import Path

from docx import Document


MAIN_HEADINGS = {
    "INTRODUCCION",
    "EJES ARTICULADORES",
    "ENSAYOS DE PROFUNDIZACION",
    "CONCLUSIONES",
    "BIBLIOGRAFIA",
}


def normalize(value: str) -> str:
    value = " ".join((value or "").split()).upper()
    replacements = {
        "Á": "A",
        "É": "E",
        "Í": "I",
        "Ó": "O",
        "Ú": "U",
        "Ü": "U",
        "Ñ": "N",
    }
    for original, replacement in replacements.items():
        value = value.replace(original, replacement)
    return value


def remove_paragraph(paragraph) -> None:
    element = paragraph._element
    parent = element.getparent()
    parent.remove(element)
    paragraph._p = paragraph._element = None


def repair_docx(path: Path) -> int:
    doc = Document(path)
    seen_content_header = False
    seen_headings = set()
    removed = 0

    for paragraph in list(doc.paragraphs):
        text = " ".join(paragraph.text.split())
        normalized = normalize(text)
        should_remove = False

        if normalized.startswith("CONTENIDO:"):
            if seen_content_header:
                should_remove = True
            else:
                seen_content_header = True
        elif normalized in MAIN_HEADINGS:
            if normalized in seen_headings:
                should_remove = True
            else:
                seen_headings.add(normalized)

        if should_remove:
            remove_paragraph(paragraph)
            removed += 1

    if removed:
        doc.save(path)
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Limpia encabezados repetidos en guiones DOCX ya generados.")
    parser.add_argument("--dir", default="outputs", help="Carpeta con documentos .docx")
    args = parser.parse_args()

    output_dir = Path(args.dir)
    for path in sorted(output_dir.glob("*.docx")):
        removed = repair_docx(path)
        print(f"{path}: {removed} parrafos repetidos eliminados")


if __name__ == "__main__":
    main()
