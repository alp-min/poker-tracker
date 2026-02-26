from django.test import TestCase

# Create your tests here.

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render

from .models import Entry


@login_required
def dashboard(request):
    entries = Entry.objects.filter(user=request.user).order_by("played_at")

    # totals
    total_buy_in = sum((e.buy_in for e in entries), start=0)
    total_rake = sum((e.rake for e in entries), start=0)
    total_cash_out = sum((e.cash_out for e in entries), start=0)
    total_profit = sum((e.profit for e in entries), start=0)

    # bankroll curve (cumulative profit)
    labels = []
    bankroll = []
    running = 0
    for e in entries:
        running += float(e.profit)
        labels.append(e.played_at.strftime("%d %b"))
        bankroll.append(running)

    context = {
        "entries": entries,
        "total_profit": total_profit,
        "total_buy_in": total_buy_in,
        "total_rake": total_rake,
        "total_cash_out": total_cash_out,
        "labels": labels,
        "bankroll": bankroll,
    }
    return render(request, "pokerlog/dashboard.html", context)