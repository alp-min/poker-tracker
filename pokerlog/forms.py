from django import forms
from .models import Entry, Profile, Venue
from django.utils import timezone


class EntryForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if not self.initial.get("played_at"):
            dt = timezone.localtime(timezone.now())
            self.initial["played_at"] = dt.strftime("%Y-%m-%dT%H:%M")
        if user is not None:
            self.fields["venue"].queryset = Venue.objects.filter(user=user)
        self.fields["venue"].required = False
        self.fields["venue"].empty_label = "No venue / unknown"

    class Meta:
        model  = Entry
        fields = [
            "title",
            "played_at",
            "format",
            "currency",
            "venue",
            "buy_in",
            "cash_out",
            "duration_minutes",
            "table_count",
            "mood",
            "notes",
        ]
        widgets = {
            "title":     forms.TextInput(attrs={"placeholder": "e.g. Monday night tourney (optional)"}),
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


class VenueForm(forms.ModelForm):
    class Meta:
        model  = Venue
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Nico's game", "maxlength": 100}),
        }


class ProfileForm(forms.ModelForm):
    class Meta:
        model  = Profile
        fields = ["starting_bankroll", "max_buyin_pct", "stop_loss_buyins", "default_currency"]
