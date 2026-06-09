from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class Profile(models.Model):
    CURRENCY_CHOICES = [("GBP", "£ GBP"), ("USD", "$ USD")]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    starting_bankroll = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    max_buyin_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=2.00,
        help_text="Max buy-in as % of bankroll (e.g. 2.00 = 2%)"
    )
    stop_loss_buyins = models.DecimalField(
        max_digits=6, decimal_places=2, default=5.00,
        help_text="Stop-loss in buy-ins per day/session block"
    )
    default_currency = models.CharField(
        max_length=3, choices=CURRENCY_CHOICES, default="GBP",
        help_text="Default currency for new sessions"
    )

    def __str__(self):
        return f"{self.user.username} profile"


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)


class Venue(models.Model):
    """A named game/venue preset — e.g. 'Nico's game', 'Monday Society'."""
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="venues")
    name       = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("user", "name")]

    def __str__(self):
        return self.name


class Entry(models.Model):
    FORMAT_CHOICES = [
        ("MTT", "MTT"),
        ("SNG", "SNG"),
        ("CASH", "Cash"),
    ]
    CURRENCY_CHOICES = [("GBP", "£ GBP"), ("USD", "$ USD")]

    user       = models.ForeignKey(User, on_delete=models.CASCADE)
    played_at  = models.DateTimeField()
    format     = models.CharField(max_length=10, choices=FORMAT_CHOICES, default="MTT")
    currency   = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="GBP")
    venue      = models.ForeignKey(
        Venue, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="entries"
    )

    buy_in   = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rake     = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cash_out = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    title            = models.CharField(max_length=100, blank=True, default="")
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    table_count      = models.PositiveIntegerField(null=True, blank=True)
    mood             = models.IntegerField(null=True, blank=True)
    notes            = models.TextField(blank=True, default="")
    created_at       = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Only auto-fill title on new entries where the user left it blank.
        # Never touches existing entries.
        if not self.title and self.played_at:
            self.title = self.played_at.strftime("%d %B %Y")
        super().save(*args, **kwargs)

    @property
    def total_cost(self):
        return self.buy_in + self.rake

    @property
    def profit(self):
        return self.cash_out - self.total_cost

    def __str__(self):
        return f"{self.user.username} {self.played_at.date()} {self.format} profit={self.profit}"
