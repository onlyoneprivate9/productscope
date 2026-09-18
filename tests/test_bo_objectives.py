import csv
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from tkinter import Tcl, Tk, StringVar
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from calculations import compute_metrics


class BOObjectiveTests(unittest.TestCase):
    def setUp(self):
        library = json.loads((PROJECT_DIR / 'product_library_template.json').read_text())
        self.settings = {}
        for product in library['products']:
            for name in [product['canonical_name'], *product['aliases']]:
                self.settings[name] = dict(product)
        self.measurements = [
            {'sample': 'A', 'product': product, 'amount_mol_l': concentration}
            for product, concentration in [('Glycerol', .03), ('GA', .01),
                                           ('LA', .005), ('FA', .02)]
        ]
        self.inputs = {'reactant_name': 'Glycerol', 'dilution_factor': 2,
                       'electrolyte_volume_l': .1, 'total_charge_c': 964.8533212,
                       'initial_reactant_concentration_mol_l': .1}

    def calculate(self):
        return compute_metrics(self.measurements, self.settings, self.inputs)

    def test_objectives_exclude_c1_and_remaining_glycerol(self):
        result = self.calculate()
        summary = result['sample_summaries'][0]
        # 2 mmol glycolate + 1 mmol lactate contain 7 mmol carbon.
        self.assertAlmostEqual(summary.get('c2_c3_total_fe_pct', -1), 86.6666666667)
        self.assertAlmostEqual(summary.get('c2_c3_carbon_mmol', -1), 7.0)
        for row in result['rows']:
            self.assertAlmostEqual(row.get('c2_c3_total_fe_pct', -1), 86.6666666667)
            self.assertAlmostEqual(row.get('c2_c3_carbon_mmol', -1), 7.0)

    def test_carbon_amount_does_not_require_final_glycerol_measurement(self):
        self.measurements = self.measurements[1:]
        summary = self.calculate()['sample_summaries'][0]
        self.assertAlmostEqual(summary.get('c2_c3_carbon_mmol', -1), 7.0)

    def test_aliases_and_multiple_signals_contribute_once(self):
        self.measurements[1]['amount_mol_l'] = .006
        self.measurements.extend([
            {'sample': 'A', 'product': 'Glycolic acid', 'amount_mol_l': .002},
            {'sample': 'A', 'product': 'GA', 'signal': 'second', 'amount_mol_l': .002},
        ])
        summary = self.calculate()['sample_summaries'][0]
        self.assertAlmostEqual(summary.get('c2_c3_total_fe_pct', -1), 86.6666666667)
        self.assertAlmostEqual(summary.get('c2_c3_carbon_mmol', -1), 7.0)

    def test_stoichiometry_and_per_sample_inputs_are_used(self):
        self.settings['Glycolic acid']['stoich_factor'] = 2
        self.measurements += [dict(row, sample='B') for row in self.measurements]
        self.inputs['sample_inputs'] = {'B': {'total_charge_c': 1929.7066424,
                                            'initial_reactant_concentration_mol_l': .2}}
        a, b = self.calculate()['sample_summaries']
        self.assertAlmostEqual(a.get('c2_c3_total_fe_pct', -1), 53.3333333333)
        self.assertAlmostEqual(b.get('c2_c3_total_fe_pct', -1), 26.6666666667)
        self.assertAlmostEqual(b.get('c2_c3_carbon_mmol', -1), 7.0)

    def test_no_target_products_gives_zero_with_valid_inputs(self):
        self.measurements = [self.measurements[0], self.measurements[3]]
        summary = self.calculate()['sample_summaries'][0]
        self.assertEqual(summary.get('c2_c3_total_fe_pct', -1), 0)
        self.assertEqual(summary.get('c2_c3_carbon_mmol', -1), 0)

    def test_invalid_denominators_are_unavailable(self):
        for field, metric in [('total_charge_c', 'c2_c3_total_fe_pct'),
                              ('electrolyte_volume_l', 'c2_c3_total_fe_pct'),
                              ('electrolyte_volume_l', 'c2_c3_carbon_mmol')]:
            original = self.inputs[field]
            for value in [0, -1, None, '', 'invalid', float('nan'), float('inf')]:
                with self.subTest(field=field, value=value):
                    self.inputs[field] = value
                    summary = self.calculate()['sample_summaries'][0]
                    self.assertIsNone(summary.get(metric, 'missing'))
            self.inputs[field] = original

    def test_missing_target_fe_does_not_produce_partial_total(self):
        self.settings['Glycolic acid']['electrons'] = 0
        summary = self.calculate()['sample_summaries'][0]
        self.assertIsNone(summary.get('c2_c3_total_fe_pct', 'missing'))
        self.assertAlmostEqual(summary.get('c2_c3_carbon_mmol', -1), 7.0)

    def test_invalid_target_amounts_are_unavailable(self):
        for value in [-.01, None, '', 'invalid', float('nan'), float('inf')]:
            with self.subTest(value=value):
                self.measurements[1]['amount_mol_l'] = value
                summary = self.calculate()['sample_summaries'][0]
                self.assertIsNone(summary.get('c2_c3_total_fe_pct', 'missing'))
                self.assertIsNone(summary.get('c2_c3_carbon_mmol', 'missing'))

    def test_carbon_amount_does_not_depend_on_initial_concentration(self):
        for value in [0, None, float('nan')]:
            self.inputs['initial_reactant_concentration_mol_l'] = value
            summary = self.calculate()['sample_summaries'][0]
            self.assertAlmostEqual(summary.get('c2_c3_carbon_mmol', -1), 7.0)

    def test_carbon_amount_scales_with_electrolyte_volume(self):
        self.inputs['electrolyte_volume_l'] = .2
        summary = self.calculate()['sample_summaries'][0]
        self.assertAlmostEqual(summary.get('c2_c3_carbon_mmol', -1), 14.0)

    def test_invalid_sample_override_does_not_fall_back_to_global_value(self):
        self.inputs['sample_inputs'] = {'A': {'electrolyte_volume_l': ''}}
        summary = self.calculate()['sample_summaries'][0]
        self.assertIsNone(summary.get('c2_c3_total_fe_pct', 'missing'))
        self.assertIsNone(summary.get('c2_c3_carbon_mmol', 'missing'))

    def test_blank_gui_measurement_or_volume_leaves_objectives_blank(self):
        from gui_app import ProductScopeApp

        root = Tk()
        root.withdraw()
        try:
            app = ProductScopeApp(root)
            app.measurements = self.measurements
            app.sample_inputs = {'A': {key: self.inputs[key] for key in
                                      ('total_charge_c', 'electrolyte_volume_l',
                                       'initial_reactant_concentration_mol_l')}}
            app._refresh_all()
            app.measurement_table.rows[1]['amount_mol_l'] = ''
            app.run_calculations()
            self.assertIsNone(app.sample_summaries['A'].get('c2_c3_total_fe_pct', 'missing'))
            self.assertIsNone(app.sample_summaries['A'].get('c2_c3_carbon_mmol', 'missing'))
            app.measurement_table.rows[1]['amount_mol_l'] = '.01'
            app._measurement_table_changed()
            app.sample_table.rows[0]['electrolyte_volume_l'] = ''
            app._sample_table_changed()
            app.run_calculations()
            self.assertIsNone(app.sample_summaries['A'].get('c2_c3_carbon_mmol', 'missing'))
            self.assertEqual(app.bo_objectives_table.rows[0]['c2_c3_carbon_mmol'], '')
        finally:
            root.destroy()

    def test_bo_csv_and_plot_use_sample_totals(self):
        from gui_app import ProductScopeApp

        self.measurements += [dict(row, sample='B') for row in self.measurements]
        self.inputs['sample_inputs'] = {'B': {'total_charge_c': 0}}
        result = self.calculate()
        app = ProductScopeApp.__new__(ProductScopeApp)
        tk = Tcl()
        app.results = result['rows']
        app.sample_summaries = {row['sample']: row for row in result['sample_summaries']}
        app.sample_inputs = {'A': {}, 'B': {}}
        app.status_text = StringVar(tk)
        app.plot_right_metric = StringVar(tk, value='C2/C3 total FE (%)')
        self.assertAlmostEqual(app._overlay_values(['A'])[0], 86.6666666667)
        self.assertTrue(math.isnan(app._overlay_values(['B'])[0]))
        app.plot_right_metric.set('C2/C3 carbon produced (mmol-C)')
        self.assertAlmostEqual(app._overlay_values(['A'])[0], 7.0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'objectives.csv'
            with patch('gui_app.filedialog.asksaveasfilename', return_value=str(path)):
                app.export_bo_objectives_csv()
            with path.open(newline='') as handle:
                exported = list(csv.DictReader(handle))
            self.assertEqual([row['sample'] for row in exported], ['A', 'B'])
            self.assertAlmostEqual(float(exported[0]['c2_c3_total_fe_pct']), 86.6666666667)
            self.assertEqual(exported[1]['c2_c3_total_fe_pct'], '')
            self.assertAlmostEqual(float(exported[1]['c2_c3_carbon_mmol']), 7.0)


if __name__ == '__main__':
    unittest.main()
