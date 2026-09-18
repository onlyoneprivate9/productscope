from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, List, Optional


FARADAY_CONSTANT = 96485.33212


@dataclass
class ProductSetting:
    canonical_name: str = ""
    electrons: float = 0.0
    stoich_factor: float = 1.0
    carbon_number: int = 1
    is_reactant: bool = False


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_settings(raw_settings: Dict[str, dict]) -> Dict[str, ProductSetting]:
    parsed: Dict[str, ProductSetting] = {}
    for product, raw in (raw_settings or {}).items():
        parsed[product] = ProductSetting(
            canonical_name=str(raw.get("canonical_name", product)).strip() or product,
            electrons=_to_float(raw.get("electrons"), 0.0),
            stoich_factor=max(_to_float(raw.get("stoich_factor"), 1.0), 1e-12),
            carbon_number=max(_to_int(raw.get("carbon_number"), 1), 0),
            is_reactant=bool(raw.get("is_reactant", False)),
        )
    return parsed


def _norm_key(text: str) -> str:
    return (text or "").strip().lower()


def compute_metrics(
    measurements: List[dict],
    product_settings: Dict[str, dict],
    global_inputs: dict,
) -> dict:
    dilution_factor = _to_float(global_inputs.get("dilution_factor", 1.0), math.nan)
    global_electrolyte_volume_l = _to_float(global_inputs.get("electrolyte_volume_l", 1.0), math.nan)
    global_total_charge_c = _to_float(global_inputs.get("total_charge_c"), 0.0)
    global_initial_reactant_conc = _to_float(global_inputs.get("initial_reactant_concentration_mol_l"), 0.0)
    reactant_name = str(global_inputs.get("reactant_name", "Glycerol")).strip()
    sample_inputs = global_inputs.get("sample_inputs", {}) or {}

    settings = _build_settings(product_settings)
    settings_ci = {_norm_key(k): v for k, v in settings.items()}

    # Ensure reactant exists and is flagged.
    if reactant_name and reactant_name not in settings and _norm_key(reactant_name) not in settings_ci:
        settings[reactant_name] = ProductSetting(
            canonical_name=reactant_name,
            electrons=0.0,
            stoich_factor=1.0,
            carbon_number=3,
            is_reactant=True,
        )
        settings_ci[_norm_key(reactant_name)] = settings[reactant_name]
    elif reactant_name:
        direct = settings.get(reactant_name) or settings_ci.get(_norm_key(reactant_name))
        if direct:
            direct.is_reactant = True

    by_sample: Dict[str, List[dict]] = {}
    for row in measurements:
        sample = str(row.get("sample", "Unknown sample"))
        by_sample.setdefault(sample, []).append(row)

    computed_rows: List[dict] = []
    sample_summaries: List[dict] = []

    for sample, rows in by_sample.items():
        per_sample = sample_inputs.get(sample, {})
        electrolyte_volume_l = _to_float(per_sample.get("electrolyte_volume_l", global_electrolyte_volume_l), math.nan)
        total_charge_c = _to_float(per_sample.get("total_charge_c", global_total_charge_c), math.nan)
        initial_reactant_conc = _to_float(
            per_sample.get("initial_reactant_concentration_mol_l"),
            global_initial_reactant_conc,
        )

        # Enriched rows for sample.
        enriched_map: Dict[str, dict] = {}
        for row in rows:
            product_raw = str(row.get("product", "")).strip()
            raw_setting = settings.get(product_raw) or settings_ci.get(_norm_key(product_raw)) or ProductSetting(canonical_name=product_raw)
            product = raw_setting.canonical_name or product_raw
            canonical_setting = settings.get(product) or settings_ci.get(_norm_key(product)) or raw_setting
            measured_conc = _to_float(row.get("amount_mol_l"), math.nan)
            adjusted_conc = measured_conc * dilution_factor
            moles = adjusted_conc * electrolyte_volume_l
            key = f"{product}||{row.get('signal','')}"
            if key not in enriched_map:
                enriched_map[key] = {
                    "sample": sample,
                    "signal": row.get("signal", ""),
                    "product": product,
                    "raw_products": [product_raw],
                    "measured_concentration_mol_l": measured_conc,
                    "adjusted_concentration_mol_l": adjusted_conc,
                    "moles": moles,
                    "electrons": canonical_setting.electrons,
                    "stoich_factor": canonical_setting.stoich_factor,
                    "carbon_number": canonical_setting.carbon_number,
                    "is_reactant": canonical_setting.is_reactant or _norm_key(product) == _norm_key(reactant_name),
                }
            else:
                merged = enriched_map[key]
                merged["raw_products"].append(product_raw)
                merged["measured_concentration_mol_l"] += measured_conc
                merged["adjusted_concentration_mol_l"] += adjusted_conc
                merged["moles"] += moles

        enriched: List[dict] = list(enriched_map.values())

        reactant_row: Optional[dict] = next((x for x in enriched if _norm_key(x["product"]) == _norm_key(reactant_name)), None)
        reactant_final_conc = reactant_row["adjusted_concentration_mol_l"] if reactant_row else None
        consumed_reactant_moles = None
        if reactant_final_conc is not None:
            consumed_reactant_moles = max((initial_reactant_conc - reactant_final_conc) * electrolyte_volume_l, 0.0)

        total_non_reactant_moles = sum(x["moles"] for x in enriched if not x["is_reactant"])

        numerator_carbon = sum(x["carbon_number"] * x["moles"] for x in enriched if not x["is_reactant"])
        reactant_setting = settings.get(reactant_name) or settings_ci.get(_norm_key(reactant_name)) or ProductSetting(carbon_number=3)
        reactant_carbon = reactant_setting.carbon_number
        carbon_balance_pct = None
        if consumed_reactant_moles is not None and consumed_reactant_moles > 0 and reactant_carbon > 0:
            carbon_balance_pct = 100.0 * numerator_carbon / (reactant_carbon * consumed_reactant_moles)

        for x in enriched:
            fe_pct = None
            if total_charge_c > 0 and x["electrons"] > 0:
                fe_pct = 100.0 * (x["moles"] * x["electrons"] * FARADAY_CONSTANT) / (x["stoich_factor"] * total_charge_c)

            selectivity_pct = None
            if not x["is_reactant"] and consumed_reactant_moles is not None and consumed_reactant_moles > 0:
                selectivity_pct = 100.0 * x["moles"] / consumed_reactant_moles

            distribution_pct = None
            if not x["is_reactant"] and total_non_reactant_moles > 0:
                distribution_pct = 100.0 * x["moles"] / total_non_reactant_moles

            x["faradaic_efficiency_pct"] = fe_pct
            x["selectivity_pct"] = selectivity_pct
            x["product_distribution_pct"] = distribution_pct
            x["carbon_balance_pct"] = carbon_balance_pct
            computed_rows.append(x)

        # BO objectives are sample totals; select targets by the product library.
        targets = [x for x in enriched if not x["is_reactant"] and x["carbon_number"] in (2, 3)]
        valid_amounts = (
            math.isfinite(electrolyte_volume_l) and electrolyte_volume_l > 0
            and math.isfinite(dilution_factor) and dilution_factor > 0
            and all(math.isfinite(x["moles"]) and x["moles"] >= 0 for x in targets)
        )
        c2_c3_total_fe_pct = None
        target_fes = [x["faradaic_efficiency_pct"] for x in targets]
        if (valid_amounts and math.isfinite(total_charge_c) and total_charge_c > 0
                and all(fe is not None and math.isfinite(fe) and fe >= 0 for fe in target_fes)):
            total_fe = sum(target_fes)
            if math.isfinite(total_fe):
                c2_c3_total_fe_pct = total_fe

        c2_c3_carbon_mmol = None
        if valid_amounts:
            target_carbon_moles = sum(x["carbon_number"] * x["moles"] for x in targets)
            carbon_mmol = 1000.0 * target_carbon_moles
            if math.isfinite(carbon_mmol):
                c2_c3_carbon_mmol = carbon_mmol

        objectives = {
            "c2_c3_total_fe_pct": c2_c3_total_fe_pct,
            "c2_c3_carbon_mmol": c2_c3_carbon_mmol,
        }
        for x in enriched:
            x.update(objectives)

        sample_summaries.append(
            {
                **objectives,
                "sample": sample,
                "reactant_name": reactant_name,
                "total_charge_c": total_charge_c,
                "electrolyte_volume_l": electrolyte_volume_l,
                "reactant_final_concentration_mol_l": reactant_final_conc,
                "initial_reactant_concentration_mol_l": initial_reactant_conc,
                "consumed_reactant_moles": consumed_reactant_moles,
                "total_non_reactant_moles": total_non_reactant_moles,
                "carbon_balance_pct": carbon_balance_pct,
            }
        )

    return {"rows": computed_rows, "sample_summaries": sample_summaries}
