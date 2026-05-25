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

En desarrollo Vite proxifica `/api` hacia `http://localhost:8000`, por lo que puedes dejar `VITE_API_BASE_URL` vacío. Si sirves frontend y backend por separado en otro host, define `VITE_API_BASE_URL` con la URL del backend. En la imagen monolítica de deploy, `VITE_API_BASE_URL` puede quedar vacío porque FastAPI sirve frontend y API desde el mismo origen.

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

Nota operativa: mientras los jobs vivan en memoria y `/tmp`, Cloud Run debe preferir `max-instances=1` para evitar que el polling consulte una instancia distinta a la que creó el job. El frontend maneja `404/410` como estado recuperable, pero el almacenamiento compartido sigue siendo la solución definitiva para escalar múltiples instancias.

Configura estas variables en GitHub Actions:

- `GCP_PROJECT_ID`: ID del proyecto GCP.
- `GCP_REGION`: opcional. Si no existe usa `us-central1`.
- `GCP_ARTIFACT_REPOSITORY`: opcional. Si no existe usa `cloud-run`.
- `CLOUD_RUN_SERVICE`: opcional. Si no existe usa `automatizacion-gif-integration`.
- `CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT`: opcional. Si no existe Cloud Run usa su service account por defecto.
- `OPENAI_MODEL`: opcional. Si no existe usa `gpt-4o`.

Configura este secreto en GitHub Actions:

- `GCP_SA_KEY`: JSON completo del service account que GitHub Actions usa para construir, subir la imagen y desplegar.

Configura este secreto en Google Secret Manager:

- `OPENAI_API_KEY`: API key de OpenAI. El workflow lo monta en Cloud Run como variable de entorno usando `--set-secrets`.

Versionamiento de imagenes:

- Cada despliegue a `integration` crea una imagen `latest` y otra versionada `vMAJOR.MINOR.PATCH`.
- Si el despliegue viene de un PR, el workflow lee labels `major`, `minor` o `patch`. Si no encuentra label, usa `patch`.
- Si se ejecuta manualmente (`workflow_dispatch`), puedes escoger `major`, `minor` o `patch`.
- Tambien crea el tag Git anotado correspondiente, por ejemplo `v1.2.3`.

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

## Arquitectura de Persistencia (Fase 2)

### Estado Actual

El backend usa un modelo de persistencia en dos niveles:

| Nivel | Proposito | Ubicacion |
|---|---|---|
| **Memoria** | Estado en vivo de jobs activos | `jobs.py: _JOBS` |
| **/tmp (staging)** | Archivos durante generacion | `/tmp/automatizacion-gif/jobs/{job_id}/` |
| **GCS (opcional)** | Persistencia de archivos generados | `gs://GCS_BUCKET/jobs/{job_id}/` |

### /tmp como Staging

`/tmp` se usa exclusivamente como espacio de trabajo temporal durante la generacion:

- Los subprocesses escriben archivos aqui mientras trabajan
- Al completar cada fase, los archivos se sincronizan a GCS (si esta configurado)
- `/tmp` se limpia automaticamente en cada reinicio de Cloud Run
- **No es almacenamiento principal**, solo staging

### GCS como Persistencia Opcional de Archivos

Si la variable `GCS_BUCKET` esta configurada, el backend sube automaticamente:

- Syllabus original al crear el job
- Archivos generados al completar cada fase (granules, pipeline_local, materials)
- ZIPs generados para descargas

Si `GCS_BUCKET` no esta configurado, el sistema funciona exactamente igual usando solo almacenamiento local.

Estructura en GCS:

```text
gs://GCS_BUCKET/
└── jobs/
    └── {job_id}/
        ├── input/syllabus.docx
        ├── generated/*.docx
        ├── pipeline_local/*.txt, *.docx
        ├── materials/**/*.docx
        └── zips/*.zip
```

### Descargas con Fallback

Los endpoints de descarga siguen esta logica:

1. Intentar leer archivo localmente (mas rapido)
2. Si no existe localmente y GCS_BUCKET esta configurado, descargar desde GCS a tmp
3. Si no existe en ningun lado, responder error 404 claro

### Firestore (Fase Futura)

La metadata de jobs (status, phase_status, logs, etc.) sigue almacenada en disco local via `LocalDiskJobStore`.

En la siguiente fase se implementara `FirestoreJobStore` para:

- Persistir metadata en Firestore (multi-instancia)
- TTL automatico para cleanup de jobs expirados
- Habilitar `max-instances > 1` en Cloud Run

### Multi-Instancia

Actualmente Cloud Run usa `max-instances=1` porque:

- Los jobs viven en memoria y `/tmp`
- Un job creado en instancia A no existe en instancia B

Multi-instancia se activara en Fase 5, despues de migrar metadata a Firestore.

### Variables de Persistencia

| Variable | Valor | Descripcion |
|---|---|---|
| `GCS_BUCKET` | `automatizacion-gif-jobs` | Bucket de GCS para persistencia de archivos (opcional) |
| `USE_FIRESTORE` | `0` | Preparado para futura fase, no implementar todavia |
| `AUTOMATIZACION_GIF_JOBS_ROOT` | `/tmp/automatizacion-gif/jobs` | Directorio local de staging |
| `AUTOMATIZACION_GIF_DRIVE_CONTENT_ROOT` | `/tmp/automatizacion-gif/drive_content` | Directorio temporal para Drive |

### Capas de Almacenamiento

```
backend/job_store.py            → Interfaz abstracta JobStore
backend/job_store_local.py      → Implementacion LocalDiskJobStore (actual)
backend/job_store_gcs.py        → GCSFileStore para archivos
backend/job_store_factory.py    → Factory para seleccionar implementacion
```
