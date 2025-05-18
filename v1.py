import tkinter as tk
from tkinter import filedialog, ttk
import numpy as np
import time
import threading
import queue
import random
from datetime import datetime
from PIL import Image, ImageTk

class CPU:
    def __init__(self):
        self.registers = np.zeros(256, dtype=np.uint64)
        self.pc = np.uint64(0)

    def execute_instruction(self, instruction):
        log_queue.put(('success', f"Executing instruction: 0x{instruction:016x}"))
        self.pc += 8  # Adjusted for 64-bit instructions

class Memory:
    def __init__(self, size):
        self.memory = np.zeros(size // 8, dtype=np.uint64)

    def read(self, address):
        return self.memory[address // 8]

    def write(self, address, value):
        self.memory[address // 8] = value

class Emulator:
    def __init__(self):
        self.cpu = CPU()
        self.memory = Memory(16 * 1024 * 1024 * 1024)  # 16GB
        self.is_running = False
        self.game_loaded = False
        self.framebuffer = np.zeros((64, 64, 4), dtype=np.uint8)  # 64x64 RGBA framebuffer

    def load_game(self, game_data):
        log_queue.put(('warning', 'Loading game...'))
        for i in range(0, len(game_data), 8):
            value = np.frombuffer(game_data[i:i+8], dtype=np.uint64)[0] if i+8 <= len(game_data) else 0
            self.memory.write(i, value)
        self.game_loaded = True
        log_queue.put(('success', 'Game loaded successfully.'))
        status_queue.put(('Game loaded', 'success'))

    def start(self):
        if not self.game_loaded:
            log_queue.put(('error', 'No game loaded!'))
            return
        self.is_running = True
        log_queue.put(('success', 'Emulator started.'))
        status_queue.put(('Running', 'success'))

    def pause(self):
        self.is_running = False
        log_queue.put(('warning', 'Emulator paused.'))
        status_queue.put(('Paused', 'warning'))

    def stop(self):
        self.is_running = False
        self.cpu.pc = 0
        log_queue.put(('error', 'Emulator stopped.'))
        status_queue.put(('Stopped', 'error'))

    def run_cycle(self):
        if not self.is_running:
            return
        instruction = self.memory.read(self.cpu.pc)
        self.cpu.execute_instruction(instruction)
        if self.is_running:
            # Simulate graphics by updating a random pixel in the framebuffer
            x = random.randint(0, 63)
            y = random.randint(0, 63)
            self.framebuffer[y, x] = [random.randint(0, 255), random.randint(0, 255), random.randint(0, 255), 255]
        if self.cpu.pc >= len(self.memory.memory) * 8:
            self.stop()

class EmulatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("PS5 Emulator PoC")
        self.root.geometry("600x400")
        self.root.configure(bg='#1e1e1e')
        self.emulator = Emulator()
        self.frame_count = 0
        self.last_frame_time = time.time()
        self.photo = None  # Reference for PhotoImage
        self.setup_ui()
        self.log_queue = queue.Queue()
        self.status_queue = queue.Queue()
        self.running = True
        self.update_thread = threading.Thread(target=self.update_loop, daemon=True)
        self.update_thread.start()

    def setup_ui(self):
        style = ttk.Style()
        style.configure('TButton', background='#007acc', foreground='white', font=('Segoe UI', 10))
        style.configure('TLabel', background='#1e1e1e', foreground='white', font=('Segoe UI', 10))
        style.map('TButton', background=[('active', '#005999')])

        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Toolbar frame (inspired by Dolphin's top toolbar)
        toolbar_frame = ttk.Frame(main_frame)
        toolbar_frame.pack(fill=tk.X, pady=5)
        buttons = [
            ('Start', self.emulator.start),
            ('Pause', self.emulator.pause),
            ('Stop', self.emulator.stop),
            ('Load Game', self.load_game),
            ('Config', self.show_config)
        ]
        for text, command in buttons:
            ttk.Button(toolbar_frame, text=text, command=command).pack(side=tk.LEFT, padx=5)

        # Main display area (canvas for graphical output)
        self.canvas = tk.Canvas(main_frame, width=560, height=180, bg='black', highlightthickness=0)
        self.canvas.pack(pady=10)

        # Status and performance frame
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=5)
        self.status_label = ttk.Label(status_frame, text="Status: Idle")
        self.status_label.pack(side=tk.LEFT, padx=10)
        self.fps_label = ttk.Label(status_frame, text="FPS: 0")
        self.fps_label.pack(side=tk.LEFT, padx=10)
        self.cpu_label = ttk.Label(status_frame, text="CPU Usage: 0%")
        self.cpu_label.pack(side=tk.LEFT, padx=10)
        self.ram_label = ttk.Label(status_frame, text="RAM Usage: 0 MB")
        self.ram_label.pack(side=tk.LEFT, padx=10)

        # Log area (bottom, like Dolphin's log window)
        self.log_text = tk.Text(main_frame, height=5, width=70, bg='#323232', fg='#00ff00', font=('Courier', 10))
        self.log_text.pack(pady=5)
        self.log_text.config(state='disabled')

    def load_game(self):
        file_path = filedialog.askopenfilename(filetypes=[("Game files", "*.bin *.iso")])
        if file_path:
            with open(file_path, 'rb') as f:
                game_data = f.read()
            self.emulator.load_game(game_data)

    def show_config(self):
        log_queue.put(('warning', 'Configuration window opened (not implemented in this PoC)'))

    def update_loop(self):
        target_fps = 60
        frame_time = 1.0 / target_fps
        while self.running:
            start_time = time.time()
            self.emulator.run_cycle()
            self.update_canvas()
            self.update_logs()
            self.update_status()
            self.frame_count += 1
            if time.time() - self.last_frame_time >= 1.0:
                self.update_performance()
                self.frame_count = 0
                self.last_frame_time = time.time()
            elapsed = time.time() - start_time
            sleep_time = max(0, frame_time - elapsed)
            time.sleep(sleep_time)

    def update_canvas(self):
        self.canvas.delete("all")
        # Display framebuffer as an image
        img = Image.fromarray(self.emulator.framebuffer, 'RGBA').convert('RGB')
        self.photo = ImageTk.PhotoImage(img)
        self.canvas.create_image(0, 0, image=self.photo, anchor='nw')
        # Overlay CPU status
        self.canvas.create_text(70, 10, text=f"PC: 0x{self.emulator.cpu.pc:016x}", fill="white", font=('Segoe UI', 10), anchor='nw')
        regs = ', '.join(map(str, self.emulator.cpu.registers[:8]))
        self.canvas.create_text(70, 30, text=f"Registers: {regs}...", fill="white", font=('Segoe UI', 10), anchor='nw')

    def update_logs(self):
        while not self.log_queue.empty():
            type_, message = self.log_queue.get()
            self.log_text.config(state='normal')
            timestamp = datetime.now().strftime("%H:%M:%S")
            color = {'success': '#4caf50', 'warning': '#ff9800', 'error': '#f44336'}.get(type_, '#00ff00')
            self.log_text.insert(tk.END, f"[{timestamp}] {message}\n", type_)
            self.log_text.tag_configure(type_, foreground=color)
            self.log_text.config(state='disabled')
            self.log_text.see(tk.END)

    def update_status(self):
        while not self.status_queue.empty():
            status, type_ = self.status_queue.get()
            self.status_label.config(text=f"Status: {status}")
            color = {'success': '#4caf50', 'warning': '#ff9800', 'error': '#f44336'}.get(type_, 'white')
            self.status_label.config(foreground=color)

    def update_performance(self):
        self.fps_label.config(text=f"FPS: {self.frame_count}")
        self.cpu_label.config(text=f"CPU Usage: {random.randint(0, 100)}%")
        self.ram_label.config(text=f"RAM Usage: {random.randint(4000, 12000)} MB")

    def destroy(self):
        self.running = False
        self.update_thread.join()
        self.root.destroy()

if __name__ == "__main__":
    log_queue = queue.Queue()
    status_queue = queue.Queue()
    root = tk.Tk()
    app = EmulatorApp(root)
    root.mainloop()
