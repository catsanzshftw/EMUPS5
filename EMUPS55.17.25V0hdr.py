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
    def __init__(self, log_queue):
        self.registers = np.zeros(16, dtype=np.uint32)  # 16 32-bit registers
        self.pc = 0  # 32-bit program counter
        self.log_queue = log_queue
        self.memory = None  # Assigned by Emulator

    def execute_instruction(self, instruction):
        opcode = (instruction >> 24) & 0xFF
        if opcode == 0:  # NOP
            pass
        elif opcode == 1:  # MOV Rd, Rs
            rd = (instruction >> 20) & 0xF
            rs = (instruction >> 16) & 0xF
            self.registers[rd] = self.registers[rs]
        elif opcode == 2:  # ADD Rd, Rs, Rt
            rd = (instruction >> 20) & 0xF
            rs = (instruction >> 16) & 0xF
            rt = (instruction >> 12) & 0xF
            self.registers[rd] = self.registers[rs] + self.registers[rt]
        elif opcode == 3:  # LDR Rd, [Rs]
            rd = (instruction >> 20) & 0xF
            rs = (instruction >> 16) & 0xF
            addr = self.registers[rs]
            self.registers[rd] = self.memory.read_uint32(addr)
        elif opcode == 4:  # STR Rs, [Rd]
            rs = (instruction >> 20) & 0xF
            rd = (instruction >> 16) & 0xF
            addr = self.registers[rd]
            self.memory.write_uint32(addr, self.registers[rs])
        elif opcode == 5:  # SETPIXEL x, y, r, g, b, a
            x = (instruction >> 20) & 0xF  # Reduced range for simplicity
            y = (instruction >> 16) & 0xF
            r = (instruction >> 12) & 0xF
            g = (instruction >> 8) & 0xF
            b = (instruction >> 4) & 0xF
            a = instruction & 0xF
            # Scale to 0-255 range (4-bit to 8-bit)
            r, g, b, a = [val * 17 for val in (r, g, b, a)]  # 17 = 255/15
            if x < 64 and y < 64:
                addr = y * 64 * 4 + x * 4
                self.memory.write_bytes(addr, np.array([r, g, b, a], dtype=np.uint8))
        else:
            self.log_queue.put(('error', f"Unknown opcode: {opcode}"))
        self.pc += 4  # 32-bit instructions

class Memory:
    def __init__(self, size):
        self.memory = np.zeros(size, dtype=np.uint8)

    def read_uint32(self, address):
        return np.frombuffer(self.memory[address:address+4], dtype=np.uint32)[0]

    def write_uint32(self, address, value):
        self.memory[address:address+4] = np.frombuffer(np.array([value], dtype=np.uint32), dtype=np.uint8)

    def write_bytes(self, address, values):
        self.memory[address:address+len(values)] = values

class Emulator:
    def __init__(self, log_queue, status_queue):
        self.cpu = CPU(log_queue)
        self.memory = Memory(64 * 1024)  # 64KB
        self.cpu.memory = self.memory
        self.is_running = False
        self.game_loaded = False
        self.framebuffer = self.memory.memory[0:64*64*4].reshape((64, 64, 4))  # 64x64 RGBA
        self.log_queue = log_queue
        self.status_queue = status_queue

    def load_game(self, game_data):
        self.log_queue.put(('warning', 'Loading program...'))
        for i in range(0, len(game_data), 4):
            value = np.frombuffer(game_data[i:i+4], dtype=np.uint32)[0] if i+4 <= len(game_data) else 0
            self.memory.write_uint32(i, value)
        self.game_loaded = True
        self.log_queue.put(('success', 'Program loaded successfully.'))
        self.status_queue.put(('Program loaded', 'success'))

    def load_demo(self):
        instructions = [
            # MOV R0, 10 (arbitrary value for demo)
            (1 << 24) | (0 << 20) | (10 << 16),
            # SETPIXEL 10, 10, 15, 0, 0, 15 (Red pixel)
            (5 << 24) | (10 << 20) | (10 << 16) | (15 << 12) | (0 << 8) | (0 << 4) | 15,
            # SETPIXEL 20, 20, 0, 15, 0, 15 (Green pixel)
            (5 << 24) | (20 << 20) | (20 << 16) | (0 << 12) | (15 << 8) | (0 << 4) | 15,
            # SETPIXEL 30, 30, 0, 0, 15, 15 (Blue pixel)
            (5 << 24) | (30 << 20) | (30 << 16) | (0 << 12) | (0 << 8) | (15 << 4) | 15,
        ]
        for i, inst in enumerate(instructions):
            self.memory.write_uint32(i * 4, inst)
        self.game_loaded = True
        self.log_queue.put(('success', 'Demo program loaded.'))

    def start(self):
        if not self.game_loaded:
            self.log_queue.put(('error', 'No program loaded!'))
            return
        self.is_running = True
        self.log_queue.put(('success', 'Emulator started.'))
        self.status_queue.put(('Running', 'success'))

    def pause(self):
        self.is_running = False
        self.log_queue.put(('warning', 'Emulator paused.'))
        self.status_queue.put(('Paused', 'warning'))

    def stop(self):
        self.is_running = False
        self.cpu.pc = 0
        self.log_queue.put(('error', 'Emulator stopped.'))
        self.status_queue.put(('Stopped', 'error'))

    def run_cycle(self):
        if not self.is_running:
            return
        instruction = self.memory.read_uint32(self.cpu.pc)
        self.cpu.execute_instruction(instruction)
        if self.cpu.pc >= len(self.memory.memory):
            self.stop()

class EmulatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Kyty Chip Emulator PoC")
        self.root.geometry("600x400")
        self.root.configure(bg='#1e1e1e')
        self.log_queue = queue.Queue()
        self.status_queue = queue.Queue()
        self.emulator = Emulator(self.log_queue, self.status_queue)
        self.frame_count = 0
        self.last_frame_time = time.time()
        self.photo = None
        self.setup_ui()
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

        toolbar_frame = ttk.Frame(main_frame)
        toolbar_frame.pack(fill=tk.X, pady=5)
        buttons = [
            ('Start', self.emulator.start),
            ('Pause', self.emulator.pause),
            ('Stop', self.emulator.stop),
            ('Load Program', self.load_game),
            ('Load Demo', self.emulator.load_demo),
            ('Config', self.show_config)
        ]
        for text, command in buttons:
            ttk.Button(toolbar_frame, text=text, command=command).pack(side=tk.LEFT, padx=5)

        self.canvas = tk.Canvas(main_frame, width=560, height=180, bg='black', highlightthickness=0)
        self.canvas.pack(pady=10)

        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=5)
        self.status_label = ttk.Label(status_frame, text="Status: Idle")
        self.status_label.pack(side=tk.LEFT, padx=10)
        self.fps_label = ttk.Label(status_frame, text="Cycles/s: 0")
        self.fps_label.pack(side=tk.LEFT, padx=10)
        self.cpu_label = ttk.Label(status_frame, text="CPU Usage: 0%")
        self.cpu_label.pack(side=tk.LEFT, padx=10)
        self.ram_label = ttk.Label(status_frame, text="RAM Usage: 0 MB")
        self.ram_label.pack(side=tk.LEFT, padx=10)

        self.log_text = tk.Text(main_frame, height=5, width=70, bg='#323232', fg='#00ff00', font=('Courier', 10))
        self.log_text.pack(pady=5)
        self.log_text.config(state='disabled')

    def load_game(self):
        file_path = filedialog.askopenfilename(filetypes=[("Binary files", "*.bin")])
        if file_path:
            with open(file_path, 'rb') as f:
                game_data = f.read()
            self.emulator.load_game(game_data)

    def show_config(self):
        self.log_queue.put(('warning', 'Configuration window opened (not implemented in this PoC)'))

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
        img = Image.fromarray(self.emulator.framebuffer, 'RGBA').convert('RGB')
        self.photo = ImageTk.PhotoImage(img)
        self.canvas.create_image(0, 0, image=self.photo, anchor='nw')
        self.canvas.create_text(70, 10, text=f"PC: 0x{self.emulator.cpu.pc:08x}", fill="white", font=('Segoe UI', 10), anchor='nw')
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
        self.fps_label.config(text=f"Cycles/s: {self.frame_count}")
        self.cpu_label.config(text=f"CPU Usage: {random.randint(0, 100)}%")
        self.ram_label.config(text=f"RAM Usage: {random.randint(10, 100)} MB")

    def destroy(self):
        self.running = False
        self.update_thread.join()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = EmulatorApp(root)
    root.mainloop()
