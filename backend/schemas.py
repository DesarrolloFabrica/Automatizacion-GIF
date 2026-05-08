from __future__ import annotations

from pydantic import BaseModel


class JobCreateResponse(BaseModel):
    jobId: str
    status: str


class JobStatusResponse(BaseModel):
    jobId: str
    status: str
    progressStep: str
    logs: list[str]
    files: list[str]
    granulesStatus: str = "pending"
    pipelineLocalStatus: str = "pending"
    specializationMaterialsStatus: str = "pending"
    currentPhase: str = "pending"
    availableNextAction: str = "none"
    phaseStatus: dict | None = None


class PreviewTopic(BaseModel):
    index: int
    title: str


class DetectedCourse(BaseModel):
    asignatura: str
    programa: str
    escuela: str
    semestre: str
    temas: list[str]


class SyllabusPreviewResponse(BaseModel):
    fileName: str
    subjectName: str
    programName: str
    detectedTopics: list[PreviewTopic]
    totalGranules: int
    coursesDetected: list[DetectedCourse] = []
    selectedCourse: DetectedCourse | None = None


class DriveUploadLink(BaseModel):
    name: str
    link: str
    kind: str  # "txt" | "docx"


class ScriptsJobCreateResponse(BaseModel):
    jobId: str
    status: str


class ScriptsJobStatusResponse(BaseModel):
    jobId: str
    status: str
    progressStep: str
    logs: list[str]
    driveLinks: list[DriveUploadLink]


class LocalGeneratedFile(BaseModel):
    name: str
    kind: str  # "txt" | "docx"
    sizeBytes: int


class ScriptsLocalJobCreateResponse(BaseModel):
    jobId: str
    status: str


class ScriptsLocalJobStatusResponse(BaseModel):
    jobId: str
    status: str
    progressStep: str
    logs: list[str]
    files: list[LocalGeneratedFile]


class MaterialFile(BaseModel):
    granule: str
    name: str
    relativePath: str


class GranuleMaterials(BaseModel):
    granuleCode: str
    granuleFolder: str
    files: list[MaterialFile]
    totalMaterials: int


class EspecializacionJobStatusResponse(BaseModel):
    jobId: str
    status: str
    progressStep: str
    logs: list[str]
    files: list[str]
    granulesMaterials: list[GranuleMaterials]
