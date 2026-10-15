from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class CourseInput(Input):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)

    @field_validator("title")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("제목을 입력하세요")
        return value.strip()

class SessionInput(CourseInput):
    kind: Literal["lecture", "meeting"]
    course_id: str | None = None
    lecture_no: int | None = Field(default=None, ge=1)
    started_at: str | None = None

class Session(SessionInput):
    id: str
    created_at: str
    recording_status: str = "idle"

class SourceRef(BaseModel):
    id: str
    kind: Literal["material", "transcript", "note", "web", "ai_interpretation"]
    asset_id: str | None = None
    session_id: str | None = None
    version: int = 1
    url: str | None = None
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    coord_system: Literal["pdf_points", "pixels"] | None = None
    source_width: float | None = None
    source_height: float | None = None
    start_ms: int | None = None
    end_ms: int | None = None


class Scope(Input):
    session_id: str
    mode: Literal["course","current","selected"] = "course"
    lecture_ids: list[str] = Field(default_factory=list,max_length=2000)

class Evidence(BaseModel):
    ref: SourceRef
    text: str
    label: str
    retrieved_at: str | None = None

class SearchResult(BaseModel):
    evidence: list[Evidence]
    mode: Literal["keyword","hybrid"]
    warning: str | None = None

class ProviderConfig(Input):
    provider: Literal['openai','gemini','claude','ollama'] = 'ollama'
    model: str = Field(default='qwen3.5:4b',pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,199}$')
    context_limit: int = Field(default=8192,ge=512,le=262144)
    vision: bool = False

class ProviderResult(BaseModel):
    digest:str|None=None
    text: str
    model: str
    usage: dict
    elapsed_ms: int

class AIRequest(Input):
    session_id: str
    kind: Literal['answer','explain','summary','quiz','grade','minutes','vision','note','candidates']
    prompt: str=Field(default='',max_length=10000)
    scope: Scope
    provider: ProviderConfig
    web: bool=False
    web_query: str|None=Field(default=None,max_length=500)
    image_id: str|None=None
    note_source_id: str|None=None
    anchor_ms: int|None=Field(default=None,ge=0,strict=True)

class GeneratedArtifact(BaseModel):
    id: str
    job_id: str
    kind: str
    body: dict
    evidence: list[Evidence]
    provider: str
    model: str
    cutoff_ms: int|None
    retrieval_mode: str
    edited: bool=False
    confirmed: bool=False
