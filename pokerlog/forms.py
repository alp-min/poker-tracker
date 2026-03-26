from django import forms
from .models import Entry, Profile
from django.utils import timezone


class EntryForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.initial.get("played_at"):
            dt = timezone.localtime(timezone.now())
            self.initial["played_at"] = dt.strftime("%Y-%m-%dT%H:%M")

    class Meta:
        model  = Entry
        fields = [
            "played_at",
            "format",
            "currency",
            "buy_in",
            "cash_out",
            "ev_profit",
            "duration_minutes",
            "table_count",
            "mood",
            "notes",
        ]
        # rake is intentionally excluded from the form going forward.
        # existing entries retain their rake value in profit calculations.
        widgets = {
            "played_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "notes":     forms.Textarea(attrs={"rows": 3}),
            "mood":      forms.Select(choices=[
                ("", "Select mood"),
                (1, "Tilted"),
                (5, "Neutral"),
                (9, "Calm"),
            ]),
            "currency":  forms.Select(attrs={"class": "currency-select"}),
        }


class ProfileForm(forms.ModelForm):
    class Meta:
        model  = Profile
        fields = ["starting_bankroll", "max_buyin_pct", "stop_loss_buyins", "default_currency"]
