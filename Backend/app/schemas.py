from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RestaurantCreate(BaseModel):
    name: str
    location: str | None = None
    owner_user_id: str | None = None


class RestaurantRead(RestaurantCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class InventoryItemBase(BaseModel):
    restaurant_id: int | None = None
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
    restaurant_id: int
    normalized_name: str
    created_at: datetime
    updated_at: datetime


class CountSessionCreate(BaseModel):
    restaurant_id: int | None = None
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

    count_id: int
    restaurant_id: int
    area: str | None
    item_name_raw: str | None
    item_name_clean: str
    quantity: float | None
    unit: str
    status: str
    original_phrase: str | None
    created_at: datetime
    counted_by: str | None


class ParseVoiceRequest(BaseModel):
    restaurant_id: int | None = None
    count_session_id: int | None = None
    text: str
    area: str | None = None
    save: bool = False


class ParseUploadRequest(ParseVoiceRequest):
    pass


class ParsedEntry(BaseModel):
    count_id: int
    restaurant_id: int
    quantity: float | None
    unit: str | None
    area: str | None = None
    item_name_raw: str
    item_name_clean: str
    category: str | None = None
    status: str
    original_phrase: str
    created_at: datetime | None = None
    counted_by: str | None = None
    par_status: Literal["sufficient", "low", "critical", "unknown"] = "unknown"
    estimated_par_quantity: float | None = None
    par_unit: str | None = None
    par_reason: str = ""
    par_confidence: Literal["high", "medium", "low"] = "low"
    is_demo_estimate: bool = True


class ParseResponse(BaseModel):
    count_session_id: int | None = None
    entries: list[ParsedEntry]
    saved: bool
    parser_source: Literal["claude", "deterministic_fallback"] = "deterministic_fallback"
    external_ai_enabled: bool = False
    text_ai_provider: str = ""
    anthropic_model: str = ""
    anthropic_key_present: bool = False


class NormalizeItemRequest(BaseModel):
    restaurant_id: int | None = None
    item_name: str


class AuthRestaurant(BaseModel):
    id: int
    name: str


class AuthMeResponse(BaseModel):
    user_id: str
    email: str | None
    restaurant: AuthRestaurant


class DevLinkRestaurantRequest(BaseModel):
    email: str | None = None
    restaurant_name: str


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
    count_id: int
    restaurant_id: int
    area: str | None
    item_name_raw: str | None
    item_name_clean: str
    category: str | None = None
    quantity: float | None
    unit: str
    status: str
    original_phrase: str | None = None
    created_at: datetime
    counted_by: str | None = None
    par_status: Literal["sufficient", "low", "critical", "unknown"] = "unknown"
    estimated_par_quantity: float | None = None
    par_unit: str | None = None
    par_reason: str = ""
    par_confidence: Literal["high", "medium", "low"] = "low"
    is_demo_estimate: bool = True


class ReportResponse(BaseModel):
    count_id: int
    status: str
    entries: list[ReportEntry]
    summary: dict[str, int]
