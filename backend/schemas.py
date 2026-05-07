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
