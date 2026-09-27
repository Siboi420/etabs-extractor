"""A read-only, timestamped log panel for the etabs_extractor GUI."""

from __future__ import annotations

import datetime

import customtkinter as ctk


class LogPanel(ctk.CTkFrame):
    """A read-only scrolling text log; ``append(line)`` adds a timestamped
    entry and auto-scrolls to the bottom."""

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.textbox = ctk.CTkTextbox(self, wrap="word", state="disabled")
        self.textbox.pack(fill="both", expand=True)

    def append(self, line: str) -> None:
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.textbox.configure(state="normal")
        self.textbox.insert("end", f"[{stamp}] {line}\n")
        self.textbox.configure(state="disabled")
        self.textbox.see("end")

    def clear(self) -> None:
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")
