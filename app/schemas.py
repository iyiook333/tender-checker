from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ResultCategory(str, Enum):
    qualification = "qualification"
    rejection = "rejection"
    materials = "materials"
    deadlines = "deadlines"


class SourceLocation(BaseModel):
    source_id: str
    page: int | None = None
    paragraph: int | None = None
    table: int | None = None
    row: int | None = None
    column: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    label: str


class DocumentSegment(BaseModel):
    source_id: str
    text: str
    location: SourceLocation
    start_offset: int
    end_offset: int


class ParsedDocument(BaseModel):
    filename: str
    media_type: str
    segments: list[DocumentSegment]
    warnings: list[str] = Field(default_factory=list)
    total_characters: int = 0


class ExtractedItem(BaseModel):
    category: ResultCategory
    title: str = Field(min_length=1, max_length=500)
    requirement: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(min_length=1, max_length=3000)
    source_id: str
    severity: str = "待核验"
    confidence: float = Field(default=0.5, ge=0, le=1)
    ambiguity: str | None = None
    time_type: str | None = None
    normalized_time: str | None = None
    verified: bool = False
    verification_note: str | None = None
    location: SourceLocation | None = None


class LLMItem(BaseModel):
    category: ResultCategory
    title: str
    requirement: str
    evidence: str
    source_id: str
    severity: str = "待核验"
    confidence: float = 0.5
    ambiguity: str | None = None
    time_type: str | None = None
    normalized_time: str | None = None


class TaskStatus(BaseModel):
    task_id: str
    filename: str
    status: str
    stage: str
    progress: int = Field(ge=0, le=100)
    message: str = ""
    warnings: list[str] = Field(default_factory=list)
    result: dict[str, list[ExtractedItem]] | None = None
    error: str | None = None


class AnalyzeOptions(BaseModel):
    model: str | None = None
    protocol: str = "openai"
    base_url: str | None = None
    max_concurrency: int | None = Field(default=None, ge=1, le=4)


def empty_result() -> dict[str, list[ExtractedItem]]:
    return {category.value: [] for category in ResultCategory}


def item_to_dict(item: ExtractedItem) -> dict[str, Any]:
    return item.model_dump(mode="json")
