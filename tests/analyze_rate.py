"""
تحلیل خودکار Rate Limit
- کل لاگ رو می‌خونه
- الگوی موفقیت/شکست رو پیدا می‌کنه
- محدودیت دقیق هر اکانت رو حساب می‌کنه
"""
import sqlite3
import re
from datetime import datetime
from collections import defaultdict

DB = "/root/tg_master_bot/models/tg_system.db"

conn = sqlite3.connect(DB, timeout=10)
conn.row_factory = sqlite3.Row

print("\n" + "█" * 70)
print("  🔬 تحلیل خودکار Rate Limit")
print("█" * 70)

# ═══════════════════════════════════════════════════════════
# ۱. همه سین‌ها رو بخون
# ═══════════════════════════════════════════════════════════
rows = conn.execute("""
    SELECT datetime(created_at, 'localtime') as t, message
    FROM debug_log
    WHERE module='listener' AND step='new_post' AND message LIKE '%موفق%'
    ORDER BY id ASC
""").fetchall()

if not rows:
    print("\n❌ هیچ سین‌ای پیدا نشد")
    exit()

events = []
for r in rows:
    m = re.search(r'موفق:\s*(\d+)/(\d+)', r['message'])
    if m:
        events.append({
            "time": datetime.fromisoformat(r['t']),
            "suc": int(m.group(1)),
            "tot": int(m.group(2)),
        })

print(f"\n📊 {len(events)} رویداد سین در لاگ")
print(f"⏰ از {events[0]['time'].strftime('%H:%M:%S')} تا {events[-1]['time'].strftime('%H:%M:%S')}")

# ═══════════════════════════════════════════════════════════
# ۲. پیدا کردن «پنجره‌های Rate Limit»
# ═══════════════════════════════════════════════════════════
# Rate limit یعنی: از یه نقطه، یه سری پست پی‌درپی همه پایین یا صفر شدن

print("\n" + "═" * 70)
print("  📉 شناسایی پنجره‌های Rate Limit")
print("═" * 70)

windows = []
i = 0
while i < len(events):
    e = events[i]
    # شروع پنجره: موفق کم
    if e["suc"] <= 5:
        start = i
        while i < len(events) and events[i]["suc"] <= 5:
            i += 1
        end = i - 1
        windows.append({
            "start": events[start]["time"],
            "end": events[end]["time"],
            "count": end - start + 1,
            "avg_suc": sum(e["suc"] for e in events[start:end+1]) / (end - start + 1),
        })
    else:
        i += 1

if not windows:
    print("\n✅ هیچ Rate Limit پیدا نشد — همه سین‌ها موفق بودن!")
else:
    print(f"\n⚠️  {len(windows)} پنجره Rate Limit:")
    for w in windows:
        duration = (w["end"] - w["start"]).total_seconds()
        print(f"\n  🔴 از {w['start'].strftime('%H:%M:%S')} تا {w['end'].strftime('%H:%M:%S')}")
        print(f"     📨 {w['count']} پست پی‌درپی")
        print(f"     ⏱️  طول: {duration:.0f} ثانیه")
        print(f"     📊 میانگین موفق: {w['avg_suc']:.1f}/{events[0]['tot']}")

# ═══════════════════════════════════════════════════════════
# ۳. «قبل از هر پنجره» چقدر موفق بودیم؟
# ═══════════════════════════════════════════════════════════
print("\n" + "═" * 70)
print("  🔍 قبل از هر پنجره Rate Limit — چند پست موفق؟")
print("═" * 70)

if windows:
    for w in windows:
        # آخرین پنجره موفق قبل از شروع rate limit
        start_idx = next(i for i, e in enumerate(events) if e["time"] == w["start"])
        # برو عقب تا اولین پست شکست خورده پیدا کنی
        j = start_idx - 1
        good_streak = 0
        while j >= 0 and events[j]["suc"] >= 25:
            good_streak += 1
            j -= 1

        if good_streak > 0:
            first_good = events[j+1]["time"]
            last_good = events[start_idx - 1]["time"]
            duration = (last_good - first_good).total_seconds()
            print(f"\n  ✅ قبل از {w['start'].strftime('%H:%M:%S')}:")
            print(f"     {good_streak} پست موفق پی‌درپی")
            print(f"     از {first_good.strftime('%H:%M:%S')} تا {last_good.strftime('%H:%M:%S')}")
            print(f"     ⏱️  طول: {duration:.0f} ثانیه")
            print(f"     🎯 نتیجه: هر اکانت {good_streak} بار تونست سین بزنه")

# ═══════════════════════════════════════════════════════════
# ۴. «بعد از پنجره» چقدر طول کشید تا آزاد شه؟
# ═══════════════════════════════════════════════════════════
print("\n" + "═" * 70)
print("  ⏰ بعد از هر پنجره — چقدر طول کشید تا آزاد شه؟")
print("═" * 70)

if windows:
    for w in windows:
        # اولین پست موفق بعد از پایان پنجره
        end_idx = next(i for i, e in enumerate(events) if e["time"] == w["end"])
        j = end_idx + 1
        while j < len(events) and events[j]["suc"] <= 5:
            j += 1

        if j < len(events):
            recovery = (events[j]["time"] - w["end"]).total_seconds()
            print(f"\n  🔄 بعد از {w['end'].strftime('%H:%M:%S')}:")
            print(f"     اولین موفق: {events[j]['time'].strftime('%H:%M:%S')} ({events[j]['suc']}/{events[j]['tot']})")
            print(f"     ⏱️  زمان آزادسازی: {recovery:.0f} ثانیه ({recovery/60:.1f} دقیقه)")

# ═══════════════════════════════════════════════════════════
# ۵. نتیجه‌گیری نهایی
# ═══════════════════════════════════════════════════════════
print("\n" + "█" * 70)
print("  🎯 نتیجه‌گیری و پیشنهاد تنظیمات")
print("█" * 70)

total_acc = events[0]["tot"] if events else 30

if windows:
    # میانگین موفقیت قبل از ریزش
    pre_window_counts = []
    for w in windows:
        start_idx = next(i for i, e in enumerate(events) if e["time"] == w["start"])
        j = start_idx - 1
        cnt = 0
        while j >= 0 and events[j]["suc"] >= 25:
            cnt += 1
            j -= 1
        pre_window_counts.append(cnt)

    # میانگین زمان آزادسازی
    recovery_times = []
    for w in windows:
        end_idx = next(i for i, e in enumerate(events) if e["time"] == w["end"])
        j = end_idx + 1
        while j < len(events) and events[j]["suc"] <= 5:
            j += 1
        if j < len(events):
            recovery_times.append((events[j]["time"] - w["end"]).total_seconds())

    avg_pre = sum(pre_window_counts) / len(pre_window_counts) if pre_window_counts else 0
    avg_recovery = sum(recovery_times) / len(recovery_times) if recovery_times else 0

    print(f"\n  📊 محدودیت هر اکانت:")
    print(f"     🎯 سقف سین پی‌درپی: {avg_pre:.0f} پست")
    print(f"     ⏰ زمان آزادسازی: {avg_recovery:.0f} ثانیه ({avg_recovery/60:.1f} دقیقه)")

    print(f"\n  💡 تنظیمات پیشنهادی:")

    # چرخش: تعداد اکانت لازم
    print(f"\n     ┌─────────────────────────────────────────────┐")
    print(f"     │ برای پست‌های پی‌درپی بدون ریزش:              │")
    print(f"     │                                             │")

    # اگه هر اکانت avg_pre سین بزنه قبل از قفل،
    # و بین هر 3 پست یه گروه استفاده شه:
    # اگه 30 اکانت → هر گروه 10 اکانت → هر گروه avg_pre پست می‌زنه

    for n_posts_per_sec in [1, 2, 5, 10]:
        # چند ثانیه بین هر پست
        sec_between = 1 / n_posts_per_sec
        # چند اکانت لازم برای هر پست
        # با 3 گروه: هر گروه هر 3 پست یه بار
        # با avg_pre=10: هر گروه 10 پست کار می‌کنه، بعد قفل
        # پس هر گروه در ثانیه: 1/3 پست
        # هر اکانت در پنجره: avg_pre سین
        # اکانت لازم: total_posts_in_window / avg_pre

        print(f"     │  🚀 {n_posts_per_sec} پست/ثانیه:")
        # اگه هر پست باید X اکانت بزنه
        for n_groups in [1, 3, 5, 10]:
            acc_per_group = total_acc // n_groups
            # هر گروه هر n_groups پست یه بار
            # پس با avg_pre پست، هر گروه avg_pre * n_groups پست زنده می‌مونه
            max_posts_ok = avg_pre * n_groups
            print(f"     │     {n_groups} گروه × {acc_per_group} اکانت → {max_posts_ok} پست سالم")
        print(f"     │")

    print(f"     └─────────────────────────────────────────────┘")

    # پیشنهاد کلی
    print(f"\n  🎯 پیشنهاد کلی:")
    if avg_pre <= 15:
        rec_groups = 5
        rec_n_acc = 75
    elif avg_pre <= 25:
        rec_groups = 4
        rec_n_acc = 60
    else:
        rec_groups = 3
        rec_n_acc = 30

    print(f"     • {rec_groups} گروه از اکانت‌ها")
    print(f"     • {rec_n_acc} اکانت توصیه می‌شه")
    print(f"     • هر گروه هر {rec_groups} پست یه بار استفاده شه")

    # نکته مهم
    print(f"\n  ⚠️  نکات حیاتی:")
    print(f"     • بین پست‌های گروه، حداقل {avg_recovery:.0f} ثانیه فاصله باشه")
    print(f"     • اگه پست‌ها خیلی سریع بیاد، خیلی از اکانت‌ها قفل می‌شن")
    print(f"     • بهترین حالت: بین دو پست همون گروه، حداقل {avg_recovery:.0f} ثانیه")

else:
    print("\n  ✅ هیچ محدودیتی مشاهده نشد")
    print("     • می‌تونی بدون نگرانی ادامه بدی")
    print("     • هر اکانت به قدر کافی خوب کار می‌کنه")

conn.close()
print("\n" + "█" * 70)
print("  🏁 پایان تحلیل")
print("█" * 70)
