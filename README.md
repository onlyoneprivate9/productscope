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
- Export:
  - results CSV
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
      "electrons": 2.6666666667,
      "stoich_factor": 1,
      "carbon_number": 1,
      "color": "#10b981",
      "is_reactant": false
    }
  ]
}
```

## Calculation Equations

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
