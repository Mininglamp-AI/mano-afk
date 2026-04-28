"""
CustomTkinter UI overlay panel.
Migrated from task_overlay_view.py with updated imports.
"""
from typing import Optional
import platform
import traceback

import customtkinter as ctk
from config import WINDOW_CONFIG, ANIMATION_CONFIG, TEXT_CONSTANTS, TASK_STATUS

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


class TaskOverlayView:
    """View layer: pure UI display, receive data through binding, trigger operations through commands."""

    def __init__(self):
        self._ui_initialized = False
        self.root = None
        self._blink = True
        self._blink_job = None
        self._blink_text = TEXT_CONSTANTS["RUNNING_TEXT"]
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._minimized = False

        self.on_stop_command = None
        self.on_close_command = None
        self.on_continue_command = None

        self.button_frame = None
        self.continue_button = None

        self._safe_init_ui()

    def _safe_init_ui(self):
        try:
            self._previous_app = None
            if platform.system() == "Darwin":
                try:
                    from AppKit import NSWorkspace
                    self._previous_app = NSWorkspace.sharedWorkspace().frontmostApplication()
                except ImportError:
                    pass

            self.root = ctk.CTk()
            self.root.withdraw()

            self._configure_window()
            self._setup_ui()
            self._setup_dragging()
            self._setup_window_close()

            self._ui_initialized = True
            print("UI panel initialized successfully")

        except Exception as e:
            print(f"UI panel initialization failed: {e}")
            traceback.print_exc()
            self._ui_initialized = False

    def _configure_window(self):
        if not self.root:
            return
        self.root.title(TEXT_CONSTANTS["WINDOW_TITLE"])
        self.root.overrideredirect(False)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", WINDOW_CONFIG["ALPHA"])
        self.root.configure(fg_color=WINDOW_CONFIG["BG_COLOR"])
        self.root.geometry(f"{WINDOW_CONFIG['WIDTH']}x{WINDOW_CONFIG['MIN_HEIGHT']}")
        self.root.update_idletasks()
        self._position_top_right()
        self.root.after(100, lambda: self.root.overrideredirect(True))

    def _position_top_right(self):
        if not self.root:
            return
        try:
            if platform.system() == "Windows":
                import ctypes
                user32 = ctypes.windll.user32
                screen_width = user32.GetSystemMetrics(0)
            else:
                screen_width = self.root.winfo_screenwidth()

            x = max(WINDOW_CONFIG["MARGIN"], screen_width - WINDOW_CONFIG["WIDTH"] - WINDOW_CONFIG["MARGIN"])
            y = max(WINDOW_CONFIG["MARGIN"], WINDOW_CONFIG["MARGIN"])
            self.root.geometry(f"{WINDOW_CONFIG['WIDTH']}x{WINDOW_CONFIG['MIN_HEIGHT']}+{x}+{y}")
        except Exception as e:
            print(f"Window positioning failed: {e}")
            self.root.geometry(f"{WINDOW_CONFIG['WIDTH']}x{WINDOW_CONFIG['MIN_HEIGHT']}+200+200")

    def _setup_window_close(self):
        if not self.root:
            return

        def close():
            if self.on_close_command:
                self.on_close_command()

        self.root.protocol("WM_DELETE_WINDOW", close)

    def _setup_ui(self):
        if not self.root:
            return

        main_frame = ctk.CTkFrame(
            self.root,
            fg_color=WINDOW_CONFIG["BG_COLOR"],
            corner_radius=WINDOW_CONFIG["CORNER_RADIUS"],
        )
        main_frame.pack(fill="both", expand=True, padx=2, pady=2)

        self.top_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        self.top_frame.pack(fill="x", padx=14, pady=(12, 0))

        self.status_label = ctk.CTkLabel(
            self.top_frame,
            text=f"{TEXT_CONSTANTS['RUNNING_TEXT']}\u2026",
            font=ctk.CTkFont(size=WINDOW_CONFIG["TITLE_FONT_SIZE"]),
            text_color=WINDOW_CONFIG["TEXT_COLOR"],
        )
        self.status_label.pack(side="left")

        self.minimize_button = ctk.CTkButton(
            self.top_frame,
            text="\u2212",
            width=20,
            height=18,
            font=ctk.CTkFont(size=13),
            fg_color="transparent",
            hover_color="#444444",
            text_color=WINDOW_CONFIG["TEXT_COLOR"],
            corner_radius=4,
            border_spacing=0,
            command=self._toggle_minimize,
        )
        self.minimize_button.pack(side="right", padx=(4, 0))

        self.step_label = ctk.CTkLabel(
            self.top_frame,
            text=f"{TEXT_CONSTANTS['STEP_PREFIX']}0",
            font=ctk.CTkFont(size=WINDOW_CONFIG["TITLE_FONT_SIZE"]),
            text_color=WINDOW_CONFIG["TEXT_COLOR"],
        )
        self.step_label.pack(side="right")

        self.main_frame = main_frame

        self.task_name_label = ctk.CTkTextbox(
            main_frame,
            height=50,
            font=ctk.CTkFont(size=WINDOW_CONFIG["TITLE_FONT_SIZE"]),
            fg_color="transparent",
            text_color=WINDOW_CONFIG["TEXT_COLOR"],
            wrap="word",
            activate_scrollbars=False,
        )
        self.task_name_label.pack(fill="x", padx=14, pady=(8, 0))
        self.task_name_label.insert("1.0", f"{TEXT_CONSTANTS['TASK_PREFIX']}")
        self.task_name_label.configure(state="disabled")

        self.log_text = ctk.CTkTextbox(
            main_frame,
            height=100,
            font=ctk.CTkFont(size=WINDOW_CONFIG["LOG_FONT_SIZE"]),
            fg_color=WINDOW_CONFIG["LOG_BG_COLOR"],
            text_color=WINDOW_CONFIG["TEXT_COLOR"],
            corner_radius=WINDOW_CONFIG["BUTTON_RADIUS"],
            wrap="word",
        )
        self.log_text.pack(fill="both", expand=True, padx=14, pady=(8, 0))
        self.log_text.configure(state="disabled")

        self.button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        self.button_frame.pack(fill="x", padx=14, pady=(8, 12))
        self.button_frame.grid_columnconfigure(0, weight=1)
        self.button_frame.grid_columnconfigure(1, weight=1)

        self.stop_button = ctk.CTkButton(
            self.button_frame,
            text=TEXT_CONSTANTS["STOP_BUTTON_TEXT"],
            font=ctk.CTkFont(size=WINDOW_CONFIG["TITLE_FONT_SIZE"]),
            fg_color=WINDOW_CONFIG["STOP_BTN_COLOR"],
            hover_color=WINDOW_CONFIG["STOP_BTN_HOVER"],
            corner_radius=WINDOW_CONFIG["BUTTON_RADIUS"],
            height=WINDOW_CONFIG["BUTTON_HEIGHT"],
            command=self._on_stop_clicked,
        )
        self.stop_button.grid(row=0, column=0, columnspan=2, sticky="ew", padx=0, pady=0)

        self.continue_button = ctk.CTkButton(
            self.button_frame,
            text="Proceed",
            font=ctk.CTkFont(size=WINDOW_CONFIG["TITLE_FONT_SIZE"]),
            fg_color="#2ecc71",
            hover_color="#27ae60",
            corner_radius=WINDOW_CONFIG["BUTTON_RADIUS"],
            height=WINDOW_CONFIG["BUTTON_HEIGHT"],
            command=self._on_continue_clicked,
            state="hidden",
        )

        self.root.after(ANIMATION_CONFIG["HEIGHT_ADJUST_DELAY"], self._safe_adjust_window_height)

    def _on_continue_clicked(self):
        if self.on_continue_command:
            try:
                self.on_continue_command()
            except Exception as e:
                print(f"Failed to execute continue command: {e}")

    def _toggle_minimize(self):
        if not self._ui_initialized or not self.root:
            return

        self._minimized = not self._minimized

        if self._minimized:
            self._expanded_x = self.root.winfo_x()
            self._expanded_y = self.root.winfo_y()
            self.task_name_label.pack_forget()
            self.log_text.pack_forget()
            self.button_frame.pack_forget()
            self.step_label.pack_forget()
            self.minimize_button.pack_forget()
            self.status_label.pack_forget()
            self.top_frame.pack_configure(padx=6, pady=(2, 2))
            self.minimize_button.configure(text="+")
            self.minimize_button.pack(side="right", padx=(0, 2))
            self.status_label.pack(side="left", padx=(2, 2))
            try:
                screen_width = self.root.winfo_screenwidth()
                screen_height = self.root.winfo_screenheight()
                x = screen_width - WINDOW_CONFIG["MINIMIZED_WIDTH"] - WINDOW_CONFIG["MARGIN"]
                y = screen_height - WINDOW_CONFIG["MINIMIZED_HEIGHT"] - WINDOW_CONFIG["MARGIN"] - 50
            except Exception:
                x = self._expanded_x
                y = self._expanded_y
            self.root.geometry(
                f"{WINDOW_CONFIG['MINIMIZED_WIDTH']}x{WINDOW_CONFIG['MINIMIZED_HEIGHT']}+{x}+{y}"
            )
        else:
            self.status_label.pack_forget()
            self.minimize_button.pack_forget()
            self.top_frame.pack_configure(padx=14, pady=(12, 0))
            self.status_label.pack(side="left")
            self.minimize_button.configure(text="\u2212")
            self.minimize_button.pack(side="right", padx=(4, 0))
            self.step_label.pack(side="right")
            self.task_name_label.pack(fill="x", padx=14, pady=(8, 0))
            self.log_text.pack(fill="both", expand=True, padx=14, pady=(8, 0))
            self.button_frame.pack(fill="x", padx=14, pady=(8, 12))
            x = getattr(self, "_expanded_x", self.root.winfo_x())
            y = getattr(self, "_expanded_y", self.root.winfo_y())
            self.root.geometry(f"{WINDOW_CONFIG['WIDTH']}x{WINDOW_CONFIG['MIN_HEIGHT']}+{x}+{y}")
            self.root.after(ANIMATION_CONFIG["HEIGHT_ADJUST_DELAY"], self._safe_adjust_window_height)

    def _setup_dragging(self):
        if not self.root:
            return

        def start_drag(event):
            self._drag_start_x = event.x
            self._drag_start_y = event.y

        def do_drag(event):
            try:
                x = self.root.winfo_x() + event.x - self._drag_start_x
                y = self.root.winfo_y() + event.y - self._drag_start_y
                screen_width = self.root.winfo_screenwidth()
                screen_height = self.root.winfo_screenheight()
                x = max(0, min(x, screen_width - WINDOW_CONFIG["WIDTH"]))
                y = max(0, min(y, screen_height - WINDOW_CONFIG["MIN_HEIGHT"]))
                self.root.geometry(f"+{x}+{y}")
            except Exception:
                pass

        for widget in (self.status_label, self.step_label, self.minimize_button):
            widget.bind("<Button-1>", start_drag)
            widget.bind("<B1-Motion>", do_drag)

    def _on_stop_clicked(self):
        if self.on_stop_command:
            try:
                self.on_stop_command()
            except Exception as e:
                print(f"Failed to execute stop command: {e}")

    def update_task_state(self, task_state):
        if not self._ui_initialized or not self.root:
            return
        try:
            self.task_name_label.configure(state="normal")
            self.task_name_label.delete("1.0", "end")
            self.task_name_label.insert("1.0", f"{TEXT_CONSTANTS['TASK_PREFIX']}{task_state.task_name}")
            self.task_name_label.configure(state="disabled")

            self.step_label.configure(text=f"{TEXT_CONSTANTS['STEP_PREFIX']}{task_state.progress.step_idx}")
            self._update_log_text(task_state.progress.action, task_state.progress.reasoning)
            self._update_status_ui(task_state.status, task_state.error_msg)
            self.root.after(ANIMATION_CONFIG["HEIGHT_ADJUST_DELAY"], self._safe_adjust_window_height)
        except Exception as e:
            print(f"Failed to update task state: {e}")

    def _update_log_text(self, action: str, reasoning: str = ""):
        if not self._ui_initialized:
            return
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        if action:
            log_text = f"{TEXT_CONSTANTS['ACTION_PREFIX']}{action}"
            if reasoning.strip():
                log_text += f"\n{TEXT_CONSTANTS['REASONING_PREFIX']}{reasoning}"
            self.log_text.insert("1.0", log_text)
        self.log_text.configure(state="disabled")

    def _update_status_ui(self, status: str, error_msg: Optional[str] = None):
        if not self._ui_initialized:
            return

        self._stop_blink()

        if status == TASK_STATUS["RUNNING"]:
            self.status_label.configure(text=f"{TEXT_CONSTANTS['RUNNING_TEXT']}\u2026")
            self._start_blink()
            self._switch_to_single_button()
            self.stop_button.configure(
                text=TEXT_CONSTANTS["STOP_BUTTON_TEXT"],
                state="normal",
            )
        elif status == TASK_STATUS["COMPLETED"]:
            self.status_label.configure(text=TEXT_CONSTANTS["DONE_TEXT"])
            self._switch_to_single_button()
            self.stop_button.configure(
                text=TEXT_CONSTANTS["CLOSE_BUTTON_TEXT"],
                command=self.on_close_command,
                state="normal",
            )
            self.root.after(5000, self._auto_close)
        elif status == TASK_STATUS["STOPPED"]:
            self.status_label.configure(text=TEXT_CONSTANTS["STOPPED_TEXT"])
            self._switch_to_single_button()
            self.stop_button.configure(
                text=TEXT_CONSTANTS["CLOSE_BUTTON_TEXT"],
                command=self.on_close_command,
                state="normal",
            )
            self.root.after(5000, self._auto_close)
        elif status == TASK_STATUS["ERROR"]:
            self.status_label.configure(text=TEXT_CONSTANTS["ERROR_TEXT"])
            if error_msg:
                self.log_text.configure(state="normal")
                self.log_text.delete("1.0", "end")
                self.log_text.insert("1.0", error_msg)
                self.log_text.configure(state="disabled")
            self._switch_to_single_button()
            self.stop_button.configure(
                text=TEXT_CONSTANTS["CLOSE_BUTTON_TEXT"],
                command=self.on_close_command,
                state="normal",
            )
            self.root.after(5000, self._auto_close)
        elif status == TASK_STATUS["EVALUATING"]:
            self.status_label.configure(text=f"{TEXT_CONSTANTS['EVALUATING_TEXT']}\u2026")
            self._start_blink(TEXT_CONSTANTS["EVALUATING_TEXT"])
            self._switch_to_single_button()
            self.stop_button.configure(
                text=TEXT_CONSTANTS["STOP_BUTTON_TEXT"],
                state="normal",
            )
        elif status == TASK_STATUS["CALL_USER"]:
            self.status_label.configure(text="Pending Confirmation")
            self._switch_to_double_buttons()

    def _switch_to_single_button(self):
        self.continue_button.grid_forget()
        self.stop_button.grid_configure(row=0, column=0, columnspan=2, sticky="ew", padx=0, pady=0)

    def _switch_to_double_buttons(self):
        self.stop_button.grid_configure(row=0, column=1, columnspan=1, sticky="ew", padx=(2, 0), pady=0)
        self.continue_button.grid(row=0, column=0, sticky="ew", padx=(0, 2), pady=0)
        self.stop_button.configure(state="normal", text=TEXT_CONSTANTS["STOP_BUTTON_TEXT"])
        self.continue_button.configure(state="normal")

    def _start_blink(self, text=None):
        if not self._ui_initialized:
            return
        self._blink = True
        self._blink_text = text or TEXT_CONSTANTS["RUNNING_TEXT"]
        self._blink_job = self.root.after(ANIMATION_CONFIG["BLINK_INTERVAL"], self._blink_title)

    def _stop_blink(self):
        if not self.root or not self._blink_job:
            return
        try:
            self.root.after_cancel(self._blink_job)
            self._blink_job = None
        except Exception:
            pass

    def _blink_title(self):
        if not self._ui_initialized:
            return
        try:
            dots = "\u2026" if self._blink else ""
            self.status_label.configure(text=f"{self._blink_text}{dots}")
            self._blink = not self._blink
            self._blink_job = self.root.after(ANIMATION_CONFIG["BLINK_INTERVAL"], self._blink_title)
        except Exception:
            self._stop_blink()

    def _safe_adjust_window_height(self):
        if not self._ui_initialized or not self.root or self._minimized:
            return
        try:
            self.root.update_idletasks()
            task_label_height = self.task_name_label.winfo_reqheight()

            base_height = 60
            button_height = 52
            log_min_height = 80
            single_line_height = 25
            extra_height = max(0, task_label_height - single_line_height)

            new_height = base_height + task_label_height + log_min_height + button_height + extra_height
            new_height = max(WINDOW_CONFIG["MIN_HEIGHT"], min(new_height, WINDOW_CONFIG["MAX_HEIGHT"]))

            current_height = self.root.winfo_height()
            if abs(new_height - current_height) > 5:
                x = self.root.winfo_x()
                y = self.root.winfo_y()
                self.root.geometry(f"{WINDOW_CONFIG['WIDTH']}x{new_height}+{x}+{y}")
        except Exception as e:
            print(f"Failed to adjust window height: {e}")

    def show(self):
        if not self._ui_initialized or not self.root:
            print("UI not initialized, cannot show")
            return
        try:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self.root.update()
            if self._previous_app:
                try:
                    self._previous_app.activateWithOptions_(0)
                except Exception:
                    pass
            self._keep_on_top()
            print("UI window displayed")
        except Exception as e:
            print(f"Failed to show window: {e}")
            traceback.print_exc()

    def close(self):
        if not self._ui_initialized or not self.root:
            return
        self._ui_initialized = False
        self._stop_blink()
        try:
            self.root.quit()
            self.root.after(100, self.root.destroy)
        except Exception:
            pass
        print("UI window closed")

    def _keep_on_top(self):
        if not self._ui_initialized or not self.root:
            return
        try:
            self.root.attributes("-topmost", True)
            self.root.after(2000, self._keep_on_top)
        except Exception:
            pass

    def _auto_close(self):
        if self._ui_initialized and self.on_close_command:
            self.on_close_command()

    def run_mainloop(self):
        if not self._ui_initialized or not self.root:
            raise RuntimeError("UI not initialized, cannot run main loop")
        try:
            self.root.mainloop()
        except Exception as e:
            raise RuntimeError(f"UI main loop exception: {e}") from e
