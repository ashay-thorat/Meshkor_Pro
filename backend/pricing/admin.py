from django.contrib import admin

from .models import RunSignoff

admin.site.site_header = "Infusion Drug Markup Audit — admin"


@admin.register(RunSignoff)
class RunSignoffAdmin(admin.ModelAdmin):
    list_display = ("run_generated_at", "signed_by", "signed_at", "comparison_sha256")
    readonly_fields = ("comparison_sha256", "run_generated_at", "signed_by", "signed_at")
