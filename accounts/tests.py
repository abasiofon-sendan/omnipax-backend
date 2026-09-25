from django.test import TestCase
from rest_framework.test import APIClient

from .models import OTPVerification, User


class AuthFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signup_payload = {
            "email": "rider@example.com",
            "phone_number": "+2348012345678",
            "password": "strongpass1",
        }

    def signup(self, payload=None):
        return self.client.post(
            "/api/auth/signup/", payload or self.signup_payload, format="json"
        )

    def latest_code(self, email):
        return OTPVerification.objects.filter(email=email).latest("created_at").code

    def test_signup_creates_unverified_user_and_otp(self):
        res = self.signup()
        self.assertEqual(res.status_code, 201)
        user = User.objects.get(email="rider@example.com")
        self.assertFalse(user.is_verified)
        self.assertTrue(user.check_password("strongpass1"))
        self.assertEqual(OTPVerification.objects.filter(email=user.email).count(), 1)

    def test_login_blocked_until_verified(self):
        self.signup()
        res = self.client.post(
            "/api/auth/login/",
            {"phone_number": "+2348012345678", "password": "strongpass1"},
            format="json",
        )
        self.assertEqual(res.status_code, 403)

    def test_verify_then_login(self):
        self.signup()
        code = self.latest_code("rider@example.com")
        res = self.client.post(
            "/api/auth/otp/verify/",
            {"email": "rider@example.com", "code": code},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.data)
        self.assertTrue(User.objects.get(email="rider@example.com").is_verified)

        res = self.client.post(
            "/api/auth/login/",
            {"phone_number": "+2348012345678", "password": "strongpass1"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)

    def test_login_wrong_password(self):
        self.signup()
        User.objects.filter(email="rider@example.com").update(is_verified=True)
        res = self.client.post(
            "/api/auth/login/",
            {"phone_number": "+2348012345678", "password": "wrongpass1"},
            format="json",
        )
        self.assertEqual(res.status_code, 401)

    def test_wrong_code_rejected_and_attempts_capped(self):
        self.signup()
        url = "/api/auth/otp/verify/"
        payload = {"email": "rider@example.com", "code": "000000"}
        for _ in range(5):
            res = self.client.post(url, payload, format="json")
            self.assertEqual(res.status_code, 400)
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, 429)

    def test_otp_request_rate_limited(self):
        self.signup()  # 1st OTP
        url = "/api/auth/otp/request/"
        payload = {"email": "rider@example.com"}
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 200)
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 200)
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, 429)

    def test_duplicate_signup_rejected(self):
        self.assertEqual(self.signup().status_code, 201)
        res = self.signup()
        self.assertEqual(res.status_code, 400)
