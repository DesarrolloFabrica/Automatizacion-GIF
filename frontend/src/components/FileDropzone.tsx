import type { ChangeEvent } from 'react'

interface FileDropzoneProps {
  selectedFile: File | null
  onFileSelected: (file: File | null) => void
  syllabusFileName?: string
}

function FileDropzone({ selectedFile, onFileSelected, syllabusFileName }: FileDropzoneProps) {
  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null
    onFileSelected(file)
  }

  const displayFileName = selectedFile?.name ?? syllabusFileName

  return (
    <article className="card granule-card syllabus-console-card">
      <div className="granule-card-header">
        <span className="granule-card-kicker">INPUT PRINCIPAL</span>
      </div>
      <div className="granule-card-body">
        <h2>Syllabus .docx</h2>
        <p className="card-description">
          Arranca el pipeline académico desde el documento base del curso.
        </p>
        <div className="syllabus-dropzone">
          <label htmlFor="syllabus-file" className="file-input-label">
            <strong>Soltar o seleccionar syllabus</strong>
            <span>Formato Word .docx</span>
          </label>
          <input
            id="syllabus-file"
            type="file"
            accept=".docx"
            onChange={handleFileChange}
            className="file-input"
          />
          <p className={`file-pill ${displayFileName ? 'is-loaded' : ''}`}>
            {displayFileName ?? 'Sin archivo cargado'}
          </p>
        </div>
      </div>
    </article>
  )
}

export default FileDropzone
