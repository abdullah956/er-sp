from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.database import SessionLocal, engine, get_db
from app.dependencies import AdminUser, CurrentUser, DbSession, LoggedInUser
from app.models import (
    AssistanceRequest,
    AssistanceStatus,
    Base,
    Favorite,
    Notification,
    ParkingLocation,
    ParkingReport,
    ParkingSpot,
    ReportStatus,
    Role,
    SpotStatus,
    SystemSetting,
    User,
)
from app.security import hash_password, verify_password
from app.services import (
    apply_approved_report,
    auto_approve_reports,
    fetch_locations,
    location_as_dict,
    prediction_for_location,
    reject_report,
    reward_badge,
    seed_database,
)


BASE_DIR = Path(__file__).resolve().parent
settings = get_settings()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        await seed_database(session)
    yield
    await engine.dispose()


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, https_only=not settings.debug, same_site="lax")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def page_context(request: Request, user: User | None, **context: object) -> dict:
    return {"request": request, "user": user, "app_name": settings.app_name, **context}


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=status.HTTP_303_SEE_OTHER)


def login_redirect() -> RedirectResponse:
    return redirect("/login?error=" + quote("Please log in to continue."))


def admin_redirect() -> RedirectResponse:
    return redirect("/dashboard?error=" + quote("Administrator access is required."))


@app.get("/", include_in_schema=False)
async def home(current_user: CurrentUser):
    return redirect("/dashboard" if current_user else "/login")


@app.get("/register", include_in_schema=False)
async def register_page(request: Request, current_user: CurrentUser):
    if current_user:
        return redirect("/dashboard")
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context=page_context(request, None, error=request.query_params.get("error")),
    )


@app.post("/register", include_in_schema=False)
async def register(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    clean_name = full_name.strip()
    clean_email = email.strip().lower()
    if len(clean_name) < 2:
        return redirect("/register?error=" + quote("Please enter your full name."))
    if len(password) < 8:
        return redirect("/register?error=" + quote("Password must contain at least 8 characters."))
    if await db.scalar(select(User).where(User.email == clean_email)):
        return redirect("/register?error=" + quote("An account already exists for that email address."))
    user = User(full_name=clean_name, email=clean_email, password_hash=hash_password(password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    request.session.clear()
    request.session["user_id"] = user.id
    return redirect("/dashboard?message=" + quote("Your account has been created."))


@app.get("/login", include_in_schema=False)
async def login_page(request: Request, current_user: CurrentUser):
    if current_user:
        return redirect("/dashboard")
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context=page_context(request, None, error=request.query_params.get("error"), message=request.query_params.get("message")),
    )


@app.post("/login", include_in_schema=False)
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    user = await db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return redirect("/login?error=" + quote("Invalid email or password."))
    request.session.clear()
    request.session["user_id"] = user.id
    return redirect("/dashboard")


@app.post("/logout", include_in_schema=False)
async def logout(request: Request):
    request.session.clear()
    return redirect("/login?message=" + quote("You have been logged out."))


@app.get("/dashboard", include_in_schema=False)
async def dashboard(request: Request, db: DbSession, current_user: CurrentUser):
    if current_user is None:
        return login_redirect()
    locations = await fetch_locations(db)
    favorite_ids = set(
        (await db.scalars(select(Favorite.location_id).where(Favorite.user_id == current_user.id))).all()
    )
    favorite_locations = [location for location in locations if location.id in favorite_ids]
    higher_ranked_users = await db.scalar(
        select(func.count(User.id)).where(
            User.role == Role.USER,
            User.is_active.is_(True),
            User.reward_points > current_user.reward_points,
        )
    )
    leaderboard = await db.scalars(
        select(User)
        .where(User.role == Role.USER, User.is_active.is_(True))
        .order_by(User.reward_points.desc(), User.full_name)
        .limit(5)
    )
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context=page_context(
            request,
            current_user,
            locations=[location_as_dict(location, favorite_ids) for location in locations],
            favorite_locations=[location_as_dict(location, favorite_ids) for location in favorite_locations],
            reward_badge=reward_badge(current_user.reward_points),
            community_rank=(higher_ranked_users or 0) + 1,
            leaderboard=list(leaderboard),
            error=request.query_params.get("error"),
            message=request.query_params.get("message"),
        ),
    )


@app.get("/notifications", include_in_schema=False)
async def notifications_page(request: Request, db: DbSession, current_user: CurrentUser):
    if current_user is None:
        return login_redirect()
    notifications = await db.scalars(
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
    )
    return templates.TemplateResponse(
        request=request,
        name="notifications.html",
        context=page_context(
            request,
            current_user,
            notifications=list(notifications),
            message=request.query_params.get("message"),
        ),
    )


@app.post("/notifications/read", include_in_schema=False)
async def mark_notifications_read(current_user: LoggedInUser, db: DbSession):
    notifications = await db.scalars(
        select(Notification).where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
    )
    for notification in notifications:
        notification.is_read = True
    await db.commit()
    return redirect("/notifications?message=" + quote("All alerts have been marked as read."))


@app.get("/map", include_in_schema=False)
async def parking_map(request: Request, db: DbSession, current_user: CurrentUser):
    if current_user is None:
        return login_redirect()
    locations = await fetch_locations(db)
    return templates.TemplateResponse(
        request=request,
        name="map.html",
        context=page_context(request, current_user, locations=locations),
    )


@app.get("/analytics", include_in_schema=False)
async def analytics_page(request: Request, db: DbSession, current_user: CurrentUser):
    if current_user is None:
        return login_redirect()
    return templates.TemplateResponse(
        request=request,
        name="analytics.html",
        context=page_context(request, current_user, locations=await fetch_locations(db), current_hour=datetime.now().hour),
    )


@app.get("/profile", include_in_schema=False)
async def profile_page(request: Request, db: DbSession, current_user: CurrentUser):
    if current_user is None:
        return login_redirect()
    requests = await db.scalars(
        select(AssistanceRequest)
        .options(selectinload(AssistanceRequest.location))
        .where(AssistanceRequest.user_id == current_user.id)
        .order_by(AssistanceRequest.created_at.desc())
    )
    return templates.TemplateResponse(
        request=request,
        name="profile.html",
        context=page_context(
            request,
            current_user,
            locations=await fetch_locations(db),
            assistance_requests=list(requests),
            error=request.query_params.get("error"),
            message=request.query_params.get("message"),
        ),
    )


@app.post("/profile", include_in_schema=False)
async def update_profile(
    current_user: LoggedInUser,
    full_name: str = Form(...),
    assistance_needs: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    name = full_name.strip()
    if len(name) < 2:
        return redirect("/profile?error=" + quote("Please enter your full name."))
    current_user.full_name = name
    current_user.assistance_needs = assistance_needs.strip() or None
    await db.commit()
    return redirect("/profile?message=" + quote("Profile saved."))


@app.post("/assistance-requests", include_in_schema=False)
async def create_assistance_request(
    current_user: LoggedInUser,
    location_id: int | None = Form(None),
    details: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    clean_details = details.strip()
    if not clean_details:
        return redirect("/profile?error=" + quote("Describe the assistance you need."))
    if location_id and await db.get(ParkingLocation, location_id) is None:
        return redirect("/profile?error=" + quote("Please choose a valid parking location."))
    db.add(AssistanceRequest(user_id=current_user.id, location_id=location_id, details=clean_details))
    await db.commit()
    return redirect("/profile?message=" + quote("Your assistance request has been sent."))


@app.get("/api/parking-locations")
async def parking_locations_api(
    db: DbSession,
    current_user: CurrentUser,
    query: str = "",
    accessible_only: bool = False,
):
    locations = await fetch_locations(db)
    search = query.strip().lower()
    if search:
        locations = [
            location
            for location in locations
            if search in f"{location.name} {location.city} {location.address}".lower()
        ]
    if accessible_only:
        locations = [location for location in locations if location.is_accessible]
    favorite_ids: set[int] = set()
    if current_user:
        favorite_ids = set(
            (await db.scalars(select(Favorite.location_id).where(Favorite.user_id == current_user.id))).all()
        )
    return {"locations": [location_as_dict(location, favorite_ids) for location in locations]}


@app.post("/api/favorites/{location_id}")
async def add_favorite(location_id: int, current_user: LoggedInUser, db: AsyncSession = Depends(get_db)):
    if await db.get(ParkingLocation, location_id) is None:
        raise HTTPException(status_code=404, detail="Parking location not found.")
    favorite = await db.scalar(
        select(Favorite).where(Favorite.user_id == current_user.id, Favorite.location_id == location_id)
    )
    if favorite is None:
        db.add(Favorite(user_id=current_user.id, location_id=location_id))
        await db.commit()
    return {"is_favorite": True}


@app.delete("/api/favorites/{location_id}")
async def remove_favorite(location_id: int, current_user: LoggedInUser, db: AsyncSession = Depends(get_db)):
    favorite = await db.scalar(
        select(Favorite).where(Favorite.user_id == current_user.id, Favorite.location_id == location_id)
    )
    if favorite is not None:
        await db.delete(favorite)
        await db.commit()
    return {"is_favorite": False}


@app.post("/api/reports")
async def submit_parking_report(
    current_user: LoggedInUser,
    db: DbSession,
    location_id: int = Form(...),
    reported_status: SpotStatus = Form(...),
    note: str = Form(""),
):
    location = await db.get(ParkingLocation, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Parking location not found.")
    report = ParkingReport(
        reporter_id=current_user.id,
        location_id=location.id,
        reported_status=reported_status,
        note=note.strip()[:300] or None,
    )
    db.add(report)
    await db.flush()
    if await auto_approve_reports(db):
        await apply_approved_report(db, report)
        report.reviewed_by_id = current_user.id
        message = f"Report confirmed. {settings.report_reward_points} reward points were added to your profile."
    else:
        message = "Report submitted for administrator validation. Reward points are added when it is approved."
    await db.commit()
    return JSONResponse({"report_id": report.id, "message": message, "report_status": report.validation_status.value})


@app.get("/api/analytics/prediction")
async def prediction_api(location_id: int, hour: int, current_user: LoggedInUser, db: AsyncSession = Depends(get_db)):
    if not 0 <= hour <= 23:
        raise HTTPException(status_code=422, detail="Hour must be between 0 and 23.")
    location = await db.scalar(
        select(ParkingLocation).options(selectinload(ParkingLocation.spots)).where(ParkingLocation.id == location_id)
    )
    if location is None:
        raise HTTPException(status_code=404, detail="Parking location not found.")
    return await prediction_for_location(db, location, hour)


@app.get("/admin", include_in_schema=False)
async def admin_page(request: Request, db: DbSession, current_user: CurrentUser):
    if current_user is None:
        return login_redirect()
    if current_user.role != Role.ADMIN:
        return admin_redirect()
    reports = await db.scalars(
        select(ParkingReport)
        .options(selectinload(ParkingReport.reporter), selectinload(ParkingReport.location))
        .order_by(ParkingReport.created_at.desc())
        .limit(50)
    )
    assistance = await db.scalars(
        select(AssistanceRequest)
        .options(selectinload(AssistanceRequest.user), selectinload(AssistanceRequest.location))
        .order_by(AssistanceRequest.created_at.desc())
    )
    users = await db.scalars(select(User).order_by(User.role.desc(), User.full_name))
    locations = await fetch_locations(db)
    total_reports = await db.scalar(select(func.count(ParkingReport.id))) or 0
    approved_reports = await db.scalar(
        select(func.count(ParkingReport.id)).where(ParkingReport.validation_status == ReportStatus.APPROVED)
    ) or 0
    active_users = await db.scalar(select(func.count(User.id)).where(User.is_active.is_(True))) or 0
    total_spaces = sum(len(location.spots) for location in locations)
    available_spaces = sum(
        sum(spot.status == SpotStatus.AVAILABLE for spot in location.spots) for location in locations
    )
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context=page_context(
            request,
            current_user,
            locations=locations,
            reports=list(reports),
            users=list(users),
            assistance_requests=list(assistance),
            auto_approve=await auto_approve_reports(db),
            analytics={
                "active_users": active_users,
                "total_reports": total_reports,
                "approved_reports": approved_reports,
                "available_spaces": available_spaces,
                "total_spaces": total_spaces,
            },
            message=request.query_params.get("message"),
            error=request.query_params.get("error"),
        ),
    )


@app.post("/admin/reports/{report_id}", include_in_schema=False)
async def review_report(report_id: int, admin: AdminUser, db: DbSession, action: str = Form(...)):
    report = await db.get(ParkingReport, report_id)
    if report is None:
        return redirect("/admin?error=" + quote("Report not found."))
    report.reviewed_by_id = admin.id
    if action == "approve":
        await apply_approved_report(db, report)
        message = "Report approved and parking availability updated."
    elif action == "reject":
        await reject_report(db, report)
        message = "Report rejected."
    else:
        return redirect("/admin?error=" + quote("Unknown report action."))
    await db.commit()
    return redirect("/admin?message=" + quote(message))


@app.post("/admin/users/{user_id}/toggle", include_in_schema=False)
async def toggle_user(user_id: int, admin: AdminUser, db: DbSession):
    user = await db.get(User, user_id)
    if user is None:
        return redirect("/admin?error=" + quote("User not found."))
    if user.id == admin.id:
        return redirect("/admin?error=" + quote("You cannot deactivate your own administrator account."))
    user.is_active = not user.is_active
    await db.commit()
    return redirect("/admin?message=" + quote("User status updated."))


@app.post("/admin/locations", include_in_schema=False)
async def add_location(
    admin: AdminUser,
    db: DbSession,
    name: str = Form(...),
    city: str = Form(...),
    address: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    description: str = Form(""),
    is_accessible: bool = Form(False),
):
    existing = await db.scalar(select(ParkingLocation).where(ParkingLocation.name == name.strip()))
    if existing:
        return redirect("/admin?error=" + quote("A parking location with that name already exists."))
    db.add(
        ParkingLocation(
            name=name.strip(), city=city.strip(), address=address.strip(), latitude=latitude, longitude=longitude,
            description=description.strip() or None, is_accessible=is_accessible,
        )
    )
    await db.commit()
    return redirect("/admin?message=" + quote("Parking location added."))


@app.post("/admin/locations/{location_id}", include_in_schema=False)
async def update_location(
    location_id: int,
    admin: AdminUser,
    db: DbSession,
    name: str = Form(...),
    city: str = Form(...),
    address: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    description: str = Form(""),
    is_accessible: bool = Form(False),
):
    location = await db.get(ParkingLocation, location_id)
    if location is None:
        return redirect("/admin?error=" + quote("Parking location not found."))
    duplicate = await db.scalar(select(ParkingLocation).where(ParkingLocation.name == name.strip(), ParkingLocation.id != location_id))
    if duplicate:
        return redirect("/admin?error=" + quote("A parking location with that name already exists."))
    location.name, location.city, location.address = name.strip(), city.strip(), address.strip()
    location.latitude, location.longitude = latitude, longitude
    location.description, location.is_accessible = description.strip() or None, is_accessible
    await db.commit()
    return redirect("/admin?message=" + quote("Parking location updated."))


@app.post("/admin/locations/{location_id}/delete", include_in_schema=False)
async def delete_location(location_id: int, admin: AdminUser, db: DbSession):
    location = await db.get(ParkingLocation, location_id)
    if location is None:
        return redirect("/admin?error=" + quote("Parking location not found."))
    await db.delete(location)
    await db.commit()
    return redirect("/admin?message=" + quote("Parking location removed."))


@app.post("/admin/locations/{location_id}/spots", include_in_schema=False)
async def add_spot(
    location_id: int,
    admin: AdminUser,
    db: DbSession,
    label: str = Form(...),
    spot_status: SpotStatus = Form(SpotStatus.AVAILABLE),
    is_accessible: bool = Form(False),
):
    if await db.get(ParkingLocation, location_id) is None:
        return redirect("/admin?error=" + quote("Parking location not found."))
    if await db.scalar(select(ParkingSpot).where(ParkingSpot.location_id == location_id, ParkingSpot.label == label.strip())):
        return redirect("/admin?error=" + quote("That spot label already exists at this location."))
    db.add(ParkingSpot(location_id=location_id, label=label.strip(), status=spot_status, is_accessible=is_accessible))
    await db.commit()
    return redirect("/admin?message=" + quote("Parking spot added."))


@app.post("/admin/spots/{spot_id}", include_in_schema=False)
async def update_spot(
    spot_id: int,
    admin: AdminUser,
    db: DbSession,
    spot_status: SpotStatus = Form(...),
    is_accessible: bool = Form(False),
):
    spot = await db.get(ParkingSpot, spot_id)
    if spot is None:
        return redirect("/admin?error=" + quote("Parking spot not found."))
    spot.status, spot.is_accessible = spot_status, is_accessible
    await db.commit()
    return redirect("/admin?message=" + quote("Parking spot updated."))


@app.post("/admin/spots/{spot_id}/delete", include_in_schema=False)
async def delete_spot(spot_id: int, admin: AdminUser, db: DbSession):
    spot = await db.get(ParkingSpot, spot_id)
    if spot is None:
        return redirect("/admin?error=" + quote("Parking spot not found."))
    await db.delete(spot)
    await db.commit()
    return redirect("/admin?message=" + quote("Parking spot removed."))


@app.post("/admin/settings", include_in_schema=False)
async def update_settings(
    admin: AdminUser, db: DbSession, auto_approve: bool = Form(False)
):
    setting = await db.get(SystemSetting, "auto_approve_reports")
    if setting is None:
        setting = SystemSetting(key="auto_approve_reports", value=str(auto_approve).lower())
        db.add(setting)
    else:
        setting.value = str(auto_approve).lower()
    await db.commit()
    return redirect("/admin?message=" + quote("Report validation setting saved."))


@app.post("/admin/assistance/{request_id}/resolve", include_in_schema=False)
async def resolve_assistance(request_id: int, admin: AdminUser, db: DbSession):
    assistance = await db.get(AssistanceRequest, request_id)
    if assistance is None:
        return redirect("/admin?error=" + quote("Assistance request not found."))
    assistance.status = AssistanceStatus.RESOLVED
    db.add(
        Notification(
            user_id=assistance.user_id,
            title="Assistance request resolved",
            message="Your special-assistance request has been marked as resolved by the Smart Park administrator.",
        )
    )
    await db.commit()
    return redirect("/admin?message=" + quote("Assistance request marked as resolved."))
