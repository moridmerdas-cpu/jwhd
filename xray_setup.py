"""
راه‌اندازی Xray با کانفیگ‌های VLESS
هر کانفیگ → یه SOCKS5 محلی
"""
import json, subprocess, os, shutil, time, urllib.parse, re, base64
from pathlib import Path

XRAY_DIR = Path("/root/tg_master_bot/xray")
XRAY_BIN = Path("/usr/local/bin/xray")

# ═══ کانفیگ‌های VLESS ═══
CONFIGS = [
    {
        "name": "UK1_dia01",
        "socks_port": 10801,
        "server": "dia01.dontbanmeplz.com",
        "port": 443,
        "uuid": "b53c4152-42ee-4587-ad70-54472b1cd4d3",
        "sni": "dia01.dontbanmeplz.com",
        "path": "/dn7701?ed=2560",
    },
    {
        "name": "UK2_dia02",
        "socks_port": 10802,
        "server": "dia02.saat-tamir.com",
        "port": 443,
        "uuid": "b53c4152-42ee-4587-ad70-54472b1cd4d3",
        "sni": "dia02.saat-tamir.com",
        "path": "/dn7702?ed=2560",
    },
]


def run(cmd, **kwargs):
    return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, **kwargs)


def install_xray():
    if XRAY_BIN.exists():
        print("✅ Xray از قبل نصبه")
        r = run([str(XRAY_BIN), "version"])
        print(f"   {r.stdout.splitlines()[0] if r.stdout else '?'}")
        return True

    print("⏳ دانلود Xray-core...")
    arch = "64"
    url = f"https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-{arch}.zip"
    zip_path = "/tmp/xray.zip"

    r = run(f"wget -q '{url}' -O {zip_path}")
    if not os.path.exists(zip_path):
        print("❌ دانلود fail")
        return False

    print("⏳ استخراج...")
    r = run(f"unzip -o {zip_path} -d /tmp/xray-extract")
    if not os.path.exists("/tmp/xray-extract/xray"):
        print(f"❌ unzip fail: {r.stderr}")
        return False

    shutil.move("/tmp/xray-extract/xray", str(XRAY_BIN))
    os.chmod(str(XRAY_BIN), 0o755)
    print("✅ Xray نصب شد")

    # geoip/geosite
    for f in ["geoip.dat", "geosite.dat"]:
        src = f"/tmp/xray-extract/{f}"
        if os.path.exists(src):
            shutil.copy(src, f"/usr/local/share/{f}")

    return True


def build_config(cfg):
    """ساخت config Xray برای یه کانفیگ VLESS"""
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "tag": "socks-in",
            "port": cfg["socks_port"],
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True},
        }],
        "outbounds": [{
            "tag": "vless-out",
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": cfg["server"],
                    "port": cfg["port"],
                    "users": [{
                        "id": cfg["uuid"],
                        "encryption": "none",
                        "flow": "",
                    }],
                }],
            },
            "streamSettings": {
                "network": "ws",
                "security": "tls",
                "tlsSettings": {
                    "serverName": cfg["sni"],
                    "fingerprint": "firefox",
                    "allowInsecure": True,
                },
                "wsSettings": {
                    "path": cfg["path"],
                    "headers": {"Host": cfg["sni"]},
                },
            },
        }],
    }


def setup_config(cfg):
    XRAY_DIR.mkdir(parents=True, exist_ok=True)
    cfg_dir = XRAY_DIR / cfg["name"]
    cfg_dir.mkdir(exist_ok=True)

    config_path = cfg_dir / "config.json"
    config_path.write_text(json.dumps(build_config(cfg), indent=2))

    # systemd service
    service = f"""[Unit]
Description=Xray {cfg['name']}
After=network.target

[Service]
Type=simple
User=root
ExecStart={XRAY_BIN} run -config {config_path}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
    svc_path = f"/etc/systemd/system/xray-{cfg['name']}.service"
    Path(svc_path).write_text(service)

    return cfg_dir, svc_path


def main():
    print("═" * 60)
    print("🚀 راه‌اندازی Xray")
    print("═" * 60)

    if not install_xray():
        return

    for cfg in CONFIGS:
        print(f"\n🔧 {cfg['name']} (port {cfg['socks_port']})")
        cfg_dir, svc_path = setup_config(cfg)
        print(f"  ✅ config: {cfg_dir}/config.json")
        print(f"  ✅ service: {svc_path}")

    # reload + restart
    run("systemctl daemon-reload")

    for cfg in CONFIGS:
        svc = f"xray-{cfg['name']}"
        run(f"systemctl enable {svc}")
        run(f"systemctl restart {svc}")
        time.sleep(3)

        # تست
        r = run(f"curl -s --max-time 15 -x socks5h://127.0.0.1:{cfg['socks_port']} https://api.ipify.org")
        ip = r.stdout.strip()
        if ip and ip.count(".") == 3:
            print(f"  ✅ {cfg['name']} → IP: {ip}")
            cfg["exit_ip"] = ip
        else:
            print(f"  ❌ {cfg['name']} timeout")
            # لاگ
            r2 = run(f"journalctl -u {svc} -n 5 --no-pager")
            print(f"     log: {r2.stdout[-200:]}")

    # ذخیره کانفیگ‌ها با IP
    result_path = XRAY_DIR / "configs.json"
    result_path.write_text(json.dumps(CONFIGS, indent=2))
    print(f"\n💾 ذخیره شد: {result_path}")


if __name__ == "__main__":
    main()
