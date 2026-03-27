from django.contrib import admin
from .models import Entry, Profile, Venue


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ("user", "played_at", "format", "currency", "venue", "buy_in", "cash_out")
    list_filter = ("format", "played_at", "venue")
    search_fields = ("user__username", "notes")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "starting_bankroll", "max_buyin_pct", "stop_loss_buyins")


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "created_at")
    search_fields = ("user__username", "name")