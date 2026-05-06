# Generador semiautomatizado de guiones académicos

Este proyecto toma un sílabo en Word (`.docx`) o PDF (`.pdf`), identifica la información principal de la asignatura, divide el curso en cinco temas y genera cinco documentos base con una estructura homogénea tipo guion editorial.

## Archivos principales

- `generate_guiones.py`: script principal para extraer el sílabo y generar los documentos.
- `prompts/`: carpeta de prompts por nivel academico (`pregrado.md`, `especializacion.md`, `diplomado.md`, `maestria.md`).
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

Por defecto el script usa `--nivel auto`: intenta detectar si el silabo corresponde a pregrado, especializacion, diplomado o maestria, y carga el prompt de `prompts/<nivel>.md`.

Si quieres elegir el prompt manualmente, usa `--nivel`:

```powershell
python generate_guiones.py --syllabus "Silabo Especializacion.docx" --nivel especializacion --dry-run
python generate_guiones.py --syllabus "Silabo Diplomado.pdf" --nivel diplomado --dry-run
python generate_guiones.py --syllabus "Silabo Maestria.docx" --nivel maestria --dry-run
python generate_guiones.py --syllabus "Silabo Pregrado.docx" --nivel pregrado --dry-run
```

Tambien puedes usar un prompt externo puntual con `--prompt`:

```powershell
python generate_guiones.py --syllabus "Mi Silabo.docx" --nivel especializacion --prompt "prompts/especializacion.md"
```

## Generación real

```powershell
python generate_guiones.py --syllabus "7. Habilidades Comunicativas.docx" --semester "Semestre N°1" --subject "Habilidades Comunicativas"
```

Ejemplo para especializacion:

```powershell
python generate_guiones.py --syllabus "Silabo Especializacion.docx" --nivel especializacion
```

Si el PDF o el sílabo tiene un formato difícil y no detecta los cinco temas, puedes forzarlos manualmente:

```powershell
python generate_guiones.py --syllabus "Mi Silabo.pdf" --subject "Nombre de la materia" --semester "Semestre N°2" --topics "Tema 1; Tema 2; Tema 3; Tema 4; Tema 5"
```

El generador crea cada documento largo por secciones. Para cada tema hace varias llamadas a la API: introducción, ejes articuladores, tres ensayos de profundización, conclusiones y bibliografía. Esto evita que el modelo entregue documentos demasiado cortos.

Además, el script valida la extensión mínima de cada sección. Si una sección queda corta, solicita automáticamente una ampliación antes de ensamblar el `.docx`.

La bibliografía se ajusta al nivel seleccionado: pregrado usa 20 a 30 referencias, especializacion 30 a 40, diplomado 15 a 25 y maestria 40 a 55. El generador filtra la bibliografía del sílabo para priorizar fuentes posteriores a 2020 y reescribe la sección si detecta referencias de 2020 o anteriores.

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

## Flujo 2: generar TXT desde guiones ya creados

Este flujo usa como entrada los guiones `.docx` que ya tengas generados y produce varios archivos `.txt` nuevos usando un prompt específico.

Carpeta de entrada:

```text
entrada_guiones_txt
```

Carpeta de salida:

```text
salidas_txt
```

Coloca en `entrada_guiones_txt` los 4 o 5 guiones `.docx` ya creados. Luego crea el prompt específico en:

```text
prompts/txt_desde_guiones.md
```

Prueba sin consumir API:

```powershell
python generate_txt_from_guiones.py --dry-run
```

Generación real:

```powershell
python generate_txt_from_guiones.py
```

Por defecto genera estos 4 TXT:

```text
PDA.txt
QUIZ 1.txt
QUIZ 2.txt
QUIZ 3.txt
```

Si quieres indicar otros nombres o enfoques para los 4 TXT:

```powershell
python generate_txt_from_guiones.py --titles "Guion 1; Guion 2; Guion 3; Guion 4"
```

También puedes cambiar la cantidad:

```powershell
python generate_txt_from_guiones.py --count 5
```

## Flujo 3: generar TXT leyendo desde Google Drive

Este flujo usa OAuth con el correo que tiene acceso a la carpeta de Drive. La primera vez abre el navegador para iniciar sesión y autorizar permisos. Luego guarda el acceso en `token_drive.json`.

Archivos necesarios:

```text
credentials.json
```

Ese archivo es el OAuth Client JSON descargado desde Google Cloud. Déjalo en la raíz del proyecto, junto a `generate_txt_from_drive.py`.

El script lee únicamente archivos Word `.docx` desde una carpeta de Drive por ID, ignora otros formatos como `.mpr`, crea o reutiliza una subcarpeta llamada `contenido complementario`, y sube allí los TXT generados.

El ID de carpeta sale de la URL de Drive. Ejemplo:

```text
https://drive.google.com/drive/folders/ID_DE_LA_CARPETA
```

Prueba sin consumir OpenAI ni subir resultados:

```powershell
python generate_txt_from_drive.py --drive-folder-id "ID_DE_LA_CARPETA" --dry-run
```

Generación real:

```powershell
python generate_txt_from_drive.py --drive-folder-id "ID_DE_LA_CARPETA"
```

Por defecto genera o actualiza estos archivos en la subcarpeta `contenido complementario`:

```text
PDA.txt
QUIZ 1.txt
QUIZ 2.txt
QUIZ 3.txt
```

Si el programa o la asignatura no se detectan bien desde los Word, indícalos manualmente:

```powershell
python generate_txt_from_drive.py --drive-folder-id "ID_DE_LA_CARPETA" --programa "ADMINISTRACIÓN DEPORTIVA" --asignatura "Macroeconomía"
```

Con nombres/enfoques personalizados:

```powershell
python generate_txt_from_drive.py --drive-folder-id "ID_DE_LA_CARPETA" --titles "PDA; Quiz 1; Quiz 2; Quiz 3"
```

## Nota de seguridad

Si una API key fue compartida en un chat o documento, conviene revocarla y crear una nueva desde el panel de OpenAI. Este proyecto espera la key desde `OPENAI_API_KEY` para evitar dejar secretos guardados en archivos.

## Generador de documentos académicos (ACA, PRESENTACIÓN, FORO)

Flujo independiente del generador de guiones. Toma exactamente 5 archivos fuente (`.pdf`, `.docx` o `.txt`) desde la carpeta `inputs/`, los analiza con OpenAI usando un prompt maestro y produce 3 documentos `.docx` listos para entrega institucional. La estructura de cada documento está definida en el prompt y en el código; no requiere plantillas externas.

### Uso rápido (recomendado)

1. Coloca exactamente 5 archivos en `inputs/`.
2. Ejecuta:

```powershell
python generate_documentos_academicos.py
```

El script infiere automáticamente la asignatura y el programa del contenido de los archivos. Los resultados quedan en `outputs/documentos_academicos/`.

### Uso con parámetros explícitos

```powershell
python generate_documentos_academicos.py --input-dir "inputs" --output-dir "outputs\documentos_academicos" --subject "Macroeconomía" --program "Administración Deportiva"
```

Para revisar lectura y prompt sin consumir API:

```powershell
python generate_documentos_academicos.py --dry-run
```

### Estructura de carpetas

- `inputs/`: coloca aquí los 5 archivos fuente (`.pdf`, `.docx` o `.txt`).
- `outputs/documentos_academicos/`: aquí se guardan los `.docx` generados.
- `prompts/system_prompt_documentos_academicos.md`: prompt maestro editable.

### Salida esperada

Tres archivos en `outputs/documentos_academicos/`:

- `ACA_ASIGNATURA_PROGRAMA.docx`
- `PRESENTACION_ASIGNATURA_PROGRAMA.docx`
- `FORO_ASIGNATURA_PROGRAMA.docx`

Todos en Arial 12, títulos Arial 14 negrita, fuente negra, viñetas donde corresponde.
