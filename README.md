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

After **Run Analysis**, the Results tab shows a BO objectives table. **Export BO
Objectives CSV** exports all analysed samples once each, with columns `sample`,
`c2_c3_total_fe_pct`, and `c2_c3_carbon_mmol`. FE is in percent; carbon amount is in
mmol-C. The regular Results CSV also includes
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
