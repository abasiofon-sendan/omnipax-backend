# Omnipax Backend — Design Spec

**Date:** 2026-09-23
**Status:** Draft — pending user review
**Source:** `Omnipax_Backend_Build_Spec.md` (single source of truth for requirements),
refined through brainstorming on 2026-09-23.
**Decisions locked in brainstorming:** hackathon deadline; full spec scope (all 12 build
steps); JWT via `djangorestframework-simplejwt`; plain `DecimalField` lat/lng with
haversine in Python (GeoDjango unavailable — no psycopg2/GDAL in venv); Approach A
(spec-native sequential build order); heatmap-first driver model with Option C
(public heat, nearest-set push alerts + completion eligibility); tip = emergency
payment that pages the single nearest eligible driver with accept/decline +
reservation (replaces heat-boost/pool-expansion; alert fires on webhook-confirmed
payment only); password + OTP auth (phone = login ID, email = OTP-verified identity;
phone is required because password login uses it — this supersedes the earlier
"phone never compulsory" call).

---

## 1. Context and goal

Omnipax is a pooled public-transit demand system for Keke Napep and mini-bus commuters
in Uyo. It is NOT 1-to-1 dispatch: passengers signal demand at a junction (a "pin"),
pins are pooled into per-junction aggregate demand, and drivers see a heatmap of that
demand — never individual pins. The nearest online drivers to new demand get push
alerts, and only alerted/eligible drivers can complete a pin; a 4-digit pickup code,
held by the passenger, confirms completion when the driver physically picks someone up.
The individual pin surfaces only at completion time, via the code. A passenger in
an emergency can attach a tip to their pin: once Bachs confirms payment, the backend
pages the single nearest eligible driver, who must accept (reserving the pin) or
decline within 90 seconds.

**Goal of this design:** a Django + DRF backend that collects pins, resolves GPS to
junctions, computes zone scores, tracks driver presence, manages pin expiry (6 min
default), handles tip payments via Bachs (direct capture, no escrow), enforces
restricted-route rules, and pushes realtime updates — with polling fallbacks so every
feature works over plain REST.

**Starting state:** empty project directory with a Python 3.12 venv containing only
Django 6.1.1. DRF, Channels, Celery, Redis client, simplejwt, and psycopg still need
installing. No app code exists yet.

---

## 2. Architecture

Monolithic Django + DRF app with three layers:

- **Sync layer (Django/DRF):** auth, pin CRUD, driver actions, admin ops, webhook
  receiver. Every realtime feature has a polling-equivalent REST endpoint.
- **Async layer (Celery + Celery Beat, Redis broker):** pin expiry sweep every
  30–60s; periodic zone-score recompute.
- **Realtime layer (Django Channels, Redis channel layer):** one group per junction
  (`junction_{junction_id}`) carrying aggregate demand deltas (active-pin counts and
  scores — never individual pins), plus one group per driver (`driver_{driver_id}`)
  carrying targeted alerts for demand the driver is in the visibility set for.
  Driver consumer at `ws/driver/{driver_id}/` subscribes to the corridor's junction
  groups (heat) and its own driver group (alerts). WebSocket is an enhancement layer,
  never a dependency.

**Data flow (pin lifecycle):**
passenger POSTs GPS → junction resolved (haversine, 300m max radius) →
restricted-zone check → pickup code generated → pin created (`standard`) → pin
pooled into the junction's aggregate demand → junction group notified with a demand
delta + push alerts to the nearest online drivers → all drivers see updated heat;
alerted drivers know demand is near them → passenger in an emergency attaches a tip
→ Bachs webhook confirms payment → pin upgraded to `priority` and the single nearest
eligible driver is paged (accept → `reserved`; decline/timeout → released back to
`active`, re-pageable) → (reserved) driver drives to the junction, passenger shows
the 4-digit code → driver enters code (server checks the driver holds the reservation)
→ pin `completed`, tip claim recorded.

---

## 3. Tech stack

| Concern | Choice |
|---|---|
| Framework | Django 6.1.1 + Django REST Framework |
| Auth | Custom `User` model (`AUTH_USER_MODEL`, `AbstractBaseUser`, `USERNAME_FIELD=phone_number`, set before first migration), JWT via simplejwt; signup (email + phone + password) → email OTP verification → login (phone + password) |
| Realtime | Django Channels + Redis channel layer, polling fallback (10–15s client interval) |
| Background jobs | Celery + Celery Beat, Redis as broker |
| Database | PostgreSQL; plain `Decimal(9,6)` lat/lng + haversine in `core/geo_utils.py` (no GeoDjango) |
| Payments | Bachs sandbox; webhook-only confirmation, signature-verified, idempotent |
| Observability | WatchUp on backend endpoints only |

---

## 4. App structure

```
omnipax/
├── accounts/   # User model, OTP auth, driver registration
├── geo/        # Corridor, Junction, RestrictedZone
├── rides/      # Pin, pin lifecycle, expiry
├── drivers/    # DriverProfile, DriverLocation, zone scoring, visibility
├── payments/   # Tip, Bachs integration, webhook
├── realtime/   # Channels consumers and routing
└── core/       # haversine distance, junction resolver, pickup-code generator
```

Each app owns one bounded context and exposes it through serializers/views; `core`
holds pure, dependency-free geo/code utilities with unit tests.

---

## 5. Data models

### 5.1 `accounts`

**User** (custom, UUID PK, extends `AbstractBaseUser` for built-in password hashing —
never roll custom crypto): `phone_number` (unique, E.164, `USERNAME_FIELD`, the login
ID — required), `email` (unique, validated as email — required, verified via OTP),
`role` (`passenger` / `driver` / `admin`), `is_verified` (email verified via OTP;
password login requires `is_verified=True`), `created_at`. Auth flows:
signup creates the user (unverified) → OTP to email verifies it → login is
phone number + password → JWT.

**OTPVerification:** `email`, `code` (6-char; plain OK for sandbox, hashed in
production), `created_at`, `expires_at` (+5 min), `is_used`, `attempt_count`.
OTP is delivered by email (console backend in dev, SMTP via env vars in prod).
Rate limits: max 3 OTP requests per email per 15 min; max 5 verification attempts
per code.

### 5.2 `geo`

**Corridor:** `name` (e.g. "Oron Road"), `description`, `is_active`.
**Junction:** `name` (e.g. "Ibom Plaza"), FK → Corridor, `latitude`/`longitude`
`Decimal(9,6)`, `is_active`.
**RestrictedZone:** `name`, nullable FK → Junction, `coordinates` JSONField
(center point + radius for MVP), `restriction_type` (`full_closure` /
`time_window`), nullable `start_time`/`end_time` (required for `time_window`),
`effective_date`, `reason`, `is_active`. Zone containment is a center+radius
haversine check, documented in code as an MVP simplification (not full geofencing).

### 5.3 `rides`

**Pin:** `passenger` FK, `device_id`, `raw_latitude`/`raw_longitude` (stored GPS),
resolved `junction` FK + `corridor` FK, `direction` (free text), `vehicle_type`
(`keke` / `minibus`), `status` (`active` / `reserved` / `expired` / `completed` /
`cancelled`), `priority` (`standard` default → `priority` on confirmed emergency
payment), `pickup_code`
(4-digit, unique among active pins), `expires_at` (created + 6 min, configurable
5–8), nullable `completed_by` + `completed_at`, nullable `reserved_by`
(FK → DriverProfile) + `reserved_at` + `reservation_expires_at`
(accept window, default 90s).
**Business rule:** at most one `active` pin per `device_id`, enforced at creation.
**PinDriverVisibility** (alert/eligibility record): `pin`, `driver`, `distance_meters`,
`rank`, `assigned_at`. Each row records that a driver was alerted to a pin's demand
and is eligible to complete it (nearest `STANDARD_VISIBILITY_COUNT` online drivers
per standard pin at creation-alert time; emergency pages are recorded separately
in `EmergencyPage`).
Computed live at alert time and re-checked at completion; persist the table since
completion validation depends on it.

**EmergencyPage** (one row per page attempt): `pin` FK, `driver` FK → DriverProfile,
`outcome` (`paged` / `accepted` / `declined` / `expired`), `created_at`,
`resolved_at` (nullable). Re-pages skip drivers already paged for that pin. This is
the record that lets a released pin be re-paged to the next-nearest driver without
charging the passenger twice.

### 5.4 `drivers`

**DriverProfile:** `user` OneToOne, `registration_id` (unique, state registry ID),
`vehicle_type`, `plate_number`, `approved_corridor` FK, `verification_status`
(`pending` / `verified` / `rejected`), `is_online` (default False), `created_at`.
**DriverLocation** (current row only, OneToOne): `latitude`/`longitude`,
nullable `accuracy_meters`, `recorded_at` (upserted on every heartbeat). No history
table for MVP. Locations older than 2 min are stale and excluded from availability
and visibility.

### 5.5 `payments`

**Tip** (OneToOne → Pin): `amount` (default 100.00), `currency` (default "NGN"),
`status` (`pending` / `paid` / `failed` — no `refunded`), nullable unique
`bachs_reference`, nullable `paid_at`, nullable `claimed_by_driver`
(bookkeeping record only, NOT a fund transfer). A tip IS an emergency payment: on
webhook-confirmed `paid`, the backend pages the single nearest eligible driver
(§7 rule 6). Paid-but-unclaimed tips stay
`paid` with `claimed_by_driver = null`. This is an accepted MVP gap and must be
stated plainly in any demo.

---

## 6. API endpoints

**Auth:** `POST /api/auth/signup/` (`{email, phone_number, password}` → creates
unverified User, sends OTP to email), `POST /api/auth/otp/request/` (`{email}` →
re-sends OTP), `POST /api/auth/otp/verify/` (`{email, code}` → sets `is_verified`),
`POST /api/auth/login/` (`{phone_number, password}` → returns JWT; requires
`is_verified=True`),
`POST /api/auth/driver/register/` (same account fields plus `registration_id`,
`vehicle_type`, `plate_number`, `approved_corridor_id`; drivers log in with phone +
password like everyone else),
`POST /api/auth/driver/verify/` (admin-only).

**Pins:** `POST /api/pins/` (resolve junction, zone check, one-pin-per-device
check, returns pin + pickup code), `GET /api/pins/active/`,
`POST /api/pins/{id}/cancel/`, `GET /api/pins/{id}/status/` (poll fallback for pin
state, including emergency/page state: `none` / `paged` / `reserved` / `no_driver` /
`released`).

**Tips (emergency):** `POST /api/pins/{id}/tip/` (creates Bachs session, returns
redirect URL; if the pin already has a `paid` tip and is back to `active` after a
decline/timeout, re-pages the next-nearest un-paged eligible driver instead of
charging again), `POST /api/payments/webhook/bachs/` (signature-verified,
idempotent; sets `Tip.paid`, `Pin.priority=priority`, pages the single nearest
eligible driver — verified, online, fresh location, same corridor, matching vehicle
type; if none qualifies, pin stays `priority` with emergency state `no_driver` and
the passenger sees it on the status poll).

**Driver:** `POST /api/driver/location/` (heartbeat upsert),
`POST /api/driver/online/` (toggle), `GET /api/driver/zones/` (the primary driver
interface: top-3 junctions by `active_pins / max(available_drivers, 1)` PLUS the
full per-junction demand array that renders the heatmap — heat is public to all
online drivers in the corridor), `GET /api/driver/pins/` (NOT a request inbox:
returns only pins this driver was alerted to / is eligible to complete),
`POST /api/driver/pins/{id}/complete/` (`pickup_code`, rate-limited to 5 tries per
pin; mandatory: reject drivers outside the pin's visibility set with a clear error),
`POST /api/driver/pins/{id}/accept/` (paged driver only, within the accept window →
pin `reserved`, `EmergencyPage` → `accepted`), `POST /api/driver/pins/{id}/decline/`
(paged driver only → release reservation, pin back to `active`, `EmergencyPage` →
`declined`; passenger may re-page).

**Admin:** CRUD `/api/admin/restricted-zones/`, `/api/admin/junctions/`,
`/api/admin/corridors/` (all `role=admin` + staff permission),
`GET /api/admin/dashboard/` (active pins, online drivers, per-junction demand).

---

## 7. Key business rules

1. **Pin creation:** reject if device has an active pin → resolve nearest junction
   (reject beyond 300m) → reject if inside an active restricted zone (honouring
   time windows) → generate collision-free 4-digit code → create `active /
   standard` pin → pool into junction aggregate → publish a demand delta to the
   junction group and push alerts to the nearest online drivers (persisting
   `PinDriverVisibility` rows).
2. **Visibility = alerts + completion eligibility (Option C):** the heatmap is public
   to all online drivers in the corridor. The nearest-set rule
   (`STANDARD_VISIBILITY_COUNT`, fresh locations only) decides who gets push alerts
   on new demand and who may complete the pin. (There is no expanded pool or heat
   boost for paid pins anymore — see rule 6.) Anti-herding is enforced through alert scoping, not by hiding demand;
   everything depends on the 15–30s driver heartbeat cadence (documented for the
   client).
3. **Zone scoring:** `score = active_pin_count / max(available_driver_count, 1)`;
   endpoint returns the top 3 descending PLUS the full per-junction demand array for
   the heatmap; stale locations excluded.
4. **Expiry:** Celery Beat every 30–60s flips overdue `active` pins to `expired`
   AND releases overdue reservations (`reservation_expires_at < now` →
   `EmergencyPage` → `expired`, pin back to `active` unless `expires_at` also
   passed); no refund logic.
5. **Completion:** validate status + code + reservation hold — a `reserved` pin is
   completable ONLY by its `reserved_by` driver; a non-reserved `active` pin keeps
   the MANDATORY visibility-membership check (the driver needs no prior sighting of
   the pin — the passenger's code plus server-side eligibility is sufficient) →
   set `completed`/`completed_by` → record `claimed_by_driver` on any paid tip
   (no money movement).
6. **Emergency payments:** never trust browser redirect; only the verified webhook
   confirms payment; handler is idempotent per `bachs_reference`. On confirmation:
   set `Tip.paid`, `Pin.priority=priority`, page the single nearest eligible driver
   (verified, online, fresh location ≤120s, same corridor, matching vehicle type;
   persist `EmergencyPage` as `paged`, set `reservation_expires_at = now + 90s`).
   If no eligible driver qualifies, the pin stays `priority` with emergency state
   `no_driver`, visible on the status poll; the passenger retries paging later via
   the tip endpoint (already-paid → re-page, never re-charge).
7. **Verification:** pluggable `verify_driver(registration_id)`; MVP = manual
   admin-approval queue (`pending` → `verified`); registry API swaps in later
   without touching callers.

---

## 8. Security and validation

OTP rate limits (§5.1); passwords hashed with Django's default hasher (min length 8
via validators); login throttled per phone (lockout/backoff, exact policy at build
time); `device_id` + `phone_number` checked before new pins;
mandatory webhook signature verification; pickup-code rate limiting (5/pin);
coordinate sanity check against Akwa Ibom bounding box; admin endpoints gated by
`role=admin` + staff permission via DRF permission classes.

## 8b. Tunable settings and defaults

Single source of defaults (Django settings, overridable per environment):

| Setting | Default |
|---|---|
| `PIN_TTL_MINUTES` | 6 (allowed 5–8) |
| `MAX_JUNCTION_RADIUS_METERS` | 300 |
| `DRIVER_HEARTBEAT_SECONDS` (client cadence) | 15–30 |
| `DRIVER_LOCATION_STALE_SECONDS` | 120 |
| `STANDARD_VISIBILITY_COUNT` | 3 (nearest online drivers alerted + eligible per standard pin) |
| `EMERGENCY_ACCEPT_SECONDS` | 90 (paged driver accept window) |
| `ZONE_SCORE_PROXIMITY_METERS` | 2000 (driver counts as near a junction) |
| `OTP_REQUEST_LIMIT` / window | 3 per 15 min per email |
| `EMAIL_BACKEND` | console in dev, SMTP (env-configured) in prod |
| `OTP_VERIFY_ATTEMPTS` | 5 per code |
| `PICKUP_CODE_ATTEMPTS` | 5 per pin |
| `PIN_EXPIRY_SWEEP_SECONDS` | 30–60 |
| `POLLING_FALLBACK_SECONDS` | 10–15 |

Open integration detail: Bachs sandbox base URL, signature header/scheme, and
event names are not in the requirements and must be read from the Bachs docs at
the start of build step 8 — the webhook contract in §6 assumes standard
HMAC-signed JSON webhooks and will be corrected to match Bachs exactly.

---

## 9. Testing checklist

Pin junction resolution + out-of-radius rejection; one-active-pin-per-device;
restricted-zone blocking incl. time windows; expiry job precision; heatmap/zones
endpoint reflects pooled per-junction counts (never individual pins); new-demand
alerts fire to the nearest `STANDARD_VISIBILITY_COUNT` online drivers only;
completion by a driver outside the visibility set is rejected; confirmed emergency
payment pages exactly one nearest eligible driver (verified, online, fresh location,
same corridor, matching vehicle type) and `no_driver` is reported when none
qualifies; accept reserves the pin and only the reserving driver can complete it;
decline/timeout releases back to `active` and re-page skips already-paged drivers
without re-charging; webhook
idempotency under duplicate delivery; pickup completion incl. wrong-code/expired
failures + `claimed_by_driver` recording; zone scoring reacting to
online/offline and pin churn; stale-location exclusion (>2 min).

---

## 10. Build order (Approach A — spec-native sequential)

1. Scaffolding (Django + DRF + Channels + Celery + Postgres + Redis; custom User
   before first migration; install DRF, Channels, Celery, simplejwt, psycopg).
2. `accounts` (custom User, signup/login, email OTP request/verify, email backend
   config, driver registration as `pending`).
3. `geo` (models, admin CRUD, `core/geo_utils.py` resolver + unit tests).
4. `rides` (Pin model + creation wired to junction/zone checks; cancel + status).
5. `drivers` (DriverProfile, heartbeat, online toggle).
6. Visibility + scoring (alert/eligibility computed at pin-create time and
   re-checked at completion; zones endpoint live-computed).
7. Celery Beat sweep (pin expiry + reservation-expiry release).
8. `payments` (Bachs session, verified idempotent webhook, emergency paging of the
   nearest eligible driver on confirmation).
9. Pickup-code completion + accept/decline (rate limiting, mandatory
   visibility-membership / reservation-hold checks, claim recording).
10. Realtime (Channels consumers + junction groups for heat deltas + per-driver
    groups for alerts, layered over working REST/polling).
11. WatchUp (backend health/latency only).
12. Demo-data simulator management command for one pilot corridor. The pilot
    corridor name is not fixed in the requirements — confirm it before this step
    (default: whatever corridor is seeded first); the simulator plays realistic
    pins and driver movement through the real ingestion endpoints for that
    corridor.

Steps 6–7 stay after 4–5: scoring/visibility have nothing to compute until pins
and driver locations exist.

---

## 11. Flags and accepted gaps

- Raw GPS is stored intentionally; revisit retention (purge after expiry) for
  compliance post-hackathon.
- No escrow: tips captured immediately; driver payout is manual/off-platform for
  MVP — say so explicitly in the demo. Tips are emergency pages, not fare
  prepayment — say that explicitly too.
- Asymmetric alerting/eligibility (Option C) is load-bearing on heartbeat freshness:
  heat is public; only alerts and completion rights are scoped to the nearest set.
- 4-digit pickup codes are brute-forceable without the 5-try rate limit — the
  limit is mandatory, not optional.
