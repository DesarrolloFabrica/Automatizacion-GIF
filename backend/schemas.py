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


class PreviewTopic(BaseModel):
    index: int
    title: str


class SyllabusPreviewResponse(BaseModel):
    fileName: str
    subjectName: str
    detectedTopics: list[PreviewTopic]
    totalGranules: int


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
