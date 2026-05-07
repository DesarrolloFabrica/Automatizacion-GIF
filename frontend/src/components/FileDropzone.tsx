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
    <article className="card">
      <h2>Syllabus</h2>
      <p className="card-description">Carga el archivo base del curso en formato Word para iniciar el flujo.</p>

      {/* Input simple para MVP; luego puede reemplazarse por drag-and-drop completo. */}
      <label htmlFor="syllabus-file" className="file-input-label">
        Seleccionar archivo .docx
      </label>
      <input id="syllabus-file" type="file" accept=".docx" onChange={handleFileChange} className="file-input" />

      <p className="file-name">{selectedFile ? `Archivo cargado: ${selectedFile.name}` : 'No hay archivo seleccionado.'}</p>
    </article>
  )
}

export default FileDropzone
