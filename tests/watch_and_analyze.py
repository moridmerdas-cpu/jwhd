"""
ضبط زنده + تحلیل خودکار Rate Limit
- از الان هرچی میاد رو ضبط می‌کنه
- کی limit می‌خوره، کی آزاد می‌شه
- آخرش تحلیل کامل
"""
import sqlite3
import re
import time
import json
from datetime import datetime
from pathlib import Path

DB = "/root/tg_master_bot/models/tg_system.db"
OUT_JSON = "/root/tg_master_bot/tests/rate_data.json"


def parse(msg):
    m = re.search(r'موفق:\s*(\d+)/(\d+)', msg)
    return (int(m.group(1)), int(m.group(2))) if m else None


def analyze(events):
    print("\n" + "█" * 70)
    print("  📊 تحلیل کامل")
    print("█" * 70)

    if not events:
        print("\n❌ هیچ رویدادی ضبط نشد")
        return

    # آمار پایه
    total = len(events)
    acc_total = events[0]["tot"]
    success = [e["suc"] for e in events]
    avg = sum(success) / total

    print(f"\n  📨 کل پست‌ها: {total}")
    print(f"  🎯 میانگین موفق: {avg:.1f}/{acc_total}")
    print(f"  ⏰ از {events[0]['time'][11:19]} تا {events[-1]['time'][11:19]}")

    # مدت کل
    t0 = datetime.fromisoformat(events[0]["time"])
    t1 = datetime.fromisoformat(events[-1]["time"])
    print(f"  ⏱️  طول آزمایش: {(t1 - t0).total_seconds():.0f}s")

    # پیدا کردن پنجره‌های limit
    windows = []
    i = 0
    while i < len(events):
        if events[i]["suc"] == 0:
            start = i
            while i < len(events) and events[i]["suc"] == 0:
                i += 1
            end = i - 1
            windows.append((start, end))
        else:
            i += 1

    print(f"\n  🔴 تعداد پنجره‌های Rate Limit: {len(windows)}")

    if windows:
        for w_idx, (start, end) in enumerate(windows, 1):
            print(f"\n  ─── پنجره {w_idx} ───")
            print(f"  شروع: {events[start]['time'][11:19]}  |  پایان: {events[end]['time'][11:19]}")

            duration_limit = (datetime.fromisoformat(events[end]["time"]) - datetime.fromisoformat(events[start]["time"])).total_seconds()
            print(f"  ⏱️  طول: {duration_limit:.0f}s | 📨 {end - start + 1} پست پی‌درپی 0/30")

            # چقدر قبلش موفق بود
            j = start - 1
            good_before = 0
            first_good = None
            while j >= 0 and events[j]["suc"] >= 20:
                if first_good is None:
                    first_good = events[j]["time"]
                good_before += 1
                j -= 1

            if good_before > 0:
                print(f"  ✅ قبلش: {good_before} پست موفق پی‌درپی")
                print(f"     از {events[j+1]['time'][11:19]} تا {events[start-1]['time'][11:19]}")

            # چقدر بعدش آزاد شد
            j = end + 1
            while j < len(events) and events[j]["suc"] == 0:
                j += 1
            if j < len(events):
                recovery = (datetime.fromisoformat(events[j]["time"]) - datetime.fromisoformat(events[end]["time"])).total_seconds()
                print(f"  🔄 آزاد شد: {events[j]['time'][11:19]}  |  زمان: {recovery:.0f}s ({recovery/60:.1f} دقیقه)")
                print(f"     موفقیت بعد آزادسازی: {events[j]['suc']}/{events[j]['tot']}")
            else:
                print(f"  ⏳ هنوز آزاد نشده")

    # محدودیت هر اکانت
    if windows:
        pre_ok = []
        for start, end in windows:
            j = start - 1
            c = 0
            while j >= 0 and events[j]["suc"] >= 20:
                c += 1
                j -= 1
            pre_ok.append(c)

        avg_pre = sum(pre_ok) / len(pre_ok)
        max_pre = max(pre_ok)

        recoveries = []
        for start, end in windows:
            j = end + 1
            while j < len(events) and events[j]["suc"] == 0:
                j += 1
            if j < len(events):
                r = (datetime.fromisoformat(events[j]["time"]) - datetime.fromisoformat(events[end]["time"])).total_seconds()
                recoveries.append(r)

        avg_rec = sum(recoveries) / len(recoveries) if recoveries else 0

        print("\n" + "═" * 70)
        print("  🎯 نتیجه نهایی")
        print("═" * 70)
        print(f"\n  📊 محدودیت واقعی هر اکانت:")
        print(f"     🎯 سقف سین پی‌درپی: {avg_pre:.0f} پست (میانگین) / {max_pre} پست (حداکثر)")
        print(f"     ⏰ زمان آزادسازی: {avg_rec:.0f} ثانیه ({avg_rec/60:.1f} دقیقه)")

        # پیشنهاد
        print(f"\n  💡 پیشنهاد تنظیمات:")

        # الگوریتم: تعداد گروه = ceil(suc_cap / (recovery_time × post_rate))
        # ساده: 
        # هر گروه می‌تونه X پست کار کنه، بعد Y ثانیه استراحت
        # پس هر گروه با نسبت X/(X*avg_gap + Y) مشغوله
        # برای پست‌های پی‌درپی، تعداد گروه لازم = ceil(1 / (X * post_rate))  hmm

        # ساده: حداقل 3 گروه، بیشتر اگه سقف کمه
        if avg_pre >= 30:
            rec_groups = 3
        elif avg_pre >= 20:
            rec_groups = 4
        elif avg_pre >= 10:
            rec_groups = 5
        elif avg_pre >= 5:
            rec_groups = 8
        else:
            rec_groups = 10

        print(f"     • حداقل {rec_groups} گروه از اکانت‌ها")
        print(f"     • هر گروه هر {rec_groups} پست یه بار استفاده شه")

        for n_total in [30, 60, 75, 150]:
            acc_per = n_total // rec_groups
            # هر پست از یه گروه استفاده می‌کنه
            # اگه هر گروه acc_per اکانت داشته باشه، می‌تونه acc_per سین بزنه
            # پس اگه سقف acc_per باشه، هر گروه در 1 پست همه اکانتش قفل می‌شن
            # پس باید بین دو استفاده از یه گروه، حداقل avg_rec ثانیه باشه
            # اگه rec_groups گروه، و پست هر X ثانیه، زمان بین دو استفاده = X * rec_groups
            # باید >= avg_rec
            safe_interval = avg_rec / rec_groups if rec_groups else 0
            print(f"     • {n_total} اکانت → {rec_groups} گروه × {acc_per} اکانت")
            print(f"       فاصله امن بین پست‌ها: {safe_interval:.1f}s")

        # جواب قطعی برای 2 ثانیه
        print(f"\n  📌 برای پست‌های پی‌درپی (هر 2 ثانیه):")
        for n_total in [30, 60, 75, 150]:
            acc_per = n_total // rec_groups
            needed_interval = avg_rec / rec_groups
            if needed_interval <= 2:
                print(f"     ✅ {n_total} اکانت کافیه ({rec_groups} گروه)")
            else:
                # چند گروه لازمه که فاصله امن بشه
                needed_groups = int(avg_rec / 2) + 1
                needed_acc = n_total
                print(f"     ⚠️  {n_total} اکانت کافی نیست — نیاز به {needed_groups} گروه")

    else:
        print("\n  ✅ هیچ Rate Limit رخ نداد!")
        print("     همه اکانت‌ها بدون مشکل کار کردن")

    # ذخیره
    Path(OUT_JSON).write_text(json.dumps(events, indent=2, default=str))
    print(f"\n  💾 داده در: {OUT_JSON}")


def main():
    print("=" * 70)
    print("  🎬 ضبط زنده شروع شد")
    print("=" * 70)
    print("  ⏳ الان پست‌ها رو بفرست...")
    print("  🛑 برای توقف و تحلیل: Ctrl+C")
    print("=" * 70)

    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row

    row = conn.execute("SELECT MAX(id) as mid FROM debug_log WHERE module='listener' AND step='new_post'").fetchone()
    last_id = row["mid"] or 0

    events = []
    last_print_time = time.time()
    current_status = None

    try:
        while True:
            rows = conn.execute("""
                SELECT id, datetime(created_at, 'localtime') as t, message
                FROM debug_log
                WHERE module='listener' AND step='new_post'
                AND message LIKE '%موفق%'
                AND id > ?
                ORDER BY id ASC
            """, (last_id,)).fetchall()

            for r in rows:
                last_id = r["id"]
                parsed = parse(r["message"])
                if not parsed:
                    continue
                suc, tot = parsed
                evt = {"time": r["t"], "suc": suc, "tot": tot}
                events.append(evt)

                # وضعیت
                if suc == 0:
                    new_status = "limit"
                elif suc >= 20:
                    new_status = "ok"
                else:
                    new_status = "partial"

                # نمایش فقط تغییر وضعیت
                if new_status != current_status:
                    icons = {"ok": "🟢", "limit": "🔴", "partial": "🟡"}
                    print(f"  {icons[new_status]} {r['t'][11:19]} → {suc}/{tot} ({new_status})")
                    current_status = new_status

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n  🛑 ضبط متوقف شد. تحلیل می‌کنم...\n")
        analyze(events)


if __name__ == "__main__":
    main()
