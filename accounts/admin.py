"""Admin registrations for the ``accounts`` app (#15).

The custom ``User`` (issue #6) is a plain ``AbstractUser`` subclass with no
extra fields, so Django's own :class:`~django.contrib.auth.admin.UserAdmin`
registers against it unmodified — operators get user creation plus the
``is_staff`` / ``is_active`` controls it already ships.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import FilterProfile, User
from .summaries import summarize_criteria

admin.site.register(User, UserAdmin)


@admin.register(FilterProfile)
class FilterProfileAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "user",
        "delivery",
        "notify_new",
        "notify_change",
        "notify_deadline",
        "updated_at",
    )
    list_filter = ("delivery", "notify_new", "notify_deadline")
    search_fields = ("name", "user__username")
    readonly_fields = ("criteria_summary",)

    @admin.display(description="Criteria")
    def criteria_summary(self, obj):
        return summarize_criteria(obj.criteria)
