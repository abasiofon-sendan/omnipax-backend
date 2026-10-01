import hmac
import secrets

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import OTPVerification, User


def tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


def generate_otp_code():
    return f"{secrets.randbelow(1_000_000):06d}"


def send_otp_email(email, code):
    send_mail(
        subject="Your Omnipax verification code",
        message=f"Your Omnipax verification code is {code}. It expires in 5 minutes.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )


def create_and_send_otp(email):
    code = generate_otp_code()
    otp = OTPVerification.objects.create(email=email, code=code)
    send_otp_email(email, code)
    return otp


def otp_request_allowed(email):
    window_start = timezone.now() - timezone.timedelta(
        seconds=settings.OTP_REQUEST_WINDOW_SECONDS
    )
    recent = OTPVerification.objects.filter(
        email=email, created_at__gte=window_start
    ).count()
    return recent < settings.OTP_REQUEST_LIMIT


class SignupSerializer(serializers.Serializer):
    email = serializers.EmailField()
    phone_number = serializers.CharField(max_length=20)
    password = serializers.CharField(min_length=8, write_only=True)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Email is already registered.")
        return value

    def validate_phone_number(self, value):
        if User.objects.filter(phone_number=value).exists():
            raise serializers.ValidationError("Phone number is already registered.")
        return value


class OTPRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class OTPVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(min_length=6, max_length=6)


class LoginSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    password = serializers.CharField(write_only=True)


class SignupView(APIView):
    permission_classes = [AllowAny]
    serializer_class = SignupSerializer

    @extend_schema(
        request=SignupSerializer, responses=OpenApiTypes.OBJECT, tags=["auth"]
    )
    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            user = User.objects.create_user(
                phone_number=serializer.validated_data["phone_number"],
                email=serializer.validated_data["email"],
                password=serializer.validated_data["password"],
            )
            create_and_send_otp(user.email)
        return Response(
            {"id": str(user.id), "email": user.email, "detail": "OTP sent to email."},
            status=status.HTTP_201_CREATED,
        )


class OTPRequestView(APIView):
    permission_classes = [AllowAny]
    serializer_class = OTPRequestSerializer

    @extend_schema(
        request=OTPRequestSerializer, responses=OpenApiTypes.OBJECT, tags=["auth"]
    )
    def post(self, request):
        serializer = OTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        if not otp_request_allowed(email):
            return Response(
                {"detail": "Too many OTP requests. Try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        create_and_send_otp(email)
        return Response({"detail": "OTP sent to email."})


class OTPVerifyView(APIView):
    permission_classes = [AllowAny]
    serializer_class = OTPVerifySerializer

    @extend_schema(
        request=OTPVerifySerializer, responses=OpenApiTypes.OBJECT, tags=["auth"]
    )
    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        code = serializer.validated_data["code"]

        otp = (
            OTPVerification.objects.filter(email__iexact=email, is_used=False)
            .order_by("-created_at")
            .first()
        )
        if otp is None:
            return Response(
                {"detail": "No pending OTP for this email."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if otp.attempt_count >= settings.OTP_VERIFY_ATTEMPTS:
            return Response(
                {"detail": "Too many verification attempts. Request a new code."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        otp.attempt_count += 1
        otp.save(update_fields=["attempt_count"])

        if otp.is_expired or not hmac.compare_digest(otp.code, code):
            return Response(
                {"detail": "Invalid or expired code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            otp.is_used = True
            otp.save(update_fields=["is_used"])
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                return Response(
                    {"detail": "No account for this email."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            user.is_verified = True
            user.save(update_fields=["is_verified"])
        return Response({"detail": "Email verified.", **tokens_for_user(user)})


class LoginView(APIView):
    permission_classes = [AllowAny]
    serializer_class = LoginSerializer

    @extend_schema(
        request=LoginSerializer, responses=OpenApiTypes.OBJECT, tags=["auth"]
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request,
            phone_number=serializer.validated_data["phone_number"],
            password=serializer.validated_data["password"],
        )
        if user is None:
            return Response(
                {"detail": "Invalid phone number or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if not user.is_active:
            return Response(
                {"detail": "Account is disabled."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not user.is_verified:
            return Response(
                {"detail": "Email not verified. Verify the OTP first."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(tokens_for_user(user))
