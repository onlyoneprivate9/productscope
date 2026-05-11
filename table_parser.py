from __future__ import annotations

import io
from pathlib import Path
from typing import Dict, List

import pandas as pd


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
        df = pd.read_excel(io.BytesIO(file_bytes))
    elif ext in {".csv", ".txt"}:
        # Handle UTF-8 with/without BOM.
        text = file_bytes.decode("utf-8-sig")
        df = pd.read_csv(io.StringIO(text))
    else:
        raise ValueError("Unsupported file type. Upload .csv or .xlsx")

    columns = _resolve_columns(df)
    out: List[dict] = []
    sample_inputs: Dict[str, dict] = {}

    amount_col = columns.get("amount")
    measured_col = columns.get("measured_amount")
    adjusted_col = columns.get("adjusted_amount")
    for _, row in df.iterrows():
        sample = _clean_value(row[columns["sample"]])
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
    return {"rows": out, "sample_inputs": sample_inputs}
