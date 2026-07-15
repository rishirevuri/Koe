from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Restaurant(Base):
    __tablename__ = "restaurants"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    inventory_items: Mapped[list["InventoryItem"]] = relationship(back_populates="restaurant")
    count_sessions: Mapped[list["CountSession"]] = relationship(back_populates="restaurant")
    issues: Mapped[list["Issue"]] = relationship(back_populates="restaurant")


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    default_unit: Mapped[str] = mapped_column(String(80), nullable=False)
    aliases: Mapped[str] = mapped_column(Text, default="[]")
    pack_size: Mapped[str | None] = mapped_column(String(120), nullable=True)
    par_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    vendor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    restaurant: Mapped[Restaurant] = relationship(back_populates="inventory_items")
    count_entries: Mapped[list["CountEntry"]] = relationship(back_populates="inventory_item")
    issues: Mapped[list["Issue"]] = relationship(back_populates="inventory_item")


class CountSession(Base):
    __tablename__ = "count_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    area: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="draft")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    exported: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    restaurant: Mapped[Restaurant] = relationship(back_populates="count_sessions")
    entries: Mapped[list["CountEntry"]] = relationship(back_populates="count_session", cascade="all, delete-orphan")
    issues: Mapped[list["Issue"]] = relationship(back_populates="count_session")


class CountEntry(Base):
    __tablename__ = "count_entries"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    count_session_id: Mapped[int] = mapped_column(ForeignKey("count_sessions.id"), index=True)
    inventory_item_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_items.id"), nullable=True, index=True)
    item_name_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_item_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(80), default="Clean", nullable=False)
    area: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="manual")
    raw_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_phrase: Mapped[str | None] = mapped_column(Text, nullable=True)
    partial_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    counted_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    count_session: Mapped[CountSession] = relationship(back_populates="entries")
    inventory_item: Mapped[InventoryItem | None] = relationship(back_populates="count_entries")
    issues: Mapped[list["Issue"]] = relationship(back_populates="count_entry")

    @property
    def count_id(self) -> int:
        return self.count_session_id

    @property
    def restaurant_id(self) -> int | None:
        return self.count_session.restaurant_id if self.count_session else None

    @property
    def item_name_clean(self) -> str:
        return self.item_name or (self.inventory_item.name if self.inventory_item else "")


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    count_session_id: Mapped[int | None] = mapped_column(ForeignKey("count_sessions.id"), nullable=True, index=True)
    inventory_item_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_items.id"), nullable=True, index=True)
    count_entry_id: Mapped[int | None] = mapped_column(ForeignKey("count_entries.id"), nullable=True, index=True)
    issue_type: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    restaurant: Mapped[Restaurant] = relationship(back_populates="issues")
    count_session: Mapped[CountSession | None] = relationship(back_populates="issues")
    inventory_item: Mapped[InventoryItem | None] = relationship(back_populates="issues")
    count_entry: Mapped[CountEntry | None] = relationship(back_populates="issues")
