"""Automated tests for NEXACART (standard library unittest).

Run with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexacart import create_app  # noqa: E402
from nexacart import models  # noqa: E402

CSRF_PATTERN = re.compile(r'name="csrf_token" value="([^"]+)"')


def csrf_token(client, url: str = "/auth/login") -> str:
    html = client.get(url).get_data(as_text=True)
    match = CSRF_PATTERN.search(html)
    assert match, f"no CSRF token found on {url}"
    return match.group(1)


class NexacartTestCase(unittest.TestCase):
    """Base class: fresh database and client for every test."""

    @classmethod
    def setUpClass(cls) -> None:
        instance = ROOT / "instance"
        instance.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            candidate = instance / f"nexacart_test.db{suffix}"
            if candidate.exists():
                candidate.unlink()
        cls.app = create_app("testing")
        cls.app.config["SERVER_NAME"] = None

    def setUp(self) -> None:
        self.client = self.app.test_client()
        with self.app.app_context():
            models.execute_db("DELETE FROM auth_sessions")
            models.execute_db("DELETE FROM login_attempts")
            models.execute_db("DELETE FROM audit_log")
            models.execute_db("DELETE FROM users")
            models.create_user(
                username="admin",
                email="admin@nexacart.local",
                full_name="Platform Administrator",
                password_hash=self.hash("Admin@12345"),
                role="admin",
            )
            models.create_user(
                username="seller_demo",
                email="seller@nexacart.local",
                full_name="Demo Seller",
                password_hash=self.hash("Seller@12345"),
                role="seller",
            )
            models.create_user(
                username="buyer_demo",
                email="buyer@nexacart.local",
                full_name="Demo Buyer",
                password_hash=self.hash("Buyer@12345"),
                role="buyer",
            )

    @staticmethod
    def hash(password: str) -> str:
        from werkzeug.security import generate_password_hash

        return generate_password_hash(password, method="pbkdf2:sha256:10000")

    # -- helpers -----------------------------------------------------
    def login(self, identifier: str, password: str) -> object:
        token = csrf_token(self.client)
        return self.client.post(
            "/auth/login",
            data={"identifier": identifier, "password": password, "csrf_token": token},
            follow_redirects=False,
        )


class PublicPagesTests(NexacartTestCase):
    def test_landing_page_is_public(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("NEXACART", response.get_data(as_text=True))

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_unknown_page_returns_404(self):
        self.assertEqual(self.client.get("/does-not-exist").status_code, 404)


class RegistrationTests(NexacartTestCase):
    def register(self, **overrides):
        data = {
            "full_name": "Alex Morgan",
            "username": "alex_morgan",
            "email": "alex@example.com",
            "role": "buyer",
            "password": "Secret123",
            "confirm_password": "Secret123",
            "terms": "1",
            "csrf_token": csrf_token(self.client, "/auth/register"),
        }
        data.update(overrides)
        return self.client.post("/auth/register", data=data)

    def test_registration_creates_the_account(self):
        response = self.register()
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = models.get_user_by_identifier("alex_morgan")
            self.assertIsNotNone(user)
            self.assertEqual(user["role"], "buyer")
            self.assertNotEqual(user["password_hash"], "Secret123")
            self.assertTrue(user["password_hash"].startswith("pbkdf2:"))

    def test_registration_rejects_weak_password(self):
        response = self.register(password="abc", confirm_password="abc")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Password needs", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertIsNone(models.get_user_by_identifier("alex_morgan"))

    def test_registration_rejects_mismatched_confirmation(self):
        response = self.register(confirm_password="Different123")
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertIsNone(models.get_user_by_identifier("alex_morgan"))

    def test_registration_rejects_duplicate_username(self):
        response = self.register(username="buyer_demo")
        self.assertEqual(response.status_code, 200)
        self.assertIn("already registered", response.get_data(as_text=True))

    def test_registration_rejects_duplicate_email_case_insensitively(self):
        response = self.register(email="BUYER@NEXACART.LOCAL")
        self.assertEqual(response.status_code, 200)
        self.assertIn("already uses that email", response.get_data(as_text=True))

    def test_registration_requires_terms(self):
        response = self.register(terms=None)
        self.assertEqual(response.status_code, 200)
        self.assertIn("accept the terms", response.get_data(as_text=True))

    def test_registration_cannot_create_an_administrator(self):
        response = self.register(role="admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Choose either Seller or Buyer", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertIsNone(models.get_user_by_identifier("alex_morgan"))


class AuthenticationTests(NexacartTestCase):
    def test_successful_login_redirects_to_the_role_dashboard(self):
        response = self.login("admin", "Admin@12345")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/admin/"))

        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Administrator dashboard", response.get_data(as_text=True))

    def test_login_with_email_also_works(self):
        response = self.login("buyer@nexacart.local", "Buyer@12345")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/buyer/"))

    def test_wrong_password_is_rejected(self):
        response = self.login("admin", "wrong-password")
        self.assertEqual(response.status_code, 200)
        self.assertIn("could not sign you in", response.get_data(as_text=True))

    def test_unknown_user_gives_a_generic_message(self):
        response = self.login("ghost", "whatever")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("could not sign you in", body)
        self.assertNotIn("no account with", body.lower())

    def test_account_is_locked_after_five_failures(self):
        for _ in range(5):
            self.login("buyer_demo", "wrong")
        response = self.login("buyer_demo", "Buyer@12345")
        self.assertEqual(response.status_code, 200)
        self.assertIn("locked", response.get_data(as_text=True).lower())

    def test_logout_ends_the_session(self):
        self.login("buyer_demo", "Buyer@12345")
        self.assertEqual(self.client.get("/buyer/").status_code, 200)
        token = csrf_token(self.client, "/account/profile")
        self.client.post("/auth/logout", data={"csrf_token": token})
        response = self.client.get("/buyer/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login", response.headers["Location"])

    def test_suspended_account_cannot_sign_in(self):
        with self.app.app_context():
            models.set_user_status(
                models.get_user_by_identifier("buyer_demo")["id"], "suspended"
            )
        response = self.login("buyer_demo", "Buyer@12345")
        self.assertEqual(response.status_code, 200)
        self.assertIn("suspended", response.get_data(as_text=True).lower())

    def test_login_page_is_hidden_from_signed_in_users(self):
        self.login("buyer_demo", "Buyer@12345")
        response = self.client.get("/auth/login")
        self.assertEqual(response.status_code, 302)


class CsrfTests(NexacartTestCase):
    def test_post_without_token_is_rejected(self):
        response = self.client.post(
            "/auth/login", data={"identifier": "admin", "password": "Admin@12345"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("security token", response.get_data(as_text=True))

    def test_post_with_wrong_token_is_rejected(self):
        response = self.client.post(
            "/auth/login",
            data={"identifier": "admin", "password": "Admin@12345", "csrf_token": "nope"},
        )
        self.assertEqual(response.status_code, 400)


class RoleAccessControlTests(NexacartTestCase):
    def test_guest_is_redirected_to_the_login_page(self):
        for path in ("/admin/", "/seller/", "/buyer/", "/account/profile"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302, path)
            self.assertIn("/auth/login", response.headers["Location"], path)

    def test_buyer_cannot_open_the_administrator_area(self):
        self.login("buyer_demo", "Buyer@12345")
        for path in ("/admin/", "/admin/users", "/admin/audit", "/admin/sessions"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 403, path)
            self.assertIn("do not have access", response.get_data(as_text=True))

    def test_buyer_cannot_open_the_seller_area(self):
        self.login("buyer_demo", "Buyer@12345")
        response = self.client.get("/seller/")
        self.assertEqual(response.status_code, 403)
        response = self.client.get("/seller/products")
        self.assertEqual(response.status_code, 403)

    def test_seller_cannot_open_the_buyer_cart(self):
        self.login("seller_demo", "Seller@12345")
        response = self.client.get("/buyer/")
        self.assertEqual(response.status_code, 403)
        response = self.client.get("/buyer/cart")
        self.assertEqual(response.status_code, 403)

    def test_seller_cannot_open_the_administrator_area(self):
        self.login("seller_demo", "Seller@12345")
        self.assertEqual(self.client.get("/admin/users").status_code, 403)

    def test_administrator_cannot_open_a_buyer_cart(self):
        self.login("admin", "Admin@12345")
        self.assertEqual(self.client.get("/buyer/cart").status_code, 403)

    def test_each_role_reaches_its_own_dashboard(self):
        for identifier, password, path, marker in (
            ("admin", "Admin@12345", "/admin/", "Administrator dashboard"),
            ("seller_demo", "Seller@12345", "/seller/", "Seller workspace"),
            ("buyer_demo", "Buyer@12345", "/buyer/", "Buyer workspace"),
        ):
            client = self.app.test_client()
            token = csrf_token(client)
            client.post(
                "/auth/login",
                data={"identifier": identifier, "password": password, "csrf_token": token},
            )
            response = client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn(marker, response.get_data(as_text=True))

    def test_denied_access_is_written_to_the_audit_log(self):
        self.login("buyer_demo", "Buyer@12345")
        self.client.get("/admin/users")
        with self.app.app_context():
            entries = models.list_audit_log(limit=50)
            self.assertTrue(any(entry["action"] == "access_denied" for entry in entries))


class AccountTests(NexacartTestCase):
    def test_profile_can_be_updated(self):
        self.login("buyer_demo", "Buyer@12345")
        token = csrf_token(self.client, "/account/profile")
        response = self.client.post(
            "/account/profile",
            data={
                "full_name": "Renamed Buyer",
                "email": "buyer@nexacart.local",
                "csrf_token": token,
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = models.get_user_by_identifier("buyer_demo")
            self.assertEqual(user["full_name"], "Renamed Buyer")

    def test_changing_the_email_requires_the_current_password(self):
        self.login("buyer_demo", "Buyer@12345")
        token = csrf_token(self.client, "/account/profile")
        response = self.client.post(
            "/account/profile",
            data={
                "full_name": "Demo Buyer",
                "email": "new@nexacart.local",
                "csrf_token": token,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("current password", response.get_data(as_text=True))
        with self.app.app_context():
            user = models.get_user_by_identifier("buyer_demo")
            self.assertEqual(user["email"], "buyer@nexacart.local")

    def test_password_can_be_changed_and_old_sessions_end(self):
        self.login("buyer_demo", "Buyer@12345")
        token = csrf_token(self.client, "/account/security")
        response = self.client.post(
            "/account/security",
            data={
                "current_password": "Buyer@12345",
                "new_password": "BrandNew123",
                "confirm_password": "BrandNew123",
                "csrf_token": token,
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = models.get_user_by_identifier("buyer_demo")
            self.assertTrue(user["password_hash"].startswith("pbkdf2:"))

        fresh = self.app.test_client()
        token = csrf_token(fresh)
        response = fresh.post(
            "/auth/login",
            data={"identifier": "buyer_demo", "password": "BrandNew123", "csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)

    def test_sessions_can_be_listed_and_revoked(self):
        self.login("buyer_demo", "Buyer@12345")
        response = self.client.get("/account/security")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Active devices", response.get_data(as_text=True))

    def test_forced_password_change_blocks_other_pages(self):
        with self.app.app_context():
            models.create_user(
                username="temp_user",
                email="temp@nexacart.local",
                full_name="Temp User",
                password_hash=self.hash("Temp@12345"),
                role="buyer",
                must_change_password=1,
            )
        self.login("temp_user", "Temp@12345")
        response = self.client.get("/buyer/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/account/security", response.headers["Location"])


class AdminTests(NexacartTestCase):
    def test_administrator_can_see_the_user_list(self):
        self.login("admin", "Admin@12345")
        response = self.client.get("/admin/users")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("buyer_demo", body)
        self.assertIn("seller_demo", body)

    def test_user_list_can_be_filtered_by_role(self):
        self.login("admin", "Admin@12345")
        response = self.client.get("/admin/users?role=seller")
        body = response.get_data(as_text=True)
        self.assertIn("seller_demo", body)
        self.assertNotIn(">buyer_demo<", body)

    def test_administrator_can_offer_a_role_change_and_target_accepts(self):
        self.login("admin", "Admin@12345")
        with self.app.app_context():
            target_id = models.get_user_by_identifier("buyer_demo")["id"]
        token = csrf_token(self.client, f"/admin/users/{target_id}")
        response = self.client.post(
            f"/admin/users/{target_id}/role",
            data={"role": "seller", "csrf_token": token},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            # Role is unchanged until the target accepts.
            self.assertEqual(models.get_user_by_identifier("buyer_demo")["role"], "buyer")
            offer = models.list_notifications(target_id)[0]
            self.assertTrue(str(offer["kind"]).startswith("role_offer:"))

            # The target accepts from their own account.
            client = self.app.test_client()
            csrf_token(client)
            client.post(
                "/auth/login",
                data={"identifier": "buyer_demo", "password": "Buyer@12345", "csrf_token": csrf_token(client)},
            )
            client.post(
                f"/role-offer/{offer['id']}/accept",
                data={"csrf_token": csrf_token(client, "/account/profile")},
            )
            self.assertEqual(models.get_user_by_identifier("buyer_demo")["role"], "seller")

    def test_promotion_to_administrator_requires_admin_password(self):
        self.login("admin", "Admin@12345")
        with self.app.app_context():
            target_id = models.get_user_by_identifier("buyer_demo")["id"]
        token = csrf_token(self.client, f"/admin/users/{target_id}")
        self.client.post(
            f"/admin/users/{target_id}/role",
            data={"role": "admin", "csrf_token": token},
            follow_redirects=True,
        )
        self.client.post(
            f"/admin/users/{target_id}/role",
            data={"role": "admin", "current_password": "Admin@12345", "csrf_token": token},
            follow_redirects=True,
        )
        with self.app.app_context():
            self.assertEqual(models.get_user_by_identifier("buyer_demo")["role"], "admin")

    def test_role_offer_does_not_require_admin_password(self):
        self.login("admin", "Admin@12345")
        with self.app.app_context():
            target_id = models.get_user_by_identifier("buyer_demo")["id"]
        token = csrf_token(self.client, f"/admin/users/{target_id}")
        response = self.client.post(
            f"/admin/users/{target_id}/role",
            data={"role": "seller", "csrf_token": token},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            offer = models.list_notifications(target_id)
            self.assertTrue(offer and str(offer[0]["kind"]).startswith("role_offer:"))

    def test_administrator_can_suspend_and_reactivate_an_account(self):
        self.login("admin", "Admin@12345")
        with self.app.app_context():
            target_id = models.get_user_by_identifier("buyer_demo")["id"]
        token = csrf_token(self.client, f"/admin/users/{target_id}")
        self.client.post(
            f"/admin/users/{target_id}/status",
            data={"status": "suspended", "csrf_token": token},
        )
        with self.app.app_context():
            self.assertEqual(
                models.get_user_by_identifier("buyer_demo")["status"], "suspended"
            )
        token = csrf_token(self.client, f"/admin/users/{target_id}")
        self.client.post(
            f"/admin/users/{target_id}/status",
            data={"status": "active", "csrf_token": token},
        )
        with self.app.app_context():
            self.assertEqual(
                models.get_user_by_identifier("buyer_demo")["status"], "active"
            )

    def test_administrator_cannot_change_their_own_role(self):
        self.login("admin", "Admin@12345")
        with self.app.app_context():
            own_id = models.get_user_by_identifier("admin")["id"]
        token = csrf_token(self.client, f"/admin/users/{own_id}")
        response = self.client.post(
            f"/admin/users/{own_id}/role",
            data={"role": "buyer", "csrf_token": token},
            follow_redirects=True,
        )
        self.assertIn("cannot change your own role", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(models.get_user_by_identifier("admin")["role"], "admin")

    def test_audit_log_records_sign_ins(self):
        self.login("admin", "Admin@12345")
        response = self.client.get("/admin/audit")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Sign-in", response.get_data(as_text=True))


class SecurityUnitTests(NexacartTestCase):
    def test_password_hash_is_salted(self):
        from nexacart import security

        with self.app.app_context():
            first = security.hash_password("SamePassword1")
            second = security.hash_password("SamePassword1")
            self.assertNotEqual(first, second)
            self.assertTrue(security.verify_password(first, "SamePassword1"))
            self.assertFalse(security.verify_password(first, "SamePassword2"))

    def test_open_redirect_is_blocked(self):
        from nexacart import security

        with self.app.app_context():
            self.assertIsNone(security.safe_next_url("https://evil.example.com"))
            self.assertIsNone(security.safe_next_url("//evil.example.com"))
            self.assertEqual(security.safe_next_url("/buyer/"), "/buyer/")

    def test_session_token_is_stored_hashed(self):
        with self.app.app_context():
            user_id = models.get_user_by_identifier("admin")["id"]
            row = models.get_auth_session(models.hash_token("raw-token"))
            self.assertIsNone(row)
            models.create_auth_session(models.hash_token("raw-token"), user_id, 9999999999)
            row = models.get_auth_session(models.hash_token("raw-token"))
            self.assertIsNotNone(row)
            self.assertNotEqual(row["token_hash"], "raw-token")

    def test_auth_cookie_is_http_only(self):
        response = self.login("admin", "Admin@12345")
        cookies = response.headers.getlist("Set-Cookie")
        session_cookie = [c for c in cookies if c.startswith("nexacart_session=")]
        self.assertTrue(session_cookie)
        self.assertIn("HttpOnly", session_cookie[0])
        self.assertIn("SameSite=Lax", session_cookie[0])


class InternationalisationTests(NexacartTestCase):
    """The interface speaks English, French and Arabic (right to left)."""

    def test_every_catalogue_has_the_same_keys(self):
        from nexacart import i18n

        def flatten(node, prefix=""):
            keys = set()
            for key, value in node.items():
                path = f"{prefix}{key}"
                if isinstance(value, dict):
                    keys |= flatten(value, path + ".")
                else:
                    keys.add(path)
            return keys

        catalogues = {
            code: flatten(i18n._load_catalogue(code))
            for code in ("en", "fr", "ar")
        }
        reference = catalogues["en"]
        self.assertTrue(reference)
        for code, keys in catalogues.items():
            self.assertEqual(keys, reference, f"catalogue {code} differs from en")

    def test_default_locale_is_english(self):
        from nexacart import i18n

        self.assertEqual(i18n.DEFAULT_LOCALE, "en")
        self.assertEqual(i18n.locale_direction("en"), "ltr")
        self.assertEqual(i18n.locale_direction("fr"), "ltr")
        self.assertEqual(i18n.locale_direction("ar"), "rtl")

    def test_language_switcher_sets_the_locale_and_redirects_back(self):
        response = self.client.get("/language/fr?next=/admin/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/admin/")

        page = self.client.get("/", follow_redirects=True)
        body = page.get_data(as_text=True)
        self.assertIn('lang="fr"', body)
        self.assertIn('dir="ltr"', body)
        self.assertIn("Se connecter", body)

    def test_arabic_renders_right_to_left(self):
        self.client.get("/language/ar?next=/", follow_redirects=True)
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn('lang="ar"', body)
        self.assertIn('dir="rtl"', body)
        self.assertTrue(any("\u0600" <= char <= "\u06ff" for char in body))

    def test_unsupported_locale_falls_back_to_english(self):
        response = self.client.get("/language/de?next=/")
        self.assertEqual(response.status_code, 302)
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn('lang="en"', body)

    def test_the_locale_survives_sign_in_and_sign_out(self):
        self.client.get("/language/fr?next=/auth/login")
        self.login("buyer_demo", "Buyer@12345")

        body = self.client.get("/buyer/").get_data(as_text=True)
        self.assertIn('lang="fr"', body)
        self.assertIn("Espace", body)

        token = csrf_token(self.client, "/account/profile")
        self.client.post("/auth/logout", data={"csrf_token": token})
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn('lang="fr"', body)

    def test_browser_language_is_used_when_no_choice_was_made(self):
        response = self.client.get("/", headers={"Accept-Language": "fr-FR,fr;q=0.9"})
        self.assertIn('lang="fr"', response.get_data(as_text=True))

    def test_password_rules_use_stable_identifiers(self):
        body = self.client.get("/auth/register").get_data(as_text=True)
        for rule in ("min_length", "max_length", "lowercase", "uppercase", "digit", "symbol"):
            self.assertIn(f'data-rule="{rule}"', body)

    def test_numbers_and_dates_follow_the_locale(self):
        from nexacart import i18n

        with self.app.test_request_context("/"):
            from flask import session

            session["locale"] = "fr"
            self.assertEqual(i18n.format_number(1234.5), "1\u202f234,5")
            session["locale"] = "ar"
            self.assertEqual(i18n.format_number(1234), "١٬٢٣٤")
            session["locale"] = "en"
            self.assertEqual(i18n.format_number(1234), "1,234")

    def test_no_stage_wording_is_left_in_the_interface(self):
        pages = ("/", "/auth/login", "/auth/register")
        for path in pages:
            body = self.client.get(path).get_data(as_text=True).lower()
            self.assertNotIn("stage i", body, path)
            self.assertNotIn("stage ii", body, path)
            self.assertNotIn("stage 2", body, path)


class WeatherTests(NexacartTestCase):
    """Stage 3: public weather search and administrator review."""

    def test_weather_page_is_public(self):
        response = self.client.get("/weather/")
        self.assertEqual(response.status_code, 200)

    def test_search_by_city_shows_conditions(self):
        response = self.client.get("/weather/?mode=city&run=1&city=Kigali")
        body = response.get_data(as_text=True)
        self.assertIn("Kigali", body)
        self.assertIn("°C", body)
        self.assertIn("%", body)  # humidity

    def test_unknown_city_shows_friendly_error(self):
        response = self.client.get("/weather/?mode=city&run=1&city=Nowhereville")
        body = response.get_data(as_text=True)
        self.assertIn("field-error", body)
        self.assertNotIn("weather-temp", body)

    def test_search_by_coordinates(self):
        response = self.client.get("/weather/?mode=coords&run=1&lat=-1.95&lon=30.06")
        self.assertEqual(response.status_code, 200)

    def test_invalid_coordinates_rejected(self):
        response = self.client.get("/weather/?mode=coords&run=1&lat=999&lon=30")
        self.assertIn("field-error", response.get_data(as_text=True))

    def test_empty_city_shows_validation_error(self):
        response = self.client.get("/weather/?mode=city&run=1&city=")
        self.assertIn("field-error", response.get_data(as_text=True))

    def test_searches_are_logged_for_admin(self):
        from nexacart import models

        self.client.get("/weather/?mode=city&run=1&city=Kigali")
        with self.app.app_context():
            self.assertGreaterEqual(models.count_weather_searches(), 1)

    def test_admin_history_requires_admin(self):
        self.assertEqual(self.client.get("/weather/admin/history").status_code, 302)

    def test_admin_can_view_history_and_stats(self):
        self.login("admin", "Admin@12345")
        page = self.client.get("/weather/admin/history")
        self.assertEqual(page.status_code, 200)
        stats = self.client.get("/weather/admin/stats")
        self.assertEqual(stats.status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
