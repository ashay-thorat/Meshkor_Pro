"""Create the reviewer and viewer groups. Safe to run more than once."""
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the reviewer and viewer groups."

    def handle(self, **_):
        for g in ("reviewer", "viewer"):
            _, made = Group.objects.get_or_create(name=g)
            self.stdout.write(f"{g}: {'created' if made else 'exists'}")
