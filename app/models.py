from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Role(str, Enum):
    USER = "user"
    ADMIN = "admin"


class SpotStatus(str, Enum):
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    ISSUE = "issue"


class ReportStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AssistanceStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(SqlEnum(Role, name="user_role"), default=Role.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    reward_points: Mapped[int] = mapped_column(Integer, default=0)
    assistance_needs: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    favorites: Mapped[list[Favorite]] = relationship(back_populates="user", cascade="all, delete-orphan")
    reports: Mapped[list[ParkingReport]] = relationship(back_populates="reporter", foreign_keys="ParkingReport.reporter_id")
    assistance_requests: Mapped[list[AssistanceRequest]] = relationship(back_populates="user", cascade="all, delete-orphan")
    notifications: Mapped[list[Notification]] = relationship(back_populates="user", cascade="all, delete-orphan")


class ParkingLocation(Base):
    __tablename__ = "parking_locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    city: Mapped[str] = mapped_column(String(80), index=True)
    address: Mapped[str] = mapped_column(String(255))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_accessible: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    spots: Mapped[list[ParkingSpot]] = relationship(back_populates="location", cascade="all, delete-orphan")
    reports: Mapped[list[ParkingReport]] = relationship(back_populates="location", cascade="all, delete-orphan")
    favorites: Mapped[list[Favorite]] = relationship(back_populates="location", cascade="all, delete-orphan")
    assistance_requests: Mapped[list[AssistanceRequest]] = relationship(back_populates="location")


class ParkingSpot(Base):
    __tablename__ = "parking_spots"
    __table_args__ = (UniqueConstraint("location_id", "label", name="uq_spot_label_per_location"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("parking_locations.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(40))
    status: Mapped[SpotStatus] = mapped_column(SqlEnum(SpotStatus, name="spot_status"), default=SpotStatus.AVAILABLE)
    is_accessible: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    location: Mapped[ParkingLocation] = relationship(back_populates="spots")
    reports: Mapped[list[ParkingReport]] = relationship(back_populates="spot")


class ParkingReport(Base):
    __tablename__ = "parking_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("parking_locations.id", ondelete="CASCADE"), index=True)
    spot_id: Mapped[int | None] = mapped_column(ForeignKey("parking_spots.id", ondelete="SET NULL"), nullable=True)
    reported_status: Mapped[SpotStatus] = mapped_column(SqlEnum(SpotStatus, name="reported_spot_status"))
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    validation_status: Mapped[ReportStatus] = mapped_column(SqlEnum(ReportStatus, name="report_status"), default=ReportStatus.PENDING)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    reporter: Mapped[User] = relationship(back_populates="reports", foreign_keys=[reporter_id])
    location: Mapped[ParkingLocation] = relationship(back_populates="reports")
    spot: Mapped[ParkingSpot | None] = relationship(back_populates="reports")


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "location_id", name="uq_user_location_favorite"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    location_id: Mapped[int] = mapped_column(ForeignKey("parking_locations.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="favorites")
    location: Mapped[ParkingLocation] = relationship(back_populates="favorites")


class AssistanceRequest(Base):
    __tablename__ = "assistance_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("parking_locations.id", ondelete="SET NULL"), nullable=True)
    details: Mapped[str] = mapped_column(String(400))
    status: Mapped[AssistanceStatus] = mapped_column(SqlEnum(AssistanceStatus, name="assistance_status"), default=AssistanceStatus.OPEN)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="assistance_requests")
    location: Mapped[ParkingLocation | None] = relationship(back_populates="assistance_requests")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(String(300))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    user: Mapped[User] = relationship(back_populates="notifications")


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))
