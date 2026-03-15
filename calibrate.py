import subprocess
import os
import json
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
from pathlib import Path
from utils import BASE_DIR, CONFIG_FILE, load_json, save_json, logger


class CalibrationTool:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("HI3 Archive - Subtitle Region Calibration")
        
        self.image = None
        self.photo = None
        self.canvas = None
        self.rect_id = None
        self.start_x = None
        self.start_y = None
        self.current_rect = None
        
        self.setup_ui()
    
    def setup_ui(self):
        control_frame = tk.Frame(self.root)
        control_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        
        tk.Button(control_frame, text="Load Sample Frame", command=self.load_frame).pack(side=tk.LEFT, padx=5)
        tk.Button(control_frame, text="Extract Frame from URL", command=self.extract_from_url).pack(side=tk.LEFT, padx=5)
        tk.Button(control_frame, text="Save Config", command=self.save_config).pack(side=tk.LEFT, padx=5)
        
        self.status_var = tk.StringVar(value="Load an image or extract from YouTube URL")
        tk.Label(control_frame, textvariable=self.status_var).pack(side=tk.RIGHT, padx=5)
        
        canvas_frame = tk.Frame(self.root)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.canvas = tk.Canvas(canvas_frame, bg='black', width=1280, height=720)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        
        info_frame = tk.Frame(self.root)
        info_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=5)
        
        self.coord_var = tk.StringVar(value="Selection: None")
        tk.Label(info_frame, textvariable=self.coord_var, font=("Courier", 10)).pack(side=tk.LEFT)
        
        current_config = load_json(CONFIG_FILE) if CONFIG_FILE.exists() else {}
        crop = current_config.get("subtitle_crop", {})
        if crop:
            self.current_rect = (crop.get("x", 0), crop.get("y", 0), 
                                 crop.get("x", 0) + crop.get("width", 0),
                                 crop.get("y", 0) + crop.get("height", 0))
            self.update_coord_display()
    
    def load_frame(self):
        filepath = filedialog.askopenfilename(
            title="Select Sample Frame",
            filetypes=[("Image files", "*.png *.jpg *.jpeg"), ("All files", "*.*")]
        )
        if filepath:
            self.display_image(filepath)
    
    def extract_from_url(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Extract Frame from YouTube")
        dialog.geometry("500x100")
        
        tk.Label(dialog, text="YouTube URL:").pack(padx=5, pady=5)
        url_entry = tk.Entry(dialog, width=60)
        url_entry.pack(padx=5, pady=5)
        
        def extract():
            url = url_entry.get().strip()
            if not url:
                return
            
            dialog.destroy()
            self.status_var.set("Extracting frame from video...")
            self.root.update()
            
            try:
                result = subprocess.run(
                    ["yt-dlp", "-g", "-f", "bv[height<=720]", url],
                    capture_output=True, text=True, timeout=60
                )
                
                if result.returncode != 0:
                    messagebox.showerror("Error", f"Failed to get stream URL: {result.stderr}")
                    return
                
                stream_url = result.stdout.strip().split('\n')[0]
                
                sample_path = BASE_DIR / "sample_frame.png"
                
                ffmpeg_result = subprocess.run(
                    ["ffmpeg", "-y", "-ss", "60", "-i", stream_url, 
                     "-frames:v", "1", "-q:v", "2", str(sample_path)],
                    capture_output=True, text=True, timeout=60
                )
                
                if ffmpeg_result.returncode != 0:
                    messagebox.showerror("Error", f"Failed to extract frame: {ffmpeg_result.stderr}")
                    return
                
                self.display_image(str(sample_path))
                self.status_var.set("Frame extracted. Draw rectangle over subtitle area.")
                
            except subprocess.TimeoutExpired:
                messagebox.showerror("Error", "Operation timed out")
            except Exception as e:
                messagebox.showerror("Error", str(e))
        
        tk.Button(dialog, text="Extract", command=extract).pack(pady=5)
    
    def display_image(self, filepath):
        try:
            self.image = Image.open(filepath)
            
            canvas_width = self.canvas.winfo_width()
            canvas_height = self.canvas.winfo_height()
            
            img_width, img_height = self.image.size
            scale = min(canvas_width / img_width, canvas_height / img_height, 1.0)
            
            self.scale = scale
            self.img_offset_x = (canvas_width - int(img_width * scale)) // 2
            self.img_offset_y = (canvas_height - int(img_height * scale)) // 2
            
            display_img = self.image.resize(
                (int(img_width * scale), int(img_height * scale)),
                Image.Resampling.LANCZOS
            )
            
            self.photo = ImageTk.PhotoImage(display_img)
            self.canvas.delete("all")
            self.canvas.create_image(self.img_offset_x, self.img_offset_y, anchor=tk.NW, image=self.photo)
            
            if self.current_rect:
                self.draw_rect()
            
            self.status_var.set(f"Loaded: {filepath} ({img_width}x{img_height})")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load image: {e}")
    
    def on_press(self, event):
        if self.photo is None:
            return
        self.start_x = event.x
        self.start_y = event.y
    
    def on_drag(self, event):
        if self.start_x is None:
            return
        
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, event.x, event.y,
            outline='red', width=2
        )
    
    def on_release(self, event):
        if self.start_x is None:
            return
        
        x1 = int((min(self.start_x, event.x) - self.img_offset_x) / self.scale)
        y1 = int((min(self.start_y, event.y) - self.img_offset_y) / self.scale)
        x2 = int((max(self.start_x, event.x) - self.img_offset_x) / self.scale)
        y2 = int((max(self.start_y, event.y) - self.img_offset_y) / self.scale)
        
        x1 = max(0, x1)
        y1 = max(0, y1)
        if self.image:
            x2 = min(self.image.width, x2)
            y2 = min(self.image.height, y2)
        
        self.current_rect = (x1, y1, x2, y2)
        self.update_coord_display()
        
        self.start_x = None
        self.start_y = None
    
    def draw_rect(self):
        if not self.current_rect or not hasattr(self, 'scale'):
            return
        
        x1, y1, x2, y2 = self.current_rect
        cx1 = int(x1 * self.scale + self.img_offset_x)
        cy1 = int(y1 * self.scale + self.img_offset_y)
        cx2 = int(x2 * self.scale + self.img_offset_x)
        cy2 = int(y2 * self.scale + self.img_offset_y)
        
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(cx1, cy1, cx2, cy2, outline='red', width=2)
    
    def update_coord_display(self):
        if self.current_rect:
            x1, y1, x2, y2 = self.current_rect
            width = x2 - x1
            height = y2 - y1
            self.coord_var.set(f"Selection: x={x1}, y={y1}, width={width}, height={height}")
        else:
            self.coord_var.set("Selection: None")
    
    def save_config(self):
        if not self.current_rect:
            messagebox.showwarning("Warning", "No region selected")
            return
        
        config = load_json(CONFIG_FILE) if CONFIG_FILE.exists() else {}
        target_quality = config.get("video_quality", 720)
        
        if self.image:
            img_height = self.image.height
            if img_height > target_quality:
                if not messagebox.askyesno(
                    "Resolution Mismatch",
                    f"Calibration image is {self.image.width}x{img_height}, but video_quality is set to {target_quality}p.\n\n"
                    f"Crop coordinates will be invalid for {target_quality}p videos.\n\n"
                    "Use 'Extract Frame from URL' to get a frame at the correct resolution.\n\n"
                    "Save anyway?"
                ):
                    return
        
        x1, y1, x2, y2 = self.current_rect
        width = x2 - x1
        height = y2 - y1
        
        config["subtitle_crop"] = {
            "x": x1,
            "y": y1,
            "width": width,
            "height": height
        }
        
        save_json(CONFIG_FILE, config)
        messagebox.showinfo("Success", f"Saved to {CONFIG_FILE}")
        logger.info(f"Saved crop config: x={x1}, y={y1}, width={width}, height={height}")
    
    def run(self):
        self.root.mainloop()


def main():
    tool = CalibrationTool()
    tool.run()


if __name__ == "__main__":
    main()
