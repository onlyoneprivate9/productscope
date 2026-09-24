"""Import measurement tables, reshape sample grids, and export PRD records."""
from __future__ import annotations

import io
import math
import re
from pathlib import Path
from typing import Dict, List

import pandas as pd


# Sample identities, master details, and PRD exports.
OBJECTIVES = {
    "BO 1 - C2/C3 FE(%)": "c2_c3_total_fe_pct",
    "BO 2 - C2/C3 carbon produced (mmol-C)": "c2_c3_carbon_mmol",
}
HEADERS = ["ID", "Name", "Project", "Number", "Repeat", "Category", "Label",
           "Components", *OBJECTIVES]


def normalize_mea_id(value):
    value = str(value or "").strip()
    match = re.fullmatch(r"P([0-9]{1,3})-MEA-([0-9]{1,3})", value, re.IGNORECASE)
    return f"P{int(match[1]):03d}-MEA-{int(match[2]):03d}" if match else value


def sample_identity(mea, repeat):
    mea = normalize_mea_id(mea)
    repeat = str(repeat).strip()
    if not re.fullmatch(r"repeat[1-9][0-9]*", repeat):
        raise ValueError("HPLC Repeat must be repeat1, repeat2, etc.")
    # Legacy non-register labels can still be analysed before assigning MEA IDs.
    return f"{mea} [{repeat}]" if re.fullmatch(r"P[0-9]{3}-MEA-[0-9]{3}", mea) else mea


def identity_mapping(inputs):
    renamed, updated = {}, {}
    for old, cfg in inputs.items():
        cfg = dict(cfg)
        cfg["mea_id"] = normalize_mea_id(cfg.get("mea_id", old))
        cfg["hplc_repeat"] = cfg.get("hplc_repeat", "repeat1")
        key = sample_identity(cfg["mea_id"], cfg["hplc_repeat"])
        if key in updated:
            raise ValueError(f"Duplicate sample: {cfg['mea_id']} / {cfg['hplc_repeat']}. Each MEA ID + HPLC Repeat must be unique.")
        renamed[old] = key
        updated[key] = cfg
    return renamed, updated


def read_mea_details(path):
    import openpyxl
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        values = book["ExperimentPlan"].iter_rows(values_only=True)
        headers = next(values)
        if not {"ID", "Name", "Category"}.issubset(headers):
            raise ValueError("ExperimentPlan must contain ID, Name and Category.")
        details = {}
        def number(value):
            if isinstance(value, bool):
                return None
            try:
                parsed = float(value)
                return parsed if math.isfinite(parsed) and parsed >= 0 else None
            except (TypeError, ValueError):
                return None

        for values in values:
            row = dict(zip(headers, values))
            if row.get("Category") == "MEA" and row.get("ID"):
                if row["ID"] in details:
                    raise ValueError(f"Duplicate MEA ID: {row['ID']}")
                # Only the explicit total-current header is accepted. A current
                # density cannot be converted to charge without an electrode area.
                current = number(row.get("Applied current (mA)"))
                duration = number(row.get("Applied current duration(s)"))
                charge = current * duration / 1000 if current is not None and duration is not None else None
                if charge is not None and not math.isfinite(charge):
                    charge = None
                volume = number(row.get("Electrolyte volume(L)"))
                details[row["ID"]] = {
                    "mea_name": row.get("Name") or "",
                    "total_charge_c": charge,
                    "electrolyte_volume_l": volume if volume and volume > 0 else None,
                    "initial_reactant_concentration_mol_l": number(row.get("Concentration of glycerol (M)")),
                }
        return details
    finally:
        book.close()


def read_mea_names(path):
    return {mea: cfg["mea_name"] for mea, cfg in read_mea_details(path).items()}


def build_prd_rows(summaries, sample_inputs, start_number=1):
    if not re.fullmatch(r"[0-9]+", str(start_number).strip()):
        raise ValueError("PRD starting number must be a whole number from 1 to 999.")
    start = int(start_number)
    summaries = list(summaries)
    if start < 1 or start + len(summaries) - 1 > 999:
        raise ValueError("PRD numbers must stay between 001 and 999.")
    output = []
    seen = set()
    for number, summary in enumerate(summaries, start):
        sample = summary["sample"]
        cfg = sample_inputs.get(sample, {})
        mea = normalize_mea_id(cfg.get("mea_id", sample))
        match = re.fullmatch(r"(P[0-9]{3})-MEA-[0-9]{3}", mea)
        if not match:
            raise ValueError(f"{sample}: enter a valid MEA ID, for example P005-MEA-004.")
        repeat = str(cfg.get("hplc_repeat", "repeat1")).strip()
        if not re.fullmatch(r"repeat[1-9][0-9]*", repeat):
            raise ValueError(f"{sample}: HPLC Repeat must be repeat1, repeat2, etc.")
        if (mea, repeat) in seen:
            raise ValueError(f"{mea}: duplicate HPLC {repeat}. Give each measurement a distinct repeat.")
        seen.add((mea, repeat))
        project = match[1]
        output.append({
            "ID": f"{project}-PRD-{number:03d}", "Name": cfg.get("mea_name", ""),
            "Project": project, "Number": f"{number:03d}", "Repeat": repeat,
            "Category": "PRD", "Label": "Product analysis", "Components": mea,
            **{header: summary.get(key) for header, key in OBJECTIVES.items()},
        })
    return output


# Measurement table imports.
def _norm_header(name: str) -> str:
    return "".join(ch for ch in str(name).strip().lower() if ch.isalnum())


HEADER_ALIASES = {
    "sample": {"sample", "samplename", "sampleid", "run", "samplelabel"},
    "product": {"product", "name", "compound", "species", "analyte"},
    "amount": {
        "amount",
        "concentration",
        "amountmoll",
        "amountmolliter",
        "amountmolar",
        "amountm",
        "conc",
        "concmoll",
    },
    "measured_amount": {
        "measuredconcentrationmoll",
    },
    "adjusted_amount": {
        "adjustedconcentrationmoll",
    },
    "signal": {"signal", "detector", "channel"},
    "mea_id": {"meaid", "components", "samplemeaid"},
    "hplc_repeat": {"hplcrepeat", "repeat"},
    "mea_name": {"meaname"},
    "total_charge_c": {"totalchargec", "totalchargeq", "totalchargeqc"},
    "electrolyte_volume_l": {"electrolytevolumel", "electrolytevolume"},
    "initial_reactant_conc": {
        "initialreactantconcentrationmoll",
        "initialreactantconc",
        "initialreactantconcentration",
    },
}


def _resolve_columns(df: pd.DataFrame) -> Dict[str, str]:
    normalized = {_norm_header(c): c for c in df.columns}
    result: Dict[str, str] = {}

    for key, candidates in HEADER_ALIASES.items():
        for candidate in candidates:
            if candidate in normalized:
                result[key] = normalized[candidate]
                break

    # Amount can come from input template (amount), measured export column, or adjusted export column.
    has_amount = any(x in result for x in ("amount", "measured_amount", "adjusted_amount"))
    missing = [x for x in ("sample", "product") if x not in result]
    if not has_amount:
        missing.append("amount/measured_concentration/adjusted_concentration")
    if missing:
        raise ValueError(
            "Missing required columns. Need columns for sample, product, amount. "
            f"Detected columns: {list(df.columns)}"
        )
    return result


def _clean_value(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def parse_uploaded_table(filename: str, file_bytes: bytes) -> dict:
    ext = Path(filename or "").suffix.lower()
    if ext in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    elif ext in {".csv", ".txt"}:
        # Handle UTF-8 with/without BOM.
        text = file_bytes.decode("utf-8-sig")
        df = pd.read_csv(io.StringIO(text), dtype=str)
    else:
        raise ValueError("Unsupported file type. Upload .csv or .xlsx")

    dilution_factor = None
    dilution_columns = [c for c in df.columns if _norm_header(c) == 'dilutionfactor']
    if dilution_columns:
        values = {_clean_value(v) for v in df[dilution_columns[0]] if _clean_value(v)}
        if len(values) > 1:
            raise ValueError('Use one dilution factor per file.')
        if values:
            dilution_factor = float(values.pop())
            if not math.isfinite(dilution_factor) or dilution_factor <= 0:
                raise ValueError('Dilution factor must be positive and finite.')
    products = None
    normalized = {_norm_header(c): c for c in df.columns}
    has_product = any(h in normalized for h in HEADER_ALIASES['product'])
    has_amount = any(h in normalized for k in ('amount', 'measured_amount', 'adjusted_amount') for h in HEADER_ALIASES[k])
    if not (has_product and has_amount):
        metadata = {h for key, aliases in HEADER_ALIASES.items() if key not in ('product', 'amount', 'measured_amount', 'adjusted_amount') for h in aliases}
        metadata.add('dilutionfactor')
        product_headers = [c for c in df.columns if _norm_header(c) not in metadata]
        sample_col = next((c for c in df.columns if _norm_header(c) in HEADER_ALIASES['sample'] | HEADER_ALIASES['mea_id']), None)
        repeat_col = next((c for c in df.columns if _norm_header(c) in HEADER_ALIASES['hplc_repeat']), None)
        if not sample_col or not product_headers:
            raise ValueError('Use Sample (MEA ID), HPLC Repeat, and one concentration column per product.')
        products = [(str(c)[:-8] if str(c).endswith(' [mol/L]') else str(c)) for c in product_headers]
        records, seen = [], set()
        for _, row in df.iterrows():
            if all(not _clean_value(v) for v in row):
                continue
            sample = _clean_value(row[sample_col])
            repeat = _clean_value(row[repeat_col]) if repeat_col else 'repeat1'
            if not sample:
                raise ValueError('Every input row needs a Sample (MEA ID).')
            if (sample, repeat) in seen:
                raise ValueError(f'Duplicate sample row: {sample} / {repeat}.')
            seen.add((sample, repeat))
            base = {c: row[c] for c in df.columns if c not in product_headers}
            base['sample'] = sample
            for column, product_label in zip(product_headers, products):
                text = _clean_value(row[column])
                amount = float(text) if text else math.nan
                if text and (not math.isfinite(amount) or amount < 0):
                    raise ValueError(f'{sample} / {column}: use a non-negative concentration or a blank.')
                product, _, signal = product_label.partition(' | ')
                records.append({**base, 'product': product, 'signal': signal, 'amount': amount})
        df = pd.DataFrame(records, columns=list(dict.fromkeys([*df.columns, 'sample', 'product', 'signal', 'amount'])))
    columns = _resolve_columns(df)
    out: List[dict] = []
    sample_inputs: Dict[str, dict] = {}

    # Split repeated injections before concentration rows reach the calculator.
    # Source labels are temporary grouping keys; the final identity below is
    # derived exclusively from the MEA ID and HPLC repeat.
    repeats_by_sample = {}
    if "hplc_repeat" in columns:
        for _, row in df.iterrows():
            source = _clean_value(row[columns["sample"]])
            repeat = _clean_value(row[columns["hplc_repeat"]]) or "repeat1"
            repeats_by_sample.setdefault(source, set()).add(repeat)
    identities = {}

    amount_col = columns.get("amount")
    measured_col = columns.get("measured_amount")
    adjusted_col = columns.get("adjusted_amount")
    for _, row in df.iterrows():
        sample = _clean_value(row[columns["sample"]])
        source_sample = sample
        repeat = (_clean_value(row[columns["hplc_repeat"]]) if "hplc_repeat" in columns else "repeat1") or "repeat1"
        if len(repeats_by_sample.get(sample, ())) > 1:
            sample = f"{sample} [{repeat}]"
        identity = (source_sample, repeat)
        if sample in identities and identities[sample] != identity:
            raise ValueError(f"Ambiguous HPLC sample label: {sample}. Use unique labels for each injection.")
        identities[sample] = identity
        product = _clean_value(row[columns["product"]])
        if not sample and not product:
            continue
        amount_raw = None
        if amount_col:
            amount_raw = row[amount_col]
        elif measured_col:
            amount_raw = row[measured_col]
        elif adjusted_col:
            # Backward compatibility: if old results CSV has only adjusted concentration.
            amount_raw = row[adjusted_col]

        try:
            amount = float(amount_raw)
        except Exception:
            # Skip non-numeric amount rows.
            continue

        signal = ""
        if "signal" in columns:
            signal = _clean_value(row[columns["signal"]])

        out.append(
            {
                "sample": sample or "Unknown sample",
                "signal": signal,
                "product": product or "Unknown product",
                "amount_mol_l": amount,
            }
        )

        sample_key = sample or "Unknown sample"
        if sample_key not in sample_inputs:
            sample_inputs[sample_key] = {}

        metadata = {
            "mea_id": _clean_value(row[columns["mea_id"]]) if "mea_id" in columns else source_sample,
            "hplc_repeat": repeat,
            "mea_name": _clean_value(row[columns["mea_name"]]) if "mea_name" in columns else "",
        }
        for key, value in metadata.items():
            if key in sample_inputs[sample_key] and sample_inputs[sample_key][key] != value:
                raise ValueError(f"Conflicting {key} for HPLC sample {sample_key}.")
            sample_inputs[sample_key][key] = value

        if "total_charge_c" in columns:
            try:
                sample_inputs[sample_key]["total_charge_c"] = float(row[columns["total_charge_c"]])
            except Exception:
                pass
        if "electrolyte_volume_l" in columns:
            try:
                sample_inputs[sample_key]["electrolyte_volume_l"] = float(row[columns["electrolyte_volume_l"]])
            except Exception:
                pass
        if "initial_reactant_conc" in columns:
            try:
                sample_inputs[sample_key]["initial_reactant_concentration_mol_l"] = float(row[columns["initial_reactant_conc"]])
            except Exception:
                pass

    # Drop empty sample_input entries.
    sample_inputs = {k: v for k, v in sample_inputs.items() if v}
    renamed, sample_inputs = identity_mapping(sample_inputs)
    for row in out:
        row["sample"] = renamed[row["sample"]]
    return {"rows": out, "sample_inputs": sample_inputs, "products": products,
            "dilution_factor": dilution_factor}


# Editable measurement grid conversions.
DEFAULT_PRODUCTS = ['Glycerol', 'Glyceric acid', 'Glycolic acid', 'Formic acid', 'Oxalic acid']


def product_column(row):
    product = row['product']
    return f"{product} | {row['signal']}" if row.get('signal') else product


def grid_rows(measurements, inputs, products):
    rows = {sample: {'sample': sample, 'mea_id': cfg.get('mea_id', sample),
                     'hplc_repeat': cfg.get('hplc_repeat', 'repeat1'),
                     **{p: '' for p in products}} for sample, cfg in inputs.items()}
    seen = set()
    for measurement in measurements:
        sample = measurement['sample']
        if sample not in rows:
            rows[sample] = {'sample': sample, 'mea_id': sample, 'hplc_repeat': 'repeat1',
                            **{p: '' for p in products}}
        column = product_column(measurement)
        try:
            value = float(measurement['amount_mol_l'])
        except (TypeError, ValueError):
            value = math.nan
        if (sample, column) in seen:
            value += float(rows[sample][column]) if rows[sample][column] != '' else math.nan
        seen.add((sample, column))
        rows[sample][column] = format(value, '.15g') if math.isfinite(value) else ''
    return list(rows.values())


def calculation_rows(rows, products):
    result = []
    for row in rows:
        for column in products:
            text = str(row.get(column, '')).strip()
            if not text:
                value = math.nan
            else:
                try:
                    value = float(text)
                except ValueError:
                    raise ValueError(f"{row['mea_id']} / {column}: enter a concentration or leave blank.")
                if not math.isfinite(value) or value < 0:
                    raise ValueError(f"{row['mea_id']} / {column}: concentration must be finite and non-negative.")
            product, _, signal = column.partition(' | ')
            result.append({'sample': row['sample'], 'product': product, 'signal': signal,
                           'amount_mol_l': value})
    return result
