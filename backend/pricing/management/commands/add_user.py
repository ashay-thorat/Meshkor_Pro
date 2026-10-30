"""Create or update a user with one role.

    python manage.py add_user anita --role reviewer
    python manage.py add_user ravi --role viewer --name "Ravi Kumar"
    python manage.py add_user vikram --role admin

The password is asked twice on screen (never passed on the command line).
"""
import getpass

from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

ROLES = ("admin", "reviewer", "viewer")


class Command(BaseCommand):
    help = "Create or update a user and set the role (admin, reviewer, viewer)."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--role", required=True, choices=ROLES)
        parser.add_argument("--name", default="", help="Full name, shown in sign-offs")
        parser.add_argument("--email", default="")

    def handle(self, username, role, name, email, **_):
        for g in ("reviewer", "viewer"):
            Group.objects.get_or_create(name=g)
        user, created = User.objects.get_or_create(username=username)
        pw1 = getpass.getpass("Password: ")
        pw2 = getpass.getpass("Password again: ")
        if pw1 != pw2:
            raise CommandError("Passwords do not match.")
        try:
            validate_password(pw1, user)
        except ValidationError as e:
            raise CommandError(" ".join(e.messages))
        user.set_password(pw1)
        if name:
            first, _, last = name.partition(" ")
            user.first_name, user.last_name = first, last
        if email:
            user.email = email
        user.is_active = True
        user.is_superuser = user.is_staff = role == "admin"
        user.save()
        user.groups.clear()
        if role in ("reviewer", "viewer"):
            user.groups.add(Group.objects.get(name=role))
        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if created else 'Updated'} {username} with role {role}."))
