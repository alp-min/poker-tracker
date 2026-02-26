from django.db import models
from django.contrib.auth.models import User


from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    starting_bankroll = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # risk settings
    max_buyin_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=2.00,
        help_text="Max buy-in as % of bankroll (e.g. 2.00 = 2%)"
    )
    stop_loss_buyins = models.DecimalField(
        max_digits=6, decimal_places=2, default=5.00,
        help_text="Stop-loss in buy-ins per day/session block"
    )

    def __str__(self):
        return f"{self.user.username} profile"

@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)



class Entry(models.Model):
    FORMAT_CHOICES = [
        ("MTT", "MTT"),
        ("SNG", "SNG"),
        ("CASH", "Cash"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    played_at = models.DateTimeField()

    format = models.CharField(max_length=10, choices=FORMAT_CHOICES, default="MTT")

    buy_in = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rake = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cash_out = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    ev_profit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Expected profit for this session"
    )

    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    table_count = models.PositiveIntegerField(null=True, blank=True)

    mood = models.IntegerField(null=True, blank=True)  # 1-10 (tilt indicator)
    notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def total_cost(self):
        return self.buy_in + self.rake

    @property
    def profit(self):
        return self.cash_out - self.total_cost

    def __str__(self):
        return f"{self.user.username} {self.played_at.date()} {self.format} profit={self.profit}"