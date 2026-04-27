# Generador semiautomatizado de guiones académicos

Este proyecto toma un sílabo en Word (`.docx`) o PDF (`.pdf`), identifica la información principal de la asignatura, divide el curso en cinco temas y genera cinco documentos base con una estructura homogénea tipo guion editorial.

## Archivos principales

- `generate_guiones.py`: script principal para extraer el sílabo y generar los documentos.
- `prompts/system_prompt_guion_academico.md`: prompt maestro editable.
- `notebooks/generador_guiones.ipynb`: flujo en Jupyter para el equipo.
- `outputs/`: carpeta donde quedan los `.docx` generados.

## Instalación

```powershell
pip install -r requirements.txt
```

Configura la API key como variable de entorno. No la dejes escrita dentro del código.

```powershell
$env:OPENAI_API_KEY="TU_API_KEY"
$env:OPENAI_MODEL="gpt-4o"
```

## Prueba sin consumir API

```powershell
python generate_guiones.py --syllabus "7. Habilidades Comunicativas.docx" --dry-run
```

También puedes probar un PDF:

```powershell
python generate_guiones.py --syllabus "Mi Silabo.pdf" --dry-run
```

## Generación real

```powershell
python generate_guiones.py --syllabus "7. Habilidades Comunicativas.docx" --semester "Semestre N°1" --subject "Habilidades Comunicativas"
```

Si el PDF o el sílabo tiene un formato difícil y no detecta los cinco temas, puedes forzarlos manualmente:

```powershell
python generate_guiones.py --syllabus "Mi Silabo.pdf" --subject "Nombre de la materia" --semester "Semestre N°2" --topics "Tema 1; Tema 2; Tema 3; Tema 4; Tema 5"
```

El generador crea cada documento largo por secciones. Para cada tema hace varias llamadas a la API: introducción, ejes articuladores, tres ensayos de profundización, conclusiones y bibliografía. Esto evita que el modelo entregue documentos demasiado cortos.

Además, el script valida la extensión mínima de cada sección. Si una sección queda corta, solicita automáticamente una ampliación antes de ensamblar el `.docx`.

La bibliografía debe incluir entre 20 y 30 referencias de 2021 en adelante. El generador filtra la bibliografía del sílabo para priorizar fuentes posteriores a 2020 y reescribe la sección si detecta referencias de 2020 o anteriores.

El script genera un archivo por cada tema detectado. Para este sílabo, los temas esperados son:

1. Escucha activa
2. Comunicación verbal
3. Comunicación no verbal
4. Empatía
5. Asertividad

Los documentos se nombran con el formato:

```text
G[numero]_nombre-del-tema.docx
```

Ejemplo:

```text
G1_marco-logico.docx
G2_viabilidad-del-mercado-internacional.docx
```

## Extensión esperada

Cada documento queda diseñado para aproximarse a 20 a 30 páginas, dependiendo del interlineado y formato final de Word. Si un archivo sigue quedando corto, aumenta `--max-tokens` por sección:

```powershell
python generate_guiones.py --syllabus "7. Habilidades Comunicativas.docx" --max-tokens 6000
```

## Nota de seguridad

Si una API key fue compartida en un chat o documento, conviene revocarla y crear una nueva desde el panel de OpenAI. Este proyecto espera la key desde `OPENAI_API_KEY` para evitar dejar secretos guardados en archivos.
