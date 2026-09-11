# Kuwait Smart Park — Project Documentation

## 1. Document status and authority

This is the single maintained documentation source of truth for the Kuwait Smart Park repository. It describes the intended university-project scope and the behaviour implemented in this codebase.

When there is a conflict, use this order of authority:

1. The running application and source code define the exact current behaviour.
2. This document defines the maintained project scope, setup, architecture, and acceptance criteria.
3. The supplied course documents define the original requirements and project context.
4. The user's explicit technical instruction overrides alternative technologies suggested by the course documents. Therefore, this project uses FastAPI/Python, PostgreSQL, a `.env` template, and Conda.

## 2. Source material and scope interpretation

| Source | Purpose in this project |
| --- | --- |
| `SMART PARK PPT.pptx` | Core login, profile, assistance, responsive UI, and DFD/use-case intent. |
| `Smart Park Web Proposal.pdf` | Parking-map, prediction, community reporting, rewards, accessibility, navigation, and administration requirements. |
| `SMART PARKING SYSTEM REPORT.docx` | Detailed functional/non-functional requirements, map/search/report/directions/admin use cases, and project context. |

The supplied documents describe a web portal for reducing parking-search time in Salmiya, Kuwait City, and Mubarakiya through community-updated parking availability, map guidance, prediction, accessibility support, and administration.

### Delivered requirements traceability

| Requirement from the supplied documents | Delivered implementation |
| --- | --- |
| Secure user registration and login | Session-based authentication; passwords are hashed with Argon2 through `pwdlib`. |
| Profile access and management | Logged-in users can update their name and accessibility/assistance preferences. |
| Special assistance | Users submit a location-linked assistance request; administrators resolve it; the user receives an alert. |
| User data storage | PostgreSQL stores accounts, profiles, parking locations/spaces, reports, favourites, assistance requests, alerts, and settings. |
| Interactive parking map | Leaflet/OpenStreetMap map with server-provided parking locations and availability markers. |
| Colour-coded availability | Green = available, orange = limited, red = unavailable or no available spaces. |
| Search and location discovery | Search by location name, city, or address, plus an accessible-location filter. |
| Live parking information | Map data refreshes every 10 seconds. |
| Community parking updates | Signed-in users report available, occupied, or issue states. |
| Report validation | Reports are pending until an administrator approves/rejects them, unless the administrator enables auto-approval. |
| Reward-based participation | Approved reports award configurable points. Dashboard shows a badge, user rank, and leaderboard. |
| Predictive availability | A transparent estimate combines current confirmed availability with approved same-location updates from similar hours over the last 21 days. |
| GPS/navigation support | The selected map location opens a Google Maps directions URL. |
| Accessibility support | Accessible locations and individual accessible spaces are marked and can be filtered. |
| Admin monitoring and user management | The administrator can view analytics, approve/reject reports, enable/disable users, manage locations/spaces, resolve assistance, and control report auto-approval. |
| Alerts/notifications | Users receive alerts after a report is approved/rejected and after assistance is resolved; alerts can be marked read. |
| Usability and responsiveness | Server-rendered pages use a card-based responsive CSS layout and clear feedback messages. |

### Intentional boundaries

The following are not part of the delivered scope:

- Physical IoT/sensor hardware, gates, cameras, RFID, or automated vehicle detection. The source documents describe sensors as a possible future/infrastructure direction; the delivered application uses community reports and stored parking-space data.
- Parking reservation, payment, vehicle management, licence-plate recognition, and social/OAuth login. These appear in research, illustrative designs, or broader smart-parking examples, not as required functions for this implementation.
- Reward redemption. It is a future feature, not a delivered flow.

The prediction never reserves a parking space and is explicitly an estimate, not a guarantee.

## 3. Technology and architecture

| Layer | Technology / responsibility |
| --- | --- |
| Web application | FastAPI on Python 3.12. |
| Views | Jinja2 server-rendered HTML templates. |
| Browser behaviour | Plain JavaScript for map, filtering, favourites, reporting, and prediction requests. |
| Styling | Responsive custom CSS. |
| Database | PostgreSQL 16 via SQLAlchemy 2 async engine and `asyncpg`. |
| Authentication | Signed server-side session cookie with Argon2 password hashes. |
| Map | Leaflet with OpenStreetMap tiles. |
| Directions | Google Maps directions link for the selected coordinates. |
| Local environment | Conda environment definition and Docker Compose PostgreSQL service. |

### Runtime flow

```text
Browser
  ├─ HTML pages / forms ────────────> FastAPI + Jinja2
  ├─ map/report/favourite/prediction ─> FastAPI JSON endpoints
  ├─ Leaflet tiles ─────────────────> OpenStreetMap
  └─ directions link ───────────────> Google Maps

FastAPI ────────────────────────────> PostgreSQL
```

The application creates its database schema on startup and seeds the initial administrator, system setting, three sample locations, spaces, and historic demonstration reports when the database is empty. This is deliberately simple for a university project; it does not use a migration tool.

## 4. Repository layout

```text
app/
  main.py             FastAPI application, pages, API endpoints, and admin actions
  config.py           `.env` settings model
  database.py         Async SQLAlchemy engine and database-session dependency
  dependencies.py     Current-user and administrator authorization dependencies
  models.py           SQLAlchemy data model and state enums
  security.py         Argon2 password hash/verify helpers
  services.py         Seeding, availability, reporting, rewards, and prediction rules
  templates/          Jinja2 pages
  static/app.js       Browser-side map and prediction behaviour
  static/styles.css   Responsive project styling
docs/
  PROJECT_DOCUMENTATION.md  This source-of-truth document
docker-compose.yml    Local PostgreSQL service
environment.yml       Conda environment definition
requirements.txt      Python package constraints
.env.example          Safe configuration template
```

## 5. Data model

| Entity | Key information and relationships |
| --- | --- |
| `User` | Name, email, password hash, role (`user` or `admin`), active state, points, assistance preferences, favourites, reports, requests, and alerts. |
| `ParkingLocation` | Unique name, city, address, latitude/longitude, description, accessibility flag, and parking spaces. |
| `ParkingSpot` | Location, unique label within that location, status (`available`, `occupied`, or `issue`), accessibility flag, and update time. |
| `ParkingReport` | Reporter, location, optional selected space, reported status/note, review status (`pending`, `approved`, `rejected`), reviewer, and timestamps. |
| `Favorite` | Unique user-to-location saved relationship. |
| `AssistanceRequest` | User, optional location, request details, and status (`open` or `resolved`). |
| `Notification` | User alert title/message, read state, and creation time. |
| `SystemSetting` | Key/value setting; currently stores `auto_approve_reports`. |

Deleting a parking location cascades to its spaces, reports, and favourites. Deleting a selected space leaves its historical report record but sets that report's `spot_id` to `NULL`.

## 6. User-facing behaviour

### Authentication and sessions

- Visitors can register with a name, unique email, and a password of at least eight characters.
- An active account can log in and log out.
- Inactive users cannot log in; any existing session for an inactive user is cleared.
- Sessions are signed using `SMART_PARK_SECRET_KEY`. In production, `SMART_PARK_DEBUG` must be `false` so session cookies require HTTPS.

### Dashboard, map, and favourites

- The dashboard shows availability summaries, the user's reward badge, community rank, leaderboard, and saved locations.
- The map shows each location's available-space count and availability colour.
- Search matches a location's name, city, or address. The accessible-only filter restricts results to accessible locations.
- Selecting a location displays its address, availability, accessibility note, Google Maps directions link, and favourite action.
- Map data refetches every 10 seconds. If OpenStreetMap/Leaflet cannot load, the page still presents the location list and does not claim live map rendering.

### Availability rules

For a location with `total` spaces and `available` available spaces:

| Condition | Map colour |
| --- | --- |
| `total == 0` or `available == 0` | Red |
| `available / total < 0.4` | Orange |
| Otherwise | Green |

### Community reports, rewards, and alerts

1. A signed-in user submits a report as `available`, `occupied`, or `issue`, with an optional note of up to 300 characters.
2. It is pending by default. If auto-approval is enabled, it is approved immediately.
3. When approved, the system chooses a suitable parking space at the reported location and updates its status.
4. The reporter receives `SMART_PARK_REPORT_REWARD_POINTS` points and an approval notification. A rejected report does not change availability and produces a rejection notification.
5. Reward badges are: 0–9 `New Contributor`, 10–19 `Parking Helper`, 20–49 `Community Contributor`, and 50+ `Parking Champion`.

### Prediction

The prediction endpoint accepts a location and hour from 0 to 23. It uses approved reports for that location from the last 21 days that were created within one hour of the requested time.

- With matching historic reports: `70%` historic available-report ratio + `30%` current available-space ratio.
- Without matching historic reports: current available-space ratio only.
- Result bands: High (`>=70%`), Medium (`40–69%`), Low (`<40%`).

This formula is shown in the product as its basis so the feature is transparent rather than presented as unexplained AI.

### Profile and assistance

- The profile stores the user's name and optional assistance needs.
- An assistance request requires details and may be associated with a known location.
- Administrators mark requests resolved. This creates an alert for the requester.

## 7. Administrator behaviour

Only an active user whose role is `admin` can open `/admin` or use administrator actions.

| Area | Administrator capability |
| --- | --- |
| System overview | See active users, report totals, approved report totals, and available/total spaces. |
| Reports | Approve or reject a report. Approval updates space availability and awards points once. |
| Users | Activate/deactivate another user; an administrator cannot deactivate their own account. |
| Locations | Add, edit, and delete a location, including coordinates and accessibility. |
| Spaces | Add, edit, and delete a location's individual parking spaces. |
| Assistance | View requests and mark them resolved. |
| Settings | Turn automatic report approval on or off. |

## 8. Routes

All HTML pages below redirect unauthenticated users to login where appropriate. Form endpoints use browser form data and redirect with a success/error message. JSON endpoints return normal HTTP error responses for invalid or unauthorized requests.

| Method | Path | Access | Purpose |
| --- | --- | --- | --- |
| GET | `/` | Public | Redirect to login or dashboard. |
| GET / POST | `/register` | Public | Registration page and account creation. |
| GET / POST | `/login` | Public | Login page and session creation. |
| POST | `/logout` | Signed in | End session. |
| GET | `/dashboard` | Signed in | Dashboard, rewards, favourites, and leaderboard. |
| GET | `/map` | Signed in | Interactive parking map page. |
| GET | `/analytics` | Signed in | Prediction page. |
| GET / POST | `/profile` | Signed in | View/update profile and accessibility preferences. |
| POST | `/assistance-requests` | Signed in | Create assistance request. |
| GET | `/notifications` | Signed in | View alerts. |
| POST | `/notifications/read` | Signed in | Mark all alerts read. |
| GET | `/api/parking-locations` | Public; favourites shown when signed in | List locations. Supports `query` and `accessible_only`. |
| POST / DELETE | `/api/favorites/{location_id}` | Signed in | Save/remove favourite. |
| POST | `/api/reports` | Signed in | Submit parking report. |
| GET | `/api/analytics/prediction` | Signed in | Get prediction. Requires `location_id` and `hour`. |
| GET | `/admin` | Administrator | Administration page and system analytics. |
| POST | `/admin/reports/{report_id}` | Administrator | Approve/reject report. |
| POST | `/admin/users/{user_id}/toggle` | Administrator | Toggle user active state. |
| POST | `/admin/locations` | Administrator | Add a location. |
| POST | `/admin/locations/{location_id}` | Administrator | Update a location. |
| POST | `/admin/locations/{location_id}/delete` | Administrator | Delete a location. |
| POST | `/admin/locations/{location_id}/spots` | Administrator | Add a parking space. |
| POST | `/admin/spots/{spot_id}` | Administrator | Update a space. |
| POST | `/admin/spots/{spot_id}/delete` | Administrator | Delete a space. |
| POST | `/admin/settings` | Administrator | Set auto-approval. |
| POST | `/admin/assistance/{request_id}/resolve` | Administrator | Resolve an assistance request. |

## 9. Installation and local operation

### Prerequisites

- Conda
- Docker Desktop or Docker Engine with Compose
- A modern browser and internet connection for map tiles/directions

### First run

Run these commands from the repository root:

```bash
conda env create -f environment.yml
conda activate smart-park
cp .env.example .env
docker compose up -d postgres
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>.

On its first start with an empty database, the application creates the tables and seeds:

- `Salmiya Waterfront Parking`
- `Kuwait City Business District`
- `Mubarakiya Market Parking`
- The administrator configured in `.env`
- Historic sample reports for the prediction demonstration

The template's initial development administrator is:

```text
Email:    admin@smartpark.local
Password: ChangeMe123!
```

Set a unique initial password and session secret in `.env` before the very first application start if this will be shared. Changing those values later does not change an administrator that has already been seeded.

### Stop and reset

Stop the database without deleting data:

```bash
docker compose stop
```

To erase the local PostgreSQL volume and recreate clean demonstration data on the next start, run:

```bash
docker compose down -v
```

This reset permanently removes local database data.

## 10. Configuration

The application reads `.env` through the `SMART_PARK_` prefix. `.env` is intentionally ignored by Git; copy `.env.example` to create it.

| Variable | Required for local run | Meaning |
| --- | --- | --- |
| `SMART_PARK_APP_NAME` | No | Browser/application title. Defaults to `Kuwait Smart Park`. |
| `SMART_PARK_DEBUG` | No | Enables SQL logging and allows non-HTTPS local session cookies. Use `false` outside local development. |
| `SMART_PARK_DATABASE_URL` | Yes | SQLAlchemy async PostgreSQL URL. |
| `SMART_PARK_POSTGRES_PORT` | Yes for Compose | Host port mapped to PostgreSQL's container port 5432. |
| `SMART_PARK_SECRET_KEY` | Yes | Long secret for signing sessions. |
| `SMART_PARK_INITIAL_ADMIN_EMAIL` | Yes | Email for the first seeded administrator. |
| `SMART_PARK_INITIAL_ADMIN_PASSWORD` | Yes | Password for the first seeded administrator. |
| `SMART_PARK_REPORT_REWARD_POINTS` | No | Points awarded after an approved report. Defaults to `10`. |

If port 5432 is already occupied, change both `SMART_PARK_POSTGRES_PORT` and the port inside `SMART_PARK_DATABASE_URL` to the same unused port, such as 5433. The checked local `.env` uses 5433 for this reason; `.env.example` shows the normal 5432 default.

## 11. Verification and acceptance checklist

The handoff verification used the actual `.env`, a Docker PostgreSQL database, and an HTTP client with cookie-session behaviour. It passed all of the following:

- Registration, login, logout, dashboard display, and Google Maps directions link.
- Parking-location API, search, accessible-only filtering, favourites add/remove/add, and prediction.
- Manual available/occupied reports, automatic approval, and user alerts for approved/rejected reports.
- Profile update and assistance creation; admin resolution and resulting notification.
- Administrator login, analytics, report approval/rejection, user deactivate/reactivate, auto-approval setting, location CRUD, and space CRUD.
- Notification display and mark-all-read.
- Python compilation, JavaScript syntax, Python dependency consistency, and whitespace checks.

For a repeatable manual demonstration, follow this sequence:

1. Start the stack and log in as the administrator in one browser session.
2. Register a normal user in a separate/incognito session.
3. Search/select a map location, save it, request a prediction, and send a parking report.
4. In the administrator session, approve the report and resolve an assistance request.
5. Return to the user session and verify the points, badge/rank, live availability, and alerts.

## 12. Operational limitations

- The project is designed as a university demonstration, not a production deployment.
- Map tiles and Google directions rely on third-party internet services; the core FastAPI/PostgreSQL flows remain local.
- Live availability means the application's current approved data. It does not claim physical real-world sensor confirmation.
- Schema creation is automatic at startup. For future production changes, introduce database migrations rather than editing a live schema manually.
- No automated test-suite files are included; the recorded end-to-end handoff check is described above.
