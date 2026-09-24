from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
from tkinter import (
    BooleanVar,
    Button,
    Canvas,
    DoubleVar,
    StringVar,
    Tk,
    Toplevel,
    colorchooser,
    filedialog,
    messagebox,
    simpledialog,
)
from tkinter import ttk

try:
    from matplotlib import rcParams
    from matplotlib.backends.backend_agg import RendererAgg
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
except ImportError as exc:  # pragma: no cover - exercised only when deps are missing.
    raise SystemExit(
        "Matplotlib is required for the native GUI.\n"
        "Install dependencies from the productscope folder with:\n"
        "  python3 -m pip install -r requirements.txt"
    ) from exc

from .calculations import compute_metrics
from .data_io import (
    HEADERS as BO_OBJECTIVE_HEADERS,
    DEFAULT_PRODUCTS,
    build_prd_rows,
    calculation_rows,
    grid_rows,
    identity_mapping,
    normalize_mea_id,
    parse_uploaded_table,
    product_column,
    read_mea_details,
)


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY_FILE = BASE_DIR / "product_library_template.json"

RESULT_HEADERS = [
    "sample",
    "mea_id",
    "hplc_repeat",
    "mea_name",
    "product",
    "measured_concentration_mol_l",
    "adjusted_concentration_mol_l",
    "total_charge_c",
    "electrolyte_volume_l",
    "initial_reactant_concentration_mol_l",
    "moles",
    "faradaic_efficiency_pct",
    "selectivity_pct",
    "product_distribution_pct",
    "carbon_balance_pct",
    "c2_c3_total_fe_pct",
    "c2_c3_carbon_mmol",
]

BO_OBJECTIVE_METRICS = {
    "C2/C3 total FE (%)": "c2_c3_total_fe_pct",
    "C2/C3 carbon produced (mmol-C)": "c2_c3_carbon_mmol",
}

PLOT_METRICS = {
    "Adjusted Concentration (mM)": ("adjusted_concentration_mol_l", "Adjusted concentration (mM)", 1000.0),
    "Adjusted Concentration (mol/L)": ("adjusted_concentration_mol_l", "Adjusted concentration (mol/L)", 1.0),
    "Faradaic Efficiency (%)": ("faradaic_efficiency_pct", "Faradaic efficiency (%)", 1.0),
    "Selectivity (%)": ("selectivity_pct", "Selectivity (%)", 1.0),
    "Product Distribution (%)": ("product_distribution_pct", "Product distribution (%)", 1.0),
}

PLOT_LABEL_MODES = ["Smart", "Inside", "Outside", "Off"]
PLOT_GRID_STYLES = ["Solid", "Dashed", "Dotted"]
PLOT_LEGEND_POSITIONS = ["Top", "Right", "Bottom", "None"]
PLOT_EXPORT_FORMATS = ["PNG", "PDF", "SVG"]
PLOT_RIGHT_METRICS = ["None", "Total FE (%)", "Carbon conversion (%)", "Total charge passed (C)", *BO_OBJECTIVE_METRICS]
PLOT_FONT_FAMILY = "Arial"

FALLBACK_PALETTE = [
    "#ef4444",
    "#10b981",
    "#2563eb",
    "#f59e0b",
    "#7c3aed",
    "#0ea5e9",
    "#ec4899",
    "#84cc16",
    "#f97316",
    "#14b8a6",
]

COLORS = {
    "bg": "#f6f9fc",
    "panel": "#ffffff",
    "panel_soft": "#f8fbfd",
    "ink": "#16324f",
    "muted": "#64748b",
    "line": "#d9e2ec",
    "line_strong": "#b9c6d4",
    "teal": "#0f766e",
    "teal_hover": "#115e59",
}


def _float_text(value: object, digits: int = 6) -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
        return f"{number:.{digits}g}" if math.isfinite(number) else ""
    except (TypeError, ValueError):
        return ""


def _to_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: str, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def _format_plot_value(value: float) -> str:
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}"
    if abs(value) >= 1:
        return f"{value:.2f}"
    return f"{value:.2g}"


class EditableTable(ttk.Frame):
    def __init__(self, master, columns: list[tuple[str, str, int]], height: int = 8):
        super().__init__(master)
        self.columns = columns
        self.rows: list[dict] = []
        self._editor = None
        self._on_change = None
        self.readonly_columns = set()

        self.tree = ttk.Treeview(
            self,
            columns=[key for key, _, _ in columns],
            show="headings",
            height=height,
            selectmode="browse",
        )
        yscroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        for key, label, width in columns:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=70, stretch=True)

        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", self._begin_edit)

    def set_on_change(self, callback) -> None:
        self._on_change = callback

    def load_rows(self, rows: list[dict]) -> None:
        self.rows = rows
        self.refresh()

    def refresh(self) -> None:
        selected = self.tree.selection()
        self._close_editor(save=False)
        self.tree.delete(*self.tree.get_children())
        keys = [key for key, _, _ in self.columns]
        for idx, row in enumerate(self.rows):
            self.tree.insert("", "end", iid=str(idx), values=[row.get(key, "") for key in keys])
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])

    def selected_index(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    def _begin_edit(self, event) -> None:
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        row_id = self.tree.identify_row(event.y)
        column_id = self.tree.identify_column(event.x)
        if not row_id or not column_id:
            return

        column_index = int(column_id.replace("#", "")) - 1
        column_key = self.columns[column_index][0]
        if column_key in self.readonly_columns:
            return
        bbox = self.tree.bbox(row_id, column_id)
        if not bbox:
            return

        self._close_editor(save=False)
        value = self.rows[int(row_id)].get(column_key, "")
        editor = ttk.Entry(self.tree)
        editor.insert(0, str(value))
        editor.select_range(0, "end")
        editor.focus_set()
        editor.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
        editor.bind("<Return>", lambda _event: self._close_editor(save=True))
        editor.bind("<Escape>", lambda _event: self._close_editor(save=False))
        editor.bind("<FocusOut>", lambda _event: self._close_editor(save=True))
        self._editor = (editor, int(row_id), column_key)

    def _close_editor(self, save: bool) -> None:
        if not self._editor:
            return
        editor, row_index, column_key = self._editor
        self._editor = None
        value = editor.get()
        editor.destroy()
        if save and row_index < len(self.rows):
            self.rows[row_index][column_key] = value
            if self._on_change:
                self._on_change()
        self.refresh()


class ProductScopeApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("ProductScope")
        self.root.geometry("1360x920")
        self.root.minsize(1120, 820)
        self.root.configure(bg=COLORS["bg"])
        self.measurements: list[dict] = []
        self.sample_inputs: dict[str, dict] = {}
        self.product_library = self._load_default_library()
        self.input_products = list(DEFAULT_PRODUCTS)
        try:
            saved = json.loads((BASE_DIR / 'input_preferences.json').read_text())
            if isinstance(saved, list) and saved and all(isinstance(p, str) and p for p in saved):
                self.input_products = list(dict.fromkeys(saved))
        except (OSError, ValueError):
            pass
        self.results: list[dict] = []
        self.sample_summaries: dict[str, dict] = {}
        self.mea_names = {}
        self.mea_details = {}
        self.prd_start_number = StringVar(value="1")
        self.prd_preview_note = StringVar(value="")
        # None follows all samples, while an empty set explicitly selects none.
        self.selected_samples: set[str] | None = None

        self.dilution_factor = DoubleVar(value=2.0)
        self.reactant_name = StringVar(value="Glycerol")
        self.plot_metric = StringVar(value="Adjusted Concentration (mM)")
        self.sample_selection_text = StringVar(value="Samples: 0 of 0")
        self.plot_right_metric = StringVar(value="None")
        self.plot_overlay_color = StringVar(value="#222222")
        self.plot_width_in = DoubleVar(value=7.0)
        self.plot_height_in = DoubleVar(value=4.5)
        self.plot_dpi = StringVar(value="600")
        self.plot_x_title = StringVar(value="Sample")
        self.plot_y_title = StringVar(value=PLOT_METRICS[self.plot_metric.get()][1])
        self.plot_grid_enabled = BooleanVar(value=True)
        self.plot_grid_style = StringVar(value="Solid")
        self.plot_label_mode = StringVar(value="Smart")
        self.plot_label_threshold = DoubleVar(value=10.0)
        self.plot_legend_position = StringVar(value="Top")
        self.plot_export_format = StringVar(value="PNG")
        self.status_text = StringVar(value="Ready.")
        self.summary_samples = StringVar(value="0")
        self.summary_products = StringVar(value="0")
        self.summary_rows = StringVar(value="0")
        self.summary_peak = StringVar(value="-")
        self.figure_status_text = StringVar(value="No calculated figure yet.")
        self._auto_y_axis_title = True
        self._updating_axis_titles = False
        self.plot_y_title.trace_add("write", self._plot_y_title_changed)

        self._configure_style()
        self._build_ui()
        self.prd_start_number.trace_add("write", lambda *_: self._refresh_bo_preview())
        self._refresh_all()

    def _configure_style(self) -> None:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        rcParams["font.family"] = "sans-serif"
        rcParams["font.sans-serif"] = [PLOT_FONT_FAMILY, "DejaVu Sans", "Liberation Sans"]
        rcParams["pdf.fonttype"] = 42
        rcParams["ps.fonttype"] = 42
        style.configure(".", background=COLORS["bg"], foreground=COLORS["ink"])
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("Soft.TFrame", background=COLORS["panel_soft"], relief="flat")
        style.configure("TButton", padding=(10, 6), bordercolor=COLORS["line_strong"])
        style.configure(
            "Primary.TButton",
            background=COLORS["teal"],
            foreground="#ffffff",
            bordercolor=COLORS["teal"],
            focusthickness=2,
            focuscolor=COLORS["teal"],
        )
        style.map(
            "Primary.TButton",
            background=[("active", COLORS["teal_hover"]), ("pressed", COLORS["teal_hover"])],
            foreground=[("active", "#ffffff"), ("pressed", "#ffffff")],
        )
        style.configure("TLabel", padding=(0, 2), background=COLORS["bg"], foreground=COLORS["ink"])
        style.configure("Muted.TLabel", background=COLORS["bg"], foreground=COLORS["muted"])
        style.configure("Header.TLabel", font=("TkDefaultFont", 14, "bold"), foreground=COLORS["ink"])
        style.configure("Title.TLabel", font=("TkDefaultFont", 24, "bold"), foreground=COLORS["ink"])
        style.configure("StatValue.TLabel", font=("TkDefaultFont", 22, "bold"), background=COLORS["panel_soft"])
        style.configure("StatLabel.TLabel", font=("TkDefaultFont", 10), background=COLORS["panel_soft"], foreground=COLORS["muted"])
        style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff", rowheight=27, bordercolor=COLORS["line"])
        style.configure("Treeview.Heading", background="#edf3f8", foreground="#334155", font=("TkDefaultFont", 10, "bold"))
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 8), background="#edf3f8", foreground="#334155")
        style.map("TNotebook.Tab", background=[("selected", "#ffffff")], foreground=[("selected", COLORS["teal"])])

    def _build_ui(self) -> None:
        root_frame = ttk.Frame(self.root, padding=12)
        root_frame.pack(fill="both", expand=True)
        root_frame.grid_columnconfigure(0, weight=1)
        root_frame.grid_rowconfigure(1, weight=1)

        header = ttk.Frame(root_frame)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.grid_columnconfigure(0, weight=1)
        title_box = ttk.Frame(header)
        title_box.grid(row=0, column=0, sticky="w")
        ttk.Label(title_box, text="ProductScope", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            title_box,
            text="General product analysis for chromatography and electrochemical workflows",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Label(header, textvariable=self.status_text, style="Muted.TLabel").grid(row=0, column=1, sticky="e")

        notebook = ttk.Notebook(root_frame)
        notebook.grid(row=1, column=0, sticky="nsew")
        self.data_tab = ttk.Frame(notebook, padding=10)
        self.library_tab = ttk.Frame(notebook, padding=10)
        self.results_tab = ttk.Frame(notebook, padding=10)
        self.figure_tab = ttk.Frame(notebook, padding=10)
        notebook.add(self.data_tab, text="Data")
        notebook.add(self.library_tab, text="Product Library")
        notebook.add(self.results_tab, text="Results")
        notebook.add(self.figure_tab, text="Figure")

        self._build_data_tab()
        self._build_library_tab()
        self._build_results_tab()
        self._build_figure_tab()

    def _build_data_tab(self) -> None:
        self.data_tab.grid_columnconfigure(0, weight=1)
        self.data_tab.grid_rowconfigure(2, weight=1)
        self.data_tab.grid_rowconfigure(4, weight=1)

        controls = ttk.Frame(self.data_tab)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(controls, text="Load CSV/XLSX", command=self.load_data_file, style="Primary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Export Input CSV", command=self.export_input_csv).pack(side="left", padx=4)
        ttk.Button(controls, text="Add Sample", command=self.add_measurement).pack(side="left", padx=4)
        ttk.Button(controls, text="Add HPLC Repeat", command=self.add_hplc_repeat).pack(side="left", padx=4)
        ttk.Button(controls, text="Products…", command=self.choose_input_products).pack(side="left", padx=4)
        ttk.Button(controls, text="Delete Sample", command=self.delete_measurement).pack(side="left", padx=4)
        ttk.Button(controls, text="Clear", command=self.clear_measurements).pack(side="left", padx=4)

        settings = ttk.Frame(self.data_tab)
        settings.grid(row=1, column=0, sticky="ew", pady=4)
        ttk.Label(settings, text="Measurements — concentrations in mol/L", style="Header.TLabel").pack(side="left")
        ttk.Label(settings, text="Dilution coefficient").pack(side="left", padx=(20, 5))
        ttk.Entry(settings, textvariable=self.dilution_factor, width=8).pack(side="left")
        ttk.Label(settings, text="Reactant").pack(side="left", padx=(14, 5))
        ttk.Entry(settings, textvariable=self.reactant_name, width=16).pack(side="left")
        self.measurement_table = EditableTable(
            self.data_tab,
            [
                ("mea_id", "Sample (MEA ID)", 180),
                ("hplc_repeat", "HPLC Repeat", 110),
                *[(p, p, 150) for p in self.input_products],
            ],
            height=10,
        )
        self.measurement_table.grid(row=2, column=0, sticky="nsew", pady=(4, 12))
        self.measurement_table.set_on_change(self._measurement_table_changed)
        self.measurement_table.tree.bind('<Control-v>', self.paste_measurements)
        self.measurement_table.tree.bind('<Command-v>', self.paste_measurements)
        self.measurement_table.tree.bind('<Button-1>', self._remember_paste_cell, add='+')

        sample_controls = ttk.Frame(self.data_tab)
        sample_controls.grid(row=3, column=0, sticky="ew")
        ttk.Label(sample_controls, text="Per-sample electrolysis inputs", style="Header.TLabel").pack(side="left")
        ttk.Button(sample_controls, text="Refresh Samples", command=self._sync_sample_inputs).pack(side="right")
        ttk.Button(sample_controls, text="Load MEA details from master", command=self.load_master_details).pack(side="right", padx=6)

        self.sample_table = EditableTable(
            self.data_tab,
            [
                ("mea_id", "Sample (MEA ID)", 170),
                ("hplc_repeat", "HPLC Repeat", 100),
                ("mea_name", "Name", 240),
                ("total_charge_c", "Total Charge Q [C]", 150),
                ("electrolyte_volume_l", "Electrolyte Volume [L]", 160),
                ("initial_reactant_concentration_mol_l", "Initial Reactant Conc. [mol/L]", 200),
            ],
            height=8,
        )
        self.sample_table.grid(row=4, column=0, sticky="nsew", pady=(4, 0))
        self.sample_table.set_on_change(self._sample_table_changed)
        self.sample_table.readonly_columns.add("sample")

    def _build_library_tab(self) -> None:
        self.library_tab.grid_columnconfigure(0, weight=1)
        self.library_tab.grid_rowconfigure(1, weight=1)
        controls = ttk.Frame(self.library_tab)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(controls, text="Load Library JSON", command=self.load_library_file, style="Primary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Save Library JSON", command=self.save_library_file, style="Primary.TButton").pack(side="left", padx=6)
        ttk.Button(controls, text="Load Built-In Library", command=self.load_builtin_library).pack(side="left", padx=6)
        ttk.Button(controls, text="Add Product", command=self.add_product).pack(side="left", padx=6)
        ttk.Button(controls, text="Delete Product", command=self.delete_product).pack(side="left", padx=6)
        ttk.Button(controls, text="Choose Row Color", command=self.choose_product_color).pack(side="left", padx=6)

        self.library_table = EditableTable(
            self.library_tab,
            [
                ("canonical_name", "Canonical Product", 170),
                ("aliases", "Aliases", 220),
                ("electrons", "Electrons (z)", 110),
                ("stoich_factor", "Stoich Factor (s)", 130),
                ("carbon_number", "Carbon Number", 120),
                ("color", "Color", 100),
                ("is_reactant", "Reactant?", 100),
            ],
            height=18,
        )
        self.library_table.grid(row=1, column=0, sticky="nsew")
        self.library_table.set_on_change(self._library_table_changed)

    def _build_results_tab(self) -> None:
        self.results_tab.grid_columnconfigure(0, weight=1)
        self.results_tab.grid_rowconfigure(1, weight=3)
        self.results_tab.grid_rowconfigure(3, weight=1)

        controls = ttk.Frame(self.results_tab)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(controls, text="Run Analysis", command=self.run_calculations, style="Primary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Export Results CSV", command=self.export_results_csv, style="Primary.TButton").pack(side="left", padx=6)
        ttk.Button(controls, text="Export Plot", command=self.export_plot, style="Primary.TButton").pack(side="left", padx=6)
        ttk.Label(controls, text="Use the Figure tab for plot settings and preview.", style="Muted.TLabel").pack(side="left", padx=(18, 0))

        self.results_table = EditableTable(
            self.results_tab,
            [
                ("sample", "Sample", 150),
                ("hplc_repeat", "HPLC Repeat", 110),
                ("product", "Product", 150),
                ("adjusted_concentration_mol_l", "Adj. Conc. [mol/L]", 150),
                ("moles", "Moles", 120),
                ("faradaic_efficiency_pct", "FE [%]", 110),
                ("selectivity_pct", "Selectivity [%]", 120),
                ("product_distribution_pct", "Distribution [%]", 130),
                ("carbon_balance_pct", "Carbon Balance [%]", 140),
            ],
            height=18,
        )
        self.results_table.grid(row=1, column=0, sticky="nsew", pady=(4, 0))

        bo_controls = ttk.Frame(self.results_tab)
        bo_controls.grid(row=2, column=0, sticky="ew", pady=(10, 4))
        ttk.Label(bo_controls, text="BO objectives — maximise C2/C3 FE and carbon produced.").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(bo_controls, text="First PRD number (1–999):").grid(row=1, column=0, sticky="w", pady=6)
        self.prd_number_control = ttk.Spinbox(bo_controls, from_=1, to=999, textvariable=self.prd_start_number, width=8)
        self.prd_number_control.grid(row=1, column=1, sticky="w", padx=8)
        bo_controls.columnconfigure(2, weight=1)
        ttk.Button(bo_controls, text="Export BO Objectives CSV", command=self.export_bo_objectives_csv,
                   style="Primary.TButton").grid(row=1, column=2, sticky="e")
        self.bo_objectives_table = EditableTable(
            self.results_tab,
            [(key, key, 260 if key.startswith("BO ") else 150) for key in BO_OBJECTIVE_HEADERS],
            height=5,
        )
        self.bo_objectives_table.grid(row=3, column=0, sticky="nsew")
        self.bo_objectives_table.tree.unbind("<Double-1>")
        ttk.Label(self.results_tab, textvariable=self.prd_preview_note, wraplength=1000).grid(
            row=4, column=0, sticky="w")

    def _build_figure_tab(self) -> None:
        self.figure_tab.grid_columnconfigure(0, weight=1)
        self.figure_tab.grid_rowconfigure(3, weight=1)

        controls = ttk.Frame(self.figure_tab)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(controls, text="Run Analysis", command=self.run_calculations, style="Primary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Export Plot", command=self.export_plot, style="Primary.TButton").pack(side="left", padx=6)
        ttk.Label(controls, text="Metric").pack(side="left", padx=(24, 5))
        metric_box = ttk.Combobox(controls, textvariable=self.plot_metric, values=list(PLOT_METRICS), state="readonly", width=27)
        metric_box.pack(side="left")
        metric_box.bind("<<ComboboxSelected>>", self._plot_metric_changed)
        ttk.Button(controls, textvariable=self.sample_selection_text, command=self._choose_samples).pack(side="left", padx=(14, 8))
        ttk.Label(controls, text="Right axis").pack(side="left", padx=(6, 5))
        right_box = ttk.Combobox(controls, textvariable=self.plot_right_metric, values=PLOT_RIGHT_METRICS, state="readonly", width=30)
        right_box.pack(side="left")
        right_box.bind("<<ComboboxSelected>>", lambda _event: self.draw_plot())
        ttk.Label(controls, text="Colour").pack(side="left", padx=(8, 4))
        self.overlay_color_button = Button(
            controls, width=2, background=self.plot_overlay_color.get(),
            activebackground=self.plot_overlay_color.get(), relief="raised",
            borderwidth=2, command=self.choose_overlay_color,
        )
        self.overlay_color_button.pack(side="left")

        self._build_plot_settings(self.figure_tab).grid(row=1, column=0, sticky="ew", pady=(0, 10))

        figure_header = ttk.Frame(self.figure_tab)
        figure_header.grid(row=2, column=0, sticky="ew")
        ttk.Label(figure_header, text="Stacked Product Figure", style="Header.TLabel").pack(side="left")
        ttk.Label(figure_header, textvariable=self.figure_status_text, style="Muted.TLabel").pack(side="right")
        self.figure = Figure(figsize=(11.5, 6.2), dpi=100)
        self.axis = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.figure_tab)
        self.canvas.get_tk_widget().grid(row=3, column=0, sticky="nsew", pady=(4, 0))
        self.canvas.mpl_connect("resize_event", lambda _event: self.draw_plot())

    def _build_plot_settings(self, parent: ttk.Frame) -> ttk.Frame:
        settings = ttk.LabelFrame(parent, text="Essential Plot Settings", padding=(10, 8))
        for column in range(8):
            settings.grid_columnconfigure(column, weight=1)

        ttk.Label(settings, text="Export width [in]").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(settings, textvariable=self.plot_width_in, width=8).grid(row=1, column=0, sticky="ew", padx=(0, 8))
        ttk.Label(settings, text="Export height [in]").grid(row=0, column=1, sticky="w", padx=(0, 6))
        ttk.Entry(settings, textvariable=self.plot_height_in, width=8).grid(row=1, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(settings, text="DPI").grid(row=0, column=2, sticky="w", padx=(0, 6))
        ttk.Entry(settings, textvariable=self.plot_dpi, width=8).grid(row=1, column=2, sticky="ew", padx=(0, 8))

        ttk.Label(settings, text="Legend").grid(row=0, column=3, sticky="w", padx=(0, 6))
        legend_box = ttk.Combobox(settings, textvariable=self.plot_legend_position, values=PLOT_LEGEND_POSITIONS, state="readonly", width=10)
        legend_box.grid(row=1, column=3, sticky="ew", padx=(0, 8))
        legend_box.bind("<<ComboboxSelected>>", lambda _event: self.draw_plot())

        ttk.Label(settings, text="Labels").grid(row=0, column=4, sticky="w", padx=(0, 6))
        label_box = ttk.Combobox(settings, textvariable=self.plot_label_mode, values=PLOT_LABEL_MODES, state="readonly", width=10)
        label_box.grid(row=1, column=4, sticky="ew", padx=(0, 8))
        label_box.bind("<<ComboboxSelected>>", lambda _event: self.draw_plot())

        ttk.Label(settings, text="Label >= %").grid(row=0, column=5, sticky="w", padx=(0, 6))
        ttk.Entry(settings, textvariable=self.plot_label_threshold, width=8).grid(row=1, column=5, sticky="ew", padx=(0, 8))

        ttk.Label(settings, text="Grid").grid(row=0, column=6, sticky="w", padx=(0, 6))
        grid_box = ttk.Frame(settings)
        grid_box.grid(row=1, column=6, sticky="ew", padx=(0, 8))
        ttk.Checkbutton(grid_box, variable=self.plot_grid_enabled, command=self.draw_plot).pack(side="left")
        grid_style = ttk.Combobox(grid_box, textvariable=self.plot_grid_style, values=PLOT_GRID_STYLES, state="readonly", width=8)
        grid_style.pack(side="left", fill="x", expand=True)
        grid_style.bind("<<ComboboxSelected>>", lambda _event: self.draw_plot())

        ttk.Label(settings, text="Format").grid(row=0, column=7, sticky="w", padx=(0, 6))
        format_box = ttk.Combobox(settings, textvariable=self.plot_export_format, values=PLOT_EXPORT_FORMATS, state="readonly", width=8)
        format_box.grid(row=1, column=7, sticky="ew")

        ttk.Label(settings, text="X axis title").grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Entry(settings, textvariable=self.plot_x_title).grid(row=3, column=0, columnspan=2, sticky="ew", padx=(0, 8))
        ttk.Label(settings, text="Y axis title").grid(row=2, column=2, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Entry(settings, textvariable=self.plot_y_title).grid(row=3, column=2, columnspan=3, sticky="ew", padx=(0, 8))
        ttk.Button(settings, text="Apply Plot Settings", command=self.draw_plot).grid(row=3, column=5, columnspan=3, sticky="ew")
        return settings

    def _add_summary_card(self, parent: ttk.Frame, column: int, label: str, value: StringVar) -> None:
        card = ttk.Frame(parent, style="Soft.TFrame", padding=(14, 10))
        card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 8, 0))
        ttk.Label(card, text=label, style="StatLabel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(card, textvariable=value, style="StatValue.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _plot_y_title_changed(self, *_args) -> None:
        if not self._updating_axis_titles:
            self._auto_y_axis_title = False

    def _plot_metric_changed(self, _event=None) -> None:
        if self._auto_y_axis_title:
            self._set_auto_y_axis_title()
        self.draw_plot()

    def _set_auto_y_axis_title(self) -> None:
        self._updating_axis_titles = True
        self.plot_y_title.set(PLOT_METRICS[self.plot_metric.get()][1])
        self._updating_axis_titles = False
        self._auto_y_axis_title = True

    def _plot_dimensions(self) -> tuple[float, float]:
        width = max(2.0, min(20.0, _to_float(self.plot_width_in.get(), 7.0)))
        height = max(2.0, min(20.0, _to_float(self.plot_height_in.get(), 4.5)))
        return width, height

    def _plot_export_dpi(self) -> int:
        return max(72, min(1200, _to_int(self.plot_dpi.get(), 600)))

    def _grid_linestyle(self) -> str:
        return {"Solid": "-", "Dashed": "--", "Dotted": ":"}.get(self.plot_grid_style.get(), "-")

    def _plot_title_text(self, fallback: str) -> str:
        return (fallback or "").strip()

    def _load_default_library(self) -> dict:
        with DEFAULT_LIBRARY_FILE.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
            raise ValueError("Invalid product_library_template.json")
        return payload

    def _refresh_all(self) -> None:
        self.measurement_table.load_rows(self._display_measurements())
        self.sample_table.load_rows(self._display_sample_inputs())
        self.library_table.load_rows(self._display_library())
        self._refresh_sample_filter()
        self._refresh_results_table()
        self._refresh_summary_cards()
        self.draw_plot()

    def _set_product_columns(self, products):
        self.input_products = list(dict.fromkeys(products))
        table = self.measurement_table
        table.columns = [("mea_id", "Sample (MEA ID)", 180),
                         ("hplc_repeat", "HPLC Repeat", 110),
                         *[(p, p, 150) for p in self.input_products]]
        table.tree.configure(columns=[key for key, _, _ in table.columns])
        for key, label, width in table.columns:
            table.tree.heading(key, text=label)
            table.tree.column(key, width=width, minwidth=90, stretch=True)

    def _display_measurements(self) -> list[dict]:
        products = list(dict.fromkeys(product_column(r) for r in self.measurements))
        if products:
            self._set_product_columns(products)
        return grid_rows(self.measurements, self.sample_inputs, self.input_products)

    def _display_sample_inputs(self) -> list[dict]:
        return [
            {
                "sample": sample,
                "mea_id": values.get("mea_id", sample),
                "hplc_repeat": values.get("hplc_repeat", "repeat1"),
                "mea_name": values.get("mea_name") or self.mea_names.get(values.get("mea_id", sample), ""),
                "total_charge_c": _float_text(values.get("total_charge_c"), 8),
                "electrolyte_volume_l": _float_text(values.get("electrolyte_volume_l"), 8),
                "initial_reactant_concentration_mol_l": _float_text(
                    values.get("initial_reactant_concentration_mol_l"), 8
                ),
            }
            for sample, values in self.sample_inputs.items()
        ]

    def _display_library(self) -> list[dict]:
        out = []
        for product in self.product_library.get("products", []):
            out.append(
                {
                    "canonical_name": product.get("canonical_name", ""),
                    "aliases": ", ".join(product.get("aliases", [])),
                    "electrons": _float_text(product.get("electrons"), 17),
                    "stoich_factor": _float_text(product.get("stoich_factor"), 8),
                    "carbon_number": str(product.get("carbon_number", 0)),
                    "color": product.get("color", ""),
                    "is_reactant": "yes" if product.get("is_reactant") else "no",
                }
            )
        return out

    def _apply_sample_inputs(self, inputs):
        try:
            renamed, updated = identity_mapping(inputs)
        except ValueError as exc:
            messagebox.showerror("Duplicate or invalid sample", str(exc))
            self.sample_table.load_rows(self._display_sample_inputs())
            self.measurement_table.load_rows(self._display_measurements())
            return False
        self.sample_inputs = updated
        for rows in (self.measurements, self.results, self.measurement_table.rows):
            for row in rows:
                row["sample"] = renamed.get(row["sample"], row["sample"])
        self.sample_summaries = {
            renamed.get(key, key): dict(summary, sample=renamed.get(key, key))
            for key, summary in self.sample_summaries.items()
        }
        if self.selected_samples is not None:
            self.selected_samples = {renamed.get(key, key) for key in self.selected_samples}
        self.sample_table.load_rows(self._display_sample_inputs())
        for row in self.measurement_table.rows:
            cfg = updated.get(row["sample"], {})
            row["mea_id"] = cfg.get("mea_id", row["sample"])
            row["hplc_repeat"] = cfg.get("hplc_repeat", "repeat1")
        self.measurement_table.refresh()
        self._refresh_sample_filter()
        self._refresh_results_table()
        self.draw_plot()
        return True

    def _measurement_table_changed(self) -> bool:
        inputs = {key: dict(cfg) for key, cfg in self.sample_inputs.items()}
        try:
            calculation_rows(self.measurement_table.rows, self.input_products)
        except ValueError as exc:
            messagebox.showerror("Invalid concentration", str(exc))
            return False
        for row in self.measurement_table.rows:
            sample = row["sample"]
            cfg = inputs.setdefault(sample, {})
            mea = normalize_mea_id(row.get("mea_id", sample))
            if mea != cfg.get("mea_id", sample):
                cfg["mea_name"] = self.mea_names.get(mea, "")
            cfg["mea_id"] = mea
            cfg["hplc_repeat"] = row.get("hplc_repeat", "repeat1")
        if not self._apply_sample_inputs(inputs):
            return False
        self.measurements = calculation_rows(self.measurement_table.rows, self.input_products)
        self._sync_sample_inputs()
        return True

    def _sample_table_changed(self) -> None:
        inputs = {}
        for row in self.sample_table.rows:
            sample = row["sample"]
            inputs[sample] = {
                "mea_id": normalize_mea_id(row.get("mea_id")),
                "hplc_repeat": (row.get("hplc_repeat") or "").strip(),
                "mea_name": (row.get("mea_name") or "").strip(),
                **{key: _to_float(row.get(key), math.nan) for key in (
                    "total_charge_c", "electrolyte_volume_l", "initial_reactant_concentration_mol_l")},
            }
            mea = inputs[sample]["mea_id"]
            if mea != self.sample_inputs.get(sample, {}).get("mea_id", sample):
                inputs[sample]["mea_name"] = self.mea_names.get(mea, "")
        self._apply_sample_inputs(inputs)

    def _library_table_changed(self) -> None:
        products = []
        for row in self.library_table.rows:
            canonical = (row.get("canonical_name") or "").strip()
            if not canonical:
                continue
            aliases = [alias.strip() for alias in (row.get("aliases") or "").split(",") if alias.strip()]
            products.append(
                {
                    "canonical_name": canonical,
                    "aliases": aliases,
                    "electrons": _to_float(row.get("electrons"), 0.0),
                    "stoich_factor": _to_float(row.get("stoich_factor"), 1.0),
                    "carbon_number": _to_int(row.get("carbon_number"), 0),
                    "color": (row.get("color") or "#6b7280").strip(),
                    "is_reactant": _norm(row.get("is_reactant")) in {"yes", "true", "1", "y"},
                }
            )
        self.product_library = {"products": products}
        self.draw_plot()

    def _sync_sample_inputs(self) -> None:
        samples = []
        for row in self.measurements:
            sample = (row.get("sample") or "").strip()
            if sample and sample not in samples:
                samples.append(sample)
        self.sample_inputs = {
            sample: {
                "total_charge_c": 0.0,
                "electrolyte_volume_l": 0.05,
                "initial_reactant_concentration_mol_l": 0.1,
                **self.sample_inputs.get(sample, {}),
            }
            for sample in samples
        }
        self.sample_table.load_rows(self._display_sample_inputs())
        self._refresh_sample_filter()

    def _refresh_sample_filter(self) -> None:
        samples = self._available_plot_samples()
        if self.selected_samples is not None:
            self.selected_samples.intersection_update(samples)
        count = len(samples) if self.selected_samples is None else len(self.selected_samples)
        self.sample_selection_text.set(f"Samples: {count} of {len(samples)}")

    def _available_plot_samples(self) -> list[str]:
        calculated = list(dict.fromkeys(row['sample'] for row in self.results))
        if not calculated:
            return list(self.sample_inputs)
        return [sample for sample in self.sample_inputs if sample in calculated] + [
            sample for sample in calculated if sample not in self.sample_inputs
        ]

    def _choose_samples(self) -> None:
        samples = self._available_plot_samples()
        dialog = Toplevel(self.root)
        dialog.title("Select samples")
        dialog.transient(self.root)
        dialog.geometry("420x460")
        dialog.minsize(320, 260)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)
        choices = {sample: BooleanVar(dialog, value=self.selected_samples is None or sample in self.selected_samples)
                   for sample in samples}
        actions = ttk.Frame(dialog, padding=10)
        actions.grid(row=0, column=0, sticky="ew")

        def set_all(value):
            for choice in choices.values():
                choice.set(value)

        ttk.Button(actions, text="Select All", command=lambda: set_all(True)).pack(side="left")
        ttk.Button(actions, text="Clear All", command=lambda: set_all(False)).pack(side="left", padx=6)
        viewport = ttk.Frame(dialog)
        viewport.grid(row=1, column=0, sticky="nsew", padx=10)
        viewport.columnconfigure(0, weight=1)
        viewport.rowconfigure(0, weight=1)
        canvas = Canvas(viewport, highlightthickness=0, background=COLORS['bg'])
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        checklist = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=checklist, anchor="nw")
        checklist.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        dialog.bind("<MouseWheel>", lambda event: canvas.yview_scroll(-int(event.delta / 120), "units"))
        for sample, choice in choices.items():
            item = ttk.Frame(checklist)
            item.pack(fill="x", pady=3)
            ttk.Checkbutton(item, variable=choice).pack(side="left")
            label = ttk.Label(item, text=sample, wraplength=320)
            label.pack(side="left", fill="x", expand=True)
            label.bind("<Button-1>", lambda _event, var=choice: var.set(not var.get()))
        if not samples:
            ttk.Label(checklist, text="No samples available.").pack(anchor="w")

        def apply_selection():
            selected = {sample for sample, choice in choices.items() if choice.get()}
            self.selected_samples = None if selected and len(selected) == len(samples) else selected
            self._refresh_sample_filter()
            dialog.destroy()
            self.draw_plot()

        footer = ttk.Frame(dialog, padding=10)
        footer.grid(row=2, column=0, sticky="ew")
        ttk.Button(footer, text="Apply", command=apply_selection, style="Primary.TButton").pack(side="right")
        ttk.Button(footer, text="Cancel", command=dialog.destroy).pack(side="right", padx=6)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.grab_set()

    def _refresh_results_table(self) -> None:
        formatted = []
        for row in self.results:
            formatted.append(
                {
                    "sample": self.sample_inputs.get(row["sample"], {}).get("mea_id", row["sample"]),
                    "hplc_repeat": self.sample_inputs.get(row["sample"], {}).get("hplc_repeat", "repeat1"),
                    "product": row.get("product", ""),
                    "adjusted_concentration_mol_l": _float_text(row.get("adjusted_concentration_mol_l"), 8),
                    "moles": _float_text(row.get("moles"), 8),
                    "faradaic_efficiency_pct": _float_text(row.get("faradaic_efficiency_pct"), 6),
                    "selectivity_pct": _float_text(row.get("selectivity_pct"), 6),
                    "product_distribution_pct": _float_text(row.get("product_distribution_pct"), 6),
                    "carbon_balance_pct": _float_text(row.get("carbon_balance_pct"), 6),
                }
            )
        self.results_table.load_rows(formatted)
        self._refresh_bo_preview()

    def _refresh_bo_preview(self) -> None:
        try:
            rows = build_prd_rows(self.sample_summaries.values(), self.sample_inputs,
                                  self.prd_start_number.get())
        except ValueError as exc:
            self.bo_objectives_table.load_rows([])
            self.prd_preview_note.set(str(exc))
            return
        for row in rows:
            for key in BO_OBJECTIVE_HEADERS[-2:]:
                row[key] = _float_text(row[key], 6)
        self.bo_objectives_table.load_rows(rows)
        self.prd_preview_note.set("PRD numbers follow export order. Set the starting number for each batch.")

    def _refresh_summary_cards(self) -> None:
        data = self._plot_data()
        product_names = set(data['products'])
        self.summary_samples.set(str(len(self.sample_inputs)))
        self.summary_products.set(str(len(product_names)))
        self.summary_rows.set(str(len(self.results)))
        metric_key, _ylabel, multiplier = PLOT_METRICS[self.plot_metric.get()]
        values = [
            float(row.get(metric_key) or 0) * multiplier
            for row in data['rows']
            if not row.get("is_reactant") and row.get(metric_key) is not None
        ]
        peak = _float_text(max(values), 5) if values else "-"
        self.summary_peak.set(peak)
        sample_count = len(data['samples'])
        sample_label = "sample" if sample_count == 1 else "samples"
        product_label = "product" if len(product_names) == 1 else "products"
        if self.results:
            self.figure_status_text.set(
                f"{sample_count} {sample_label} | {len(product_names)} {product_label} | peak {peak}"
            )
            if self.plot_right_metric.get() != "None":
                missing = sum(not math.isfinite(value) for value in self._overlay_values(data['samples']))
                if missing:
                    self.figure_status_text.set(self.figure_status_text.get() + f" | Right axis: {missing} unavailable")
        else:
            self.figure_status_text.set("No calculated figure yet.")

    def load_data_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Load product data",
            filetypes=[("CSV and Excel files", "*.csv *.xlsx *.xlsm"), ("All files", "*.*")],
        )
        if not path:
            return
        file_path = Path(path)
        try:
            parsed = parse_uploaded_table(file_path.name, file_path.read_bytes())
        except Exception as exc:
            messagebox.showerror("Import failed", str(exc))
            return
        self.measurements = parsed.get("rows", [])
        self.sample_inputs = parsed.get("sample_inputs", {}) or {}
        if parsed.get("dilution_factor") is not None:
            self.dilution_factor.set(parsed["dilution_factor"])
        self._set_product_columns(parsed.get("products") or list(dict.fromkeys(product_column(r) for r in self.measurements)) or self.input_products)
        self.results = []
        self.sample_summaries = {}
        self.selected_samples = None
        self._sync_sample_inputs()
        self.measurement_table.load_rows(self._display_measurements())
        self._refresh_results_table()
        self.draw_plot()
        self._refresh_summary_cards()
        self.status_text.set(f"Loaded {len(self.measurements)} rows from {file_path.name}.")

    def _append_sample(self, mea, repeat, cfg=None):
        mea = normalize_mea_id(mea)
        inputs = {key: dict(value) for key, value in self.sample_inputs.items()}
        temporary = "__new_sample__"
        inputs[temporary] = {"total_charge_c": None, "electrolyte_volume_l": None,
            "initial_reactant_concentration_mol_l": None,
            **(cfg or self.mea_details.get(mea, {})), "mea_id": mea, "hplc_repeat": repeat}
        try:
            renamed, updated = identity_mapping(inputs)
        except ValueError as exc:
            messagebox.showerror("Cannot add sample", str(exc))
            return
        key = renamed[temporary]
        self.sample_inputs = updated
        self.measurements.extend(calculation_rows([
            {"sample": key, "mea_id": mea, "hplc_repeat": repeat}], self.input_products))
        self._sync_sample_inputs()
        self.measurement_table.load_rows(self._display_measurements())
        index = str(len(self.measurement_table.rows) - 1)
        self.measurement_table.tree.selection_set(index)
        self.measurement_table.tree.see(index)

    def add_measurement(self) -> None:
        self.measurement_table._close_editor(save=True)
        mea = simpledialog.askstring("Add Sample", "Sample (MEA ID), e.g. P005-MEA-014:", parent=self.root)
        if mea and mea.strip():
            self._append_sample(mea, "repeat1")

    def add_hplc_repeat(self) -> None:
        self.measurement_table._close_editor(save=True)
        index = self.measurement_table.selected_index()
        if index is None:
            messagebox.showinfo("Select a sample", "Select the sample to repeat first.")
            return
        cfg = self.sample_inputs[self.measurement_table.rows[index]["sample"]]
        mea = cfg["mea_id"]
        repeats = [int(c.get("hplc_repeat", "repeat1")[6:]) for c in self.sample_inputs.values() if c.get("mea_id") == mea]
        self._append_sample(mea, f"repeat{max(repeats) + 1}", cfg)

    def delete_measurement(self) -> None:
        idx = self.measurement_table.selected_index()
        if idx is None:
            return
        sample = self.measurement_table.rows[idx]["sample"]
        self.measurements = [r for r in self.measurements if r["sample"] != sample]
        self.sample_inputs.pop(sample, None)
        self.results = [r for r in self.results if r["sample"] != sample]
        self.sample_summaries.pop(sample, None)
        self._sync_sample_inputs()
        self.measurement_table.load_rows(self._display_measurements())
        self._refresh_results_table()
        self.draw_plot()

    def clear_measurements(self) -> None:
        self.measurements = []
        self.sample_inputs = {}
        self.results = []
        self.sample_summaries = {}
        self.selected_samples = None
        self._refresh_all()
        self.status_text.set("Measurements cleared.")

    def export_input_csv(self) -> None:
        self.measurement_table._close_editor(save=True)
        self.sample_table._close_editor(save=True)
        if not self._measurement_table_changed():
            return
        path = filedialog.asksaveasfilename(title="Export editable input table",
            defaultextension=".csv", filetypes=[("CSV files", "*.csv")], initialfile="productscope_inputs.csv")
        if not path:
            return
        metadata = ['mea_name', 'total_charge_c', 'electrolyte_volume_l',
                    'initial_reactant_concentration_mol_l']
        headers = ['sample', 'hplc_repeat', *self.input_products, *metadata, 'dilution_factor']
        with Path(path).open('w', newline='', encoding='utf-8-sig') as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for row in self.measurement_table.rows:
                cfg = self.sample_inputs[row['sample']]
                values = {key: cfg.get(key, '') if key == 'mea_name' else _float_text(cfg.get(key), 15) for key in metadata}
                writer.writerow({'sample': row['mea_id'], 'hplc_repeat': row['hplc_repeat'],
                    **{p: row.get(p, '') for p in self.input_products}, **values,
                    'dilution_factor': self.dilution_factor.get()})
        self.status_text.set(f"Saved editable input table to {Path(path).name}.")

    def choose_input_products(self) -> None:
        self.measurement_table._close_editor(save=True)
        choices = list(dict.fromkeys([*self.input_products,
            *[p['canonical_name'] for p in self.product_library['products']]]))
        dialog = Toplevel(self.root)
        dialog.title('Product columns')
        variables = {p: BooleanVar(dialog, value=p in self.input_products) for p in choices}
        ttk.Label(dialog, text='Choose the products measured in each sample.').pack(padx=16, pady=10)
        for p, variable in variables.items():
            ttk.Checkbutton(dialog, text=p, variable=variable).pack(anchor='w', padx=16)
        def apply():
            selected = [p for p, variable in variables.items() if variable.get()]
            if not selected:
                messagebox.showwarning('Select products', 'Choose at least one product.', parent=dialog)
                return
            rows = self.measurement_table.rows
            if any(str(row.get(p, '')).strip() for row in rows for p in self.input_products if p not in selected):
                messagebox.showwarning('Product has measurements', 'Clear the concentration cells before removing that product column.', parent=dialog)
                return
            self._set_product_columns(selected)
            self.measurements = calculation_rows(rows, selected)
            self.measurement_table.load_rows(grid_rows(self.measurements, self.sample_inputs, selected))
            try:
                (BASE_DIR / 'input_preferences.json').write_text(json.dumps(selected, indent=2))
            except OSError as exc:
                messagebox.showwarning('Preferences not saved', str(exc), parent=dialog)
            self.results = []
            self.sample_summaries = {}
            self._refresh_results_table()
            self.draw_plot()
            dialog.destroy()
        ttk.Button(dialog, text='Apply', command=apply).pack(pady=12)

    def _remember_paste_cell(self, event):
        row = self.measurement_table.tree.identify_row(event.y)
        column = self.measurement_table.tree.identify_column(event.x)
        if row and column:
            self._paste_cell = (int(row), int(column[1:]) - 1)

    def paste_measurements(self, _event=None):
        self.measurement_table._close_editor(save=True)
        start_row, start_col = getattr(self, '_paste_cell', (0, 2))
        try:
            block = list(csv.reader(io.StringIO(self.root.clipboard_get()), delimiter='\t'))
            rows = [dict(r) for r in self.measurement_table.rows]
            columns = [key for key, _, _ in self.measurement_table.columns]
            if start_row + len(block) > len(rows) or any(start_col + len(line) > len(columns) for line in block):
                raise ValueError('The pasted block does not fit. Add sample rows first, then click the first destination cell.')
            for i, line in enumerate(block):
                for j, value in enumerate(line):
                    rows[start_row + i][columns[start_col + j]] = value.strip()
            calculation_rows(rows, self.input_products)
            candidate = {r['sample']: {**self.sample_inputs[r['sample']], 'mea_id': r['mea_id'],
                'hplc_repeat': r['hplc_repeat']} for r in rows}
            identity_mapping(candidate)
        except Exception as exc:
            messagebox.showerror('Cannot paste', str(exc))
            return 'break'
        self.measurement_table.load_rows(rows)
        self._measurement_table_changed()
        return 'break'

    def load_library_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Load product library",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
                raise ValueError("Expected JSON format: {\"products\": [...]}")
        except Exception as exc:
            messagebox.showerror("Library load failed", str(exc))
            return
        self.product_library = payload
        self.library_table.load_rows(self._display_library())
        self.status_text.set(f"Loaded product library from {Path(path).name}.")
        self.draw_plot()

    def save_library_file(self) -> None:
        self._library_table_changed()
        path = filedialog.asksaveasfilename(
            title="Save product library",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
            initialfile="product_library.json",
        )
        if not path:
            return
        Path(path).write_text(json.dumps(self.product_library, indent=2), encoding="utf-8")
        self.status_text.set(f"Saved product library to {Path(path).name}.")

    def load_builtin_library(self) -> None:
        self.product_library = self._load_default_library()
        self.library_table.load_rows(self._display_library())
        self.status_text.set("Loaded built-in product library.")
        self.draw_plot()

    def add_product(self) -> None:
        products = self.product_library.setdefault("products", [])
        products.append(
            {
                "canonical_name": "New product",
                "aliases": [],
                "electrons": 0,
                "stoich_factor": 1,
                "carbon_number": 1,
                "color": FALLBACK_PALETTE[len(products) % len(FALLBACK_PALETTE)],
                "is_reactant": False,
            }
        )
        self.library_table.load_rows(self._display_library())

    def delete_product(self) -> None:
        idx = self.library_table.selected_index()
        if idx is None:
            return
        self.product_library.get("products", []).pop(idx)
        self.library_table.load_rows(self._display_library())
        self.draw_plot()

    def choose_overlay_color(self) -> None:
        _rgb, color = colorchooser.askcolor(
            color=self.plot_overlay_color.get(), title="Right-axis overlay colour", parent=self.root,
        )
        if color:
            self.plot_overlay_color.set(color)
            self.overlay_color_button.configure(background=color, activebackground=color)
            self.draw_plot()

    def choose_product_color(self) -> None:
        idx = self.library_table.selected_index()
        if idx is None:
            return
        current = self.product_library.get("products", [])[idx].get("color", "#6b7280")
        _rgb, color = colorchooser.askcolor(color=current, title="Choose product color")
        if not color:
            return
        self.product_library["products"][idx]["color"] = color
        self.library_table.load_rows(self._display_library())
        self.draw_plot()

    def _product_settings(self) -> dict:
        self._library_table_changed()
        settings = {}
        reactant = _norm(self.reactant_name.get())
        for idx, product in enumerate(self.product_library.get("products", [])):
            canonical = (product.get("canonical_name") or "").strip()
            if not canonical:
                continue
            row = {
                "canonical_name": canonical,
                "electrons": _to_float(product.get("electrons"), 0.0),
                "stoich_factor": _to_float(product.get("stoich_factor"), 1.0),
                "carbon_number": _to_int(product.get("carbon_number"), 0),
                "is_reactant": bool(product.get("is_reactant")) or _norm(canonical) == reactant,
                "color": product.get("color") or FALLBACK_PALETTE[idx % len(FALLBACK_PALETTE)],
            }
            settings[canonical] = row
            for alias in product.get("aliases", []):
                if alias:
                    settings[alias] = dict(row)
        for measurement in self.measurements:
            product = (measurement.get("product") or "").strip()
            if product and product not in settings:
                settings[product] = {
                    "canonical_name": product,
                    "electrons": 0,
                    "stoich_factor": 1,
                    "carbon_number": 3 if _norm(product) == reactant else 1,
                    "is_reactant": _norm(product) == reactant,
                    "color": FALLBACK_PALETTE[0],
                }
        return settings

    def run_calculations(self) -> None:
        self.results = []
        self.sample_summaries = {}
        self.sample_table._close_editor(save=True)
        self.measurement_table._close_editor(save=True)
        self._sample_table_changed()
        if not self._measurement_table_changed():
            return
        self._sample_table_changed()
        if not self.measurements:
            messagebox.showwarning("No measurements", "Load or add measurements before calculating.")
            return
        payload = {
            "dilution_factor": self.dilution_factor.get(),
            "reactant_name": self.reactant_name.get().strip() or "Glycerol",
            "sample_inputs": self.sample_inputs,
        }
        try:
            result = compute_metrics(self.measurements, self._product_settings(), payload)
        except Exception as exc:
            messagebox.showerror("Calculation failed", str(exc))
            return
        self.results = result.get("rows", [])
        self.sample_summaries = {row['sample']: row for row in result.get('sample_summaries', [])}
        self._refresh_sample_filter()
        self._refresh_results_table()
        self._refresh_summary_cards()
        self.draw_plot()
        self.status_text.set(f"Calculated {len(self.results)} result rows.")

    def _result_row_for_export(self, row: dict) -> dict:
        sample_cfg = self.sample_inputs.get(row.get("sample"), {})
        return {
            **row,
            "sample": sample_cfg.get("mea_id", row.get("sample", "")),
            "mea_id": sample_cfg.get("mea_id", row.get("sample", "")),
            "hplc_repeat": sample_cfg.get("hplc_repeat", "repeat1"),
            "mea_name": sample_cfg.get("mea_name", ""),
            "total_charge_c": sample_cfg.get("total_charge_c", ""),
            "electrolyte_volume_l": sample_cfg.get("electrolyte_volume_l", ""),
            "initial_reactant_concentration_mol_l": sample_cfg.get(
                "initial_reactant_concentration_mol_l", ""
            ),
        }

    def export_results_csv(self) -> None:
        self.run_calculations()
        if not self.results:
            messagebox.showwarning("No results", "Run calculations before exporting.")
            return
        path = filedialog.asksaveasfilename(
            title="Export results CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="productscope_results.csv",
        )
        if not path:
            return
        with Path(path).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=RESULT_HEADERS)
            writer.writeheader()
            for row in self.results:
                export_row = self._result_row_for_export(row)
                writer.writerow({header: export_row.get(header, "") for header in RESULT_HEADERS})
        self.status_text.set(f"Exported results to {Path(path).name}.")

    def export_bo_objectives_csv(self) -> None:
        # Recompute from the current inputs so edited repeats/charge cannot be
        # paired with objective values left over from an earlier analysis.
        self.run_calculations()
        if not self.sample_summaries:
            messagebox.showwarning("No results", "Run calculations before exporting BO objectives.")
            return
        try:
            rows = build_prd_rows(self.sample_summaries.values(), self.sample_inputs,
                                  self.prd_start_number.get())
        except ValueError as exc:
            messagebox.showerror("Cannot export PRD report", str(exc))
            return
        path = filedialog.asksaveasfilename(
            title="Export BO objectives CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="productscope_bo_objectives.csv",
        )
        if not path:
            return
        with Path(path).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=BO_OBJECTIVE_HEADERS)
            writer.writeheader()
            writer.writerows(rows)
        self.status_text.set(f"Exported BO objectives to {Path(path).name}.")

    def load_master_details(self) -> None:
        path = filedialog.askopenfilename(title="Select master register",
                                          filetypes=[("Excel workbook", "*.xlsx")])
        if not path:
            return
        try:
            details = read_mea_details(path)
        except Exception as exc:
            messagebox.showerror("Master lookup failed", str(exc))
            return
        self.sample_table._close_editor(save=True)
        self._sample_table_changed()
        self.mea_details = details
        self.mea_names = {mea: cfg["mea_name"] for mea, cfg in details.items()}
        matched = 0
        missing = []
        incomplete = []
        for sample, cfg in self.sample_inputs.items():
            mea = normalize_mea_id(cfg.get("mea_id", sample))
            cfg["mea_id"] = mea
            if mea in details:
                cfg.update(details[mea])
                matched += 1
                if any(value is None for value in details[mea].values()):
                    incomplete.append(mea)
            else:
                missing.append(mea)
        self.sample_table.load_rows(self._display_sample_inputs())
        self._sample_table_changed()
        # Existing objective values no longer describe the newly loaded inputs.
        self.results = []
        self.sample_summaries = {}
        self._refresh_results_table()
        self._refresh_summary_cards()
        self.draw_plot()
        notice = f"Loaded MEA details for {matched} samples from {Path(path).name}. Run Analysis to update results."
        if missing:
            notice += " Not found (inputs kept): " + ", ".join(dict.fromkeys(missing)) + "."
        if incomplete:
            notice += " Missing or invalid master values left blank: " + ", ".join(dict.fromkeys(incomplete)) + "."
        self.status_text.set(notice)
        if missing:
            messagebox.showwarning("MEA IDs not found", "These samples were not found in the master register:\n"
                + "\n".join(dict.fromkeys(missing))
                + "\n\nUse the registered MEA ID without suffixes such as -failed or -2. Enter HPLC repeats in HPLC Repeat.")

    def _color_map(self) -> dict[str, str]:
        color_map = {}
        for idx, product in enumerate(self.product_library.get("products", [])):
            canonical = (product.get("canonical_name") or "").strip()
            if canonical:
                color_map[canonical] = product.get("color") or FALLBACK_PALETTE[idx % len(FALLBACK_PALETTE)]
        return color_map

    def _plot_data(self) -> dict:
        rows = [row for row in self.results if not row.get("is_reactant")]
        if self.selected_samples is not None:
            rows = [row for row in rows if row.get("sample") in self.selected_samples]

        metric_key, ylabel, multiplier = PLOT_METRICS[self.plot_metric.get()]
        samples = [sample for sample in self.sample_inputs if any(row.get("sample") == sample for row in rows)]
        for row in rows:
            sample = row.get("sample")
            if sample not in samples:
                samples.append(sample)

        products = []
        for product in self.product_library.get("products", []):
            canonical = product.get("canonical_name")
            if canonical and any(_norm(row.get("product")) == _norm(canonical) for row in rows):
                products.append(canonical)
        for row in rows:
            product = row.get("product")
            if product and product not in products:
                products.append(product)

        matrix = {sample: {product: 0.0 for product in products} for sample in samples}
        for row in rows:
            sample = row.get("sample")
            product = row.get("product")
            value = row.get(metric_key)
            if sample in matrix and product in matrix[sample] and value is not None:
                matrix[sample][product] += max(0.0, float(value) * multiplier)

        return {
            "rows": rows,
            "metric_key": metric_key,
            "metric_label": ylabel,
            "samples": samples,
            "products": products,
            "matrix": matrix,
        }

    def _sample_labels(self, samples):
        ids = [self.sample_inputs.get(s, {}).get("mea_id", s) for s in samples]
        return [f"{mea} [{self.sample_inputs[s].get('hplc_repeat', 'repeat1')}]"
                if ids.count(mea) > 1 else mea for s, mea in zip(samples, ids)]

    def _overlay_values(self, samples: list[str]) -> list[float]:
        metric = self.plot_right_metric.get()
        values = []
        for sample in samples:
            rows = [row for row in self.results if row.get('sample') == sample]
            summary = self.sample_summaries.get(sample, {})
            value = math.nan
            if metric in BO_OBJECTIVE_METRICS:
                value = _to_float(summary.get(BO_OBJECTIVE_METRICS[metric]), math.nan)
            elif metric == 'Total FE (%)':
                efficiencies = [_to_float(row.get('faradaic_efficiency_pct'), math.nan)
                                for row in rows if not row.get('is_reactant')]
                if efficiencies and all(math.isfinite(fe) for fe in efficiencies):
                    value = sum(efficiencies)
            elif metric == 'Total charge passed (C)':
                value = _to_float(summary.get('total_charge_c'), math.nan)
            elif metric == 'Carbon conversion (%)':
                initial = _to_float(summary.get('initial_reactant_concentration_mol_l'), math.nan)
                # Reactant depletion, not product carbon recovery / carbon balance.
                remaining = [_to_float(row.get('adjusted_concentration_mol_l'), math.nan)
                             for row in rows if _norm(row.get('product')) == _norm(summary.get('reactant_name'))]
                if initial > 0 and math.isfinite(initial) and remaining and all(math.isfinite(v) for v in remaining):
                    value = 100.0 * (initial - sum(remaining)) / initial
            values.append(value if math.isfinite(value) else math.nan)
        return values

    def _draw_empty_plot(self, axis) -> None:
        axis.clear()
        axis.text(
            0.5,
            0.5,
            "No samples selected." if self.results and not self.selected_samples and self.selected_samples is not None
            else "Run calculations to build the figure.",
            ha="center",
            va="center",
            fontname=PLOT_FONT_FAMILY,
            fontsize=12,
            color=COLORS["muted"],
        )
        axis.set_axis_off()

    def _apply_plot_style(self, figure: Figure, axis, samples: list[str], products: list[str], *, right_axis=None, for_export: bool = False) -> None:
        axis.set_xlabel(self._plot_title_text(self.plot_x_title.get() or "Sample"), fontname=PLOT_FONT_FAMILY, fontsize=11)
        axis.set_ylabel(self._plot_title_text(self.plot_y_title.get() or PLOT_METRICS[self.plot_metric.get()][1]), fontname=PLOT_FONT_FAMILY, fontsize=11)
        rotate_x = 30 if len(samples) > 5 or any(len(str(sample)) > 14 for sample in samples) else 0
        axis.tick_params(axis="x", rotation=rotate_x, labelsize=9)
        axis.tick_params(axis="y", labelsize=9)
        if rotate_x:
            for label in axis.get_xticklabels():
                label.set_horizontalalignment("right")
        for label in axis.get_xticklabels() + axis.get_yticklabels():
            label.set_fontname(PLOT_FONT_FAMILY)
        if self.plot_grid_enabled.get():
            axis.grid(axis="y", color="#d8e0ea", linewidth=0.8, linestyle=self._grid_linestyle())
        else:
            axis.grid(False)
        axis.axhline(0, color="#94a3b8", linewidth=0.9)
        axis.set_axisbelow(True)
        axis.set_facecolor("#ffffff")
        figure.patch.set_facecolor("#ffffff")

        self._layout_plot_legend(figure, axis, right_axis)

    def _layout_plot_legend(self, figure: Figure, axis, right_axis=None) -> None:
        legend_position = self.plot_legend_position.get()
        handles, labels = axis.get_legend_handles_labels()
        if right_axis is not None:
            line_handles, line_labels = right_axis.get_legend_handles_labels()
            handles += line_handles
            labels += line_labels
        if legend_position == "None" or not handles:
            figure.tight_layout(pad=1.1)
            return

        width, height = figure.bbox.width, figure.bbox.height
        padding = 8 * figure.dpi / 72
        renderer = RendererAgg(width, height, figure.dpi)
        locations = {
            "Top": ("upper center", (0.5, 1 - padding / height)),
            "Bottom": ("lower center", (0.5, padding / height)),
            "Right": ("center right", (1 - padding / width, 0.5)),
        }
        location, anchor = locations[legend_position]
        columns = 1 if legend_position == "Right" else min(len(handles), 4)
        # Measure the actual legend and reserve its own band outside the axes.
        # Reducing columns on narrow figures keeps the font at publication size.
        while True:
            legend = axis.legend(
                handles, labels, loc=location, bbox_to_anchor=anchor,
                bbox_transform=figure.transFigure, ncol=columns,
                frameon=False, borderaxespad=0, columnspacing=1.4,
                prop={"family": PLOT_FONT_FAMILY, "size": 9},
            )
            box = legend.get_window_extent(renderer)
            if box.width <= width - 2 * padding or columns == 1:
                break
            legend.remove()
            columns -= 1
        rect = [0, 0, 1, 1]
        if legend_position == "Top":
            rect[3] = 1 - (box.height + 2 * padding) / height
        elif legend_position == "Bottom":
            rect[1] = (box.height + 2 * padding) / height
        else:
            rect[2] = 1 - (box.width + 2 * padding) / width
        legend.set_in_layout(False)
        figure.tight_layout(pad=1.1, rect=rect)
        # Include the external legend in tight-bounding-box exports.
        legend.set_in_layout(True)

    def _add_bar_labels(self, axis, samples: list[str], values: list[float], bottoms: list[float], totals: list[float]) -> None:
        mode = self.plot_label_mode.get()
        if mode == "Off":
            return
        threshold = max(0.0, _to_float(self.plot_label_threshold.get(), 10.0))
        y_min, y_max = axis.get_ylim()
        y_span = max(y_max - y_min, 1.0)
        inside_min_height = y_span * 0.045

        for idx, value in enumerate(values):
            if value <= 0:
                continue
            share = (value / totals[idx] * 100.0) if totals[idx] else 0.0
            if mode == "Smart" and share < threshold:
                continue
            x = idx
            bottom = bottoms[idx]
            label = _format_plot_value(value)
            if mode == "Inside" or (mode == "Smart" and value >= inside_min_height):
                axis.text(
                    x,
                    bottom + value / 2,
                    label,
                    ha="center",
                    va="center",
                    color="#ffffff",
                    fontsize=8,
                    fontweight="bold",
                    fontname=PLOT_FONT_FAMILY,
                )
            else:
                axis.text(
                    x,
                    bottom + value + y_span * 0.012,
                    label,
                    ha="center",
                    va="bottom",
                    color=COLORS["ink"],
                    fontsize=8,
                    fontname=PLOT_FONT_FAMILY,
                )

    def _draw_plot_on_axis(self, figure: Figure, axis, *, for_export: bool = False) -> bool:
        for old_axis in list(figure.axes):
            if old_axis is not axis:
                old_axis.remove()
        axis.clear()
        if for_export:
            width, height = self._plot_dimensions()
            figure.set_size_inches(width, height, forward=True)
        data = self._plot_data()
        rows = data["rows"]
        if not rows:
            self._draw_empty_plot(axis)
            return False

        samples = data["samples"]
        products = data["products"]
        matrix = data["matrix"]
        color_map = self._color_map()
        bottoms = [0.0 for _ in samples]
        totals = [sum(matrix[sample].get(product, 0.0) for product in products) for sample in samples]
        bar_width = 0.26 if len(samples) == 1 else 0.62
        for idx, product in enumerate(products):
            values = [matrix[sample].get(product, 0.0) for sample in samples]
            axis.bar(
                range(len(samples)),
                values,
                bottom=bottoms,
                width=bar_width,
                label=product,
                color=color_map.get(product, FALLBACK_PALETTE[idx % len(FALLBACK_PALETTE)]),
                edgecolor="white",
                linewidth=0.8,
            )
            self._add_bar_labels(axis, samples, values, bottoms, totals)
            bottoms = [bottom + value for bottom, value in zip(bottoms, values)]

        axis.set_xticks(range(len(samples)))
        axis.set_xticklabels(self._sample_labels(samples))
        if len(samples) == 1:
            axis.set_xlim(-0.65, 0.65)
        else:
            axis.set_xlim(-0.55, len(samples) - 0.45)
        if max(totals, default=0.0) > 0:
            axis.set_ylim(bottom=0, top=max(totals) * 1.16)
        right_axis = None
        if self.plot_right_metric.get() != 'None':
            right_axis = axis.twinx()
            values = self._overlay_values(samples)
            right_axis.plot(range(len(samples)), values, color=self.plot_overlay_color.get(),
                            linestyle=':', linewidth=1.6,
                            marker='o', markersize=5, markerfacecolor='white', markeredgewidth=1.4,
                            label=self.plot_right_metric.get(), zorder=5)
            right_axis.set_ylabel(self.plot_right_metric.get(), fontname=PLOT_FONT_FAMILY, fontsize=11, labelpad=10)
            right_axis.tick_params(axis='y', labelsize=9)
            for label in right_axis.get_yticklabels() + [right_axis.yaxis.get_offset_text()]:
                label.set_fontname(PLOT_FONT_FAMILY)
            right_axis.grid(False)
            finite_values = [value for value in values if math.isfinite(value)]
            low = min([0.0] + finite_values)
            high = max([0.0] + finite_values)
            span = max(high - low, 1.0)
            right_axis.set_ylim(low - span * .06 if low < 0 else 0, high + span * .16)
        self._apply_plot_style(figure, axis, samples, products, right_axis=right_axis, for_export=for_export)
        return True

    def draw_plot(self) -> None:
        self.figure.set_dpi(100)
        self._draw_plot_on_axis(self.figure, self.axis, for_export=False)
        self._refresh_summary_cards()
        self.canvas.draw()

    def export_plot(self) -> None:
        if not self.results:
            messagebox.showwarning("No plot", "Run calculations before exporting the plot.")
            return
        if not self._plot_data()['samples']:
            messagebox.showwarning("No samples", "Select at least one sample before exporting the plot.")
            return
        export_format = self.plot_export_format.get().lower()
        path = filedialog.asksaveasfilename(
            title="Export plot",
            defaultextension=f".{export_format}",
            filetypes=[
                ("PNG files", "*.png"),
                ("PDF files", "*.pdf"),
                ("SVG files", "*.svg"),
            ],
            initialfile=f"productscope_stacked_plot.{export_format}",
        )
        if not path:
            return
        export_figure = Figure(figsize=self._plot_dimensions(), dpi=self._plot_export_dpi())
        export_axis = export_figure.add_subplot(111)
        self._draw_plot_on_axis(export_figure, export_axis, for_export=True)
        export_figure.savefig(path, dpi=self._plot_export_dpi(), bbox_inches="tight", format=export_format)
        self.status_text.set(f"Exported plot to {Path(path).name}.")

    def export_plot_png(self) -> None:
        self.plot_export_format.set("PNG")
        self.export_plot()


def main() -> None:
    root = Tk()
    app = ProductScopeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
