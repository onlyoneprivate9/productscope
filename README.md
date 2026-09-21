# ProductScope

ProductScope is a cross-platform desktop app for product analysis from tabular concentration data. It is designed for chromatography and electrochemical workflows where you need to map products, apply per-sample experiment inputs, calculate product metrics, and export publication-ready stacked figures.

## What It Does

- Import `.csv` or `.xlsx` product data with flexible column headers.
- Reopen exported analysis CSV files that include saved per-sample inputs.
- Edit measurements, sample inputs, and product definitions in one desktop GUI.
- Use a product library JSON for aliases, electrons, stoichiometric factors, carbon numbers, reactant flags, and plot colors.
- Calculate:
  - adjusted concentration
  - moles
  - Faradaic efficiency
  - selectivity
  - product distribution
  - carbon balance
  - C2/C3 total FE and absolute C2/C3 carbon produced for Bayesian optimisation
- Export:
  - results CSV
  - BO objectives CSV (one row per sample)
  - product library JSON
  - high-resolution stacked product plot PNG

## Install

From this folder:

```bash
python3 -m pip install -r requirements.txt
```

On Windows, use `python` instead of `python3` if needed:

```powershell
python -m pip install -r requirements.txt
```

## Run

macOS:

```bash
./launch_productscope.command
```

Windows:

```powershell
Launch_ProductScope.bat
```

You can also run the GUI directly:

```bash
python3 gui_app.py
```

## Data File Format

Required columns, with flexible header matching:

- sample name: `sample`, `sample name`, `sample_id`, `run`, etc.
- product: `product`, `name`, `compound`, `species`, etc.
- amount: `amount`, `concentration`, `amount [mol/L]`, `conc`, etc.

Optional columns:

- signal or detector channel
- total charge `Q` in C
- electrolyte volume in L
- initial reactant concentration in mol/L

## Product Library JSON

Use `product_library_template.json` as the starting point:

```json
{
  "products": [
    {
      "canonical_name": "Formic acid",
      "aliases": ["FA", "formic acid"],
      "electrons": 2.6666666666666665,
      "stoich_factor": 1,
      "carbon_number": 1,
      "color": "#10b981",
      "is_reactant": false
    }
  ]
}
```

## Calculation Equations

The built-in library uses glycerol-based electron equivalents per mole of product, with `stoich_factor = 1`. For neutral products C_a H_b O_c, the allocation is `z = 2*c - b + 2*a/3`, referenced to glycerol's average carbon oxidation state. Thus glycolic acid uses `z = 10/3` and oxalic acid uses `z = 22/3`. This is a consistent charge-accounting convention, not a reaction-mechanism assignment; full pathway balances must include all coproducts without double-counting their charge. See [Table S1 of the supporting information](https://www.rsc.org/suppdata/d4/ee/d4ee01824a/d4ee01824a2.pdf).

Per row:

- `C_adjusted = C_measured * dilution_factor`
- `n_product = C_adjusted * V_sample`

Per canonical product, per sample:

- `FE (%) = 100 * (n * z * F) / (s * Q)`
- `Selectivity (%) = 100 * n_product / n_reactant_consumed`
- `Distribution (%) = 100 * n_product / sum(n_non_reactant_products)`

Per sample:

- `n_reactant_consumed = (C_initial_reactant - C_final_reactant_adjusted) * V_sample`
- `Carbon balance (%) = 100 * sum(carbon_i * n_i_non_reactant) / (carbon_reactant * n_reactant_consumed)`

Constant:

- `F = 96485.33212 C/mol`

## C2/C3 BO Objectives

### Entering measurements

The Measurements table has one row per **MEA ID + HPLC Repeat**, with product
concentrations across columns. All concentration cells use **mol/L**.

- **Add Sample** asks for the MEA ID and creates a blank `repeat1` row. If its
  details are already loaded from the master, they are filled automatically.
- **Add HPLC Repeat** uses the selected sample, picks the next repeat number,
  copies its electrolysis inputs, and leaves all concentrations blank.
- Double-click to edit one cell. To paste an Excel block, first add enough sample
  rows, single-click its top-left destination cell, then press **Cmd+V** on Mac
  or **Ctrl+V** on Windows. Paste contains values only, without a header row.
- **Products…** chooses columns from the product library and saves the selection
  for future sessions. Clear values before removing a populated product column.
- **Export Input CSV** saves the same wide layout, plus electrolysis inputs,
  name and dilution factor. Reopen it with **Load CSV/XLSX** to continue editing.
  With no samples, it exports an empty input template with the chosen columns.
- Existing product-per-row CSV/XLSX files and Results CSV files still load;
  their products become columns. Detector signals, where present, get separate
  columns such as `GA | UV`.

A blank cell means **not entered**, while `0` means a measured zero. Missing
target-product concentrations leave the associated BO objective unavailable.
The detailed Results CSV and PDA BO report retain their respective formats.

Example input CSV:

```csv
sample,hplc_repeat,Glycerol,Glyceric acid,Glycolic acid,Formic acid,Oxalic acid
P005-MEA-013,repeat1,0.022,0,0,0,0.00016
P005-MEA-013,repeat2,,,,,
```

Both objectives are maximised. Products are included
when their configured carbon number is 2 or 3 and they are not flagged as reactants.
Aliases and signals follow the same aggregation as the existing product metrics.

1. **C2/C3 total FE (%)**: `sum(FE_i)` over C2/C3 products, equivalently
   `100 * F / Q * sum(n_i * z_i / s_i)`.
2. **C2/C3 carbon produced (mmol-C)**: `1000 * (2 * sum(n_C2) + 3 * sum(n_C3))`,
   where product amounts `n_i` are in mol, calculated as `C_measured_i * dilution_factor * V_sample`.

The second objective is an absolute carbon amount, with no initial-glycerol or
consumed-glycerol denominator. Neither initial nor final glycerol concentration is
needed. For example, 2 mmol of C2 products plus 1 mmol of C3 products gives 7 mmol-C.
It is distinct from reactant-depletion carbon conversion and the existing carbon
balance. At the same product concentrations, doubling electrolyte volume doubles
this objective. Reactants, including unreacted glycerol, are excluded.

After **Run Analysis**, the Results tab previews the PDA report. **Export BO
Objectives CSV** recalculates the current inputs and exports one row per HPLC
sample, in input order, with columns:

`ID`, `Name`, `Project`, `Number`, `Repeat`, `Category`, `Label`, `Components`,
`BO 1 - C2/C3 FE(%)`, `BO 2 - C2/C3 carbon produced (mmol-C)`.

In **Per-sample electrolysis inputs**, enter the corresponding register ID in
**Sample (MEA ID)**, for example `P005-MEA-009`. MEA ID + HPLC Repeat is the
measurement identity throughout the app; there is no separate generated identity. Enter
**HPLC Repeat** as `repeat1`, `repeat2`, etc.; it is independent of the MEA's
electrolysis repeat. Two rows cannot have the same MEA ID and HPLC repeat.
Editing Sample (MEA ID) or HPLC Repeat updates the corresponding measurement
rows, results, figure labels, selection and exports immediately, without merging
injections or changing concentration values. Duplicate combinations are rejected
and the previous values are restored. Results show MEA ID and repeat separately;
figures append the repeat only when more than one displayed sample shares an MEA ID.
IDs such as `P05-MEA-1` are normalized to `P005-MEA-001`. Extra suffixes such
as `-failed` or `-2` are not removed automatically; use the registered MEA ID
and the separate HPLC Repeat field. Unmatched IDs are listed when loading the master.

For imports, use the MEA ID in `sample` and add a `repeat` or `hplc_repeat`
column. Legacy files with distinct source labels plus `mea_id` are also accepted;
the source labels are replaced by MEA ID + HPLC Repeat when loaded. Without a
repeat column, product rows under the same sample are treated as one analysis.
The regular Results CSV writes the current MEA ID in `sample` and stores the
HPLC repeat separately, so reloading preserves the same measurement identity.

Use **Load MEA details from master** to select `P005_GOR.xlsx`. It matches each
Sample (MEA ID) against `ExperimentPlan` and fills all four fields together:

- **Name** from `Name`.
- **Electrolyte Volume [L]** from `Electrolyte volume(L)`.
- **Total Charge Q [C]** = `Applied current (mA)` × `Applied current duration(s)` / 1000.
- **Initial Reactant Conc. [mol/L]** from `Concentration of glycerol (M)`.

Loading replaces these fields for matched samples, including all HPLC repeats
of a measurement. You can edit the values afterwards. The charge is calculated
from the registered constant current and duration; enter the measured integrated
charge manually when appropriate. Only the total-current header in mA is used,
not a current-density header. Missing or invalid master values are left blank
and reported; unmatched samples keep their existing inputs. Run Analysis again
after loading. This lookup only reads the workbook and never copies the MEA repeat.

**First PDA number (1–999)** defaults to 1; type a number or use its up/down
arrows. A batch starting at 15 produces
`P005-PDA-015`, `P005-PDA-016`, etc., regardless of the linked MEA numbers.
Set this explicitly for later batches; exporting does not automatically advance
it. `Components` stores the full MEA ID; `Project` comes from that ID; `Category`
is `PDA` and `Label` is `Product analysis`. Numbers are padded to three digits
and limited to 001–999. When opening CSV in Excel, import `Number` as text to
retain its leading zeros. This compact report is intended for column-name-based
import; it is not the full master worksheet layout. AutoCatX import is separate.

FE is in percent; carbon amount is in mmol-C. The regular Results CSV preserves
the MEA ID, HPLC repeat and name when reopened, and also includes
these sample totals, repeated on each product row; do not sum those repeated totals.
Both objectives are also available in the Figure tab's **Right axis** selector.

Unavailable objectives are blank in the table/CSV and gaps on the plot. FE requires
positive finite charge and valid FE for every measured C2/C3 product.
Both require positive finite volume and
dilution factor, and finite non-negative target product amounts. With valid inputs,
no measured C2/C3 products gives zero. FE above 100% is retained for review;
absolute carbon amount has no percentage upper bound.
Exports and overlays use the last analysis; run analysis again after editing inputs.

## Figure Sample Selection and Right Axis

In the Figure tab, open **Samples** to choose a subset with checkboxes, or use
**Select All** / **Clear All**, then **Apply**. Samples retain their input order.
Selecting all includes new samples after subsequent analysis; a subset stays
selected until changed. Selection affects the figure and its export only.

The **Right axis** selector adds sample markers connected by straight lines:

- **Total FE (%)**: sum of calculated FE for non-reactant products in each sample.
- **Carbon conversion (%)**: `100 * (C_initial - C_final_adjusted) / C_initial`,
  using the configured reactant and summing its measured signals. This is reactant
  carbon conversion at the app's fixed per-sample volume, not carbon balance or
  product carbon recovery. It requires a positive initial concentration and a
  measured final reactant concentration.
- **Total charge passed (C)**: the sample's charge, counted once.
- **None**: stacked bars only (default).

Overlay values use the last analysis results. Run Analysis after changing inputs.
Missing or non-finite values appear as gaps; total FE is unavailable if any
non-reactant product FE is unavailable. Zero remains a valid data point. The
figure status reports how many right-axis values are unavailable. Negative
conversion values are retained when the measured final concentration exceeds
the initial concentration.

The line shares the product legend and is included in PNG, PDF, and SVG exports.
Legend **None** hides both product and line legend entries. With a single selected
sample, the overlay appears as one marker. An empty selection cannot be exported.

## Development

Run tests from this folder:

```bash
python3 -m unittest discover -s tests -v
```

Run syntax checks:

```bash
python3 -m py_compile gui_app.py calculations.py table_parser.py check_gui_dependencies.py
```

## GitHub

This folder is prepared as a standalone project. To publish it later:

```bash
git remote add origin <private-productscope-repo-url>
git push -u origin main
```
