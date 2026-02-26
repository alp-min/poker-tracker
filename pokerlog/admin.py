from django.contrib import admin
from .models import Entry, Profile


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ("user", "played_at", "format", "buy_in", "cash_out", "ev_profit")
    list_filter = ("format", "played_at")
    search_fields = ("user__username", "notes")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "starting_bankroll", "max_buyin_pct", "stop_loss_buyins")