# Uyo seed data + CORS fix

Date: 2026-10-08
Status: approved (design)

Two backend-team asks: seed corridors/junctions/zones with Uyo data, and fix the
CORS error blocking the Vercel frontend.

## 1. CORS

The project has no CORS support at all — `django-cors-headers` is not installed
and no middleware is registered, so every browser call from
`https://omnipax-frontend.vercel.app` fails the preflight.

Change:

- Add `django-cors-headers==4.9.0` to `requirements.txt`, install in `venv`.
- `config/settings.py`:
  - `INSTALLED_APPS`: add `"corsheaders"` in the third-party block.
  - `MIDDLEWARE`: add `"corsheaders.middleware.CorsMiddleware"` directly after
    `SecurityMiddleware` (must precede `CommonMiddleware`).
  - `CORS_ALLOW_ALL_ORIGINS = True`, `CORS_ALLOW_CREDENTIALS = False`.

Rationale: authentication is Bearer JWT in a header (no cookies), so a
cross-origin request carries nothing credentialed; allowing all origins means
Vercel preview deploys work without per-URL maintenance. Channels WebSockets are
not governed by CORS and already accept any Origin — no change there.

Verification: preflight `OPTIONS` and `GET` against `/api/corridors/` with
`Origin: https://omnipax-frontend.vercel.app` both return
`access-control-allow-origin: *`; `manage.py check` and the test suite pass.

## 2. `seed_uyo` management command

### Scope

- New command `geo/management/commands/seed_uyo.py` (with the required
  `management/__init__.py` and `management/commands/__init__.py` packages).
- Data lives as module-level constants in that same file (pilot size ≈ 20 rows).
- No changes to `simulate_corridor` — its DEMO-junction fallback stays as-is.

### Data

**3 corridors**, ~5 junctions each, coordinates approximate Uyo lat/lng, inside
`AKWA_IBOM_BBOX`, junctions on a corridor spaced ≥400m apart so nearest-junction
resolution (default 300m radius) is unambiguous:

- **Oron Road** — Ibom Plaza, Cover Road Junction, Nwaniba Road, Town Hall,
  Odu Oron.
- **Aka Road** — Aka Road Junction, Shelter Afrik, Ekpri Nsukara, Imeette,
  Okuip Junction.
- **Ikot Ekpene Road** — Ikot Ekpene Road Junction, Abak Road Turn-off,
  Idoro Road, Mbono Uyo, Akwa Ibom Depo.

Exact coordinates are approximate and marked as such in the data comments;
operations can correct them later through admin or by editing the constants.

**4 restricted zones**, MVP shape `{"center": [lat, lng], "radius_m": N}`:

1. Always-blocking `full_closure` (effective 2026-01-01) so demos reliably hit
   the `restricted_zone` rejection.
2. `time_window` peak-hours restriction (07:00–19:00, same effective date) for
   realism.
3. A second `full_closure` on another corridor.
4. One `is_active=False` example so the admin toggle has something to show.

Each zone links to a junction (`junction` FK) where one makes sense; otherwise
the FK stays null.

### Upsert semantics

Natural keys: corridor → `name`; junction → (`corridor`, `name`); zone →
`name`.

- Missing row → create.
- Row exists with different fields → update those fields in place (never
  change the UUID).
- Row already matches → untouched.

The whole run happens in a single transaction. The command prints
`created / updated / unchanged` counts per model. Re-running on a seeded
database must report 0 created and 0 updated.

### Error handling

- Unknown/inactive junction reference in zone data raises `CommandError` with
  the zone name (caught before any write, since data is validated up front).
- Coordinate validation is the same bbox sanity check the API already applies;
  seed coordinates are verified by tests rather than at runtime.

### Testing

`geo/tests.py`:

1. Idempotency — run twice, second run reports 0 created / 0 updated.
2. Counts — 3 corridors, 15 junctions, 4 zones.
3. Every junction/zone coordinate lies within `AKWA_IBOM_BBOX`.
4. Every zone's junction FK (when set) points at an existing junction.
5. Zone blocking behaviour — the always-blocking closure actually blocks a
   point inside it via `find_blocking_zone`.

### Verification

- `python manage.py seed_uyo` twice (second run: all zeros).
- `python manage.py test`.
- `python manage.py simulate_corridor` still runs against the seeded
  Oron Road corridor.
