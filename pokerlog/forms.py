from django import forms
from .models import Entry
from django.utils import timezone
from .models import Profile


class EntryForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.initial.get("played_at"):
            dt = timezone.localtime(timezone.now())
            self.initial["played_at"] = dt.strftime("%Y-%m-%dT%H:%M")
    class Meta:
        model = Entry
        fields = [
            "played_at",
            "format",
            "buy_in",
            "rake",
            "cash_out",
            "ev_profit",
            "duration_minutes",
            "table_count",
            "mood",
            "notes",
        ]
        widgets = {
            # nice datetime picker in modern browsers
            "played_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "mood": forms.Select(choices=[(i, i) for i in range(1, 11)]),
        }

class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["starting_bankroll", "max_buyin_pct", "stop_loss_buyins"]