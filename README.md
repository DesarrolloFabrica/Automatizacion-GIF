# Generador semiautomatizado de guiones académicos

Este proyecto toma un sílabo en Word (`.docx`) o PDF (`.pdf`), identifica la información principal de la asignatura, divide el curso en cinco temas y genera cinco documentos base con una estructura homogénea tipo guion editorial.

## Estructura del proyecto

```
./
├── frontend/                    # React + Vite + TypeScript
├── backend/                     # FastAPI API
├── automation_engine/           # Motor de automatización Python
│   ├── __init__.py
│   ├── generate_guiones.py
│   ├── generate_txt_from_drive.py
│   ├── generate_txt_from_guiones.py
│   ├── generate_documentos_academicos.py
│   ├── generate_pipeline_drive.py
│   └── repair_generated_docs.py
├── prompts/                     # Prompts por nivel académico
├── outputs/                     # Documentos generados
├── inputs/                      # Archivos fuente para documentos académicos
├── entrada_guiones_txt/         # Guiones de entrada para flujo TXT
├── salidas_txt/                 # TXT generados desde guiones
├── jobs/                        # Trabajos temporales del backend
├── samples/syllabus/            # Sílabos de ejemplo
├── notebooks/                   # Notebooks Jupyter
├── docs/                        # Documentación
├── requirements.txt
├── .env
└── README.md
```

## Archivos principales

- `automation_engine/generate_guiones.py`: motor principal para extraer el sílabo y generar los documentos.
- `prompts/`: carpeta de prompts por nivel academico (`pregrado.md`, `especializacion.md`, `diplomado.md`, `maestria.md`).
- `notebooks/generador_guiones.ipynb`: flujo en Jupyter para el equipo.
- `outputs/`: carpeta donde quedan los `.docx` generados.

> Ejecuta los scripts desde la raíz del repositorio usando `python -m automation_engine.<modulo>` (ver secciones siguientes).

## Instalación

```powershell
pip install -r requirements.txt
```

Configura la API key como variable de entorno. No la dejes escrita dentro del código.

```powershell
$env:OPENAI_API_KEY="TU_API_KEY"
$env:OPENAI_MODEL="gpt-4o"
```

## Cómo ejecutar

### Backend API

```powershell
cd backend
uvicorn main:app --reload --port 8000
```

### Frontend

```powershell
cd frontend
npm run dev
```

### CLI (motor Python como módulo)

```powershell
python -m automation_engine.generate_guiones --syllabus "samples/syllabus/archivo.docx" --nivel pregrado --output-dir outputs
```

## Prueba sin consumir API

```powershell
python -m automation_engine.generate_guiones --syllabus "7. Habilidades Comunicativas.docx" --dry-run
```

También puedes probar un PDF:

```powershell
python -m automation_engine.generate_guiones --syllabus "Mi Silabo.pdf" --dry-run
```

Por defecto el script usa `--nivel auto`: intenta detectar si el silabo corresponde a pregrado, especializacion, diplomado o maestria, y carga el prompt de `prompts/<nivel>.md`.

Si quieres elegir el prompt manualmente, usa `--nivel`:

```powershell
python -m automation_engine.generate_guiones --syllabus "Silabo Especializacion.docx" --nivel especializacion --dry-run
python -m automation_engine.generate_guiones --syllabus "Silabo Diplomado.pdf" --nivel diplomado --dry-run
python -m automation_engine.generate_guiones --syllabus "Silabo Maestria.docx" --nivel maestria --dry-run
python -m automation_engine.generate_guiones --syllabus "Silabo Pregrado.docx" --nivel pregrado --dry-run
```

Tambien puedes usar un prompt externo puntual con `--prompt`:

```powershell
python -m automation_engine.generate_guiones --syllabus "Mi Silabo.docx" --nivel especializacion --prompt "prompts/especializacion.md"
```

## Generación real

```powershell
python -m automation_engine.generate_guiones --syllabus "7. Habilidades Comunicativas.docx" --semester "Semestre N°1" --subject "Habilidades Comunicativas"
```

Ejemplo para especializacion:

```powershell
python -m automation_engine.generate_guiones --syllabus "Silabo Especializacion.docx" --nivel especializacion
```

Si el PDF o el sílabo tiene un formato difícil y no detecta los cinco temas, puedes forzarlos manualmente:

```powershell
python -m automation_engine.generate_guiones --syllabus "Mi Silabo.pdf" --subject "Nombre de la materia" --semester "Semestre N°2" --topics "Tema 1; Tema 2; Tema 3; Tema 4; Tema 5"
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
python -m automation_engine.generate_guiones --syllabus "7. Habilidades Comunicativas.docx" --max-tokens 6000
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
python -m automation_engine.generate_txt_from_guiones --dry-run
```

Generación real:

```powershell
python -m automation_engine.generate_txt_from_guiones
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
python -m automation_engine.generate_txt_from_guiones --titles "Guion 1; Guion 2; Guion 3; Guion 4"
```

También puedes cambiar la cantidad:

```powershell
python -m automation_engine.generate_txt_from_guiones --count 5
```

## Flujo 3: generar TXT leyendo desde Google Drive

Este flujo usa OAuth con el correo que tiene acceso a la carpeta de Drive. La primera vez abre el navegador para iniciar sesión y autorizar permisos. Luego guarda el acceso en `token_drive.json`.

Archivos necesarios:

```text
credentials.json
```

Ese archivo es el OAuth Client JSON descargado desde Google Cloud. Déjalo en la raíz del proyecto.

El script lee únicamente archivos Word `.docx` desde una carpeta de Drive por ID, ignora otros formatos como `.mpr`, crea o reutiliza una subcarpeta llamada `contenido complementario`, y sube allí los TXT generados.

El ID de carpeta sale de la URL de Drive. Ejemplo:

```text
https://drive.google.com/drive/folders/ID_DE_LA_CARPETA
```

Prueba sin consumir OpenAI ni subir resultados:

```powershell
python -m automation_engine.generate_txt_from_drive --drive-folder-id "ID_DE_LA_CARPETA" --dry-run
```

Generación real:

```powershell
python -m automation_engine.generate_txt_from_drive --drive-folder-id "ID_DE_LA_CARPETA"
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
python -m automation_engine.generate_txt_from_drive --drive-folder-id "ID_DE_LA_CARPETA" --programa "ADMINISTRACIÓN DEPORTIVA" --asignatura "Macroeconomía"
```

Con nombres/enfoques personalizados:

```powershell
python -m automation_engine.generate_txt_from_drive --drive-folder-id "ID_DE_LA_CARPETA" --titles "PDA; Quiz 1; Quiz 2; Quiz 3"
```

## Nota de seguridad

Si una API key fue compartida en un chat o documento, conviene revocarla y crear una nueva desde el panel de OpenAI. Este proyecto espera la key desde `OPENAI_API_KEY` para evitar dejar secretos guardados en archivos.

## Generador de documentos académicos (ACA, PRESENTACIÓN, FORO)

Flujo independiente del generador de guiones. Toma exactamente 5 archivos fuente (`.pdf`, `.docx` o `.txt`) desde la carpeta `inputs/`, los analiza con OpenAI usando un prompt maestro y produce 3 documentos `.docx` listos para entrega institucional. La estructura de cada documento está definida en el prompt y en el código; no requiere plantillas externas.

### Uso rápido (recomendado)

1. Coloca exactamente 5 archivos en `inputs/`.
2. Ejecuta:

```powershell
python -m automation_engine.generate_documentos_academicos
```

El script infiere automáticamente la asignatura y el programa del contenido de los archivos. Los resultados quedan en `outputs/documentos_academicos/`.

### Uso con parámetros explícitos

```powershell
python -m automation_engine.generate_documentos_academicos --input-dir "inputs" --output-dir "outputs\documentos_academicos" --subject "Macroeconomía" --program "Administración Deportiva"
```

Para revisar lectura y prompt sin consumir API:

```powershell
python -m automation_engine.generate_documentos_academicos --dry-run
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

## Pipeline unificado desde Drive (TXT + ACA + PRESENTACIÓN + FORO)

Este flujo combina los dos anteriores en un solo comando: descarga los 5 `.docx` desde una carpeta de Google Drive, genera los 4 TXT (PDA + QUIZ 1-3) y los 3 documentos académicos (ACA, PRESENTACIÓN, FORO), y sube todo a Drive dentro de la carpeta `contenido complementario/` que ya usa el flujo del compañero.

Estructura final en Drive después de ejecutar:

```text
<carpeta fuente>/
└── contenido complementario/
    ├── txt/
    │   ├── PDA.txt
    │   ├── QUIZ 1.txt
    │   ├── QUIZ 2.txt
    │   └── QUIZ 3.txt
    ├── ACA_<ASIGNATURA>_<PROGRAMA>.docx
    ├── PRESENTACION_<ASIGNATURA>_<PROGRAMA>.docx
    └── FORO_<ASIGNATURA>_<PROGRAMA>.docx
```

Los flujos individuales (`automation_engine.generate_txt_from_drive` y `automation_engine.generate_documentos_academicos`) siguen funcionando como hasta ahora; este orquestador los combina sin modificarlos.

### Requisitos previos

- `credentials.json` en la raíz (mismo OAuth que usa el flujo Drive).
- `OPENAI_API_KEY` configurada en `.env` o variables de entorno.
- La primera ejecución pedirá autorización en el navegador y guardará `token_drive.json`.

### Uso rápido

```powershell
python -m automation_engine.generate_pipeline_drive --drive-folder-id "ID_DE_LA_CARPETA"
```

El script infiere asignatura y programa del contenido de los archivos.

### Con overrides

```powershell
python -m automation_engine.generate_pipeline_drive --drive-folder-id "ID_DE_LA_CARPETA" --asignatura "Salud Pública" --programa "Tecnología en Regencia de Farmacia"
```

### Modo prueba (no llama a OpenAI ni sube archivos)

```powershell
python -m automation_engine.generate_pipeline_drive --drive-folder-id "ID_DE_LA_CARPETA" --dry-run
```

Esto autentica con Drive, descarga las fuentes a un directorio temporal, crea las carpetas `contenido complementario/` y `contenido complementario/txt/` si no existen y muestra el manifest detectado.

### Solo TXT o solo DOCX

Si quieres regenerar solo una fase, usa los flags de salto:

```powershell
python -m automation_engine.generate_pipeline_drive --drive-folder-id "ID_DE_LA_CARPETA" --skip-docx
python -m automation_engine.generate_pipeline_drive --drive-folder-id "ID_DE_LA_CARPETA" --skip-txt
```

### Validación automática

Después de generar los DOCX el orquestador ejecuta `validate_blocks` (la misma del flujo académico): comprueba secciones obligatorias, regla de "al menos 5 compañeros" en el FORO, mínimo 3 referencias APA en el FORO, mínimo 6 en la BIBLIOGRAFÍA del ACA, presencia de los 4 ejes en el RESUMEN DE CONTENIDOS, los 3 CTA en la PRESENTACIÓN y ausencia de la palabra "Bloom" en el ACA. Si algo falla, los archivos igual se suben pero se imprime un bloque `ADVERTENCIAS DE VALIDACION` con detalle.
