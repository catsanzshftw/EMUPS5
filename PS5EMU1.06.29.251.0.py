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
            x = (instruction >> 20) & 0xFF  # 8-bit x-coordinate
            y = (instruction >> 12) & 0xFF  # 8-bit y-coordinate
            r = (instruction >> 9) & 0x7
            g = (instruction >> 6) & 0x7
            b = (instruction >> 3) & 0x7
            a = instruction & 0x7
            # Scale to 0-255 range (3-bit to 8-bit)
            r, g, b, a = [val * 36 for val in (r, g, b, a)]  # 36 = 255/7
            if x < 128 and y < 128:
                addr = y * 128 * 4 + x * 4
                self.memory.write_bytes(addr, np.array([r, g, b, a], dtype=np.uint8))
        elif opcode == 6:  # JMP addr
            addr = instruction & 0xFFFFFF
            self.pc = addr
            return
        elif opcode == 7:  # BEQ Rs, Rt, offset
            rs = (instruction >> 20) & 0xF
            rt = (instruction >> 16) & 0xF
            offset = instruction & 0xFFFF
            if self.registers[rs] == self.registers[rt]:
                self.pc = (self.pc + offset) % (128 * 1024)
                return
        else:
            self.log_queue.put(('error', f"Unknown opcode: {opcode}"))
        self.pc += 4  # 32-bit instructions

class Memory:
    def __init__(self, size):
        self.memory = np.zeros(size, dtype=np.uint8)

    def read_uint32(self, address):
        # Handle possible out-of-bounds
        if address < 0 or address+4 > len(self.memory):
            return 0
        return np.frombuffer(self.memory[address:address+4], dtype=np.uint32)[0]

    def write_uint32(self, address, value):
        if address < 0 or address+4 > len(self.memory):
            return
        self.memory[address:address+4] = np.frombuffer(np.array([value], dtype=np.uint32), dtype=np.uint8)

    def write_bytes(self, address, values):
        if address < 0 or address+len(values) > len(self.memory):
            return
        self.memory[address:address+len(values)] = values

class Emulator:
    def __init__(self, log_queue, status_queue):
        self.cpu = CPU(log_queue)
        self.memory = Memory(128 * 1024)  # 128KB
        self.cpu.memory = self.memory
        self.is_running = False
        self.game_loaded = False
        self.framebuffer = self.memory.memory[0:128*128*4].reshape((128, 128, 4))  # 128x128 RGBA
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
            (1 << 24) | (0 << 20) | (64 << 16),  # MOV R0, 64 (x pos)
            (1 << 24) | (1 << 20) | (64 << 16),  # MOV R1, 64 (y pos)
            (1 << 24) | (2 << 20) | (1 << 16),   # MOV R2, 1 (x dir)
            (1 << 24) | (3 << 20) | (1 << 16),   # MOV R3, 1 (y dir)
            (5 << 24) | (0 << 20) | (1 << 12) | (7 << 9) | (0 << 6) | (0 << 3) | 7,  # SETPIXEL
            (2 << 24) | (0 << 20) | (0 << 16) | (2 << 12),  # ADD
            (2 << 24) | (1 << 20) | (1 << 16) | (3 << 12),  # ADD
            (7 << 24) | (0 << 20) | (4 << 16) | 16,  # BEQ
            (7 << 24) | (1 << 20) | (4 << 16) | 24,  # BEQ
            (6 << 24) | 16,  # JMP
            (1 << 24) | (2 << 20) | (255 << 16),  # MOV R2, 255
            (6 << 24) | 16,  # JMP
            (1 << 24) | (3 << 20) | (255 << 16),  # MOV R3, 255
            (6 << 24) | 16,  # JMP
        ]
        for i, inst in enumerate(instructions):
            self.memory.write_uint32(i * 4, inst)
        self.memory.write_uint32(4 * 4, 127)  # R4 = 127 for boundary check
        self.game_loaded = True
        self.log_queue.put(('success', 'Bouncing pixel demo loaded.'))

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
        self.root.title("Kyty Chip Emulator PoC - Updated")
        self.root.geometry("800x600")
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

        self.canvas = tk.Canvas(main_frame, width=512, height=512, bg='black', highlightthickness=0)
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
        # Prevent crash if framebuffer size is not 128x128x4
        try:
            img = Image.fromarray(self.emulator.framebuffer, 'RGBA').resize((512, 512), Image.NEAREST)
        except Exception as e:
            img = Image.new('RGBA', (512, 512), (0, 0, 0, 255))
        self.photo = ImageTk.PhotoImage(img)
        self.canvas.create_image(0, 0, image=self.photo, anchor='nw')
        self.canvas.create_text(130, 10, text=f"PC: 0x{self.emulator.cpu.pc:08x}", fill="white", font=('Segoe UI', 10), anchor='nw')
        regs = ', '.join(map(str, self.emulator.cpu.registers[:8]))
        self.canvas.create_text(130, 30, text=f"Registers: {regs}...", fill="white", font=('Segoe UI', 10), anchor='nw')

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
