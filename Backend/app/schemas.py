from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RestaurantCreate(BaseModel):
    name: str
    location: str | None = None


class RestaurantRead(RestaurantCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class InventoryItemBase(BaseModel):
    restaurant_id: int
    name: str
    category: str | None = None
    default_unit: str
    aliases: list[str] = Field(default_factory=list)
    pack_size: str | None = None
    par_level: float | None = None
    vendor: str | None = None


class InventoryItemCreate(InventoryItemBase):
    pass


class InventoryItemUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    default_unit: str | None = None
    aliases: list[str] | None = None
    pack_size: str | None = None
    par_level: float | None = None
    vendor: str | None = None


class InventoryItemRead(InventoryItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    normalized_name: str
    created_at: datetime
    updated_at: datetime


class CountSessionCreate(BaseModel):
    restaurant_id: int
    area: str | None = None
    notes: str | None = None


class CountSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    restaurant_id: int
    area: str | None
    status: str
    started_at: datetime
    completed_at: datetime | None
    approved_at: datetime | None
    notes: str | None


class CountSessionSummary(CountSessionRead):
    summary: dict[str, int]


class CountEntryCreate(BaseModel):
    item_name: str
    quantity: float
    unit: str
    area: str | None = None
    source: str = "manual"
    raw_input: str | None = None


class CountEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    count_session_id: int
    inventory_item_id: int | None
    item_name: str
    normalized_item_name: str
    quantity: float
    unit: str
    area: str | None
    source: str
    raw_input: str | None
    partial_detail: str | None
    needs_review: bool
    review_reason: str | None
    created_at: datetime


class ParseVoiceRequest(BaseModel):
    restaurant_id: int
    count_session_id: int
    text: str
    area: str | None = None
    save: bool = False


class ParseUploadRequest(ParseVoiceRequest):
    pass


class ParsedEntry(BaseModel):
    raw_phrase: str
    item_name: str
    normalized_item_name: str
    quantity: float
    unit: str
    area: str | None = None
    source: str
    raw_input: str
    partial_detail: str | None = None
    inventory_item_id: int | None = None
    matched_name: str | None = None
    match_type: str
    needs_review: bool
    review_reason: str | None = None
    count_entry_id: int | None = None


class ParseResponse(BaseModel):
    entries: list[ParsedEntry]
    saved: bool


class NormalizeItemRequest(BaseModel):
    restaurant_id: int
    item_name: str


class MatchResponse(BaseModel):
    matched_item_id: int | None
    matched_name: str | None
    normalized_name: str
    match_type: str
    needs_review: bool
    review_reason: str | None


class IssueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    restaurant_id: int
    count_session_id: int | None
    inventory_item_id: int | None
    count_entry_id: int | None
    issue_type: str
    title: str
    description: str
    suggested_action: str | None
    status: str
    created_at: datetime
    resolved_at: datetime | None


class IssueResolveRequest(BaseModel):
    status: str = "resolved"
    resolution_note: str | None = None


class ReportEntry(BaseModel):
    name: str
    quantity: float
    unit: str
    area: str | None
    source: str
    review_status: str
    raw_input: str | None = None
    partial_detail: str | None = None


class ReportResponse(BaseModel):
    count_id: int
    status: str
    entries: list[ReportEntry]
    summary: dict[str, int]
