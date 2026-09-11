from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models import (
    Favorite,
    ParkingLocation,
    ParkingReport,
    ParkingSpot,
    Notification,
    ReportStatus,
    Role,
    SpotStatus,
    SystemSetting,
    User,
    utcnow,
)
from app.security import hash_password


def location_counts(location: ParkingLocation) -> dict[str, int]:
    counts = {status.value: 0 for status in SpotStatus}
    for spot in location.spots:
        counts[spot.status.value] += 1
    return counts


def availability_color(available: int, total: int) -> str:
    if total == 0 or available == 0:
        return "red"
    if available / total < 0.4:
        return "orange"
    return "green"


def reward_badge(points: int) -> str:
    if points >= 50:
        return "Parking Champion"
    if points >= 20:
        return "Community Contributor"
    if points >= 10:
        return "Parking Helper"
    return "New Contributor"


def location_as_dict(location: ParkingLocation, favorite_ids: set[int] | None = None) -> dict:
    counts = location_counts(location)
    total = len(location.spots)
    available = counts[SpotStatus.AVAILABLE.value]
    return {
        "id": location.id,
        "name": location.name,
        "city": location.city,
        "address": location.address,
        "description": location.description or "",
        "latitude": location.latitude,
        "longitude": location.longitude,
        "is_accessible": location.is_accessible,
        "total_spots": total,
        "available_spots": available,
        "occupied_spots": counts[SpotStatus.OCCUPIED.value],
        "issue_spots": counts[SpotStatus.ISSUE.value],
        "availability_percent": round((available / total) * 100) if total else 0,
        "color": availability_color(available, total),
        "is_favorite": location.id in (favorite_ids or set()),
    }


async def fetch_locations(db: AsyncSession) -> list[ParkingLocation]:
    result = await db.execute(
        select(ParkingLocation).options(selectinload(ParkingLocation.spots)).order_by(ParkingLocation.city, ParkingLocation.name)
    )
    return list(result.scalars().unique())


async def auto_approve_reports(db: AsyncSession) -> bool:
    setting = await db.get(SystemSetting, "auto_approve_reports")
    return setting is not None and setting.value.lower() == "true"


async def apply_approved_report(db: AsyncSession, report: ParkingReport) -> None:
    """Apply a confirmed community report to one matching spot and grant points once."""
    if report.validation_status != ReportStatus.PENDING:
        return

    if report.spot_id:
        spot = await db.get(ParkingSpot, report.spot_id)
    else:
        spot = None
    if spot is None:
        result = await db.execute(
            select(ParkingSpot)
            .where(ParkingSpot.location_id == report.location_id, ParkingSpot.status != report.reported_status)
            .order_by(ParkingSpot.id)
            .limit(1)
        )
        spot = result.scalar_one_or_none()
        if spot is None:
            result = await db.execute(
                select(ParkingSpot).where(ParkingSpot.location_id == report.location_id).order_by(ParkingSpot.id).limit(1)
            )
            spot = result.scalar_one_or_none()
    if spot is not None:
        spot.status = report.reported_status
        report.spot_id = spot.id

    report.validation_status = ReportStatus.APPROVED
    report.reviewed_at = utcnow()
    reporter = await db.get(User, report.reporter_id)
    if reporter is not None:
        reporter.reward_points += get_settings().report_reward_points
        db.add(
            Notification(
                user_id=reporter.id,
                title="Parking report approved",
                message=(
                    f"Your update for the selected parking location was confirmed. "
                    f"You earned {get_settings().report_reward_points} reward points."
                ),
            )
        )


async def reject_report(db: AsyncSession, report: ParkingReport) -> None:
    if report.validation_status == ReportStatus.PENDING:
        report.validation_status = ReportStatus.REJECTED
        report.reviewed_at = utcnow()
        db.add(
            Notification(
                user_id=report.reporter_id,
                title="Parking report reviewed",
                message="Your parking update was not approved, so the live availability was not changed.",
            )
        )


async def prediction_for_location(db: AsyncSession, location: ParkingLocation, hour: int) -> dict:
    """A transparent time/history estimate, deliberately not presented as machine learning."""
    since = utcnow() - timedelta(days=21)
    result = await db.execute(
        select(ParkingReport).where(
            ParkingReport.location_id == location.id,
            ParkingReport.validation_status == ReportStatus.APPROVED,
            ParkingReport.created_at >= since,
        )
    )
    historical = [report for report in result.scalars() if abs(report.created_at.hour - hour) <= 1]
    current = location_as_dict(location)
    current_ratio = current["availability_percent"] / 100
    if historical:
        historical_ratio = sum(report.reported_status == SpotStatus.AVAILABLE for report in historical) / len(historical)
        chance = round((historical_ratio * 0.7 + current_ratio * 0.3) * 100)
        basis = f"{len(historical)} approved community updates from similar times in the last 21 days"
    else:
        chance = round(current_ratio * 100)
        basis = "current confirmed parking availability; more approved reports will improve the time-based estimate"

    if chance >= 70:
        band = "High"
    elif chance >= 40:
        band = "Medium"
    else:
        band = "Low"
    return {"location_id": location.id, "hour": hour, "chance": chance, "band": band, "basis": basis}


async def seed_database(db: AsyncSession) -> None:
    """Create only local demonstration data so the university project is usable on first run."""
    settings = get_settings()
    admin = await db.scalar(select(User).where(User.email == settings.initial_admin_email.lower()))
    if admin is None:
        admin = User(
            full_name="Smart Park Administrator",
            email=settings.initial_admin_email.lower(),
            password_hash=hash_password(settings.initial_admin_password),
            role=Role.ADMIN,
        )
        db.add(admin)
        await db.flush()

    if await db.get(SystemSetting, "auto_approve_reports") is None:
        db.add(SystemSetting(key="auto_approve_reports", value="false"))

    existing_locations = await db.scalar(select(func.count(ParkingLocation.id)))
    if existing_locations:
        await db.commit()
        return

    locations = [
        ParkingLocation(
            name="Salmiya Waterfront Parking",
            city="Salmiya",
            address="Salem Al Mubarak Street, Salmiya",
            latitude=29.3334,
            longitude=48.0716,
            description="Community-updated parking near the waterfront shopping area.",
            is_accessible=True,
        ),
        ParkingLocation(
            name="Kuwait City Business District",
            city="Kuwait City",
            address="Al Soor Street, Kuwait City",
            latitude=29.3759,
            longitude=47.9774,
            description="Parking spaces for the central business district.",
            is_accessible=True,
        ),
        ParkingLocation(
            name="Mubarakiya Market Parking",
            city="Mubarakiya",
            address="Mubarakiya Market, Kuwait City",
            latitude=29.3765,
            longitude=47.9705,
            description="Parking near Mubarakiya Market and its surrounding streets.",
            is_accessible=False,
        ),
    ]
    db.add_all(locations)
    await db.flush()

    statuses = [
        [SpotStatus.AVAILABLE, SpotStatus.AVAILABLE, SpotStatus.OCCUPIED, SpotStatus.AVAILABLE, SpotStatus.OCCUPIED, SpotStatus.ISSUE],
        [SpotStatus.OCCUPIED, SpotStatus.AVAILABLE, SpotStatus.OCCUPIED, SpotStatus.OCCUPIED, SpotStatus.AVAILABLE, SpotStatus.OCCUPIED],
        [SpotStatus.AVAILABLE, SpotStatus.OCCUPIED, SpotStatus.ISSUE, SpotStatus.OCCUPIED, SpotStatus.AVAILABLE, SpotStatus.OCCUPIED],
    ]
    for location, location_statuses in zip(locations, statuses, strict=True):
        for index, status in enumerate(location_statuses, start=1):
            db.add(
                ParkingSpot(
                    location_id=location.id,
                    label=f"{location.city[:2].upper()}-{index}",
                    status=status,
                    is_accessible=location.is_accessible and index == 1,
                )
            )

        for day in range(1, 15):
            for sample_hour in (8, 13, 18):
                report_status = SpotStatus.AVAILABLE if (day + sample_hour + location.id) % 3 else SpotStatus.OCCUPIED
                db.add(
                    ParkingReport(
                        reporter_id=admin.id,
                        location_id=location.id,
                        reported_status=report_status,
                        note="Seeded historic availability sample",
                        validation_status=ReportStatus.APPROVED,
                        created_at=utcnow() - timedelta(days=day, hours=utcnow().hour - sample_hour),
                    )
                )
    await db.commit()
