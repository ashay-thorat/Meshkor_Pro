"""Login, logout, current user, and run sign-off."""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import data
from .models import RunSignoff
from .permissions import CanReview, CanView, roles_of


def _user_payload(user) -> dict:
    roles = roles_of(user)
    return {
        "username": user.username,
        "name": user.get_full_name() or user.username,
        "role": roles[0] if roles else None,
        "roles": roles,
        "can_review": "reviewer" in roles,
        "is_admin": "admin" in roles,
    }


def _client_ip(request) -> str:
    return request.META.get("REMOTE_ADDR", "")


@api_view(["GET"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def csrf(request):
    """Sets the CSRF cookie the login form needs."""
    return Response({"ok": True})


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    username = str(request.data.get("username", "")).strip()
    password = str(request.data.get("password", ""))
    key = f"login-fail:{username.lower()}:{_client_ip(request)}"
    fails = cache.get(key, 0)
    if fails >= settings.LOGIN_MAX_FAILURES:
        return Response({"error": "Too many failed attempts. Try again in 15 minutes."},
                        status=429)
    user = authenticate(request, username=username, password=password)
    if user is None or not roles_of(user):
        cache.set(key, fails + 1, settings.LOGIN_WINDOW_SECONDS)
        msg = ("Wrong username or password." if user is None
               else "This account has no role yet. Ask the admin to add one.")
        return Response({"error": msg}, status=400)
    cache.delete(key)
    login(request, user)
    return Response(_user_payload(user))


@api_view(["POST"])
@permission_classes([AllowAny])
def logout_view(request):
    logout(request)
    return Response({"ok": True})


@api_view(["GET"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def me(request):
    if not roles_of(request.user):
        return Response({"error": "not logged in"}, status=401)
    return Response(_user_payload(request.user))


# ---------- sign-off ----------

def current_run() -> dict:
    info = data.run_info()
    return {"generated_at": info["generated_at"], "comparison_sha256": data.comparison_sha256()}


def signoff_status() -> dict:
    run = current_run()
    s = RunSignoff.objects.filter(comparison_sha256=run["comparison_sha256"]).first()
    return {
        **run,
        "signed": s is not None,
        "signed_by": (s.signed_by.get_full_name() or s.signed_by.username) if s else None,
        "signed_at": s.signed_at.isoformat(timespec="minutes") if s else None,
        "note": s.note if s else None,
    }


@api_view(["GET", "POST"])
@permission_classes([CanView])
def signoff(request):
    try:
        if request.method == "GET":
            return Response(signoff_status())
        if not CanReview().has_permission(request, None):
            return Response({"error": CanReview.message}, status=403)
        run = current_run()
        if not RunSignoff.objects.filter(comparison_sha256=run["comparison_sha256"]).exists():
            RunSignoff.objects.create(
                comparison_sha256=run["comparison_sha256"],
                run_generated_at=run["generated_at"],
                signed_by=request.user,
                note=str(request.data.get("note", ""))[:2000])
        return Response(signoff_status())
    except data.DataMissing as e:
        return Response({"error": str(e)}, status=503)
