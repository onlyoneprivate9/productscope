from __future__ import annotations

import io
import json
import math
import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from app.calculations import compute_metrics
from app.data_io import parse_uploaded_table


class ProductScopeSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        library = json.loads((PROJECT_DIR / "product_library_template.json").read_text(encoding="utf-8"))
        self.settings = {}
        for product in library["products"]:
            row = {
                "canonical_name": product["canonical_name"],
                "electrons": product["electrons"],
                "stoich_factor": product["stoich_factor"],
                "carbon_number": product["carbon_number"],
                "is_reactant": product["is_reactant"],
            }
            self.settings[product["canonical_name"]] = row
            for alias in product.get("aliases", []):
                self.settings[alias] = row

    def test_csv_parser_loads_measurements_and_sample_inputs(self) -> None:
        data = (
            b"sample,product,amount,total_charge_c,electrolyte_volume_l,initial_reactant_concentration_mol_l\n"
            b"S1,Glycerol,0.05,120,0.05,0.12\n"
            b"S1,FA,0.003,120,0.05,0.12\n"
        )

        parsed = parse_uploaded_table("smoke.csv", data)

        self.assertEqual(len(parsed["rows"]), 2)
        self.assertEqual(parsed["rows"][1]["product"], "FA")
        self.assertEqual(parsed["sample_inputs"]["S1"]["total_charge_c"], 120.0)

    def test_xlsx_parser_loads_measurements(self) -> None:
        buffer = io.BytesIO()
        pd.DataFrame(
            [
                {"sample name": "S1", "product": "Glycerol", "amount": 0.05},
                {"sample name": "S1", "product": "FA", "amount": 0.003},
            ]
        ).to_excel(buffer, index=False)

        parsed = parse_uploaded_table("smoke.xlsx", buffer.getvalue())

        self.assertEqual(len(parsed["rows"]), 2)
        self.assertEqual(parsed["rows"][0]["sample"], "S1")

    def test_alias_mapping_and_calculation_parity(self) -> None:
        measurements = [
            {"sample": "S1", "signal": "", "product": "Glycerol", "amount_mol_l": 0.05},
            {"sample": "S1", "signal": "", "product": "FA", "amount_mol_l": 0.003},
        ]

        result = compute_metrics(
            measurements,
            self.settings,
            {
                "dilution_factor": 2,
                "reactant_name": "Glycerol",
                "sample_inputs": {
                    "S1": {
                        "total_charge_c": 120,
                        "electrolyte_volume_l": 0.05,
                        "initial_reactant_concentration_mol_l": 0.12,
                    }
                },
            },
        )

        formic = next(row for row in result["rows"] if row["product"] == "Formic acid")
        self.assertEqual(formic["raw_products"], ["FA"])
        self.assertTrue(math.isclose(formic["faradaic_efficiency_pct"], 64.32355474747072, rel_tol=1e-9))
        self.assertEqual(formic["product_distribution_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
