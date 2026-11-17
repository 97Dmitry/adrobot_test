from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255))
    tracking_url: Mapped[str] = mapped_column(default="")
    state: Mapped[str] = mapped_column(default="active")
    synced_at: Mapped[datetime | None] = mapped_column()
    streams: Mapped[list["Stream"]] = relationship(
        back_populates="campaign", order_by="Stream.position"
    )


class Stream(Base):
    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    name: Mapped[str] = mapped_column()
    position: Mapped[int] = mapped_column(default=0)
    schema_name: Mapped[str] = mapped_column(default="")
    baseline: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    pending: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    revision: Mapped[int] = mapped_column(default=1)
    __mapper_args__ = {"version_id_col": revision, "version_id_generator": False}
    dirty: Mapped[bool] = mapped_column(default=False)
    missing: Mapped[bool] = mapped_column(default=False)
    notice: Mapped[str] = mapped_column(default="")
    campaign: Mapped[Campaign] = relationship(back_populates="streams")
    offers: Mapped[list["StreamOffer"]] = relationship(
        back_populates="stream", order_by="StreamOffer.position", cascade="all, delete-orphan"
    )


class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column()


class StreamOffer(Base):
    __tablename__ = "stream_offers"
    __table_args__ = (
        UniqueConstraint("stream_id", "offer_id", name="uq_stream_offer"),
        CheckConstraint("share >= 0 AND share <= 100", name="ck_draft_share"),
        CheckConstraint(
            "published_share >= 0 AND published_share <= 100", name="ck_published_share"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"), index=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"))
    position: Mapped[int] = mapped_column()
    active: Mapped[bool] = mapped_column(default=True)
    share: Mapped[int] = mapped_column(default=0)
    pin: Mapped[int | None] = mapped_column()
    published_active: Mapped[bool] = mapped_column(default=False)
    published_share: Mapped[int] = mapped_column(default=0)
    published_pin: Mapped[int | None] = mapped_column()
    ever_published: Mapped[bool] = mapped_column(default=False)
    stream: Mapped[Stream] = relationship(back_populates="offers")
    offer: Mapped[Offer] = relationship()


class CreationOperation(Base):
    __tablename__ = "creation_operations"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    fingerprint: Mapped[str] = mapped_column()
    request: Mapped[dict[str, Any]] = mapped_column(JSON)
    alias: Mapped[str] = mapped_column(String(100), unique=True)
    campaign_id: Mapped[int | None] = mapped_column()
    phase: Mapped[str] = mapped_column(default="starting")
    error: Mapped[str] = mapped_column(default="")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
