<<<<<<< HEAD
# Nexa
Project
=======
# NEXACART - Smart E-Commerce Platform with Weather Information

NEXACART is a web based e-commerce platform: secure accounts, sign-in, account
management and role based access control for the three roles **Administrator,
Seller and Buyer**, a product catalogue with a persistent shopping cart and
simulated checkout, **live weather search powered by the OpenWeather API**, and
a fully translated interface in **English, French and Arabic**, including
complete right-to-left support for Arabic.

The project is written in **Python (Flask)** with a **SQLite 3** database and contains no
JavaScript framework dependencies, no external CSS framework and no cloud service
dependency, so it runs on any laptop with Python 3.10+.

---

## 1. Quick start

```powershell
# 1. install the dependencies (Flask + Werkzeug)
pip install -r requirements.txt

# 2. start the development server
python run.py
```

Then open **http://127.0.0.1:5000** in your browser.

> The server also accepts a custom port: `$env:PORT=5050; python run.py`
> (port 5000 is already used by another application on this machine, so 5050 is the
> convenient choice here)

On the first start the database is created in `instance/nexacart.db`, the schema is
applied and a first administrator account is created:

| Role          | Username | Password      | E-mail                |
| ------------- | -------- | ------------- | --------------------- |
| Administrator | `admin`  | `Admin@12345` | `admin@nexacart.local`|

The administrator **must change this password at the first sign-in** (the application
redirects to the security page until a new password is set).

Optional demo accounts for the seller and buyer workspaces:

```powershell
python -m flask seed-demo
```

| Role  | Username     | Password      |
| ----- | ------------ | ------------- |
| Seller| `seller_demo`| `Seller@12345`|
| Buyer | `buyer_demo` | `Buyer@12345` |

### Command line helpers

`wsgi.py` exposes the application, so the Flask CLI finds NEXACART automatically - no
extra environment variable is needed:

```powershell
python -m flask init-db        # create / update the schema
python -m flask create-admin   # create or promote an administrator
python -m flask seed-demo      # create the seller / buyer demo accounts
```

---

## 2. Weather feature (OpenWeather API)

The weather search at **/weather/** is public — no account is required. Visitors can
search **by city name** (e.g. `Kigali`, `Nairobi,KE`, `London`) **or by latitude and
longitude**; the two methods are separate tabs and only one is needed.

### Environment variable

Put your OpenWeather API key in the environment — never in the source code:

```powershell
$env:OPENWEATHER_API_KEY = "your-key-here"
python run.py
```

Without a key the feature still works end-to-end using **clearly-labelled sample
data** (a banner explains this), so the flow — search, result, history, statistics —
can be demonstrated offline. Errors (unknown city, invalid coordinates, network
failure, API failure) always show friendly feedback and never break the store.

### What is recorded

Every lookup is stored in the `weather_searches` table: the search input (city or
coordinates), the search method, the resolved city, whether it succeeded, and the
timestamp. **No personal data or user ids are stored.** Administrators can review the
history under *Dashboard → Weather history* and see aggregated usage statistics
(total searches, success rate, most searched cities) under *Statistics*, with a
confirmation-protected "Clear history" action.
python -m flask routes         # show every URL of the application
```

---

## 2. Features

### 2.1 User registration
* Sign-up with full name, username, e-mail, role choice (Seller or Buyer) and password.
* Administrator accounts **cannot** be created from the public form - only an existing
  administrator can promote someone. This prevents privilege escalation.
* Live password strength checklist, password generator and a match indicator for the
  confirmation field.
* Server side validation with clear, field level error messages (never only "invalid
  input"): duplicate username, duplicate e-mail, weak password, mismatching confirmation,
  missing terms.

### 2.2 Sign-in and sign-out
* Sign in with **username or e-mail address**.
* "Keep me signed in" (30 days) or a session that ends when the browser closes.
* Generic error message for a wrong password *and* for an unknown account, so the form
  never reveals which accounts exist.
* Five failed attempts lock the account for 15 minutes; the attempt is written to the
  activity log.
* An additional per-IP throttle protects the sign-in form against credential stuffing.
* Suspended accounts are refused with an explanatory message.

### 2.3 Account management
* Change name and e-mail (an e-mail change requires the current password).
* Change the password, which ends every other session.
* Review the devices that are currently signed in, and sign individual devices out or
  sign out of all of them at once.
* A personal activity trail of the last security events.

### 2.4 Role based access control
Every area of the application is guarded **on the server**. Hiding a button is only a
convenience - the real check happens before the page is produced.

| Area of the application                    | Administrator | Seller | Buyer |
| ------------------------------------------ | :-----------: | :----: | :---: |
| Dashboard, user management, activity log   | yes           | no     | no    |
| Seller workspace and product area          | yes           | yes    | no    |
| Buyer dashboard and shopping cart          | no            | no     | yes   |
| Own account settings and active devices    | yes           | yes    | yes   |

* A signed-in user is redirected to the dashboard that matches their role.
* A user who opens a page outside their role receives a friendly **403 access denied**
  page that names the roles allowed there - and the attempt is written to the activity
  log.

### 2.5 Administrator area
* Statistics: registered users, users per role, active sessions, failed sign-ins in the
  last 24 hours, locked and suspended accounts.
* User table with search and role filter, pagination and a detail page per user.
* Change a role, suspend an account (which ends its sessions) or reactivate it.
* Guard rails: an administrator cannot change their own role, cannot suspend themselves
  and the last active administrator cannot be demoted or suspended.
* Activity log and a list of all active sessions across the platform.

### 2.6 Internationalisation (English, French, Arabic)
* Every visible string lives in a JSON catalogue under `nexacart/translations/`
  (`en.json`, `fr.json`, `ar.json`). The templates ask for a dotted key such as
  `t("login.title")` - no wording is hard coded in HTML or Python.
* The language switcher in the header stores the choice in the signed session cookie and
  returns the visitor to the page they came from.
* When no choice has been made yet, the browser's `Accept-Language` header decides the
  language.
* **Arabic is right-to-left**: the server sends `<html lang="ar" dir="rtl">`, the
  stylesheet uses logical properties (`margin-inline-start`, `inset-inline-end`,
  `text-align: start`) instead of left/right, and Arabic letter spacing is switched off
  so that the ligatures stay intact.
* Locale aware formatting: French uses the narrow no-break space as thousands
  separator (`1 234,5`), Arabic uses Arabic-Indic digits and Arabic separators
  (`١٬٢٣٤٫٥`), and dates use the month names of the active language.
* The password checklist and the role names are keyed by **stable identifiers**
  (`data-rule="min_length"`, `role.buyer`) so the browser logic never depends on the
  wording of a language.

---

## 3. Security design

| Risk                          | Counter measure                                                                 |
| ----------------------------- | -------------------------------------------------------------------------------- |
| Password theft from database | Salted PBKDF2-SHA256 (600 000 iterations), never stored as readable text          |
| Session hijacking             | Opaque random token, only its SHA-256 digest is stored, HttpOnly + SameSite cookie |
| Session theft via database    | A leaked digest cannot be replayed - the raw token never reaches the database      |
| Cross-site request forgery    | Signed one-time CSRF token on every state changing request                         |
| Open redirect                 | Only same-site relative `next` targets are accepted                                |
| Credential stuffing           | Per-IP throttle plus a per-account lockout after five failures                     |
| XSS                           | Jinja2 autoescaping everywhere, strict Content-Security-Policy header              |
| Clickjacking / sniffing       | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`     |
| SQL injection                 | Parameterised statements only                                                      |
| Privilege escalation          | Administrator accounts are never created from the public form                      |
| Inactive sessions             | 30 minute idle timeout, 12 hour absolute timeout, revocable per device            |

The browser never receives a role, a user id or a password - the session is resolved
server side on every request, and the role is read from the database.

---

## 4. User interface and HCI

The interface was designed for the HCI project requirements:

* **Clear visual hierarchy** - one primary action per screen, headings, cards and a
  consistent 8-point spacing system.
* **Intuitive placement** - the role badge is always visible in the header, so the user
  always knows which workspace they are in.
* **Helpful error states** - every message says what happened *and* what to do next
  ("5 attempt(s) left before the account is temporarily locked").
* **Accessibility** - skip link, semantic landmarks, labelled inputs, `aria-live` for
  the message area, visible focus rings, a light/dark theme with sufficient contrast,
  `prefers-reduced-motion` and `prefers-contrast` support, keyboard operable throughout.
* **Responsive** - the layout adapts from a phone to a wide desktop screen.
* **Progressive enhancement** - every function works without JavaScript; the scripts
  only add the theme switch, the password visibility toggle, the strength meter, the
  generator and the instant match check.
* **Language independence** - the same layout serves left-to-right and right-to-left
  languages, and the language can be changed without leaving the current page.

The reasoning behind each decision is documented in [`docs/HCI_NOTES.md`](docs/HCI_NOTES.md).

---

## 5. Project structure

```
NEXACART/
├── run.py                     # development entry point
├── wsgi.py                    # WSGI entry point for the Flask CLI and a web server
├── requirements.txt
├── nexacart/
│   ├── __init__.py            # application factory, hooks, error handlers
│   ├── config.py              # configuration for dev / test / production
│   ├── db.py                  # SQLite connection, schema init, CLI commands
│   ├── schema.sql             # tables: users, auth_sessions, login_attempts, audit_log
│   ├── i18n.py                # translation engine, locale detection, formatting
│   ├── models.py              # data access layer (parameterised SQL)
│   ├── security.py            # hashing, validation, CSRF, sessions, RBAC decorators
│   ├── utils.py               # formatting helpers
│   ├── routes/                # blueprints: main, auth, account, admin, seller, buyer
│   ├── templates/             # Jinja templates (HTML5, accessible)
│   ├── translations/          # en.json, fr.json, ar.json
│   └── static/                # CSS, JavaScript, favicon
├── tests/test_app.py          # 53 automated tests (standard library unittest)
├── docs/HCI_NOTES.md          # design rationale and heuristic evaluation
└── instance/                  # created at runtime: nexacart.db, secret_key
```

---

## 6. Tests

```powershell
python -m unittest discover -s tests -v
```

53 tests cover registration and validation, sign-in (including lockout, suspension and
generic error messages), CSRF enforcement, session creation and revocation, the full
role matrix (who may open which area), administrator actions and their guard rails, the
security helpers (password hashing, open-redirect blocking, hashed session tokens,
HttpOnly cookies) and the internationalisation layer (identical catalogue keys in all
three languages, the language switcher, the right-to-left layout, locale aware number
formatting and the absence of any release-stage wording in the interface).

---

## 7. Extending the application

The architecture is ready for further product areas:

* The `users` table already distinguishes the three roles, and the RBAC decorators
  (`roles_required`, `login_required`) are ready for new blueprints.
* Two protected pages already prove the access control: `/seller/products`
  (Administrator + Seller) and `/buyer/cart` (Buyer only).
* The server side session store gives the shopping cart a home that survives page
  changes and browser restarts.
* A new feature only has to add its own strings to the three catalogues - the same key
  in `en.json`, `fr.json` and `ar.json` - and the layout follows the direction of the
  active language automatically.
>>>>>>> 8df6a31 (Initial commit)
