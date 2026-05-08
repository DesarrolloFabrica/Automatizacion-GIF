import type { ChangeEvent } from 'react'

interface FileDropzoneProps {
  selectedFile: File | null
  onFileSelected: (file: File | null) => void
}

function FileDropzone({ selectedFile, onFileSelected }: FileDropzoneProps) {
  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null
    onFileSelected(file)
  }

  return (
    <article className="card granule-card">
      <div className="granule-card-header">
        <span className="granule-card-kicker">INSUMO</span>
      </div>
      <div className="granule-card-body">
        <h2>Syllabus</h2>
        <p className="card-description">
          Carga el archivo base del curso en formato Word para iniciar el flujo.
        </p>
        <div className="syllabus-dropzone">
          <label htmlFor="syllabus-file" className="file-input-label">
            Seleccionar archivo .docx
          </label>
          <input
            id="syllabus-file"
            type="file"
            accept=".docx"
            onChange={handleFileChange}
            className="file-input"
          />
          <p className={`file-pill ${selectedFile ? 'is-loaded' : ''}`}>
            {selectedFile ? `Archivo cargado: ${selectedFile.name}` : 'No hay archivo seleccionado.'}
          </p>
        </div>
      </div>
    </article>
  )
}

export default FileDropzone
