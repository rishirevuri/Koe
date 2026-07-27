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
    needed_quantity: str = "TBD"
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
    quantity: float | str | None
    quantity_label: str | None = None
    unit: str
    needed_quantity: str = "TBD"
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
    quantity: float | str | None
    quantity_label: str | None = None
    unit: str | None
    needed_quantity: str = "TBD"
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
    fallback_reason: str = ""
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
    quantity: float | str | None
    quantity_label: str | None = None
    unit: str
    needed_quantity: str = "TBD"
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


class PurchaseItem(BaseModel):
    item_name: str
    quantity_to_purchase: str


class ReportResponse(BaseModel):
    count_id: int
    status: str
    entries: list[ReportEntry]
    purchase_items: list[PurchaseItem] = Field(default_factory=list)
    summary: dict[str, int]


class RestockPlanSummary(BaseModel):
    items_forecasted: int
    suggested_purchases: int
    needs_review: int
    safety_buffer_percent: int
    history_counts_used: int = 0
    forecast_mode: Literal["claude_adaptive", "claude_recipe_only", "deterministic_adaptive", "deterministic_recipe_only"] = "deterministic_recipe_only"
    planner_source: Literal["claude", "deterministic_fallback"] = "deterministic_fallback"
    fallback_reason: str | None = None
    overall_note: str | None = None


class RestockPlanRow(BaseModel):
    ingredient: str
    projected_need: float | None = None
    adjusted_need: float | None = None
    current_stock: float | str | None = None
    current_stock_unit: str | None = None
    suggested_purchase: float | None = None
    unit: str | None = None
    usage_multiplier: float | None = None
    action: Literal["buy", "hold", "review"] = "review"
    status: Literal["Ready", "Limited History", "Needs Review", "Unit Mismatch", "Stock Unknown"]
    confidence: Literal["High", "Medium", "Low"] = "Low"
    usage_signal: Literal["low", "medium", "high", "unknown"] = "unknown"
    history_signal: Literal[
        "stable",
        "depletes_faster_than_expected",
        "depletes_slower_than_expected",
        "inconsistent",
        "limited_history",
        "unknown",
    ] = "unknown"
    risk_signal: Literal["stockout_risk", "waste_risk", "balanced", "needs_review"] = "needs_review"
    reason: str


class RestockLearningNote(BaseModel):
    ingredient: str
    note: str


class RestockReviewWarning(BaseModel):
    ingredient: str
    warning: str


class RestockSalesPreviewRow(BaseModel):
    item_name: str
    quantity_sold: float
    date: str | None = None
    confidence: Literal["High", "Medium", "Low"] = "Medium"
    source_hint: str | None = None


class RestockSalesWarning(BaseModel):
    message: str


class RestockSalesNormalization(BaseModel):
    source: Literal["direct", "claude"] = "direct"
    rows_read: int = 0
    sales_rows_extracted: int = 0
    columns_detected: dict[str, str | None] = Field(default_factory=dict)
    warnings: list[RestockSalesWarning] = Field(default_factory=list)
    preview_rows: list[RestockSalesPreviewRow] = Field(default_factory=list)


class RestockPlanResponse(BaseModel):
    summary: RestockPlanSummary
    purchase_plan: list[RestockPlanRow]
    learning_notes: list[RestockLearningNote] = Field(default_factory=list)
    review_warnings: list[RestockReviewWarning] = Field(default_factory=list)
    sales_normalization: RestockSalesNormalization | None = None
