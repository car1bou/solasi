from typing import Literal
import json
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    kind: Literal["material", "transcript", "note", "page_note", "ink_note", "web", "ai_interpretation"]
    asset_id: str | None = None
    session_id: str | None = None
    course_id: str | None = None
    document_id: str | None = None
    document_sha256: str | None = None
    version: int = 1
    url: str | None = None
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    coord_system: Literal["pdf_points", "pixels", "normalized"] | None = None
    source_width: float | None = None
    source_height: float | None = None
    start_ms: int | None = None
    end_ms: int | None = None


class OwnerInput(Input):
    session_id: str | None = None
    course_id: str | None = None

    @model_validator(mode="after")
    def one_owner(self):
        if bool(self.session_id)==bool(self.course_id):
            raise ValueError("회차 또는 과목 한 곳을 지정하세요")
        return self


class Scope(OwnerInput):
    mode: Literal["course","current","selected"] = "course"
    lecture_ids: list[str] = Field(default_factory=list,max_length=2000)
    asset_id: str | None = None
    page: int | None = Field(default=None,ge=1,strict=True)
    document_sha256: str | None = Field(default=None,pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode="after")
    def course_scope(self):
        if self.course_id and (self.mode!='course' or self.lecture_ids):
            raise ValueError("과목 자료 범위를 지정하세요")
        if (self.page is not None or self.document_sha256) and not self.asset_id:
            raise ValueError("페이지의 자료를 지정하세요")
        return self


class InkPoint(Input):
    x: float = Field(ge=0,le=1,allow_inf_nan=False,strict=True)
    y: float = Field(ge=0,le=1,allow_inf_nan=False,strict=True)
    pressure: float = Field(ge=0,le=1,allow_inf_nan=False,strict=True)
    tilt_x: float | None = Field(default=None,ge=-90,le=90,allow_inf_nan=False,strict=True)
    tilt_y: float | None = Field(default=None,ge=-90,le=90,allow_inf_nan=False,strict=True)


class InkStroke(Input):
    id: str = Field(min_length=1,max_length=200)
    tool: Literal['pen','highlighter']
    color: str = Field(pattern=r'^#[a-fA-F0-9]{6}$')
    width: float = Field(ge=.0002,le=.1,allow_inf_nan=False,strict=True)
    opacity: float = Field(ge=.05,le=1,allow_inf_nan=False,strict=True)
    input: Literal['mouse','pen','touch']
    points: list[InkPoint] = Field(min_length=1,max_length=100000)


class PageDocumentInput(Input):
    document_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    expected_revision: int = Field(ge=0,strict=True)
    text: str = Field(max_length=200000)
    ink: list[InkStroke] = Field(max_length=2000)

    @model_validator(mode='after')
    def bounded_ink(self):
        if sum(len(stroke.points) for stroke in self.ink)>100000:
            raise ValueError('필기는 전체 100,000점까지 저장할 수 있습니다')
        if len({stroke.id for stroke in self.ink})!=len(self.ink):
            raise ValueError('획 ID가 중복되었습니다')
        if len(json.dumps([stroke.model_dump(exclude_none=True) for stroke in self.ink],ensure_ascii=False,separators=(',',':')).encode())>8*1024*1024:
            raise ValueError('필기는 8 MiB까지 저장할 수 있습니다')
        return self

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
    provider: Literal['openai','gemini','claude','ollama','local'] = 'ollama'
    model: str = Field(default='qwen3.5:4b',pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,199}$')
    context_limit: int = Field(default=8192,ge=512,le=262144)
    vision: bool = False

class ProviderResult(BaseModel):
    digest:str|None=None
    text: str
    model: str
    usage: dict
    elapsed_ms: int

class AIRequest(OwnerInput):
    kind: Literal['answer','explain','summary','quiz','grade','minutes','vision','note','candidates']
    prompt: str=Field(default='',max_length=10000)
    scope: Scope
    provider: ProviderConfig
    image_id: str|None=None
    note_source_id: str|None=None
    anchor_ms: int|None=Field(default=None,ge=0,strict=True)

    @model_validator(mode='before')
    @classmethod
    def legacy_request(cls,value):
        # Archived jobs retain retired search fields; new API input rejects them.
        if isinstance(value,dict):
            return {key:item for key,item in value.items() if key not in ('web','web_query')}
        return value

    @model_validator(mode='after')
    def valid_target(self):
        if (self.session_id,self.course_id)!=(self.scope.session_id,self.scope.course_id):
            raise ValueError('질문 소유자와 검색 범위가 일치하지 않습니다')
        if self.course_id and self.kind not in ('answer','explain','summary','vision'):
            raise ValueError('과목에서는 답변·설명·요약·페이지 설명을 사용하세요')
        return self

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
