#!/usr/bin/env python3

import os
import time
import threading
import subprocess
import struct
import socket
from time import sleep
import shutil
import json
from datetime import datetime
import fcntl
import struct as pystruct

import psutil
import requests
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from luma.core.render import canvas
from PIL import ImageFont, Image, ImageDraw

# Configuration
I2C_PORT = int(os.environ.get("OLED_I2C_PORT", "1"))
I2C_ADDR = int(os.environ.get("OLED_I2C_ADDR", "0x3c"), 0)
PING_INTERVAL = int(os.environ.get("PING_INTERVAL", "5"))
PING_COUNT = int(os.environ.get("PING_COUNT", "3"))
DEBUG_FILE = os.environ.get("DEBUG_FILE", "/tmp/display-debug.log")
WEATHER_ZIP = os.environ.get("WEATHER_ZIP", "18966")
WEATHER_FETCH_INTERVAL = int(os.environ.get("WEATHER_FETCH_INTERVAL", str(10 * 60)))

# Marquee settings
MARQUEE_SPEED_PX_PER_SEC = float(os.environ.get("MARQUEE_SPEED", "30.0"))
MARQUEE_GAP_PX = int(os.environ.get("MARQUEE_GAP", "8"))

# Initialize I2C display
serial = i2c(port=I2C_PORT, address=I2C_ADDR)
device = ssd1306(serial)

# Font
font = ImageFont.load_default()

# Shared state
ping_results = {}                     # name -> avg RTT ms or None
ping_lock = threading.Lock()
weather_lock = threading.Lock()
weather_cache = {"when": 0, "text": "Weather N/A"}

def debug(msg):
    try:
        with open(DEBUG_FILE, "a") as df:
            df.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass

def get_default_gateway():
    try:
        proc = subprocess.run(
            ["ip", "route", "show", "default"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2
        )
        out = proc.stdout.strip()
        if out:
            for line in out.splitlines():
                words = line.split()
                if "via" in words:
                    via_idx = words.index("via")
                    if via_idx + 1 < len(words):
                        return words[via_idx + 1]
    except Exception:
        pass
    try:
        with open("/proc/net/route", "r") as f:
            lines = f.read().strip().splitlines()
        for ln in lines[1:]:
            parts = ln.split()
            if len(parts) >= 3:
                dest_hex = parts[1]
                gate_hex = parts[2]
                if dest_hex == "00000000":
                    gw = socket.inet_ntoa(struct.pack("<L", int(gate_hex, 16)))
                    return gw
    except Exception:
        pass
    return None

def run_ping(addr, count=3, timeout=1):
    ping_bin = shutil.which("ping")
    if not ping_bin:
        return None
    try:
        proc = subprocess.run(
            [ping_bin, "-c", str(count), "-W", str(timeout), addr],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=(count * (timeout + 1) + 2)
        )
        out = proc.stdout
        for line in out.splitlines():
            if "min/avg/max" in line or "rtt min/avg/max" in line or "round-trip min/avg/max" in line:
                try:
                    part = line.split('=')[1].strip().split(' ')[0]
                    parts = part.split('/')
                    avg = float(parts[1])
                    return avg
                except Exception:
                    return None
        for line in reversed(out.splitlines()):
            if "=" in line and "/" in line:
                try:
                    part = line.split('=')[-1].strip().split(' ')[0]
                    parts = part.split('/')
                    avg = float(parts[1])
                    return avg
                except Exception:
                    continue
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        return None
    return None

def ping_worker(name, addr):
    while True:
        avg = run_ping(addr, count=PING_COUNT, timeout=1)
        with ping_lock:
            ping_results[name] = avg
        debug(f"ping {name} {addr} -> {avg}")
        time.sleep(PING_INTERVAL)

def get_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp_str = f.readline()
            return float(temp_str) / 1000.0
    except Exception:
        return None

def get_system_stats():
    cpu_percent = psutil.cpu_percent(interval=0.2)
    memory = psutil.virtual_memory()
    ram_percent = memory.percent
    ram_used_gb = memory.used / (1024**3)
    ram_total_gb = memory.total / (1024**3)
    cpu_temp = get_cpu_temp()
    return cpu_percent, ram_percent, ram_used_gb, ram_total_gb, cpu_temp

# Robust text pixel measurement
def measure_text_px(text, font_obj):
    try:
        tmp_img = Image.new("1", (1, 1))
        tmp_draw = ImageDraw.Draw(tmp_img)
        size = tmp_draw.textsize(text, font=font_obj)
        if isinstance(size, tuple) and len(size) == 2:
            return int(size[0]), int(size[1])
    except Exception:
        pass
    try:
        bbox = font_obj.getbbox(text)
        if bbox and len(bbox) >= 4:
            w = int(bbox[2] - bbox[0])
            h = int(bbox[3] - bbox[1])
            return w, h
    except Exception:
        pass
    try:
        mask = font_obj.getmask(text)
        if hasattr(mask, "size"):
            return int(mask.size[0]), int(mask.size[1])
    except Exception:
        pass
    try:
        size = font_obj.getsize(text)
        if isinstance(size, tuple) and len(size) == 2:
            return int(size[0]), int(size[1])
    except Exception:
        pass
    return device.width, 8

def fetch_weather_zip(zipcode):
    headers = {"User-Agent": "luma-oled-display/1.0", "Accept": "application/json"}
    url_json = f"https://wttr.in/{zipcode}?format=j1"
    try:
        r = requests.get(url_json, headers=headers, timeout=8)
        if r.status_code == 200:
            try:
                j = r.json()
            except Exception:
                debug("wttr.json: invalid JSON")
                j = None
            if j:
                cc = j.get("current_condition", [])
                weather_days = j.get("weather", [])
                day = weather_days[0] if weather_days else None

                cond_desc = ""
                temp_f = None
                humidity = None
                wind_mph = None
                chance_of_rain = None

                if isinstance(cc, list) and cc:
                    cur = cc[0]
                    temp_f = cur.get("temp_F") or cur.get("tempF") or cur.get("temp_C")
                    humidity = cur.get("humidity")
                    wind_mph = cur.get("windspeedMiles") or cur.get("windspeedKmph")
                    wd = cur.get("weatherDesc") or []
                    if isinstance(wd, list) and wd:
                        first = wd[0]
                        cond_desc = first.get("value") if isinstance(first, dict) else str(first)

                date = None
                avgtempF = None
                mintempF = None
                maxtempF = None
                sunrise = None
                sunset = None
                if isinstance(day, dict):
                    date = day.get("date")
                    avgtempF = day.get("avgtempF")
                    maxtempF = day.get("maxtempF")
                    mintempF = day.get("mintempF")
                    astro = day.get("astronomy", [])
                    if isinstance(astro, list) and astro:
                        a = astro[0]
                        sunrise = a.get("sunrise")
                        sunset = a.get("sunset")
                    hourly = day.get("hourly", [])
                    if hourly:
                        rep = None
                        for h in hourly:
                            if str(h.get("time")) in ("1200", "120", "1200"):
                                rep = h
                                break
                        if rep is None:
                            rep = hourly[len(hourly)//2]
                        chance_of_rain = rep.get("chanceofrain")
                        if humidity is None:
                            humidity = rep.get("humidity")
                        if wind_mph is None:
                            wind_mph = rep.get("windspeedMiles") or rep.get("windspeedKmph")

                parts = []
                if date:
                    parts.append(date)
                if not cond_desc and isinstance(day, dict):
                    hr_desc = ""
                    if day.get("hourly"):
                        first = day["hourly"][0].get("weatherDesc", [])
                        if isinstance(first, list) and first:
                            firstv = first[0]
                            hr_desc = firstv.get("value") if isinstance(firstv, dict) else str(firstv)
                    cond_desc = hr_desc
                if cond_desc:
                    parts.append(cond_desc)
                tparts = []
                if avgtempF:
                    tparts.append(f"avg {avgtempF}F")
                if mintempF and maxtempF:
                    tparts.append(f"min {mintempF}F/max {maxtempF}F")
                elif maxtempF:
                    tparts.append(f"max {maxtempF}F")
                elif mintempF:
                    tparts.append(f"min {mintempF}F")
                elif temp_f:
                    tparts.append(f"{temp_f}F")
                if tparts:
                    parts.append(", ".join(tparts))
                hx = []
                if humidity:
                    hx.append(f"Hum {humidity}%")
                if wind_mph:
                    hx.append(f"Wind {wind_mph}mph")
                if chance_of_rain:
                    hx.append(f"Rain {chance_of_rain}%")
                if hx:
                    parts.append(", ".join(hx))
                if sunrise or sunset:
                    ss = []
                    if sunrise:
                        ss.append(f"Sunrise {sunrise}")
                    if sunset:
                        ss.append(f"Sunset {sunset}")
                    parts.append(" / ".join(ss))

                summary = " | ".join(parts).strip()
                if summary:
                    return summary
    except Exception as ex:
        debug(f"wttr.json fetch error: {ex}")

    try:
        headers_text = {"User-Agent": "luma-oled-display/1.0", "Accept": "text/plain"}
        url_text = f"https://wttr.in/{zipcode}?format=%C+%t+%h+%w+%S+%s"
        r2 = requests.get(url_text, headers=headers_text, timeout=6)
        if r2.status_code == 200:
            txt = r2.text.strip().replace("\n", " ")
            if txt:
                return txt
    except Exception as ex:
        debug(f"wttr.text fetch error: {ex}")

    return None

def get_weather_text():
    now = time.time()
    with weather_lock:
        if now - weather_cache["when"] < WEATHER_FETCH_INTERVAL and weather_cache["text"]:
            return weather_cache["text"]
    txt = fetch_weather_zip(WEATHER_ZIP)
    if not txt:
        txt = "Weather N/A"
    with weather_lock:
        weather_cache["when"] = time.time()
        weather_cache["text"] = txt
    debug(f"weather -> {txt}")
    return txt

def get_hostname():
    try:
        return socket.gethostname()
    except Exception:
        return "hostname N/A"

def get_wireless_ip(interface="wlan0"):
    try:
        addrs = psutil.net_if_addrs()
        if interface in addrs:
            for a in addrs[interface]:
                if a.family == socket.AF_INET:
                    return a.address
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ifname = interface.encode('utf-8')
        res = fcntl.ioctl(s.fileno(), 0x8915, pystruct.pack('256s', ifname[:15]))
        ip = socket.inet_ntoa(res[20:24])
        return ip
    except Exception:
        return None

# Determine gateway and targets
gw = get_default_gateway()
if gw is None:
    debug("Default gateway not found; using placeholder --")
    gw = "--"
targets = [("gw", gw), ("dns", "208.67.222.222")]

# Initialize ping_results keys
with ping_lock:
    for name, _ in targets:
        ping_results[name] = None

# Start ping threads
for name, addr in targets:
    if addr == "--":
        continue
    t = threading.Thread(target=ping_worker, args=(name, addr), daemon=True)
    t.start()

# Marquee state
display_width = device.width
top_marquee_offset = 0.0
bottom_marquee_offset = 0.0
last_frame_time = time.time()

def fit(s, n=21):
    return s if len(s) <= n else s[:n-1] + ""

# Main loop
try:
    while True:
        now = time.time()
        dt = now - last_frame_time
        last_frame_time = now

        # Date and weather (top line)
        date_s = datetime.now().strftime("%Y-%m-%d %a")
        weather_s = get_weather_text()
        top_text = f"{date_s} {weather_s}"

        # CPU/RAM stats (middle lines)
        cpu_percent, ram_percent, ram_used_gb, ram_total_gb, cpu_temp = get_system_stats()
        if cpu_temp is not None:
            temp_s = f"{cpu_temp:.0f}C"
        else:
            temp_s = "N/A"
        cpu_s = f"CPU {cpu_percent:.0f}%"
        ram_s = f"RAM {ram_percent:.0f}%"
        mem_s = f"{ram_used_gb:.1f}/{ram_total_gb:.1f}GB"
        line1 = f"{cpu_s} {temp_s}"
        line2 = f"{ram_s} {mem_s}"

        # Top marquee update
        t_w, t_h = measure_text_px(top_text, font)
        top_needs = t_w > display_width
        if top_needs:
            top_marquee_offset += MARQUEE_SPEED_PX_PER_SEC * dt
            top_marquee_offset %= (t_w + MARQUEE_GAP_PX)
        else:
            top_marquee_offset = 0.0

        # Bottom combined text (gw, dns, ip, hostname)
        hostname = get_hostname()
        wlan_ip = get_wireless_ip("wlan0") or get_wireless_ip("wlan") or None
        if not wlan_ip:
            # fallback: first non-loopback IPv4
            try:
                addrs = psutil.net_if_addrs()
                for ifname, addrs_list in addrs.items():
                    for a in addrs_list:
                        if a.family == socket.AF_INET and not a.address.startswith("127."):
                            wlan_ip = a.address
                            break
                    if wlan_ip:
                        break
            except Exception:
                wlan_ip = None
        ip_display = wlan_ip or "no-ip"

        with ping_lock:
            gw_rt = ping_results.get("gw")
            dns_rt = ping_results.get("dns")
        gw_s = f"GW {int(gw_rt)}ms" if isinstance(gw_rt, (int, float)) else "GW -- ms"
        dns_s = f"DNS {int(dns_rt)}ms" if isinstance(dns_rt, (int, float)) else "DNS -- ms"

        bottom_text = f"{gw_s} | {dns_s} | IP {ip_display} | {hostname}"

        b_w, b_h = measure_text_px(bottom_text, font)
        bottom_needs = b_w > display_width
        if bottom_needs:
            bottom_marquee_offset += MARQUEE_SPEED_PX_PER_SEC * dt
            bottom_marquee_offset %= (b_w + MARQUEE_GAP_PX)
        else:
            bottom_marquee_offset = 0.0

        # Draw to display (4 rows: top marquee, CPU, RAM, bottom marquee)
        with canvas(device) as draw:
            # Top
            if top_needs:
                x = -int(top_marquee_offset)
                draw.text((x, 0), top_text, font=font, fill="white")
                draw.text((x + t_w + MARQUEE_GAP_PX, 0), top_text, font=font, fill="white")
            else:
                draw.text((0, 0), top_text if len(top_text) <= 21 else fit(top_text), font=font, fill="white")

            # Middle fixed lines
            draw.text((0, 14), fit(line1), font=font, fill="white")
            draw.text((0, 28), fit(line2), font=font, fill="white")

            # Bottom
            if bottom_needs:
                bx = -int(bottom_marquee_offset)
                draw.text((bx, 42), bottom_text, font=font, fill="white")
                draw.text((bx + b_w + MARQUEE_GAP_PX, 42), bottom_text, font=font, fill="white")
            else:
                draw.text((0, 42), bottom_text if len(bottom_text) <= 21 else fit(bottom_text), font=font, fill="white")

        sleep(0.03)
except KeyboardInterrupt:
    pass