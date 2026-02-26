from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import Entry, Profile
from .forms import EntryForm, ProfileForm
from collections import defaultdict
from datetime import timedelta
from django.core.paginator import Paginator
from django.db.models import Sum, Count, Avg, Max, Min, Q



def _to_float(x):
    return float(x) if x is not None else 0.0


@login_required
def dashboard(request):
    entries_qs = Entry.objects.filter(user=request.user)

    # --- Filters (table + chart) ---
    filter_format = request.GET.get("format", "ALL")
    filter_range = request.GET.get("range", "30")  # "7", "30", "90", "ALL"

    filtered_qs = entries_qs
    if filter_format != "ALL":
        filtered_qs = filtered_qs.filter(format=filter_format)

    if filter_range != "ALL":
        since = timezone.now() - timedelta(days=int(filter_range))
        filtered_qs = filtered_qs.filter(played_at__gte=since)



    # All-time dataset (risk/totals)
    entries = entries_qs.order_by("played_at")

    # Filtered datasets (chart + table)
    entries_for_chart = filtered_qs.order_by("played_at")
    entries_table = filtered_qs.order_by("-played_at")

    # Pagination on the filtered table
    paginator = Paginator(entries_table, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    # Preserve querystring without page
    querydict = request.GET.copy()
    querydict.pop("page", None)
    base_qs = querydict.urlencode()

    if request.method == "POST":
        form = EntryForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.user = request.user
            entry.save()
            return redirect("dashboard")
    else:
        form = EntryForm(initial=request.GET.dict())

    # Totals
    total_buy_in = sum((e.buy_in for e in entries), start=0)
    total_rake = sum((e.rake for e in entries), start=0)
    total_cash_out = sum((e.cash_out for e in entries), start=0)
    total_profit = sum((e.profit for e in entries), start=0)

    format_stats = defaultdict(lambda: {
        "buy_in": 0.0,
        "profit": 0.0,
        "entries": 0,
    })

    for e in entries:
        fmt = e.format
        format_stats[fmt]["buy_in"] += float(e.buy_in or 0)
        format_stats[fmt]["profit"] += float(e.profit or 0)
        format_stats[fmt]["entries"] += 1

    format_summary = []

    for fmt, stats in format_stats.items():
        roi = 0
        if stats["buy_in"] > 0:
            roi = (stats["profit"] / stats["buy_in"]) * 100

        format_summary.append({
            "format": fmt,
            "entries": stats["entries"],
            "profit": round(stats["profit"], 2),
            "roi": round(roi, 2),
        })

    # Curves
    labels = []
    bankroll = []
    ev_line = []

    running = 0.0
    ev_running = 0.0

    # Downswing metrics
    peak = 0.0
    max_drawdown = 0.0  # most negative
    current_drawdown = 0.0
    peak_index = None
    trough_index = None

    # Longest breakeven stretch (since last peak)
    longest_breakeven_len = 0
    longest_breakeven_start = None
    longest_breakeven_end = None

    last_peak_pos = 0  # index of last time we hit a new peak
    last_peak_value = 0.0

    # Tilt warnings
    warnings = []
    previous = None

    for i, e in enumerate(entries_for_chart):
        p = _to_float(e.profit)
        running += p
        bankroll.append(running)

        if e.ev_profit is not None:
            ev_running += _to_float(e.ev_profit)
        ev_line.append(ev_running)

        labels.append(e.played_at.strftime("%d %b"))

        # Update peak/drawdown
        if running >= peak:
            # new peak
            peak = running
            peak_index = i
            last_peak_pos = i
            last_peak_value = peak
        dd = running - peak  # <= 0
        if dd < max_drawdown:
            max_drawdown = dd
            trough_index = i
        current_drawdown = dd

        # Longest breakeven stretch: time since last peak while still below peak
        breakeven_len = i - last_peak_pos
        if running < last_peak_value and breakeven_len > longest_breakeven_len:
            longest_breakeven_len = breakeven_len
            longest_breakeven_start = last_peak_pos
            longest_breakeven_end = i

        # --- Tilt flags (simple heuristics) ---
        if previous is not None:
            prev_profit = _to_float(previous.profit)
            prev_buyin = _to_float(previous.buy_in)
            buyin = _to_float(e.buy_in)
            duration = e.duration_minutes or 0
            prev_duration = previous.duration_minutes or 0

            # Rule A: buy-in jump after a loss
            if prev_profit < 0 and prev_buyin > 0 and buyin >= 2.0 * prev_buyin:
                warnings.append({
                    "played_at": e.played_at,
                    "rule": "Buy-in jump after loss",
                    "detail": f"Prev buy-in {prev_buyin:.2f} → now {buyin:.2f}"
                })

            # Rule B: unusually long session after a loss (only if you track duration)
            if prev_profit < 0 and prev_duration > 0 and duration >= 1.5 * prev_duration and duration >= 90:
                warnings.append({
                    "played_at": e.played_at,
                    "rule": "Long session after loss",
                    "detail": f"Prev {prev_duration}m → now {duration}m"
                })

            # Rule C: mood drop (if you use mood 1–10)
            if previous.mood is not None and e.mood is not None and e.mood <= previous.mood - 3:
                warnings.append({
                    "played_at": e.played_at,
                    "rule": "Mood drop",
                    "detail": f"{previous.mood} → {e.mood}"
                })

        previous = e


    
    # --- Bankroll settings + risk flags ---
    profile, _ = Profile.objects.get_or_create(user=request.user)

    starting_bankroll = float(profile.starting_bankroll)
    current_bankroll = starting_bankroll + running  # running is your cumulative profit

    max_buyin_amount = (float(profile.max_buyin_pct) / 100.0) * max(current_bankroll, 0)
    recommended_max_buyin = round(max_buyin_amount, 2)

    risk_flags = []

    # --- Daily stop-loss (in buy-ins) ---
    today = timezone.localdate()

    today_qs = entries.filter(played_at__date=today)
    today_entries = list(today_qs)
    today_profit = sum(_to_float(e.profit) for e in today_entries)

    if len(today_entries) > 0:
        buyin_basis = sum(_to_float(e.buy_in) for e in today_entries) / len(today_entries)
    elif len(entries) > 0:
        buyin_basis = sum(_to_float(e.buy_in) for e in entries) / len(entries)
    else:
        buyin_basis = 0.0

    stop_loss_limit = float(profile.stop_loss_buyins) * buyin_basis

    stop_loss_triggered = False
    if buyin_basis > 0 and today_profit <= -stop_loss_limit:
        stop_loss_triggered = True
        risk_flags.append(
            f"STOP-LOSS HIT today: P/L £{today_profit:.2f} vs limit -£{stop_loss_limit:.2f}"
        )

    # Rule 1: Latest buy-in too big for current bankroll
    if len(entries) > 0 and current_bankroll > 0:
        latest = entries.last()
        latest_buyin = float(latest.buy_in)

        max_allowed = float(profile.max_buyin_pct) / 100.0 * current_bankroll
        if latest_buyin > max_allowed:
            risk_flags.append(
                f"Latest buy-in £{latest_buyin:.2f} exceeds your {float(profile.max_buyin_pct):.2f}% limit "
                f"(max £{max_allowed:.2f})."
            )

    # Rule 2: Deep downswing vs average buy-in (rough guidance)
    if len(entries) >= 5:
        avg_buyin = sum(float(e.buy_in) for e in entries) / len(entries)
        if avg_buyin > 0 and abs(current_drawdown) > 20 * avg_buyin:
            risk_flags.append(
                f"Deep downswing: current drawdown £{current_drawdown:.2f} is > 20x your avg buy-in (£{avg_buyin:.2f}). "
                f"Consider moving down."
            )

    # Friendly text for dates in metrics
    def idx_to_date(idx):
        if idx is None or idx < 0 or idx >= len(entries):
            return None
        return entries[idx].played_at.strftime("%d %b %Y")
    
    today = timezone.localdate()
    start_of_week = today - timedelta(days=today.weekday())

    week_entries = entries.filter(played_at__date__gte=start_of_week)

    week_profit = sum(float(e.profit or 0) for e in week_entries)
    week_buyin = sum(float(e.buy_in or 0) for e in week_entries)

    week_roi = 0
    if week_buyin > 0:
        week_roi = (week_profit / week_buyin) * 100

    # --- Filtered performance summary (matches table/chart filters) ---
    filtered_entries = list(filtered_qs)  # small dataset typically; OK for now

    def calc_profit(e):
        return float(e.cash_out or 0) - float(e.buy_in or 0) - float(e.rake or 0)

    profits = [calc_profit(e) for e in filtered_entries]

    fmt_profit = defaultdict(float)
    fmt_buyin = defaultdict(float)

    for e, p in zip(filtered_entries, profits):
        fmt_profit[e.format] += p
        fmt_buyin[e.format] += float(e.buy_in or 0)

    format_labels = sorted(fmt_profit.keys())
    format_profit = [round(fmt_profit[f], 2) for f in format_labels]
    format_roi = [
        round((fmt_profit[f] / fmt_buyin[f] * 100) if fmt_buyin[f] else 0.0, 2)
        for f in format_labels
    ]


    filtered_count = len(filtered_entries)
    filtered_buyin = sum(float(e.buy_in or 0) for e in filtered_entries)
    filtered_profit = sum(profits)

    filtered_roi = (filtered_profit / filtered_buyin * 100) if filtered_buyin > 0 else 0.0

    wins = sum(1 for p in profits if p > 0)
    filtered_winrate = (wins / filtered_count * 100) if filtered_count else 0.0

    filtered_biggest_win = max(profits) if profits else 0.0
    filtered_biggest_loss = min(profits) if profits else 0.0
    filtered_avg_profit = (filtered_profit / filtered_count) if filtered_count else 0.0

    filtered_minutes = sum(int(e.duration_minutes or 0) for e in filtered_entries)
    filtered_hours = filtered_minutes / 60 if filtered_minutes else 0.0
    filtered_hourly = (filtered_profit / filtered_hours) if filtered_hours else 0.0


    context = {
        "entries": entries,
        "total_profit": total_profit,
        "total_buy_in": total_buy_in,
        "total_rake": total_rake,
        "total_cash_out": total_cash_out,
        "labels": labels,
        "bankroll": bankroll,
        "ev_line": ev_line,
        "form": form,

        "max_drawdown": max_drawdown,
        "current_drawdown": current_drawdown,
        "peak_date": idx_to_date(peak_index),
        "trough_date": idx_to_date(trough_index),
        "longest_breakeven_len": longest_breakeven_len,
        "longest_breakeven_start": idx_to_date(longest_breakeven_start),
        "longest_breakeven_end": idx_to_date(longest_breakeven_end),
        "recommended_max_buyin": recommended_max_buyin,
        "today_profit": today_profit,
        "buyin_basis": buyin_basis,
        "stop_loss_limit": stop_loss_limit,
        "stop_loss_triggered": stop_loss_triggered,
        
        "profile": profile,
        "starting_bankroll": starting_bankroll,
        "current_bankroll": current_bankroll,
        "risk_flags": risk_flags,
        "context_entries": page_obj.object_list,
        "page_obj": page_obj,
        "format_summary": format_summary,

        "week_profit": round(week_profit, 2),
        "week_roi": round(week_roi, 2),

        "warnings": warnings[:20],  # cap
        "base_qs": base_qs,
        
        "filter_format": filter_format,
        "filter_range": filter_range,

        "filtered_count": filtered_count,
        "filtered_buyin": round(filtered_buyin, 2),
        "filtered_profit": round(filtered_profit, 2),
        "filtered_roi": round(filtered_roi, 2),
        "filtered_winrate": round(filtered_winrate, 1),
        "filtered_hours": round(filtered_hours, 1),
        "filtered_hourly": round(filtered_hourly, 2),
        "filtered_avg_profit": round(filtered_avg_profit, 2),
        "filtered_biggest_win": round(filtered_biggest_win, 2),
        "filtered_biggest_loss": round(filtered_biggest_loss, 2),

        "format_labels": format_labels,
        "format_profit": format_profit,
        "format_roi": format_roi,
        "filtered_avg_buyin": round((filtered_buyin / filtered_count) if filtered_count else 0.0, 2),

    }

    return render(request, "pokerlog/dashboard.html", context)

@login_required
def duplicate_last(request):
    last = Entry.objects.filter(user=request.user).order_by("-played_at").first()
    if not last:
        return redirect("dashboard")

    # Build query params to prefill the dashboard form
    data = {
        "played_at": timezone.localtime(timezone.now()).strftime("%Y-%m-%dT%H:%M"),
        "format": last.format,
        "buy_in": last.buy_in,
        "rake": last.rake,
        "cash_out": 0,
        "ev_profit": last.ev_profit,
        "mood": last.mood,
        "notes": "",
    }

    from urllib.parse import urlencode
    return redirect(f"/?{urlencode(data)}")


@login_required
def settings_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = ProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            return redirect("dashboard")
    else:
        form = ProfileForm(instance=profile)

    return render(request, "pokerlog/settings.html", {"form": form})

@login_required
def export_csv(request):
    entries = Entry.objects.filter(user=request.user).order_by("played_at")  # full dataset for analytics/risk

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="poker_entries.csv"'

    # manual CSV writing (no extra deps)
    header = "played_at,format,buy_in,rake,cash_out,profit,ev_profit,duration_minutes,table_count,mood,notes\n"
    response.write(header)

    for e in entries:
        # escape quotes in notes
        notes = (e.notes or "").replace('"', '""')
        line = (
            f'{e.played_at.isoformat()},'
            f'{e.format},'
            f'{e.buy_in},'
            f'{e.rake},'
            f'{e.cash_out},'
            f'{e.profit},'
            f'{e.ev_profit if e.ev_profit is not None else ""},'
            f'{e.duration_minutes if e.duration_minutes is not None else ""},'
            f'{e.table_count if e.table_count is not None else ""},'
            f'{e.mood if e.mood is not None else ""},'
            f'"{notes}"\n'
        )
        response.write(line)

    return response


@login_required
@require_http_methods(["GET", "POST"])
def entry_edit(request, pk):
    entry = get_object_or_404(Entry, pk=pk, user=request.user)

    form = EntryForm(request.POST or None, instance=entry)
    if request.method == "POST" and form.is_valid():
        updated = form.save(commit=False)
        updated.user = request.user  # keep ownership pinned
        updated.save()
        return redirect("dashboard")

    return render(request, "pokerlog/entry_edit.html", {"form": form, "entry": entry})


@login_required
@require_http_methods(["GET", "POST"])
def entry_delete(request, pk):
    entry = get_object_or_404(Entry, pk=pk, user=request.user)

    if request.method == "POST":
        entry.delete()
        return redirect("dashboard")

    return render(request, "pokerlog/entry_delete.html", {"entry": entry})

@login_required
def analytics(request):
    from collections import defaultdict
    import math

    entries_qs = Entry.objects.filter(user=request.user).order_by("played_at")
    entries = list(entries_qs)

    if not entries:
        return render(request, "pokerlog/analytics.html", {"no_data": True})

    def calc_profit(e):
        return float(e.cash_out or 0) - float(e.buy_in or 0) - float(e.rake or 0)

    profits = [calc_profit(e) for e in entries]
    n = len(profits)

    # ── ITM% ─────────────────────────────────────────────────────────────────
    itm_stats = {}
    for fmt in ("MTT", "SNG"):
        fmt_entries = [e for e in entries if e.format == fmt]
        if fmt_entries:
            itm_count = sum(1 for e in fmt_entries if float(e.cash_out or 0) > 0)
            itm_stats[fmt] = {
                "sessions": len(fmt_entries),
                "itm":      itm_count,
                "itm_pct":  round(itm_count / len(fmt_entries) * 100, 1),
            }

    # ── Streaks ───────────────────────────────────────────────────────────────
    longest_win = longest_loss = temp_win = temp_loss = 0
    for p in profits:
        if p > 0:
            temp_win += 1; temp_loss = 0
            longest_win = max(longest_win, temp_win)
        elif p < 0:
            temp_loss += 1; temp_win = 0
            longest_loss = max(longest_loss, temp_loss)
        else:
            temp_win = temp_loss = 0

    streak_val = 0; streak_type = None
    for p in reversed(profits):
        if p > 0:
            if streak_type is None: streak_type = "W"
            if streak_type == "W": streak_val += 1
            else: break
        elif p < 0:
            if streak_type is None: streak_type = "L"
            if streak_type == "L": streak_val += 1
            else: break
        else:
            break

    streak_info = {
        "current_val":  streak_val,
        "current_type": streak_type,
        "longest_win":  longest_win,
        "longest_loss": longest_loss,
    }

    # ── Mood ─────────────────────────────────────────────────────────────────
    mood_buckets = defaultdict(lambda: {"profits": [], "count": 0})
    for e, p in zip(entries, profits):
        if e.mood is not None:
            m = int(e.mood)
            mood_buckets[m]["profits"].append(p)
            mood_buckets[m]["count"] += 1

    mood_data = []
    for m in sorted(mood_buckets.keys()):
        b = mood_buckets[m]
        avg_p = sum(b["profits"]) / len(b["profits"])
        mood_data.append({"mood": m, "avg_profit": round(avg_p, 2), "sessions": b["count"]})

    mood_labels        = [d["mood"] for d in mood_data]
    mood_profits_chart = [d["avg_profit"] for d in mood_data]

    mood_groups = {"Low (1-4)": [], "Mid (5-7)": [], "High (8-10)": []}
    for e, p in zip(entries, profits):
        if e.mood is not None:
            m = int(e.mood)
            if m <= 4:   mood_groups["Low (1-4)"].append(p)
            elif m <= 7: mood_groups["Mid (5-7)"].append(p)
            else:        mood_groups["High (8-10)"].append(p)

    mood_group_data = []
    for label, plist in mood_groups.items():
        if plist:
            mood_group_data.append({
                "label":    label,
                "avg":      round(sum(plist) / len(plist), 2),
                "sessions": len(plist),
            })

    # ── Format breakdown ──────────────────────────────────────────────────────
    format_deep = defaultdict(lambda: {"sessions": 0, "profit": 0.0, "buy_in": 0.0, "minutes": 0, "wins": 0})
    for e, p in zip(entries, profits):
        s = format_deep[e.format]
        s["sessions"] += 1; s["profit"] += p
        s["buy_in"]   += float(e.buy_in or 0)
        s["minutes"]  += int(e.duration_minutes or 0)
        if p > 0: s["wins"] += 1

    format_breakdown = []
    for fmt, s in format_deep.items():
        hours   = s["minutes"] / 60 if s["minutes"] else 0
        roi     = (s["profit"] / s["buy_in"] * 100) if s["buy_in"] else 0
        hourly  = (s["profit"] / hours) if hours else None
        winrate = (s["wins"] / s["sessions"] * 100) if s["sessions"] else 0
        format_breakdown.append({
            "format":   fmt, "sessions": s["sessions"],
            "profit":   round(s["profit"], 2), "roi": round(roi, 2),
            "hourly":   round(hourly, 2) if hourly is not None else None,
            "winrate":  round(winrate, 1), "hours": round(hours, 1),
        })
    format_breakdown.sort(key=lambda x: x["profit"], reverse=True)

    # ── Personal bests ────────────────────────────────────────────────────────
    best_idx  = profits.index(max(profits))
    worst_idx = profits.index(min(profits))

    # ── Overall totals ────────────────────────────────────────────────────────
    total_sessions  = n
    total_profit    = sum(profits)
    total_buy_in    = sum(float(e.buy_in or 0) for e in entries)
    total_minutes   = sum(int(e.duration_minutes or 0) for e in entries)
    total_hours     = total_minutes / 60 if total_minutes else 0
    overall_roi     = (total_profit / total_buy_in * 100) if total_buy_in else 0
    overall_hourly  = (total_profit / total_hours) if total_hours else None
    overall_winrate = sum(1 for p in profits if p > 0) / n * 100

    # ── TIER 1: Distribution histogram ───────────────────────────────────────
    p_min = min(profits); p_max = max(profits)
    spread = p_max - p_min if p_max != p_min else 1
    raw_b  = spread / 10
    mag    = 10 ** math.floor(math.log10(abs(raw_b))) if raw_b > 0 else 1
    bsize  = max(round(raw_b / mag) * mag, 1)
    bstart = math.floor(p_min / bsize) * bsize
    dist_buckets = defaultdict(int)
    for p in profits:
        bk = math.floor((p - bstart) / bsize) * bsize + bstart
        dist_buckets[bk] += 1
    sorted_bks  = sorted(dist_buckets.keys())
    dist_labels = [f"£{int(k):+d}" for k in sorted_bks]
    dist_values = [dist_buckets[k] for k in sorted_bks]
    dist_colors = ["rgba(220,38,38,.55)" if k < 0 else "rgba(22,163,74,.45)" for k in sorted_bks]

    # ── TIER 1: EV gap ───────────────────────────────────────────────────────
    ev_entries = [(e, p) for e, p in zip(entries, profits) if e.ev_profit is not None]
    ev_gap_current = None; ev_gap_labels = []; cumulative_actual = []; cumulative_ev = []
    biggest_under_ev = 0; under_ev_streak = 0; total_ev = None; has_ev_data = bool(ev_entries)
    if ev_entries:
        cum_a = cum_ev = 0.0
        for e, p in ev_entries:
            ev_p = float(e.ev_profit); cum_a += p; cum_ev += ev_p
            ev_gap_labels.append(e.played_at.strftime("%d %b"))
            cumulative_actual.append(round(cum_a, 2)); cumulative_ev.append(round(cum_ev, 2))
            if cum_a - cum_ev < 0:
                under_ev_streak += 1; biggest_under_ev = max(biggest_under_ev, under_ev_streak)
            else:
                under_ev_streak = 0
        ev_gap_current = round(cum_a - cum_ev, 2); total_ev = round(cum_ev, 2)

    # ── TIER 1: Day of week ───────────────────────────────────────────────────
    day_names = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    day_buckets = defaultdict(list)
    for e, p in zip(entries, profits):
        day_buckets[e.played_at.weekday()].append(p)
    dow_profits = [round(sum(day_buckets[i]) / len(day_buckets[i]), 2) if day_buckets[i] else 0 for i in range(7)]
    dow_counts  = [len(day_buckets[i]) for i in range(7)]

    # ── TIER 1: Hour of day ───────────────────────────────────────────────────
    hour_buckets = defaultdict(list)
    for e, p in zip(entries, profits):
        hour_buckets[e.played_at.hour].append(p)
    active_hours = sorted(hour_buckets.keys())
    hour_labels  = [f"{h:02d}:00" for h in active_hours]
    hour_profits = [round(sum(hour_buckets[h]) / len(hour_buckets[h]), 2) for h in active_hours]
    hour_counts  = [len(hour_buckets[h]) for h in active_hours]

    # ── TIER 1: Moving averages ───────────────────────────────────────────────
    cumulative_profits = []
    running = 0.0
    for p in profits:
        running += p; cumulative_profits.append(round(running, 2))

    def moving_avg(data, window):
        return [None if i < window - 1 else round(sum(data[i-window+1:i+1]) / window, 2) for i in range(len(data))]

    ma_labels = [e.played_at.strftime("%d %b") for e in entries]
    ma5  = moving_avg(cumulative_profits, 5)
    ma10 = moving_avg(cumulative_profits, 10)

    # ── TIER 2: Variance & volatility ────────────────────────────────────────
    mean_profit = total_profit / n
    variance    = sum((p - mean_profit) ** 2 for p in profits) / n
    std_dev     = math.sqrt(variance)
    avg_buy_in  = total_buy_in / n if n else 1
    vol_ratio   = std_dev / avg_buy_in if avg_buy_in else 0
    if vol_ratio < 0.5:        volatility_rating, volatility_color = "Low",     "pos"
    elif vol_ratio < 1.5:      volatility_rating, volatility_color = "Medium",  "warn"
    elif vol_ratio < 3.0:      volatility_rating, volatility_color = "High",    "neg"
    else:                      volatility_rating, volatility_color = "Extreme", "neg"
    breakeven_sessions = math.ceil((1.96 * std_dev / mean_profit) ** 2) if mean_profit > 0 else None

    # ── TIER 2: Risk of Ruin ──────────────────────────────────────────────────
    try:
        from .models import Profile
        profile = Profile.objects.get(user=request.user)
        bankroll_for_ror = float(profile.starting_bankroll) + total_profit
    except Exception:
        profile = None
        bankroll_for_ror = total_profit if total_profit > 0 else None

    ror_pct = None
    if bankroll_for_ror and bankroll_for_ror > 0 and std_dev > 0 and mean_profit != 0:
        ratio = mean_profit / std_dev
        if abs(ratio) < 1:
            base    = (1 - ratio) / (1 + ratio)
            exp_val = bankroll_for_ror / std_dev
            ror_pct = round(min((base ** exp_val) * 100, 99.9), 1)
        else:
            ror_pct = 0.0

    # ── TIER 2: Session length efficiency ─────────────────────────────────────
    duration_x = []; duration_y = []; hourly_y = []; duration_labels = []
    for e, p in zip(entries, profits):
        mins = int(e.duration_minutes or 0)
        if mins > 0:
            hrs = round(mins / 60, 2)
            duration_x.append(hrs); duration_y.append(round(p, 2))
            hourly_y.append(round(p / hrs, 2)); duration_labels.append(e.played_at.strftime("%d %b"))
    has_duration_data = bool(duration_x)

    efficiency_groups = {"Short (<2h)": [], "Medium (2-4h)": [], "Long (>4h)": []}
    for hrs, p in zip(duration_x, duration_y):
        if hrs < 2:      efficiency_groups["Short (<2h)"].append((hrs, p))
        elif hrs <= 4:   efficiency_groups["Medium (2-4h)"].append((hrs, p))
        else:            efficiency_groups["Long (>4h)"].append((hrs, p))
    efficiency_summary = []
    for label, pairs in efficiency_groups.items():
        if pairs:
            avg_p   = sum(p for _, p in pairs) / len(pairs)
            avg_pph = sum(p / h for h, p in pairs) / len(pairs)
            efficiency_summary.append({
                "label": label, "sessions": len(pairs),
                "avg_profit": round(avg_p, 2), "avg_hourly": round(avg_pph, 2),
            })

    # ── TIER 2: Monthly growth ────────────────────────────────────────────────
    from datetime import datetime
    monthly_buckets = defaultdict(float); monthly_buyin = defaultdict(float)
    for e, p in zip(entries, profits):
        key = e.played_at.strftime("%b %Y")
        monthly_buckets[key] += p; monthly_buyin[key] += float(e.buy_in or 0)
    def month_sort_key(k):
        try: return datetime.strptime(k, "%b %Y")
        except: return datetime.min
    sorted_months   = sorted(monthly_buckets.keys(), key=month_sort_key)
    monthly_profits = [round(monthly_buckets[m], 2) for m in sorted_months]
    monthly_roi     = [round(monthly_buckets[m] / monthly_buyin[m] * 100, 1) if monthly_buyin[m] else 0 for m in sorted_months]
    start_br = float(profile.starting_bankroll) if profile else 0.0
    monthly_bankroll = []
    running_br = start_br
    for m in sorted_months:
        running_br += monthly_buckets[m]; monthly_bankroll.append(round(running_br, 2))
    monthly_growth = [None] + [
        round((monthly_bankroll[i] - monthly_bankroll[i-1]) / abs(monthly_bankroll[i-1]) * 100, 1)
        if monthly_bankroll[i-1] != 0 else None
        for i in range(1, len(sorted_months))
    ]
    monthly_table = [
        {"label": sorted_months[i], "profit": monthly_profits[i], "roi": monthly_roi[i],
         "bankroll": monthly_bankroll[i], "growth": monthly_growth[i]}
        for i in range(len(sorted_months))
    ]

    # =========================================================================
    # TIER 3
    # =========================================================================

    # ── EV Realisation % ─────────────────────────────────────────────────────
    ev_realisation = None; ev_realisation_label = None; ev_realisation_color = "muted"
    if ev_entries and total_ev and total_ev != 0:
        total_actual_ev_sum = sum(p for _, p in ev_entries)
        ev_realisation = round((total_actual_ev_sum / total_ev) * 100, 1)
        if ev_realisation >= 110:
            ev_realisation_label = "Running hot 🔥"; ev_realisation_color = "pos"
        elif ev_realisation >= 95:
            ev_realisation_label = "Slightly above EV"; ev_realisation_color = "pos"
        elif ev_realisation >= 85:
            ev_realisation_label = "Slightly below EV"; ev_realisation_color = "warn"
        elif ev_realisation >= 70:
            ev_realisation_label = "Running cold ❄️"; ev_realisation_color = "neg"
        else:
            ev_realisation_label = "Significant variance downswing"; ev_realisation_color = "neg"

    # ── Downswings breakdown ──────────────────────────────────────────────────
    avg_bi_ds = total_buy_in / n if n else 1
    threshold_ds = avg_bi_ds * 5
    peak_val = 0.0; current_ds_depth = 0.0; current_ds_len = 0
    downswings = []; in_downswing = False; ds_start_idx = 0; running_sum = 0.0
    for i, p in enumerate(profits):
        running_sum += p
        if running_sum > peak_val:
            if in_downswing and current_ds_depth >= threshold_ds:
                downswings.append({
                    "depth": round(current_ds_depth, 2), "length": current_ds_len,
                    "start": entries[ds_start_idx].played_at.strftime("%d %b %Y"),
                    "end":   entries[i - 1].played_at.strftime("%d %b %Y"),
                })
            peak_val = running_sum; in_downswing = False
            current_ds_depth = 0.0; current_ds_len = 0
        else:
            depth = peak_val - running_sum
            if depth >= threshold_ds:
                if not in_downswing:
                    in_downswing = True; ds_start_idx = i
                current_ds_depth = max(current_ds_depth, depth)
                current_ds_len  += 1
    if in_downswing and current_ds_depth >= threshold_ds:
        downswings.append({
            "depth": round(current_ds_depth, 2), "length": current_ds_len,
            "start": entries[ds_start_idx].played_at.strftime("%d %b %Y"), "end": "ongoing",
        })
    num_downswings  = len(downswings)
    worst_downswing = max(downswings, key=lambda x: x["depth"]) if downswings else None
    avg_ds_length   = round(sum(d["length"] for d in downswings) / num_downswings, 1) if downswings else 0

    # ── Format Edge Score ─────────────────────────────────────────────────────
    format_edge = []
    for f in format_breakdown:
        if f["sessions"] > 0:
            edge_score = round(f["roi"] * math.log(f["sessions"] + 1), 2)
            format_edge.append({
                "format": f["format"], "sessions": f["sessions"],
                "roi": f["roi"], "edge_score": edge_score,
            })
    format_edge.sort(key=lambda x: x["edge_score"], reverse=True)

    # =========================================================================
    # TIER 4
    # =========================================================================

    # ── Sharpe Ratio ──────────────────────────────────────────────────────────
    sharpe_ratio = None; sharpe_label = None; sharpe_color = "muted"
    if std_dev > 0:
        sharpe_ratio = round(mean_profit / std_dev, 3)
        if sharpe_ratio >= 0.5:
            sharpe_label, sharpe_color = "Excellent", "pos"
        elif sharpe_ratio >= 0.2:
            sharpe_label, sharpe_color = "Good", "pos"
        elif sharpe_ratio >= 0:
            sharpe_label, sharpe_color = "Marginal", "warn"
        elif sharpe_ratio >= -0.2:
            sharpe_label, sharpe_color = "Losing", "neg"
        else:
            sharpe_label, sharpe_color = "Significant losses", "neg"

    # ── Rolling ROI (20-session window) ───────────────────────────────────────
    roll_window = 20
    rolling_roi_labels = []; rolling_roi_values = []
    for i in range(roll_window - 1, n):
        w_entries = entries[i - roll_window + 1:i + 1]
        w_profits = profits[i - roll_window + 1:i + 1]
        w_bi = sum(float(e.buy_in or 0) for e in w_entries)
        roi_v = round(sum(w_profits) / w_bi * 100, 1) if w_bi else 0
        rolling_roi_labels.append(entries[i].played_at.strftime("%d %b"))
        rolling_roi_values.append(roi_v)
    has_rolling_roi = bool(rolling_roi_values)

    # ── Winrate confidence interval ───────────────────────────────────────────
    ci_lower = ci_upper = ci_note = None; ci_color = "muted"
    if n >= 5 and std_dev > 0:
        z = 2.262 if n < 10 else (2.093 if n < 20 else (2.045 if n < 30 else 1.96))
        margin = z * (std_dev / math.sqrt(n))
        ci_lower = round(mean_profit - margin, 2)
        ci_upper = round(mean_profit + margin, 2)
        if ci_lower > 0:
            ci_note, ci_color = "Edge statistically confirmed at 95% confidence ✓", "pos"
        elif ci_upper < 0:
            ci_note, ci_color = "Results statistically negative at 95% confidence.", "neg"
        else:
            ci_note = f"Edge not yet confirmed — CI crosses zero. Need more volume."
            ci_color = "warn"
    else:
        ci_note = "Need at least 5 sessions to calculate."

    context = {
        # ── Overview ─────────────────────────────────────────────────────────
        "total_sessions":   total_sessions,
        "total_profit":     round(total_profit, 2),
        "overall_roi":      round(overall_roi, 2),
        "overall_hourly":   round(overall_hourly, 2) if overall_hourly is not None else None,
        "overall_winrate":  round(overall_winrate, 1),
        "total_hours":      round(total_hours, 1),
        "format_breakdown": format_breakdown,
        "best_session":     entries[best_idx],
        "best_profit":      round(profits[best_idx], 2),
        "worst_session":    entries[worst_idx],
        "worst_profit":     round(profits[worst_idx], 2),
        "ma_labels":        ma_labels,
        "ma5":              ma5,
        "ma10":             ma10,
        "cumulative_profits": cumulative_profits,
        # ── Session analysis ─────────────────────────────────────────────────
        "dist_labels":       dist_labels,
        "dist_values":       dist_values,
        "dist_colors":       dist_colors,
        "dow_labels":        day_names,
        "dow_profits":       dow_profits,
        "dow_counts":        dow_counts,
        "hour_labels":       hour_labels,
        "hour_profits":      hour_profits,
        "hour_counts":       hour_counts,
        "has_duration_data": has_duration_data,
        "duration_x":        duration_x,
        "duration_y":        duration_y,
        "duration_labels":   duration_labels,
        "efficiency_summary": efficiency_summary,
        # ── EV & Variance ────────────────────────────────────────────────────
        "has_ev_data":        has_ev_data,
        "ev_gap_labels":      ev_gap_labels,
        "cumulative_actual":  cumulative_actual,
        "cumulative_ev":      cumulative_ev,
        "ev_gap_current":     ev_gap_current,
        "biggest_under_ev":   biggest_under_ev,
        "total_ev":           total_ev,
        "std_dev":            round(std_dev, 2),
        "variance":           round(variance, 2),
        "mean_profit":        round(mean_profit, 2),
        "volatility_rating":  volatility_rating,
        "volatility_color":   volatility_color,
        "breakeven_sessions": breakeven_sessions,
        "ror_pct":            ror_pct,
        "bankroll_for_ror":   round(bankroll_for_ror, 2) if bankroll_for_ror else None,
        "ev_realisation":     ev_realisation,
        "ev_realisation_label": ev_realisation_label,
        "ev_realisation_color": ev_realisation_color,
        "sharpe_ratio":       sharpe_ratio,
        "sharpe_label":       sharpe_label,
        "sharpe_color":       sharpe_color,
        "ci_lower":           ci_lower,
        "ci_upper":           ci_upper,
        "ci_note":            ci_note,
        "ci_color":           ci_color,
        "has_rolling_roi":    has_rolling_roi,
        "rolling_roi_labels": rolling_roi_labels,
        "rolling_roi_values": rolling_roi_values,
        # ── Streaks & Mood ───────────────────────────────────────────────────
        "streak_info":      streak_info,
        "itm_stats":        itm_stats,
        "mood_labels":      mood_labels,
        "mood_profits":     mood_profits_chart,
        "mood_group_data":  mood_group_data,
        "num_downswings":   num_downswings,
        "worst_downswing":  worst_downswing,
        "avg_ds_length":    avg_ds_length,
        "downswings":       downswings,
        "format_edge":      format_edge,
        # ── Growth ───────────────────────────────────────────────────────────
        "monthly_labels":   sorted_months,
        "monthly_profits":  monthly_profits,
        "monthly_roi":      monthly_roi,
        "monthly_bankroll": monthly_bankroll,
        "monthly_table":    monthly_table,
    }

    return render(request, "pokerlog/analytics.html", context)


