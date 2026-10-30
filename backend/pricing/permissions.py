"""Roles.

  admin     Django superuser. Manages users in /admin. Can do everything.
  reviewer  group "reviewer". Can view, export, and sign off a pipeline run.
  viewer    group "viewer". Can view and export.

A client role (brokers / TPAs, finished report only) is planned for later.
"""
from rest_framework.permissions import BasePermission

VIEWER, REVIEWER = "viewer", "reviewer"


def roles_of(user) -> list[str]:
    if not user or not user.is_authenticated or not user.is_active:
        return []
    if user.is_superuser:
        return ["admin", REVIEWER, VIEWER]
    names = set(user.groups.values_list("name", flat=True))
    out = []
    if REVIEWER in names:
        out += [REVIEWER, VIEWER]
    elif VIEWER in names:
        out.append(VIEWER)
    return out


def primary_role(user) -> str | None:
    r = roles_of(user)
    return r[0] if r else None


class CanView(BasePermission):
    message = "Log in with a viewer, reviewer or admin account."

    def has_permission(self, request, view):
        return VIEWER in roles_of(request.user)


class CanReview(BasePermission):
    message = "Only a reviewer or admin can do this."

    def has_permission(self, request, view):
        return REVIEWER in roles_of(request.user)
