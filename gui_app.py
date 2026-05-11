from __future__ import annotations

import csv
import json
from pathlib import Path
from tkinter import (
    DoubleVar,
    StringVar,
    Tk,
    colorchooser,
    filedialog,
    messagebox,
)
from tkinter import ttk

try:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
except ImportError as exc:  # pragma: no cover - exercised only when deps are missing.
    raise SystemExit(
        "Matplotlib is required for the native GUI.\n"
        "Install dependencies from the productscope folder with:\n"
        "  python3 -m pip install -r requirements.txt"
    ) from exc

try:
    from .calculations import compute_metrics
    from .table_parser import parse_uploaded_table
except ImportError:
    from calculations import compute_metrics
    from table_parser import parse_uploaded_table


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LIBRARY_FILE = BASE_DIR / "product_library_template.json"

RESULT_HEADERS = [
    "sample",
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
]

PLOT_METRICS = {
    "Adjusted Concentration (mM)": ("adjusted_concentration_mol_l", "Adjusted concentration (mM)", 1000.0),
    "Adjusted Concentration (mol/L)": ("adjusted_concentration_mol_l", "Adjusted concentration (mol/L)", 1.0),
    "Faradaic Efficiency (%)": ("faradaic_efficiency_pct", "Faradaic efficiency (%)", 1.0),
    "Selectivity (%)": ("selectivity_pct", "Selectivity (%)", 1.0),
    "Product Distribution (%)": ("product_distribution_pct", "Product distribution (%)", 1.0),
}

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
        return f"{float(value):.{digits}g}"
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


class EditableTable(ttk.Frame):
    def __init__(self, master, columns: list[tuple[str, str, int]], height: int = 8):
        super().__init__(master)
        self.columns = columns
        self.rows: list[dict] = []
        self._editor = None
        self._on_change = None

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
        self._close_editor(save=False)
        self.tree.delete(*self.tree.get_children())
        keys = [key for key, _, _ in self.columns]
        for idx, row in enumerate(self.rows):
            self.tree.insert("", "end", iid=str(idx), values=[row.get(key, "") for key in keys])

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
        if save and row_index < len(self.rows):
            self.rows[row_index][column_key] = editor.get()
            if self._on_change:
                self._on_change()
        editor.destroy()
        self._editor = None
        self.refresh()


class ProductScopeApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("ProductScope")
        self.root.geometry("1280x850")
        self.root.configure(bg=COLORS["bg"])
        self.measurements: list[dict] = []
        self.sample_inputs: dict[str, dict] = {}
        self.product_library = self._load_default_library()
        self.results: list[dict] = []

        self.dilution_factor = DoubleVar(value=2.0)
        self.reactant_name = StringVar(value="Glycerol")
        self.plot_metric = StringVar(value="Adjusted Concentration (mM)")
        self.sample_filter = StringVar(value="All Samples")
        self.status_text = StringVar(value="Ready.")
        self.summary_samples = StringVar(value="0")
        self.summary_products = StringVar(value="0")
        self.summary_rows = StringVar(value="0")
        self.summary_peak = StringVar(value="-")

        self._configure_style()
        self._build_ui()
        self._refresh_all()

    def _configure_style(self) -> None:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
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
        notebook.add(self.data_tab, text="Data")
        notebook.add(self.library_tab, text="Product Library")
        notebook.add(self.results_tab, text="Results")

        self._build_data_tab()
        self._build_library_tab()
        self._build_results_tab()

    def _build_data_tab(self) -> None:
        self.data_tab.grid_columnconfigure(0, weight=1)
        self.data_tab.grid_rowconfigure(2, weight=1)
        self.data_tab.grid_rowconfigure(4, weight=1)

        controls = ttk.Frame(self.data_tab)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(controls, text="Load CSV/XLSX", command=self.load_data_file, style="Primary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Add Measurement", command=self.add_measurement).pack(side="left", padx=6)
        ttk.Button(controls, text="Delete Measurement", command=self.delete_measurement).pack(side="left", padx=6)
        ttk.Button(controls, text="Clear Measurements", command=self.clear_measurements).pack(side="left", padx=6)
        ttk.Label(controls, text="Dilution coefficient").pack(side="left", padx=(24, 5))
        ttk.Entry(controls, textvariable=self.dilution_factor, width=8).pack(side="left")
        ttk.Label(controls, text="Reactant").pack(side="left", padx=(14, 5))
        ttk.Entry(controls, textvariable=self.reactant_name, width=16).pack(side="left")

        ttk.Label(self.data_tab, text="Measurements", style="Header.TLabel").grid(row=1, column=0, sticky="w")
        self.measurement_table = EditableTable(
            self.data_tab,
            [
                ("sample", "Sample", 180),
                ("product", "Product", 160),
                ("amount_mol_l", "Amount [mol/L]", 130),
            ],
            height=10,
        )
        self.measurement_table.grid(row=2, column=0, sticky="nsew", pady=(4, 12))
        self.measurement_table.set_on_change(self._measurement_table_changed)

        sample_controls = ttk.Frame(self.data_tab)
        sample_controls.grid(row=3, column=0, sticky="ew")
        ttk.Label(sample_controls, text="Per-sample electrolysis inputs", style="Header.TLabel").pack(side="left")
        ttk.Button(sample_controls, text="Refresh Samples", command=self._sync_sample_inputs).pack(side="right")

        self.sample_table = EditableTable(
            self.data_tab,
            [
                ("sample", "Sample", 180),
                ("total_charge_c", "Total Charge Q [C]", 150),
                ("electrolyte_volume_l", "Electrolyte Volume [L]", 160),
                ("initial_reactant_concentration_mol_l", "Initial Reactant Conc. [mol/L]", 200),
            ],
            height=8,
        )
        self.sample_table.grid(row=4, column=0, sticky="nsew", pady=(4, 0))
        self.sample_table.set_on_change(self._sample_table_changed)

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
        self.results_tab.grid_rowconfigure(3, weight=1)
        self.results_tab.grid_rowconfigure(5, weight=2)

        controls = ttk.Frame(self.results_tab)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(controls, text="Run Analysis", command=self.run_calculations, style="Primary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Export Results CSV", command=self.export_results_csv, style="Primary.TButton").pack(side="left", padx=6)
        ttk.Button(controls, text="Export Plot PNG", command=self.export_plot_png, style="Primary.TButton").pack(side="left", padx=6)
        ttk.Label(controls, text="Metric").pack(side="left", padx=(24, 5))
        metric_box = ttk.Combobox(controls, textvariable=self.plot_metric, values=list(PLOT_METRICS), state="readonly", width=30)
        metric_box.pack(side="left")
        metric_box.bind("<<ComboboxSelected>>", lambda _event: self.draw_plot())
        ttk.Label(controls, text="Sample").pack(side="left", padx=(14, 5))
        self.sample_filter_box = ttk.Combobox(controls, textvariable=self.sample_filter, state="readonly", width=22)
        self.sample_filter_box.pack(side="left")
        self.sample_filter_box.bind("<<ComboboxSelected>>", lambda _event: self.draw_plot())

        summary = ttk.Frame(self.results_tab)
        summary.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for column in range(4):
            summary.grid_columnconfigure(column, weight=1)
        self._add_summary_card(summary, 0, "Samples", self.summary_samples)
        self._add_summary_card(summary, 1, "Products", self.summary_products)
        self._add_summary_card(summary, 2, "Rows calculated", self.summary_rows)
        self._add_summary_card(summary, 3, "Peak plotted value", self.summary_peak)

        ttk.Label(self.results_tab, text="Calculated Results", style="Header.TLabel").grid(row=2, column=0, sticky="w")
        self.results_table = EditableTable(
            self.results_tab,
            [
                ("sample", "Sample", 150),
                ("product", "Product", 150),
                ("adjusted_concentration_mol_l", "Adj. Conc. [mol/L]", 150),
                ("moles", "Moles", 120),
                ("faradaic_efficiency_pct", "FE [%]", 110),
                ("selectivity_pct", "Selectivity [%]", 120),
                ("product_distribution_pct", "Distribution [%]", 130),
                ("carbon_balance_pct", "Carbon Balance [%]", 140),
            ],
            height=8,
        )
        self.results_table.grid(row=3, column=0, sticky="nsew", pady=(4, 12))

        ttk.Label(self.results_tab, text="Stacked Product Figure", style="Header.TLabel").grid(row=4, column=0, sticky="w")
        self.figure = Figure(figsize=(9.5, 4.8), dpi=100)
        self.axis = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.results_tab)
        self.canvas.get_tk_widget().grid(row=5, column=0, sticky="nsew", pady=(4, 0))

    def _add_summary_card(self, parent: ttk.Frame, column: int, label: str, value: StringVar) -> None:
        card = ttk.Frame(parent, style="Soft.TFrame", padding=(14, 10))
        card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 8, 0))
        ttk.Label(card, text=label, style="StatLabel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(card, textvariable=value, style="StatValue.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))

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

    def _display_measurements(self) -> list[dict]:
        return [
            {
                "sample": row.get("sample", ""),
                "product": row.get("product", ""),
                "amount_mol_l": _float_text(row.get("amount_mol_l"), 8),
            }
            for row in self.measurements
        ]

    def _display_sample_inputs(self) -> list[dict]:
        return [
            {
                "sample": sample,
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
                    "electrons": _float_text(product.get("electrons"), 8),
                    "stoich_factor": _float_text(product.get("stoich_factor"), 8),
                    "carbon_number": str(product.get("carbon_number", 0)),
                    "color": product.get("color", ""),
                    "is_reactant": "yes" if product.get("is_reactant") else "no",
                }
            )
        return out

    def _measurement_table_changed(self) -> None:
        self.measurements = [
            {
                "sample": (row.get("sample") or "Sample").strip(),
                "signal": "",
                "product": (row.get("product") or "Product").strip(),
                "amount_mol_l": _to_float(row.get("amount_mol_l"), 0.0),
            }
            for row in self.measurement_table.rows
        ]
        self._sync_sample_inputs()

    def _sample_table_changed(self) -> None:
        next_inputs = {}
        for row in self.sample_table.rows:
            sample = (row.get("sample") or "").strip()
            if not sample:
                continue
            next_inputs[sample] = {
                "total_charge_c": _to_float(row.get("total_charge_c"), 0.0),
                "electrolyte_volume_l": _to_float(row.get("electrolyte_volume_l"), 0.05),
                "initial_reactant_concentration_mol_l": _to_float(
                    row.get("initial_reactant_concentration_mol_l"), 0.1
                ),
            }
        old_to_new = {}
        old_samples = list(self.sample_inputs)
        for idx, sample in enumerate(next_inputs):
            if idx < len(old_samples) and old_samples[idx] != sample:
                old_to_new[old_samples[idx]] = sample
        for row in self.measurements:
            if row.get("sample") in old_to_new:
                row["sample"] = old_to_new[row["sample"]]
        self.sample_inputs = next_inputs
        self._refresh_sample_filter()
        self.measurement_table.load_rows(self._display_measurements())

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
            sample: self.sample_inputs.get(
                sample,
                {
                    "total_charge_c": 0.0,
                    "electrolyte_volume_l": 0.05,
                    "initial_reactant_concentration_mol_l": 0.1,
                },
            )
            for sample in samples
        }
        self.sample_table.load_rows(self._display_sample_inputs())
        self._refresh_sample_filter()

    def _refresh_sample_filter(self) -> None:
        current = self.sample_filter.get()
        values = ["All Samples"] + list(self.sample_inputs)
        self.sample_filter_box.configure(values=values)
        self.sample_filter.set(current if current in values else "All Samples")

    def _refresh_results_table(self) -> None:
        formatted = []
        for row in self.results:
            formatted.append(
                {
                    "sample": row.get("sample", ""),
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

    def _refresh_summary_cards(self) -> None:
        product_names = {row.get("product") for row in self.results if row.get("product") and not row.get("is_reactant")}
        self.summary_samples.set(str(len(self.sample_inputs)))
        self.summary_products.set(str(len(product_names)))
        self.summary_rows.set(str(len(self.results)))
        metric_key, _ylabel, multiplier = PLOT_METRICS[self.plot_metric.get()]
        values = [
            float(row.get(metric_key) or 0) * multiplier
            for row in self.results
            if not row.get("is_reactant") and row.get(metric_key) is not None
        ]
        self.summary_peak.set(_float_text(max(values), 5) if values else "-")

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
        self._sync_sample_inputs()
        self.measurement_table.load_rows(self._display_measurements())
        self._refresh_summary_cards()
        self.status_text.set(f"Loaded {len(self.measurements)} rows from {file_path.name}.")

    def add_measurement(self) -> None:
        self.measurements.append({"sample": "Sample", "signal": "", "product": "Product", "amount_mol_l": 0.0})
        self._sync_sample_inputs()
        self.measurement_table.load_rows(self._display_measurements())

    def delete_measurement(self) -> None:
        idx = self.measurement_table.selected_index()
        if idx is None:
            return
        self.measurements.pop(idx)
        self._sync_sample_inputs()
        self.measurement_table.load_rows(self._display_measurements())

    def clear_measurements(self) -> None:
        self.measurements = []
        self.sample_inputs = {}
        self.results = []
        self._refresh_all()
        self.status_text.set("Measurements cleared.")

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
        self._measurement_table_changed()
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
        self._refresh_results_table()
        self._refresh_summary_cards()
        self.draw_plot()
        self.status_text.set(f"Calculated {len(self.results)} result rows.")

    def _result_row_for_export(self, row: dict) -> dict:
        sample_cfg = self.sample_inputs.get(row.get("sample"), {})
        return {
            **row,
            "total_charge_c": sample_cfg.get("total_charge_c", ""),
            "electrolyte_volume_l": sample_cfg.get("electrolyte_volume_l", ""),
            "initial_reactant_concentration_mol_l": sample_cfg.get(
                "initial_reactant_concentration_mol_l", ""
            ),
        }

    def export_results_csv(self) -> None:
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

    def _color_map(self) -> dict[str, str]:
        color_map = {}
        for idx, product in enumerate(self.product_library.get("products", [])):
            canonical = (product.get("canonical_name") or "").strip()
            if canonical:
                color_map[canonical] = product.get("color") or FALLBACK_PALETTE[idx % len(FALLBACK_PALETTE)]
        return color_map

    def draw_plot(self) -> None:
        self.axis.clear()
        rows = [row for row in self.results if not row.get("is_reactant")]
        selected_sample = self.sample_filter.get()
        if selected_sample and selected_sample != "All Samples":
            rows = [row for row in rows if row.get("sample") == selected_sample]
        if not rows:
            self.axis.text(0.5, 0.5, "Run calculations to build the figure.", ha="center", va="center")
            self.axis.set_axis_off()
            self.canvas.draw_idle()
            self._refresh_summary_cards()
            return

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

        color_map = self._color_map()
        bottoms = [0.0 for _ in samples]
        for idx, product in enumerate(products):
            values = [matrix[sample].get(product, 0.0) for sample in samples]
            self.axis.bar(
                samples,
                values,
                bottom=bottoms,
                label=product,
                color=color_map.get(product, FALLBACK_PALETTE[idx % len(FALLBACK_PALETTE)]),
                edgecolor="white",
                linewidth=0.8,
            )
            bottoms = [bottom + value for bottom, value in zip(bottoms, values)]

        self.axis.set_ylabel(ylabel)
        self.axis.set_xlabel("Sample")
        self.axis.tick_params(axis="x", rotation=30)
        self.axis.legend(loc="upper center", bbox_to_anchor=(0.5, 1.16), ncol=min(max(len(products), 1), 4))
        self.axis.grid(axis="y", color="#d8e0ea", linewidth=0.8)
        self.axis.set_facecolor("#ffffff")
        self.figure.patch.set_facecolor("#ffffff")
        self.figure.tight_layout()
        self._refresh_summary_cards()
        self.canvas.draw_idle()

    def export_plot_png(self) -> None:
        if not self.results:
            messagebox.showwarning("No plot", "Run calculations before exporting the plot.")
            return
        path = filedialog.asksaveasfilename(
            title="Export plot PNG",
            defaultextension=".png",
            filetypes=[("PNG files", "*.png")],
            initialfile="productscope_stacked_plot.png",
        )
        if not path:
            return
        self.figure.savefig(path, dpi=300, bbox_inches="tight")
        self.status_text.set(f"Exported plot to {Path(path).name}.")


def main() -> None:
    root = Tk()
    app = ProductScopeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
