import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import os
import threading
import queue
import json
from dotenv import load_dotenv
from pcrs_scraper import run_scraper

class ScraperGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("PCRS Scraper - Desktop Edition")
        self.root.geometry("750x650")
        self.running = True
        
        # Load existing env vars
        load_dotenv()
        
        self.queue = queue.Queue()
        self._setup_ui()
        self._load_config()
        
        # Start checking for log messages
        self.root.after(100, self._process_queue)

    def _setup_ui(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Configuration Frame
        config_frame = ttk.LabelFrame(self.root, text="Configuration (Saved to .env)", padding=10)
        config_frame.pack(fill="x", padx=10, pady=5)
        
        # Domain
        ttk.Label(config_frame, text="PCRS Domain:").grid(row=0, column=0, sticky="w", pady=2)
        self.domain_var = tk.StringVar(value="pcrs.utm.utoronto.ca")
        self.domain_entry = ttk.Entry(config_frame, textvariable=self.domain_var, width=40)
        self.domain_entry.grid(row=0, column=1, sticky="w", padx=5)
        
        # Course ID
        ttk.Label(config_frame, text="Course ID:").grid(row=1, column=0, sticky="w", pady=2)
        self.course_var = tk.StringVar(value="209")
        self.course_entry = ttk.Entry(config_frame, textvariable=self.course_var, width=10)
        self.course_entry.grid(row=1, column=1, sticky="w", padx=5)
        
        # Cookie Name
        ttk.Label(config_frame, text="Shib Cookie Name:").grid(row=2, column=0, sticky="w", pady=2)
        self.cookie_name_var = tk.StringVar()
        self.cookie_name_entry = ttk.Entry(config_frame, textvariable=self.cookie_name_var, width=45)
        self.cookie_name_entry.grid(row=2, column=1, sticky="w", padx=5)
        
        # Cookie Value
        ttk.Label(config_frame, text="Shib Cookie Value:").grid(row=3, column=0, sticky="w", pady=2)
        self.cookie_value_var = tk.StringVar()
        self.cookie_value_entry = ttk.Entry(config_frame, textvariable=self.cookie_value_var, width=45)
        self.cookie_value_entry.grid(row=3, column=1, sticky="w", padx=5)
        
        btn_frame = ttk.Frame(config_frame)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=10)
        
        # Save Button
        self.save_btn = ttk.Button(btn_frame, text="Save Settings", command=self._save_config)
        self.save_btn.pack(side="left", padx=5)
        
        # Import JSON Button
        self.import_btn = ttk.Button(btn_frame, text="Quick Import JSON (Cookies)", command=self._open_import_dialog)
        self.import_btn.pack(side="left", padx=5)

    def _open_import_dialog(self):
        import_win = tk.Toplevel(self.root)
        import_win.title("Paste Cookie JSON")
        import_win.geometry("500x400")
        
        ttk.Label(import_win, text="Paste the JSON export from your cookie editor below:", padding=10).pack(fill="x")
        
        txt_area = scrolledtext.ScrolledText(import_win, wrap=tk.WORD, height=15)
        txt_area.pack(fill="both", expand=True, padx=10, pady=5)
        
        def do_import():
            raw_json = txt_area.get(1.0, tk.END).strip()
            if not raw_json: return
            
            try:
                data = json.loads(raw_json)
                if not isinstance(data, list):
                    data = [data]
                
                # Look for shibsession
                found = False
                for cookie in data:
                    name = cookie.get("name", "")
                    if "shibsession" in name:
                        self.cookie_name_var.set(name)
                        self.cookie_value_var.set(cookie.get("value", ""))
                        found = True
                        break
                
                if found:
                    messagebox.showinfo("Success", "Cookie info extracted! Don't forget to 'Save Settings'.", parent=import_win)
                    import_win.destroy()
                else:
                    messagebox.showwarning("Missing Info", "Could not find a cookie containing 'shibsession' in the JSON.", parent=import_win)
            except Exception as e:
                messagebox.showerror("Error", f"Invalid JSON: {e}", parent=import_win)
        
        ttk.Button(import_win, text="Extract & Import", command=do_import).pack(pady=10)

        # Control Frame
        control_frame = ttk.LabelFrame(self.root, text="Scrape Controls", padding=10)
        control_frame.pack(fill="x", padx=10, pady=5)
        
        ttk.Label(control_frame, text="Select Week:").pack(side="left", padx=5)
        self.week_var = tk.StringVar(value="All")
        weeks = ["All"] + [str(i) for i in range(1, 13)]
        self.week_combo = ttk.Combobox(control_frame, values=weeks, textvariable=self.week_var, width=10, state="readonly")
        self.week_combo.pack(side="left", padx=5)
        
        self.start_btn = ttk.Button(control_frame, text="Start Scraper", command=self._start_scrape)
        self.start_btn.pack(side="left", padx=20)

        # Logging Frame
        log_frame = ttk.LabelFrame(self.root, text="Progress Log", padding=10)
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.log_area = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=15)
        self.log_area.pack(fill="both", expand=True)

    def _load_config(self):
        self.domain_var.set(os.getenv("PCRS_DOMAIN", "pcrs.utm.utoronto.ca"))
        self.course_var.set(os.getenv("PCRS_COURSE_ID", "209"))
        self.cookie_name_var.set(os.getenv("SHIB_COOKIE_NAME", ""))
        self.cookie_value_var.set(os.getenv("SHIB_COOKIE_VALUE", ""))

    def _save_config(self):
        # Update current process env
        os.environ["PCRS_DOMAIN"] = self.domain_var.get()
        os.environ["PCRS_COURSE_ID"] = self.course_var.get()
        os.environ["SHIB_COOKIE_NAME"] = self.cookie_name_var.get()
        os.environ["SHIB_COOKIE_VALUE"] = self.cookie_value_var.get()
        
        # Write to .env file
        try:
            with open(".env", "w") as f:
                f.write(f"PCRS_DOMAIN={self.domain_var.get()}\n")
                f.write(f"PCRS_COURSE_ID={self.course_var.get()}\n")
                f.write(f"SHIB_COOKIE_NAME={self.cookie_name_var.get()}\n")
                f.write(f"SHIB_COOKIE_VALUE={self.cookie_value_var.get()}\n")
            messagebox.showinfo("Success", "Configuration saved to .env")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save .env: {e}")

    def _log_callback(self, msg):
        self.queue.put(msg)

    def _process_queue(self):
        if not self.running:
            return
        try:
            while True:
                msg = self.queue.get_nowait()
                self.log_area.insert(tk.END, msg + "\n")
                self.log_area.see(tk.END)
                self.queue.task_done()
        except queue.Empty:
            pass
        self.root.after(100, self._process_queue)

    def _on_close(self):
        self.running = False
        self.root.destroy()

    def _start_scrape(self):
        week = self.week_var.get()
        week_filter = None if week == "All" else int(week)
        
        self.start_btn.config(state="disabled")
        self.log_area.delete(1.0, tk.END)
        self.log_area.insert(tk.END, f"Starting scraper for Week: {week}...\n")
        
        # Run in thread
        threading.Thread(target=self._run_task, args=(week_filter,), daemon=True).start()

    def _run_task(self, week_filter):
        try:
            run_scraper(
                course_id=self.course_var.get(),
                week_filter=week_filter,
                domain=self.domain_var.get(),
                log_callback=self._log_callback
            )
            self._log_callback("\n[SCRAPER FINISHED]")
        except Exception as e:
            self._log_callback(f"\n[CRITICAL ERROR] {e}")
        finally:
            self.root.after(0, lambda: self.start_btn.config(state="normal"))

if __name__ == "__main__":
    root = tk.Tk()
    app = ScraperGUI(root)
    root.mainloop()
