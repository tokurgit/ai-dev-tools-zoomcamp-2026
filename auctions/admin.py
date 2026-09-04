"""Admin registrations for the ``auctions`` app (#15).

``Listing`` and ``Notification`` are large, read-mostly tables, so both carry
``list_select_related`` to keep the changelist to a bounded number of queries
regardless of row count. ``Notification`` additionally disables "add" — rows
are only ever created by :func:`auctions.notifications.queue_notifications` —
and ships a "Resend selected" action that re-dispatches the ``failed`` rows in
a selection through :func:`auctions.notifications.dispatch_pending` (no
duplicate send logic here).
"""

from django.contrib import admin

from .models import Category, Listing, Notification, Region
from .notifications import dispatch_pending


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)
    ordering = ("id",)


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)
    ordering = ("id",)


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "region",
        "category",
        "state",
        "start_time",
        "end_time",
        "start_price",
    )
    list_filter = ("state", "type", "region", "category", "ownership_type")
    search_fields = ("title", "source_id")
    date_hierarchy = "end_time"
    readonly_fields = ("raw_hash", "source_id")
    list_select_related = ("region", "category")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "filter_profile",
        "listing",
        "alert_type",
        "status",
        "created_at",
        "sent_at",
    )
    list_filter = ("status", "alert_type", "created_at")
    search_fields = ("user__username", "listing__title")
    # The AC-mandated tuple is ("user", "filter_profile", "listing"); this adds
    # "filter_profile__user" too. Without it, rendering the "filter_profile"
    # column calls FilterProfile.__str__, which touches `filter_profile.user`
    # — a second-level relation the 3-tuple doesn't cover — reintroducing a
    # one-query-per-row N+1 that the "bounded queries" acceptance criterion
    # rules out. See the #15 issue comment for detail.
    list_select_related = ("user", "filter_profile", "filter_profile__user", "listing")
    readonly_fields = ("error",)
    actions = ("resend_selected",)

    def has_add_permission(self, request):
        return False

    @admin.action(description="Resend selected")
    def resend_selected(self, request, queryset):
        failed = queryset.filter(status=Notification.Status.FAILED)
        skipped = queryset.exclude(status=Notification.Status.FAILED).count()
        failed_ids = list(failed.values_list("pk", flat=True))

        dispatch_pending(queryset=failed)

        resent = Notification.objects.filter(
            pk__in=failed_ids, status=Notification.Status.SENT
        ).count()
        still_failing = Notification.objects.filter(
            pk__in=failed_ids, status=Notification.Status.FAILED
        ).count()

        self.message_user(
            request,
            f"{resent} resent, {still_failing} still failing, {skipped} skipped",
        )
