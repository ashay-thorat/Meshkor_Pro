from django.conf import settings
from django.db import models


class RunSignoff(models.Model):
    """A reviewer's sign-off of one pipeline run.

    Tied to the SHA-256 of comparison.parquet, so a new pipeline run is a draft
    again until someone signs it off.
    """
    comparison_sha256 = models.CharField(max_length=64, db_index=True)
    run_generated_at = models.CharField(max_length=40)
    signed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    signed_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-signed_at"]

    def __str__(self):
        return f"{self.run_generated_at} signed by {self.signed_by} at {self.signed_at:%Y-%m-%d %H:%M}"
