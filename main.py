#!/usr/bin/env python3
"""
Body Fat Tracker
================
A tape-measure-only body fat percentage tracker.

Runs SIX independent %BF estimators (US Navy, YMCA, Covert Bailey,
Katch-McArdle circumference, BMI/Deurenberg, and a 13-variable Multi-Site
Regression model) side by side, shows their average, computes a physique
analysis (waist-to-height / waist-to-hip / V-taper / arm-to-wrist ratios,
FFMI, and a composite Body Score), saves every entry to a local JSON file,
and graphs your progress over time.

Every measurement field has its OWN imperial/metric toggle, so you can
freely mix units in the same entry (e.g. height in cm, weight in lb, waist
in inches) -- the app converts everything internally and stores both what
you typed AND the converted canonical value, so nothing is ever lost.

Run with:   python3 body_fat_tracker.py

Requires:   matplotlib   (pip install matplotlib)
            tkinter      (usually bundled with Python; on Linux you may
                           need: sudo apt install python3-tk)
"""

import datetime
import tkinter as tk
from tkinter import ttk, messagebox

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import calculators as calc
import storage

APP_TITLE = "Body Fat Tracker"

MEASUREMENT_TIPS = {
    "age": "Age in completed years. Use your current age at the time of measurement.",
    "height": "Measure barefoot, standing tall against a wall or height rod.",
    "weight": "Weigh yourself without heavy clothing, ideally after using the restroom and before eating.",
    "neck": "Measure just below the Adam's apple, keeping the tape level and snug but not tight.",
    "chest": "Measure across the chest at nipple line with arms relaxed at your sides.",
    "shoulders": "Measure around the widest part of your shoulders/deltoids, tape passing across chest and back, arms relaxed.",
    "waist": "Measure at the natural waistline, usually at the navel or the narrowest point of the torso. Do not suck in.",
    "hip": "Measure around the fullest part of the hips and buttocks, keeping the tape horizontal.",
    "thigh": "Measure midway between the hip and knee on the thigh, standing relaxed.",
    "knee": "Measure around the mid-patella/knee joint with the leg straight and relaxed.",
    "ankle": "Measure around the narrowest part of the ankle, just above the bony protrusion.",
    "biceps": "Measure the upper arm at its largest point with the arm relaxed and slightly bent.",
    "forearm": "Measure the fullest part of the forearm, roughly halfway between elbow and wrist.",
    "wrist": "Measure around the wrist joint, just below the hand and on top of the styloid process.",
    "calf": "Measure the largest part of the calf while standing with weight on both feet.",
}

# (key, label, "used by" hint)
FIELD_DEFS = [
    ("neck", "Neck", "Navy"),
    ("chest", "Chest", "Regression"),
    ("shoulders", "Shoulders", "V-Taper analysis"),
    ("waist", "Waist", "Navy/YMCA/Bailey/Katch/WHtR/WHR"),
    ("hip", "Hip", "Navy(F)/Bailey/Katch/WHR"),
    ("thigh", "Thigh", "Bailey(F)/Katch"),
    ("knee", "Knee", "Regression"),
    ("ankle", "Ankle", "Regression"),
    ("biceps", "Biceps (relaxed)", "Katch(M)/Regression/Arm ratio"),
    ("forearm", "Forearm", "Bailey/Katch"),
    ("wrist", "Wrist", "Bailey/Regression/Arm ratio"),
    ("calf", "Calf", "Bailey(F)/Katch(F)"),
]

# Display label -> measurement key, for the history metric picker.
MEASUREMENT_LABELS = {label: key for key, label, _ in FIELD_DEFS}

HISTORY_METRIC_CHOICES = [
    "Average Body Fat %", "Body Score", "Weight", "BMI",
    "Waist-to-Height Ratio", "Waist-to-Hip Ratio",
    "Shoulder-to-Waist Ratio", "Bicep-to-Wrist Ratio", "FFMI",
] + [label for _, label, _ in FIELD_DEFS]


def format_num(x, decimals=2):
    return "" if x is None else f"{x:.{decimals}f}"


class MeasurementTooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        self.widget.bind("<Enter>", self.show)
        self.widget.bind("<Leave>", self.hide)

    def show(self, event=None):
        if self.tip_window is not None:
            return
        self.tip_window = tk.Toplevel(self.widget)
        self.tip_window.withdraw()
        self.tip_window.overrideredirect(True)
        label = ttk.Label(
            self.tip_window, text=self.text, background="#fff9c4",
            relief="solid", borderwidth=1, padding=(6, 4), wraplength=300,
        )
        label.pack()
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + 20
        self.tip_window.geometry(f"+{x}+{y}")
        self.tip_window.deiconify()

    def hide(self, event=None):
        if self.tip_window is not None:
            self.tip_window.destroy()
            self.tip_window = None


class BodyFatTrackerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1280x900")
        self.minsize(1080, 720)

        self.sex_var = tk.StringVar(value="M")
        self.entry_vars = {}          # key -> StringVar (raw typed value)
        self.unit_vars = {}           # key -> StringVar ("in"/"cm" or "lb"/"kg")
        self._prev_unit = {}          # key -> last-known unit, for auto-convert-on-toggle
        self.method_vars = {}
        self.height_widgets = {"cm": [], "in": []}
        self.height_labels = {"ft": None, "in": None}

        self.last_raw = None
        self.last_canonical = None
        self.last_m = None
        self.last_results = None
        self.last_bmi = None
        self.last_avg = None
        self.last_analysis = None

        self._building = True
        self._build_ui()
        self._building = False

        self._update_height_fields()
        self._restore_last_measurement()
        self._refresh_history_view()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        self.entry_tab = ttk.Frame(notebook)
        self.history_tab = ttk.Frame(notebook)
        notebook.add(self.entry_tab, text="New Measurement")
        notebook.add(self.history_tab, text="History & Trends")

        self._build_entry_tab()
        self._build_history_tab()

    # -- Entry tab ------------------------------------------------------
    def _build_entry_tab(self):
        outer = ttk.Frame(self.entry_tab, padding=10)
        outer.pack(fill="both", expand=True)

        left = ttk.Frame(outer)
        left.pack(side="left", fill="y", padx=(0, 15))

        right = ttk.Frame(outer)
        right.pack(side="left", fill="both", expand=True)

        # --- quick unit presets ---
        preset_frame = ttk.Frame(left)
        preset_frame.pack(fill="x", pady=(0, 6))
        ttk.Label(preset_frame, text="Quick-set all units:").pack(side="left")
        ttk.Button(preset_frame, text="Imperial", width=9,
                   command=lambda: self._set_all_units("imperial")).pack(side="left", padx=3)
        ttk.Button(preset_frame, text="Metric", width=9,
                   command=lambda: self._set_all_units("metric")).pack(side="left")

        # --- basics ---
        basics = ttk.LabelFrame(left, text="Basics", padding=10)
        basics.pack(fill="x", pady=(0, 10))

        row = 0
        ttk.Label(basics, text="Sex:").grid(row=row, column=0, sticky="w", pady=2)
        sex_frame = ttk.Frame(basics)
        sex_frame.grid(row=row, column=1, sticky="w", columnspan=2)
        ttk.Radiobutton(sex_frame, text="Male", value="M", variable=self.sex_var).pack(side="left")
        ttk.Radiobutton(sex_frame, text="Female", value="F", variable=self.sex_var).pack(side="left")
        row += 1

        self.entry_vars["age"] = tk.StringVar()
        ttk.Label(basics, text="Age (years):").grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(basics, textvariable=self.entry_vars["age"], width=10).grid(
            row=row, column=1, sticky="w", padx=(5, 5))
        row += 1

        self.entry_vars["height"] = tk.StringVar()
        self.entry_vars["height_ft"] = tk.StringVar()
        self.entry_vars["height_in"] = tk.StringVar()
        self.unit_vars["height"] = tk.StringVar(value="in")
        self._add_height_field(basics, row)
        row += 1

        self.entry_vars["weight"] = tk.StringVar()
        self.unit_vars["weight"] = tk.StringVar(value="lb")
        self._add_measurement_field(basics, row, "Weight", "weight", "mass")
        row += 1

        # --- circumferences ---
        circ = ttk.LabelFrame(left, text="Tape Measurements (leave blank if unknown)",
                               padding=10)
        circ.pack(fill="x", pady=(0, 10))

        for i, (key, label, needed_by) in enumerate(FIELD_DEFS):
            self.entry_vars[key] = tk.StringVar()
            self.unit_vars[key] = tk.StringVar(value="in")
            self._add_measurement_field(circ, i, label, key, "length", hint=needed_by)

        # --- method selection ---
        self.method_controls = ttk.LabelFrame(left, text="Included %BF methods", padding=8)
        self.method_controls.pack(fill="x", pady=(0, 10))
        for method_name in calc.METHOD_ORDER:
            var = tk.BooleanVar(value=method_name in calc.DEFAULT_ENABLED_METHODS)
            self.method_vars[method_name] = var
            ttk.Checkbutton(self.method_controls, text=method_name, variable=var).pack(anchor="w")

        btn_frame = ttk.Frame(left)
        btn_frame.pack(fill="x", pady=(5, 0))
        ttk.Button(btn_frame, text="Calculate", command=self.on_calculate).pack(
            side="left", padx=(0, 5))
        self.save_btn = ttk.Button(btn_frame, text="Save Entry", command=self.on_save,
                                    state="disabled")
        self.save_btn.pack(side="left")

        # Now that all input widgets/vars exist, wire up invalidation +
        # unit-change tracing (must happen after creation, before any
        # programmatic restore/set below).
        self._wire_traces()

        # --- results (right side): sub-notebook with %BF results and
        # physique analysis, so both fit without a cluttered single view ---
        results_notebook = ttk.Notebook(right)
        results_notebook.pack(fill="both", expand=True)

        bf_tab = ttk.Frame(results_notebook, padding=8)
        physique_tab = ttk.Frame(results_notebook, padding=8)
        results_notebook.add(bf_tab, text="Body Fat % Results")
        results_notebook.add(physique_tab, text="Physique Analysis")

        self.results_text = tk.Text(bf_tab, height=10, wrap="word", font=("Courier New", 11))
        self.results_text.pack(fill="x", pady=(0, 10))
        self.results_text.configure(state="disabled")

        self.fig_current = Figure(figsize=(6, 4), dpi=100)
        self.ax_current = self.fig_current.add_subplot(111)
        self.canvas_current = FigureCanvasTkAgg(self.fig_current, master=bf_tab)
        self.canvas_current.get_tk_widget().pack(fill="both", expand=True)

        self._build_physique_tab(physique_tab)

    def _build_physique_tab(self, parent):
        gauge_frame = ttk.Frame(parent)
        gauge_frame.pack(fill="x")
        self.fig_score = Figure(figsize=(6, 1.1), dpi=100)
        self.ax_score = self.fig_score.add_subplot(111)
        self.canvas_score = FigureCanvasTkAgg(self.fig_score, master=gauge_frame)
        self.canvas_score.get_tk_widget().pack(fill="x")
        self._render_body_score_gauge(None)

        self.physique_text = tk.Text(parent, wrap="word", font=("TkDefaultFont", 10))
        self.physique_text.pack(fill="both", expand=True, pady=(10, 0))
        self.physique_text.tag_configure("header", font=("TkDefaultFont", 10, "bold"))
        self.physique_text.tag_configure("strength_header", foreground="#2e7d32",
                                          font=("TkDefaultFont", 9, "bold"))
        self.physique_text.tag_configure("strength", foreground="#2e7d32")
        self.physique_text.tag_configure("watch_header", foreground="#c62828",
                                          font=("TkDefaultFont", 9, "bold"))
        self.physique_text.tag_configure("watch", foreground="#c62828")
        self.physique_text.tag_configure("muted", foreground="#888888")
        self.physique_text.insert(
            "1.0", "Calculate a measurement to see your physique analysis and Body Score.",
            "muted")
        self.physique_text.configure(state="disabled")

    # -- field builders ---------------------------------------------------
    def _add_measurement_field(self, parent, row, label, key, kind, hint=None):
        ttk.Label(parent, text=label + ":").grid(row=row, column=0, sticky="w", pady=2)
        entry = ttk.Entry(parent, textvariable=self.entry_vars[key], width=10)
        entry.grid(row=row, column=1, sticky="w", padx=(5, 3))
        entry.bind("<Enter>", lambda event, k=key: self._show_field_tip(event, k))

        toggle = self._make_unit_toggle(parent, key, kind)
        toggle.grid(row=row, column=2, sticky="w", padx=(2, 8))

        if hint:
            ttk.Label(parent, text=f"used by: {hint}", foreground="#888888",
                      font=("TkDefaultFont", 8)).grid(row=row, column=3, sticky="w")

    def _make_unit_toggle(self, parent, key, kind):
        values = ("in", "cm") if kind == "length" else ("lb", "kg")
        frame = ttk.Frame(parent)
        for v in values:
            ttk.Radiobutton(frame, text=v, value=v, variable=self.unit_vars[key],
                             width=3).pack(side="left")
        return frame

    def _add_height_field(self, parent, row):
        ttk.Label(parent, text="Height:").grid(row=row, column=0, sticky="w", pady=2)
        self.height_frame = ttk.Frame(parent)
        self.height_frame.grid(row=row, column=1, sticky="w", columnspan=2)

        self.metric_height_entry = ttk.Entry(self.height_frame, textvariable=self.entry_vars["height"], width=10)
        self.height_widgets["cm"].append(self.metric_height_entry)

        self.imperial_height_ft = ttk.Entry(self.height_frame, textvariable=self.entry_vars["height_ft"], width=5)
        self.imperial_height_in = ttk.Entry(self.height_frame, textvariable=self.entry_vars["height_in"], width=5)
        self.height_widgets["in"].extend([self.imperial_height_ft, self.imperial_height_in])
        self.height_labels["ft"] = ttk.Label(self.height_frame, text="ft")
        self.height_labels["in"] = ttk.Label(self.height_frame, text="in")

        for widget in self.height_widgets["cm"] + self.height_widgets["in"]:
            widget.bind("<Enter>", lambda event: self._show_field_tip(event, "height"))

        toggle = self._make_unit_toggle(parent, "height", "length")
        toggle.grid(row=row, column=3, sticky="w", padx=(2, 8))

    def _show_field_tip(self, event, key):
        tip_text = MEASUREMENT_TIPS.get(key, "Take the measurement with a level tape and consistent tension.")
        MeasurementTooltip(event.widget, tip_text)

    # ------------------------------------------------------------------
    # Trace wiring: unit-change auto-conversion + calculation invalidation
    # ------------------------------------------------------------------
    def _wire_traces(self):
        for key in self.unit_vars:
            self._prev_unit[key] = self.unit_vars[key].get()
            self.unit_vars[key].trace_add(
                "write", lambda *_, k=key: self._on_unit_changed(k))
            self.unit_vars[key].trace_add("write", self._invalidate_calculation)

        for key in self.entry_vars:
            self.entry_vars[key].trace_add("write", self._invalidate_calculation)

        self.sex_var.trace_add("write", self._invalidate_calculation)
        for var in self.method_vars.values():
            var.trace_add("write", self._invalidate_calculation)

    def _invalidate_calculation(self, *_):
        if self._building:
            return
        if self.last_results is not None:
            self.last_results = None
            self.save_btn.configure(state="disabled")

    def _on_unit_changed(self, key):
        if self._building:
            return
        new_unit = self.unit_vars[key].get()
        old_unit = self._prev_unit.get(key, new_unit)

        if key == "height":
            self._convert_height_unit(old_unit, new_unit)
            self._update_height_fields()
        elif old_unit != new_unit:
            kind = calc.field_kind(key)
            val = self._get_float(key)
            if val is not None:
                converted = (calc.convert_length(val, old_unit, new_unit) if kind == "length"
                             else calc.convert_mass(val, old_unit, new_unit))
                self.entry_vars[key].set(format_num(converted))

        self._prev_unit[key] = new_unit

    def _convert_height_unit(self, old_unit, new_unit):
        if old_unit == new_unit:
            return
        if old_unit == "in":
            ft = self._get_float("height_ft")
            inch = self._get_float("height_in")
            if ft is None and inch is None:
                return
            total_in = (ft or 0.0) * 12.0 + (inch or 0.0)
        else:
            cm_val = self._get_float("height")
            if cm_val is None:
                return
            total_in = calc.to_inches(cm_val, "cm")

        if new_unit == "cm":
            self.entry_vars["height"].set(format_num(calc.to_cm(total_in, "in")))
        else:
            feet = int(total_in // 12)
            inches_rem = total_in - feet * 12
            self.entry_vars["height_ft"].set(str(feet))
            self.entry_vars["height_in"].set(format_num(inches_rem, 1))

    def _update_height_fields(self):
        unit = self.unit_vars["height"].get()
        for widget in self.height_widgets["cm"] + self.height_widgets["in"]:
            widget.pack_forget()
        for label in self.height_labels.values():
            if label is not None:
                label.pack_forget()

        if unit == "cm":
            self.metric_height_entry.pack(side="left")
            ttk.Label(self.height_frame, text="cm").pack_forget()  # no-op placeholder
        else:
            self.height_labels["ft"].pack(side="left", padx=(4, 0))
            self.imperial_height_ft.pack(side="left")
            self.height_labels["in"].pack(side="left", padx=(4, 0))
            self.imperial_height_in.pack(side="left")

    def _set_all_units(self, system):
        length_unit = "in" if system == "imperial" else "cm"
        mass_unit = "lb" if system == "imperial" else "kg"
        self.unit_vars["height"].set(length_unit)
        self.unit_vars["weight"].set(mass_unit)
        for key, _, _ in FIELD_DEFS:
            self.unit_vars[key].set(length_unit)

    def _get_enabled_methods(self):
        return [name for name, var in self.method_vars.items() if var.get()]

    def _get_height_value_and_unit(self):
        unit = self.unit_vars["height"].get()
        if unit == "cm":
            return self._get_float("height"), "cm"
        ft = self._get_float("height_ft")
        inch = self._get_float("height_in")
        if ft is None and inch is None:
            return None, "in"
        return (ft or 0.0) * 12.0 + (inch or 0.0), "in"

    # ------------------------------------------------------------------
    # Restore last measurement on startup
    # ------------------------------------------------------------------
    def _restore_last_measurement(self):
        entries = storage.load_history()
        if not entries:
            return
        last = entries[-1]

        self._building = True
        try:
            self.sex_var.set(last.get("sex", self.sex_var.get()))
            age = last.get("age")
            self.entry_vars["age"].set("" if age is None else str(age))

            height = last.get("height")
            if height:
                unit = height.get("unit", "in")
                self.unit_vars["height"].set(unit)
                self._prev_unit["height"] = unit
                if unit == "cm":
                    self.entry_vars["height"].set(str(height.get("value")))
                else:
                    total_in = height.get("value") or 0.0
                    feet = int(total_in // 12)
                    inches_rem = total_in - feet * 12
                    self.entry_vars["height_ft"].set(str(feet))
                    self.entry_vars["height_in"].set(format_num(inches_rem, 1))

            weight = last.get("weight")
            if weight:
                unit = weight.get("unit", "lb")
                self.unit_vars["weight"].set(unit)
                self._prev_unit["weight"] = unit
                self.entry_vars["weight"].set(str(weight.get("value")))

            measurements = last.get("measurements") or {}
            for key, _, _ in FIELD_DEFS:
                w = measurements.get(key)
                if w:
                    unit = w.get("unit", "in")
                    self.unit_vars[key].set(unit)
                    self._prev_unit[key] = unit
                    self.entry_vars[key].set(str(w.get("value")))
                else:
                    self.entry_vars[key].set("")

            enabled_methods = last.get("enabled_methods") or calc.DEFAULT_ENABLED_METHODS
            for method_name in calc.METHOD_ORDER:
                self.method_vars[method_name].set(method_name in enabled_methods)
        finally:
            self._building = False
            self._update_height_fields()

    # -- History tab ------------------------------------------------------
    def _build_history_tab(self):
        outer = ttk.Frame(self.history_tab, padding=10)
        outer.pack(fill="both", expand=True)

        table_frame = ttk.LabelFrame(outer, text="Measurement History", padding=8)
        table_frame.pack(fill="x")

        columns = ("date", "sex", "avg_bf", "score", "weight", "bmi")
        self.history_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=6)
        headers = ["Date", "Sex", "Avg Body Fat %", "Body Score", "Weight", "BMI"]
        for col, label in zip(columns, headers):
            self.history_tree.heading(col, text=label)
            self.history_tree.column(col, width=120, anchor="center")
        self.history_tree.pack(side="left", fill="x", expand=True)

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.history_tree.yview)
        self.history_tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="left", fill="y")

        btn_frame = ttk.Frame(outer)
        btn_frame.pack(fill="x", pady=8)
        ttk.Button(btn_frame, text="Delete Selected", command=self.on_delete_entry).pack(side="left")
        ttk.Button(btn_frame, text="Refresh", command=self._refresh_history_view).pack(
            side="left", padx=5)

        controls = ttk.LabelFrame(outer, text="Visual Progress Explorer", padding=8)
        controls.pack(fill="x", pady=(0, 8))

        ttk.Label(controls, text="Show metric:").pack(side="left")
        self.history_metric_var = tk.StringVar(value="Average Body Fat %")
        self.history_metric_combo = ttk.Combobox(
            controls, textvariable=self.history_metric_var,
            values=HISTORY_METRIC_CHOICES, state="readonly", width=24)
        self.history_metric_combo.pack(side="left", padx=(8, 12))
        self.history_metric_combo.bind(
            "<<ComboboxSelected>>", lambda e: self._refresh_history_chart())
        ttk.Label(controls, text="Select a measurement or ratio to see its progress over time.",
                  foreground="#666666").pack(side="left")

        visual = ttk.Panedwindow(outer, orient="vertical")
        visual.pack(fill="both", expand=True)

        graph_frame = ttk.LabelFrame(visual, text="Progress Graph", padding=8)
        details_frame = ttk.LabelFrame(visual, text="Data & Physique Summary", padding=8)
        visual.add(graph_frame, weight=4)
        visual.add(details_frame, weight=3)

        self.fig_history = Figure(figsize=(8, 5), dpi=100)
        self.ax_history = self.fig_history.add_subplot(111)
        self.canvas_history = FigureCanvasTkAgg(self.fig_history, master=graph_frame)
        self.canvas_history.get_tk_widget().pack(fill="both", expand=True)

        self.history_details = tk.Text(details_frame, wrap="word", height=10)
        self.history_details.pack(fill="both", expand=True)
        self.history_details.tag_configure("header", font=("TkDefaultFont", 10, "bold"))
        self.history_details.tag_configure("strength", foreground="#2e7d32")
        self.history_details.tag_configure("watch", foreground="#c62828")
        self.history_details.configure(state="disabled")

    # ------------------------------------------------------------------
    # Input gathering / conversion
    # ------------------------------------------------------------------
    def _get_float(self, key):
        raw = self.entry_vars[key].get().strip()
        if raw == "":
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def _gather_inputs(self):
        """Returns (raw_dict, errors_list). raw_dict values are wrapped as
        {'value':..,'unit':..} (or None), ready for storage.build_canonical."""
        errors = []
        age = self._get_float("age")
        height_val, height_unit = self._get_height_value_and_unit()
        weight_val = self._get_float("weight")
        weight_unit = self.unit_vars["weight"].get()

        if age is None:
            errors.append("Age is required.")
        if height_val is None:
            errors.append("Height is required.")
        if weight_val is None:
            errors.append("Weight is required.")

        measurements = {}
        for key, _, _ in FIELD_DEFS:
            val = self._get_float(key)
            unit = self.unit_vars[key].get()
            measurements[key] = None if val is None else {"value": val, "unit": unit}

        raw = {
            "sex": self.sex_var.get(),
            "age": age,
            "height": None if height_val is None else {"value": height_val, "unit": height_unit},
            "weight": None if weight_val is None else {"value": weight_val, "unit": weight_unit},
            "measurements": measurements,
        }
        return raw, errors

    def _to_canonical(self, raw):
        canonical = storage.build_canonical(raw["height"], raw["weight"], raw["measurements"])
        m = {
            "sex": raw["sex"],
            "age": raw["age"],
            "height_in": canonical["height_in"],
            "weight_lb": canonical["weight_lb"],
        }
        for key in storage.ALL_MEASUREMENT_KEYS:
            m[key] = canonical.get(f"{key}_in")
        return m, canonical

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def on_calculate(self):
        raw, errors = self._gather_inputs()
        if errors:
            messagebox.showerror("Missing information", "\n".join(errors))
            return

        m, canonical = self._to_canonical(raw)
        try:
            results, bmi = calc.run_all_methods(m)
        except Exception as exc:  # defensive: never crash the GUI
            messagebox.showerror("Calculation error", str(exc))
            return

        enabled_methods = self._get_enabled_methods()
        avg = calc.average_body_fat(results, enabled_methods)
        analysis = calc.physique_analysis(raw["sex"], m, avg)

        self.last_raw = raw
        self.last_canonical = canonical
        self.last_m = m
        self.last_results = results
        self.last_bmi = bmi
        self.last_avg = avg
        self.last_analysis = analysis

        self._render_results(results, bmi, m, avg, enabled_methods)
        self._render_current_chart(results, enabled_methods, avg)
        self._render_physique_panel(analysis)
        self.save_btn.configure(state="normal")

    def _render_results(self, results, bmi, m, avg, enabled_methods):
        valid = calc.filter_results(results, enabled_methods)

        lines = []
        lines.append(f"{'Method':32s} {'Body Fat %':>10s}")
        lines.append("-" * 44)
        for k, v in results.items():
            v_str = f"{v:6.2f} %" if v is not None else "  n/a  "
            selected = "*" if k in enabled_methods else " "
            lines.append(f"{selected} {k:31s} {v_str:>10s}")
        lines.append("-" * 44)
        if avg is not None:
            lines.append(f"{'AVERAGE (' + str(len(valid)) + ' methods)':32s} {avg:6.2f} %")
            category = calc.classify(m["sex"], avg)
            ffm = calc.fat_free_mass(m["weight_lb"], avg)
            fm = calc.fat_mass(m["weight_lb"], avg)
            lines.append("")
            lines.append(f"{'BMI':32s} {bmi:6.2f}")
            lines.append(f"{'Category':32s} {category:>10s}")
            lines.append(f"{'Estimated Fat-Free Mass':32s} {ffm:6.1f} lb")
            lines.append(f"{'Estimated Fat Mass':32s} {fm:6.1f} lb")
        else:
            lines.append("No enabled method could be computed - select another method or provide more measurements.")

        self.results_text.configure(state="normal")
        self.results_text.delete("1.0", "end")
        self.results_text.insert("1.0", "\n".join(lines))
        self.results_text.configure(state="disabled")

    def _render_current_chart(self, results, enabled_methods, avg):
        self.ax_current.clear()
        valid = calc.filter_results(results, enabled_methods)
        if not valid:
            self.canvas_current.draw()
            return
        names = list(valid.keys())
        values = list(valid.values())

        short_names = [n.replace(" Method", "").replace("Multi-Site Regression (13-var)", "Regression")
                       for n in names]
        bars = self.ax_current.bar(short_names, values, color="#4C72B0")
        self.ax_current.axhline(avg, color="#C44E52", linestyle="--", linewidth=1.5,
                                 label=f"Average = {avg:.1f}%")
        self.ax_current.set_ylabel("Body Fat %")
        self.ax_current.set_title("Body Fat % by Included Method")
        self.ax_current.legend(loc="upper right", fontsize=8)
        for label in self.ax_current.get_xticklabels():
            label.set_rotation(30)
            label.set_ha("right")
        for bar, val in zip(bars, values):
            self.ax_current.text(bar.get_x() + bar.get_width() / 2, val + 0.3,
                                  f"{val:.1f}", ha="center", fontsize=8)
        self.fig_current.tight_layout()
        self.canvas_current.draw()

    def _render_body_score_gauge(self, score):
        self.ax_score.clear()
        self.ax_score.set_xlim(0, 100)
        self.ax_score.set_ylim(0, 1)
        self.ax_score.set_yticks([])
        self.ax_score.set_xticks([0, 25, 50, 75, 100])
        if score is not None:
            color = "#c62828" if score < 40 else ("#f9a825" if score < 70 else "#2e7d32")
            self.ax_score.barh([0.5], [score], height=0.6, color=color)
            self.ax_score.text(min(score + 3, 92), 0.5, f"{score}", va="center",
                                fontsize=12, fontweight="bold")
        else:
            self.ax_score.text(50, 0.5, "n/a", ha="center", va="center", color="#888888")
        self.ax_score.set_title("Body Score (0-100)", fontsize=10)
        self.fig_score.tight_layout()
        self.canvas_score.draw()

    def _render_physique_panel(self, analysis):
        self._render_body_score_gauge(analysis.get("body_score"))

        t = self.physique_text
        t.configure(state="normal")
        t.delete("1.0", "end")

        def ratio_line(label, value, category):
            if value is None:
                t.insert("end", f"{label}: n/a\n")
            else:
                t.insert("end", f"{label}: {value:.2f}  ({category})\n")

        t.insert("end", "Physique Ratios\n", "header")
        ratio_line("Waist-to-Height Ratio", analysis["whtr"], analysis["whtr_category"])
        ratio_line("Waist-to-Hip Ratio", analysis["whr"], analysis["whr_category"])
        ratio_line("Shoulder-to-Waist (V-Taper)", analysis["shoulder_to_waist"],
                   analysis["shoulder_to_waist_category"])
        ratio_line("Bicep-to-Wrist Ratio", analysis["bicep_to_wrist"],
                   analysis["bicep_to_wrist_category"])
        if analysis["ffmi"] is not None:
            t.insert("end", f"FFMI: {analysis['ffmi']:.1f}  (height-normalized: {analysis['ffmi_normalized']:.1f})\n")
        else:
            t.insert("end", "FFMI: n/a\n")

        if analysis["body_score"] is not None:
            t.insert("end", f"\nBODY SCORE: {analysis['body_score']} / 100\n", "header")
            for comp in analysis["body_score_breakdown"]:
                t.insert("end", f"    {comp['component']}: {comp['score_pct']}/100 "
                                f"(weight {comp['weight']*100:.0f}%)\n")
        else:
            t.insert("end", "\nBODY SCORE: n/a (need at least body fat %, "
                             "waist+height, or waist+hip)\n")

        if analysis["strengths"]:
            t.insert("end", "\nStrengths\n", "strength_header")
            for s in analysis["strengths"]:
                t.insert("end", f"  + {s}\n", "strength")
        if analysis["watch_areas"]:
            t.insert("end", "\nWatch Areas\n", "watch_header")
            for w in analysis["watch_areas"]:
                t.insert("end", f"  - {w}\n", "watch")

        t.insert("end", "\nNote: Body Score, V-Taper, and Bicep-to-Wrist ratio are informal, "
                        "non-medical composites for tracking your own trend over time.", "muted")
        t.configure(state="disabled")

    def on_save(self):
        if self.last_results is None:
            return

        enabled_methods = self._get_enabled_methods()
        entry = {
            "schema_version": storage.SCHEMA_VERSION,
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "sex": self.last_raw["sex"],
            "age": self.last_raw["age"],
            "height": self.last_raw["height"],
            "weight": self.last_raw["weight"],
            "measurements": self.last_raw["measurements"],
            "canonical": self.last_canonical,
            "results": self.last_results,
            "enabled_methods": enabled_methods,
            "average_bf": self.last_avg,
            "bmi": self.last_bmi,
            "analysis": self.last_analysis,
        }
        storage.add_entry(entry)
        messagebox.showinfo("Saved", "Entry saved to bodyfat_history.json")
        self.save_btn.configure(state="disabled")
        self._refresh_history_view()

    def on_delete_entry(self):
        selection = self.history_tree.selection()
        if not selection:
            return
        index = self.history_tree.index(selection[0])
        storage.delete_entry(index)
        self._refresh_history_view()

    # ------------------------------------------------------------------
    # History view
    # ------------------------------------------------------------------
    def _get_entry_analysis(self, e):
        if e.get("analysis") is not None:
            return e["analysis"]
        m = storage.canonical_for_calculators(e)
        return calc.physique_analysis(e.get("sex"), m, e.get("average_bf"))

    def _refresh_history_view(self):
        for row in self.history_tree.get_children():
            self.history_tree.delete(row)

        entries = storage.load_history()
        for e in entries:
            date_str = e.get("timestamp", "")[:16].replace("T", " ")
            avg = e.get("average_bf")
            avg_str = f"{avg:.2f}%" if avg is not None else "n/a"
            analysis = self._get_entry_analysis(e)
            score = analysis.get("body_score")
            score_str = str(score) if score is not None else "n/a"
            weight_lb = (e.get("canonical") or {}).get("weight_lb")
            weight_str = f"{weight_lb:.1f} lb" if weight_lb is not None else "n/a"
            bmi = e.get("bmi")
            bmi_str = f"{bmi:.1f}" if bmi is not None else "n/a"
            self.history_tree.insert("", "end", values=(
                date_str, e.get("sex", ""), avg_str, score_str, weight_str, bmi_str))

        self._render_history_details(entries)
        self._render_history_chart(entries)

    def _render_history_details(self, entries):
        t = self.history_details
        t.configure(state="normal")
        t.delete("1.0", "end")
        if not entries:
            t.insert("1.0", "No saved measurements yet.")
            t.configure(state="disabled")
            return

        latest = entries[-1]
        analysis = self._get_entry_analysis(latest)

        t.insert("end", f"Latest measurement: {latest.get('timestamp', 'n/a')}\n", "header")
        t.insert("end", f"Sex: {latest.get('sex', 'n/a')} | Age: {latest.get('age', 'n/a')}\n")
        avg = latest.get("average_bf")
        if avg is not None:
            t.insert("end", f"Average Body Fat %: {avg:.2f}%  |  BMI: {latest.get('bmi', 'n/a'):.2f}\n")
        score = analysis.get("body_score")
        if score is not None:
            t.insert("end", f"Body Score: {score}/100\n")

        if len(entries) >= 2:
            first = entries[0]
            weight_change = None
            first_w = (first.get("canonical") or {}).get("weight_lb")
            last_w = (latest.get("canonical") or {}).get("weight_lb")
            if first_w is not None and last_w is not None:
                weight_change = last_w - first_w
            bf_change = None
            if first.get("average_bf") is not None and avg is not None:
                bf_change = avg - first["average_bf"]
            t.insert("end", "\nTrend since first entry\n", "header")
            t.insert("end", f"  Weight change: {weight_change:+.1f} lb\n" if weight_change is not None
                      else "  Weight change: n/a\n")
            t.insert("end", f"  Body-fat change: {bf_change:+.1f} pp\n" if bf_change is not None
                      else "  Body-fat change: n/a\n")

        if analysis.get("strengths"):
            t.insert("end", "\nStrengths\n", "header")
            for s in analysis["strengths"]:
                t.insert("end", f"  + {s}\n", "strength")
        if analysis.get("watch_areas"):
            t.insert("end", "\nWatch Areas\n", "header")
            for w in analysis["watch_areas"]:
                t.insert("end", f"  - {w}\n", "watch")

        t.configure(state="disabled")

    def _refresh_history_chart(self):
        self._render_history_chart(storage.load_history())

    def _metric_value(self, e, metric):
        """Returns (value, unit_label) for a given metric name and entry."""
        canonical = e.get("canonical") or {}
        if metric == "Average Body Fat %":
            return e.get("average_bf"), "%"
        if metric == "Weight":
            return canonical.get("weight_lb"), "lb"
        if metric == "BMI":
            return e.get("bmi"), ""
        if metric in MEASUREMENT_LABELS:
            key = MEASUREMENT_LABELS[metric]
            return canonical.get(f"{key}_in"), "in"

        analysis = self._get_entry_analysis(e)
        return {
            "Body Score": (analysis.get("body_score"), "pts"),
            "Waist-to-Height Ratio": (analysis.get("whtr"), ""),
            "Waist-to-Hip Ratio": (analysis.get("whr"), ""),
            "Shoulder-to-Waist Ratio": (analysis.get("shoulder_to_waist"), ""),
            "Bicep-to-Wrist Ratio": (analysis.get("bicep_to_wrist"), ""),
            "FFMI": (analysis.get("ffmi"), ""),
        }.get(metric, (None, ""))

    def _render_history_chart(self, entries):
        self.ax_history.clear()
        metric = self.history_metric_var.get()

        points = []
        for e in entries:
            value, unit = self._metric_value(e, metric)
            if value is None:
                continue
            points.append((e.get("timestamp", "")[:10], value, unit))

        if not points:
            self.ax_history.text(
                0.5, 0.5, f"No saved {metric.lower()} measurements yet.",
                ha="center", va="center", transform=self.ax_history.transAxes)
            self.ax_history.set_axis_off()
            self.canvas_history.draw()
            return

        self.ax_history.set_axis_on()
        xs = list(range(len(points)))
        labels = [p[0] for p in points]
        values = [p[1] for p in points]
        unit = points[0][2]

        self.ax_history.plot(xs, values, marker="o", linewidth=2)
        self.ax_history.fill_between(xs, values, alpha=0.08)
        for x, y in zip(xs, values):
            self.ax_history.annotate(f"{y:.1f}", (x, y), xytext=(0, 8),
                                      textcoords="offset points", ha="center", fontsize=8)

        self.ax_history.set_title(f"{metric} Progress")
        self.ax_history.set_ylabel(f"{metric} ({unit})" if unit else metric)
        self.ax_history.set_xticks(xs)
        self.ax_history.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        self.ax_history.grid(True, alpha=0.25)
        self.fig_history.tight_layout()
        self.canvas_history.draw()


def main():
    app = BodyFatTrackerApp()
    app.mainloop()


if __name__ == "__main__":
    main()