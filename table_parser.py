from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Dict, List

import pandas as pd
try:
    from .pda_export import identity_mapping
except ImportError:
    from pda_export import identity_mapping


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
