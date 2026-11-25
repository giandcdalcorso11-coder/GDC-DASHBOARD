#!/usr/bin/env python3
"""Pannello per iPad: server per Windows (solo libreria standard di Python).

Serve la pagina web in web/ e offre alla pagina:
  - stato di Spotify (brano/artista, letto dal titolo della finestra dell'app desktop)
  - uso di CPU e RAM del PC
  - pulsanti personalizzabili (buttons.json) in stile Stream Deck
Su Windows invia tasti e comandi; su altri sistemi li simula (utile per provare).
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, "web")
CONFIG = os.path.join(BASE, "buttons.json")
IS_WIN = os.name == "nt"
DEMO = os.environ.get("PANEL_DEMO") == "1"

DEFAULT_CFG = {"settings": {"port": 8080, "token": "", "columns": 4, "columnsPortrait": 3}, "buttons": []}


def log(*a):
    try:
        print(*a, flush=True)
    except Exception:
        pass


# ---------------------------------------------------------------- configurazione
_cfg = {"mtime": None, "data": DEFAULT_CFG}


def load_config():
    try:
        m = os.path.getmtime(CONFIG)
    except OSError:
        m = 0
    if m != _cfg["mtime"]:
        try:
            with open(CONFIG, encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("settings", {})
            data.setdefault("buttons", [])
            _cfg["data"] = data
        except Exception as e:
            log("buttons.json non valido, tengo la versione precedente:", e)
        _cfg["mtime"] = m
    return _cfg["data"], _cfg["mtime"]


# ---------------------------------------------------------------- Windows API
if IS_WIN:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    def _ft(ft):
        return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

    _pid_exe = {}

    def _exe_of(pid):
        if pid in _pid_exe:
            return _pid_exe[pid]
        exe = ""
        h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                exe = os.path.basename(buf.value).lower()
            kernel32.CloseHandle(h)
        _pid_exe[pid] = exe
        return exe

    def spotify_titles():
        """Titoli delle finestre di Spotify.exe (None se Spotify non e' aperto)."""
        titles, found = [], [False]

        def cb(hwnd, _):
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            if not cls.value.startswith("Chrome_WidgetWin"):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if _exe_of(pid.value) != "spotify.exe":
                return True
            found[0] = True
            n = user32.GetWindowTextLengthW(hwnd)
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                titles.append(buf.value)
            return True

        user32.EnumWindows(ENUMPROC(cb), 0)
        return titles if found[0] else None

    _cpu_prev = [None]

    def cpu_percent():
        idle, kern, usr = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(usr)):
            return 0
        cur = (_ft(idle), _ft(kern) + _ft(usr))
        prev, _cpu_prev[0] = _cpu_prev[0], cur
        if not prev or cur[1] == prev[1]:
            return 0
        return max(0, min(100, round(100 * (1 - (cur[0] - prev[0]) / (cur[1] - prev[1])))))

    def ram_percent():
        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return int(m.dwMemoryLoad)
else:
    _cpu_prev = [None]

    def spotify_titles():
        return None

    def cpu_percent():
        try:
            with open("/proc/stat") as f:
                v = [int(x) for x in f.readline().split()[1:]]
            cur = (v[3] + v[4], sum(v))
            prev, _cpu_prev[0] = _cpu_prev[0], cur
            if not prev or cur[1] == prev[1]:
                return 0
            return round(100 * (1 - (cur[0] - prev[0]) / (cur[1] - prev[1])))
        except Exception:
            return 0

    def ram_percent():
        try:
            d = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, v = line.split(":")
                    d[k] = int(v.split()[0])
            return round(100 * (1 - d["MemAvailable"] / d["MemTotal"]))
        except Exception:
            return 0


# ---------------------------------------------------------------- tasti
VK = {"ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "enter": 0x0D, "esc": 0x1B,
      "escape": 0x1B, "space": 0x20, "tab": 0x09, "backspace": 0x08, "delete": 0x2E, "del": 0x2E,
      "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23,
      "pageup": 0x21, "pagedown": 0x22, "printscreen": 0x2C, "insert": 0x2D,
      "playpause": 0xB3, "next": 0xB0, "prev": 0xB1, "stop": 0xB2,
      "mute": 0xAD, "voldown": 0xAE, "volup": 0xAF}
EXTENDED = {0xB0, 0xB1, 0xB2, 0xB3, 0xAD, 0xAE, 0xAF, 0x26, 0x28, 0x25, 0x27, 0x24, 0x23, 0x21, 0x22, 0x2E, 0x2D}
MEDIA = {"playpause", "next", "prev", "stop", "mute", "voldown", "volup"}


def vk_for(name):
    n = name.strip().lower()
    if n in VK:
        return VK[n]
    if len(n) == 1 and n.isalnum():
        return ord(n.upper())
    if n.startswith("f") and n[1:].isdigit() and 1 <= int(n[1:]) <= 24:
        return 0x70 + int(n[1:]) - 1
    raise ValueError("tasto sconosciuto: " + name)


def send_keys(combo):
    codes = [vk_for(p) for p in combo.split("+")]
    if not IS_WIN:
        log("[simulato] tasti:", combo)
        return
    for c in codes:
        user32.keybd_event(c, 0, 1 if c in EXTENDED else 0, 0)
        time.sleep(0.01)
    for c in reversed(codes):
        user32.keybd_event(c, 0, (1 if c in EXTENDED else 0) | 2, 0)


def run_action(a):
    t = a.get("type")
    if t == "hotkey":
        send_keys(a["keys"])
    elif t == "media":
        if a.get("cmd") not in MEDIA:
            raise ValueError("comando media non valido")
        send_keys(a["cmd"])
    elif t == "url":
        url = a["url"]
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("solo http/https")
        if IS_WIN:
            os.startfile(url)
        else:
            log("[simulato] apri", url)
    elif t == "run":
        cmd = [a["path"]] + [str(x) for x in a.get("args", [])]
        if IS_WIN:
            subprocess.Popen(cmd, close_fds=True)
        else:
            log("[simulato] avvia", cmd)
    elif t == "lock":
        if IS_WIN:
            subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
        else:
            log("[simulato] blocca PC")
    else:
        raise ValueError("azione sconosciuta: %s" % t)


# ---------------------------------------------------------------- stato (aggiornato ogni secondo)
IDLE_TITLES = ("", "spotify", "spotify free", "spotify premium")
STATE = {"spotify": {"running": False, "playing": False, "title": "", "artist": ""},
         "stats": {"cpu": 0, "ram": 0}}


def read_spotify():
    if DEMO:
        return {"running": True, "playing": True, "title": "Instant Crush", "artist": "Daft Punk"}
    titles = spotify_titles()
    if titles is None:
        return {"running": False, "playing": False, "title": "", "artist": ""}
    for t in titles:
        if t.strip().lower() not in IDLE_TITLES:
            artist, sep, title = t.partition(" - ")
            if not sep:
                artist, title = "", t
            return {"running": True, "playing": True, "title": title.strip(), "artist": artist.strip()}
    return {"running": True, "playing": False, "title": "", "artist": ""}


def sampler():
    while True:
        try:
            STATE["spotify"] = read_spotify()
            STATE["stats"] = {"cpu": cpu_percent(), "ram": ram_percent()}
        except Exception as e:
            log("errore lettura stato:", e)
        time.sleep(1)


# ---------------------------------------------------------------- HTTP
TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".png": "image/png", ".ico": "image/x-icon"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self, query):
        token = load_config()[0]["settings"].get("token", "")
        return not token or query.get("t", [""])[0] == token

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path.startswith("/api/"):
            if not self._authorized(q):
                return self._send(401, {"error": "token"})
            data, ver = load_config()
            if u.path == "/api/config":
                s = data["settings"]
                btns = [{"id": b.get("id"), "label": b.get("label", ""), "icon": b.get("icon", ""),
                         "color": b.get("color", "")} for b in data["buttons"]]
                return self._send(200, {"version": ver, "columns": s.get("columns", 4),
                                        "columnsPortrait": s.get("columnsPortrait", 3), "buttons": btns})
            if u.path == "/api/state":
                return self._send(200, dict(STATE, version=ver))
            return self._send(404, {"error": "not found"})
        name = "index.html" if u.path == "/" else u.path.lstrip("/")
        full = os.path.realpath(os.path.join(WEB, name))
        if not full.startswith(os.path.realpath(WEB) + os.sep) or not os.path.isfile(full):
            return self._send(404, b"not found", "text/plain")
        with open(full, "rb") as f:
            self._send(200, f.read(), TYPES.get(os.path.splitext(full)[1], "application/octet-stream"))

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._authorized(q):
            return self._send(401, {"error": "token"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            if u.path == "/api/media":
                run_action({"type": "media", "cmd": body.get("cmd")})
            elif u.path == "/api/press":
                btn = next((b for b in load_config()[0]["buttons"] if b.get("id") == body.get("id")), None)
                if not btn:
                    return self._send(404, {"error": "pulsante sconosciuto"})
                run_action(btn.get("action", {}))
            else:
                return self._send(404, {"error": "not found"})
            self._send(200, {"ok": True})
        except Exception as e:
            log("errore azione:", e)
            self._send(400, {"error": str(e)})


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "IP-DEL-PC"


def main():
    cfg = load_config()[0]
    port = int(os.environ.get("PANEL_PORT") or (sys.argv[1] if len(sys.argv) > 1 else cfg["settings"].get("port", 8080)))
    threading.Thread(target=sampler, daemon=True).start()
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    except OSError as e:
        log("Impossibile usare la porta %d: %s" % (port, e))
        sys.exit(1)
    srv.daemon_threads = True
    tok = cfg["settings"].get("token", "")
    log("Pannello attivo. Sull'iPad apri:  http://%s:%d/%s" % (local_ip(), port, ("?t=" + tok) if tok else ""))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
