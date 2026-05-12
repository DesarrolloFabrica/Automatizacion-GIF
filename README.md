# Automatizacion GIF

Aplicacion para generar materiales academicos con IA a partir de archivos de entrada.

La app tiene tres capas:

- `frontend/`: interfaz web en React + Vite + TypeScript.
- `backend/`: API FastAPI que recibe archivos, crea jobs y expone estados/descargas.
- `automation_engine/`: motor Python que lee documentos, llama a OpenAI y genera archivos de salida.
- `prompts/`: prompts editables usados por el motor.

## Flujo General

1. El usuario carga archivos desde la interfaz web o indica una carpeta de Google Drive.
2. El backend crea un job temporal.
3. El backend ejecuta un script del motor Python.
4. El motor lee los archivos fuente, construye el prompt y llama a OpenAI.
5. Los resultados se guardan temporalmente para descarga o se suben a Drive.

## Estructura Actual

```text
./
├── automation_engine/
│   ├── generate_guiones.py
│   ├── generate_txt_from_drive.py
│   ├── generate_txt_from_guiones.py
│   ├── generate_documentos_academicos.py
│   ├── generate_pipeline_drive.py
│   ├── generate_pipeline_local.py
│   └── repair_generated_docs.py
├── backend/
│   ├── main.py
│   ├── jobs.py
│   ├── schemas.py
│   └── storage.py
├── frontend/
├── prompts/
├── requirements.txt
└── README.md
```

## Carpetas de Entrada y Salida

Estas carpetas se eliminaron del repositorio porque no son necesarias como parte fija de la app:

- `inputs/`
- `entrada_guiones_txt/`
- `salidas_txt/`
- `samples/`
- `jobs/`
- `outputs/`
- `notebooks/`

La app web no necesita que esas carpetas existan antes de ejecutarse. Cuando corre un job local, el backend crea automaticamente carpetas temporales bajo:

```text
outputs/jobs/<job_id>/
```

Ese directorio es runtime: sirve para guardar insumos subidos, logs, archivos generados y ZIPs mientras el job esta disponible.

## Uso en Nube

Para despliegue en nube, no conviene depender de carpetas persistentes dentro del repo para entradas o salidas.

Recomendado:

- Entradas: subir por HTTP, leer desde Drive o recibirlas desde storage externo.
- Salidas temporales: usar disco efimero del servidor solo durante el job.
- Salidas definitivas: subir a Drive, S3, Cloud Storage, base de datos de archivos o devolver un ZIP descargable.
- Credenciales: configurar variables de entorno o secretos del proveedor cloud.

El backend actual usa `outputs/jobs` como almacenamiento temporal local. Funciona para desarrollo y para un servidor simple, pero en produccion deberia limpiarse periodicamente o reemplazarse por storage externo si se van a conservar resultados.

## Variables de Entorno

Configura:

```powershell
$env:OPENAI_API_KEY="TU_API_KEY"
$env:OPENAI_MODEL="gpt-4o"
```

Para Google Drive, en desarrollo local se usan:

- `credentials.json`
- `token_drive.json`

Para subir el paquete academico final a Drive se recomienda service account:

```powershell
$env:GOOGLE_SERVICE_ACCOUNT_FILE="C:\\ruta\\service-account.json"
```

Tambien puede configurarse en `.env`:

```text
GOOGLE_SERVICE_ACCOUNT_FILE=credentials/service-account.json
```

Comparte la carpeta destino de Drive con el email `client_email` del service account y dale permiso de Editor. El usuario pega el Folder ID en la interfaz; esa carpeta es la raíz académica en Drive (`SYLLABUS`, `CONTENIDOS`, etc.). El ZIP local puede seguir usando la carpeta lógica `PAQUETE_ACADEMICO` solo como empaquetado en archivo.

En nube, esos valores deberian manejarse como secretos, no como archivos versionados.

## Ejecutar Backend

```powershell
pip install -r requirements.txt
pip install -r backend/requirements.txt
cd backend
uvicorn main:app --reload --port 8000
```

## Ejecutar Frontend

```powershell
cd frontend
npm install
npm run dev
```

## Ejecutar con Docker

La imagen Docker es monolitica: compila el frontend React y lo sirve desde FastAPI junto con la API en el puerto `8000`.

Construir imagen:

```powershell
docker build -t automatizacion-gif:latest .
```

Ejecutar un contenedor:

```powershell
docker run --rm -p 8000:8000 `
  -e OPENAI_API_KEY="TU_API_KEY" `
  -e OPENAI_MODEL="gpt-4o" `
  -v "${PWD}\outputs:/tmp/automatizacion-gif" `
  automatizacion-gif:latest
```

La configuracion anterior de Docker Compose se retiro para evitar mantener dos caminos de ejecucion. El camino oficial es una unica imagen monolitica, lista para ejecutar localmente o desplegar en Cloud Run.

Para Drive con service account, monta credenciales como secreto/volumen y apunta la variable:

```powershell
docker run --rm -p 8000:8000 `
  -e OPENAI_API_KEY="TU_API_KEY" `
  -e GOOGLE_SERVICE_ACCOUNT_FILE="/app/credentials/service-account.json" `
  -v "${PWD}\credentials:/app/credentials:ro" `
  -v "${PWD}\outputs:/tmp/automatizacion-gif" `
  automatizacion-gif:latest
```

## Branching y Deploy en Cloud Run

La estrategia de ramas es:

- `main`: produccion.
- `integration`: desarrollo/integracion y despliegue automatico a Cloud Run de integracion.

El workflow `.github/workflows/integration.yml` se llama `integration`. Construye la imagen monolitica, la sube a Artifact Registry y despliega Cloud Run cuando hay push a la rama `integration`.

Configura estas variables en GitHub Actions:

- `GCP_PROJECT_ID`: ID del proyecto GCP.
- `GCP_REGION`: region de Cloud Run, por ejemplo `us-central1`.
- `GAR_REPOSITORY`: repositorio Docker de Artifact Registry, por ejemplo `cloud-run`.
- `CLOUD_RUN_SERVICE`: nombre del servicio de integracion, por ejemplo `automatizacion-gif-integration`.
- `IMAGE_NAME`: nombre base de la imagen, por ejemplo `automatizacion-gif`.
- `OPENAI_MODEL`: modelo OpenAI, por ejemplo `gpt-4o`.
- `CLOUD_RUN_MEMORY`, `CLOUD_RUN_CPU`, `CLOUD_RUN_TIMEOUT`, `CLOUD_RUN_CONCURRENCY`, `CLOUD_RUN_MAX_INSTANCES`: opcionales para dimensionar el servicio.
- `CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT`: opcional si quieres que Cloud Run ejecute con un service account distinto al que usa GitHub para desplegar.

Configura estos secretos en GitHub Actions:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`: recurso completo del provider de Workload Identity Federation.
- `GCP_SERVICE_ACCOUNT`: email del service account que GitHub Actions impersona para construir y desplegar.

Configura este secreto en Google Secret Manager:

- `OPENAI_API_KEY`: API key de OpenAI. El workflow lo monta en Cloud Run como variable de entorno usando `--set-secrets`.

Autenticacion de Google Drive:

- En Cloud Run no hay login OAuth de usuario en la interfaz. La app se autentica desde el backend con el service account del servicio.
- El usuario pega el ID de la carpeta Drive en la interfaz.
- Para que la app pueda leer/crear/actualizar archivos, comparte esa carpeta Drive con el email del service account de Cloud Run y dale permiso de Editor.
- En local se puede seguir usando `credentials.json` + `token_drive.json` o `GOOGLE_SERVICE_ACCOUNT_FILE`.

## Flujos Disponibles

### Crear Granulos

Endpoint principal:

```text
POST /api/jobs
```

Ejecuta:

```powershell
python -m automation_engine.generate_guiones
```

Entrada: un syllabus `.docx`.

Salida: documentos `.docx` descargables.

### Crear Materiales Desde Drive

Endpoint principal:

```text
POST /api/scripts/jobs
```

Ejecuta:

```powershell
python -m automation_engine.generate_pipeline_drive
```

Entrada: carpeta de Google Drive con granulos fuente.

Salida: TXT y DOCX subidos a Drive.

### Crear Materiales Desde Archivos Locales

Endpoint principal:

```text
POST /api/scripts/local/jobs
```

Ejecuta:

```powershell
python -m automation_engine.generate_pipeline_local
```

Entrada: 4 o 5 archivos `.docx` o `.pdf` subidos desde la interfaz.

Salida: TXT y DOCX descargables.

## Notas de Mantenimiento

- `automation_engine/generate_txt_from_guiones.py` conserva defaults historicos para uso CLI, pero la app web usa rutas temporales generadas por el backend.
- `automation_engine/generate_documentos_academicos.py` conserva defaults historicos para uso CLI, pero los pipelines web le pasan archivos explicitamente.
- `outputs/jobs/` se crea en tiempo de ejecucion y esta ignorado por Git.
