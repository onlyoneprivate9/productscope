"""PDA register export; HPLC sample identity is separate from the linked MEA."""
import re
import math


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


def build_pda_rows(summaries, sample_inputs, start_number=1):
    if not re.fullmatch(r"[0-9]+", str(start_number).strip()):
        raise ValueError("PDA starting number must be a whole number from 1 to 999.")
    start = int(start_number)
    summaries = list(summaries)
    if start < 1 or start + len(summaries) - 1 > 999:
        raise ValueError("PDA numbers must stay between 001 and 999.")
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
            "ID": f"{project}-PDA-{number:03d}", "Name": cfg.get("mea_name", ""),
            "Project": project, "Number": f"{number:03d}", "Repeat": repeat,
            "Category": "PDA", "Label": "Product analysis", "Components": mea,
            **{header: summary.get(key) for header, key in OBJECTIVES.items()},
        })
    return output
