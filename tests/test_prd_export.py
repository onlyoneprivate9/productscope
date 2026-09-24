import csv
import io
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.calculations import compute_metrics
from app.data_io import HEADERS, build_prd_rows, read_mea_details, normalize_mea_id
from app.data_io import parse_uploaded_table


class PRDExportTests(unittest.TestCase):
    def test_mea_padding_preserves_meaningful_suffixes(self):
        self.assertEqual(normalize_mea_id(' P05-MEA-1 '), 'P005-MEA-001')
        self.assertEqual(normalize_mea_id('P05-MEA-008-failed'), 'P05-MEA-008-failed')
        self.assertEqual(normalize_mea_id('P05-MEA-007-2'), 'P05-MEA-007-2')

    def test_master_details_units_missing_values_and_repeat_independence(self):
        book = MagicMock()
        headers = ['ID', 'Name', 'Category', 'Repeat', 'Applied current (mA)',
                   'Applied current duration(s)', 'Electrolyte volume(L)', 'Concentration of glycerol (M)']
        book.__getitem__.return_value.iter_rows.return_value = iter([
            headers,
            ['P005-MEA-009', 'Conditions', 'MEA', 'repeat2', 10, 3600, .01, .05],
            ['P005-MEA-010', '', 'MEA', 'repeat1', None, 3600, 0, None],
            ['P005-MEA-012', '', 'MEA', 'repeat1', 0, 3600, .01, 0],
        ])
        with patch('openpyxl.load_workbook', return_value=book) as load:
            details = read_mea_details('master.xlsx')
        load.assert_called_once_with('master.xlsx', read_only=True, data_only=True)
        book.close.assert_called_once()
        self.assertEqual(details['P005-MEA-009'], {
            'mea_name': 'Conditions', 'total_charge_c': 36,
            'electrolyte_volume_l': .01, 'initial_reactant_concentration_mol_l': .05})
        self.assertIsNone(details['P005-MEA-010']['total_charge_c'])
        self.assertIsNone(details['P005-MEA-010']['electrolyte_volume_l'])
        self.assertIsNone(details['P005-MEA-010']['initial_reactant_concentration_mol_l'])
        self.assertEqual(details['P005-MEA-012']['total_charge_c'], 0)
        self.assertEqual(details['P005-MEA-012']['initial_reactant_concentration_mol_l'], 0)

    def test_current_density_is_not_used_as_total_current(self):
        book = MagicMock()
        book.__getitem__.return_value.iter_rows.return_value = iter([
            ['ID', 'Name', 'Category', 'Applied current (mA/cm2)', 'Applied current duration(s)'],
            ['P005-MEA-001', 'Conditions', 'MEA', 10, 3600],
        ])
        with patch('openpyxl.load_workbook', return_value=book):
            self.assertIsNone(read_mea_details('master.xlsx')['P005-MEA-001']['total_charge_c'])

    def test_gui_loads_master_details_for_both_hplc_repeats(self):
        from tkinter import Tk
        from app.gui_app import ProductScopeApp
        root = Tk()
        root.withdraw()
        try:
            app = ProductScopeApp(root)
            parsed = self.parse_repeats()
            app.measurements = parsed['rows']
            app.sample_inputs = parsed['sample_inputs']
            app._refresh_all()
            self.assertNotIn('sample', [key for key, _, _ in app.sample_table.columns])
            app.sample_table.rows[0]['mea_id'] = 'P05-MEA-009'
            details = {'P005-MEA-009': {'mea_name': 'Conditions', 'total_charge_c': 36,
                'electrolyte_volume_l': .01, 'initial_reactant_concentration_mol_l': .05}}
            with patch('app.gui_app.filedialog.askopenfilename', return_value='master.xlsx'), \
                    patch('app.gui_app.read_mea_details', return_value=details):
                app.load_master_details()
            self.assertEqual([r['hplc_repeat'] for r in app.sample_table.rows], ['repeat1', 'repeat2'])
            self.assertEqual([r['mea_id'] for r in app.measurement_table.rows], ['P005-MEA-009'] * 2)
            original_amounts = [r['GA'] for r in app.measurement_table.rows]
            app.sample_table.rows[0]['mea_id'] = 'P05-MEA-004'
            app._sample_table_changed()
            self.assertEqual(app.measurement_table.rows[0]['mea_id'], 'P005-MEA-004')
            self.assertEqual(app.measurement_table.rows[1]['mea_id'], 'P005-MEA-009')
            self.assertEqual([r['GA'] for r in app.measurement_table.rows], original_amounts)
            app.sample_table.rows[0]['mea_id'] = 'P005-MEA-009'
            app._sample_table_changed()
            self.assertEqual(str(app.prd_number_control.cget('state')), 'normal')
            app.prd_start_number.set('15')
            for cfg in app.sample_inputs.values():
                self.assertEqual(cfg['total_charge_c'], 36)
                self.assertEqual(cfg['electrolyte_volume_l'], .01)
                self.assertEqual(cfg['initial_reactant_concentration_mol_l'], .05)
                self.assertEqual(cfg['mea_name'], 'Conditions')
            app.run_calculations()
            self.assertEqual(len(app.sample_summaries), 2)
            self.assertTrue(all(s['total_charge_c'] == 36 for s in app.sample_summaries.values()))
            details['P005-MEA-009']['total_charge_c'] = None
            with patch('app.gui_app.filedialog.askopenfilename', return_value='master.xlsx'), \
                    patch('app.gui_app.read_mea_details', return_value=details):
                app.load_master_details()
            self.assertEqual(app.sample_table.rows[0]['total_charge_c'], '')
            self.assertEqual(app.sample_summaries, {})
            app.run_calculations()
            self.assertTrue(all(s['c2_c3_total_fe_pct'] is None for s in app.sample_summaries.values()))
        finally:
            root.destroy()

    def parse_repeats(self):
        return parse_uploaded_table('input.csv', b'sample,repeat,product,amount,total_charge_c,electrolyte_volume_l\n'
            b'P005-MEA-009,repeat1,GA,0.01,100,0.05\n'
            b'P005-MEA-009,repeat2,GA,0.02,200,0.10\n')

    def calculate(self, parsed):
        return compute_metrics(parsed['rows'], {'GA': {'carbon_number': 2, 'electrons': 4}},
                               {'sample_inputs': parsed['sample_inputs']})

    def test_same_mea_repeats_have_separate_values_and_sequential_ids(self):
        parsed = self.parse_repeats()
        result = self.calculate(parsed)
        rows = build_prd_rows(result['sample_summaries'], parsed['sample_inputs'], '15')
        self.assertEqual(list(rows[0]), HEADERS)
        self.assertEqual([r['ID'] for r in rows], ['P005-PRD-015', 'P005-PRD-016'])
        self.assertEqual([r['Number'] for r in rows], ['015', '016'])
        self.assertEqual([r['Repeat'] for r in rows], ['repeat1', 'repeat2'])
        self.assertEqual([r['Components'] for r in rows], ['P005-MEA-009'] * 2)
        self.assertEqual([r[HEADERS[-1]] for r in rows], [1.0, 4.0])
        self.assertAlmostEqual(rows[1][HEADERS[-2]], 2 * rows[0][HEADERS[-2]])

    def test_invalid_ids_repeats_and_number_bounds(self):
        summary = [{'sample': 'run'}]
        valid = {'run': {'mea_id': 'P005-MEA-009', 'hplc_repeat': 'repeat1'}}
        for start in ['0', '-1', '1.5', '', '1000']:
            with self.subTest(start=start), self.assertRaises(ValueError):
                build_prd_rows(summary, valid, start)
        for cfg in [{'mea_id': 'A'}, {'mea_id': 'P005-PRD-001'},
                    {'mea_id': 'P005-MEA-009', 'hplc_repeat': ''}]:
            with self.subTest(cfg=cfg), self.assertRaises(ValueError):
                build_prd_rows(summary, {'run': cfg})
        with self.assertRaises(ValueError):
            build_prd_rows(summary * 2, valid)
        with self.assertRaises(ValueError):
            build_prd_rows(summary * 2, valid, 999)

    def test_explicit_source_labels_are_replaced_by_mea_and_repeat(self):
        data = b'sample,mea_id,hplc_repeat,product,amount\nrun1,P005-MEA-004,repeat1,GA,.01\nrun2,P005-MEA-004,repeat2,GA,.02\n'
        parsed = parse_uploaded_table('runs.csv', data)
        self.assertEqual([r['sample'] for r in parsed['rows']],
                         ['P005-MEA-004 [repeat1]', 'P005-MEA-004 [repeat2]'])
        rows = build_prd_rows(self.calculate(parsed)['sample_summaries'], parsed['sample_inputs'])
        self.assertEqual([r['Components'] for r in rows], ['P005-MEA-004'] * 2)

    def test_conflicting_metadata_is_rejected(self):
        data = b'sample,mea_id,hplc_repeat,product,amount\nrun1,P005-MEA-004,repeat1,GA,.01\nrun1,P005-MEA-009,repeat1,GA,.02\n'
        with self.assertRaises(ValueError):
            parse_uploaded_table('runs.csv', data)

    def test_duplicate_combinations_in_separate_source_samples_are_rejected(self):
        data = b'sample,mea_id,hplc_repeat,product,amount\na,P005-MEA-004,repeat1,GA,.01\nb,P005-MEA-004,repeat1,GA,.02\n'
        with self.assertRaisesRegex(ValueError, 'Duplicate sample'):
            parse_uploaded_table('runs.csv', data)

    def test_rename_updates_results_plot_selection_and_exports_without_merging(self):
        from tkinter import Tk
        from app.gui_app import ProductScopeApp
        root = Tk()
        root.withdraw()
        try:
            app = ProductScopeApp(root)
            parsed = self.parse_repeats()
            app.measurements = parsed['rows']
            app.sample_inputs = parsed['sample_inputs']
            app._refresh_all()
            app.run_calculations()
            old_keys = list(app.sample_inputs)
            values = [r['c2_c3_carbon_mmol'] for r in app.sample_summaries.values()]
            app.selected_samples = {old_keys[0]}
            app.sample_table.rows[0]['mea_id'] = 'P005-MEA-004'
            app._sample_table_changed()
            new_key = 'P005-MEA-004 [repeat1]'
            self.assertEqual(app.selected_samples, {new_key})
            self.assertNotIn(old_keys[0], app.sample_inputs)
            self.assertEqual(app.results_table.rows[0]['sample'], 'P005-MEA-004')
            self.assertEqual(app.measurements[0]['sample'], new_key)
            self.assertEqual([t.get_text() for t in app.axis.get_xticklabels()], ['P005-MEA-004'])
            self.assertEqual([r['c2_c3_carbon_mmol'] for r in app.sample_summaries.values()], values)
            self.assertEqual(app._result_row_for_export(app.results[0])['sample'], 'P005-MEA-004')
            app.sample_table.rows[0]['mea_id'] = 'P005-MEA-009'
            app.sample_table.rows[0]['hplc_repeat'] = 'repeat2'
            with patch('app.gui_app.messagebox.showerror') as error:
                app._sample_table_changed()
            error.assert_called_once()
            self.assertIn(new_key, app.sample_inputs)
            self.assertEqual(len(app.sample_summaries), 2)
            app.sample_table.rows[0]['mea_id'] = 'P005-MEA-009'
            app._sample_table_changed()
            app.selected_samples = None
            app.draw_plot()
            self.assertEqual([t.get_text() for t in app.axis.get_xticklabels()], old_keys)
            app.sample_table.rows[0]['hplc_repeat'] = 'repeat3'
            app._sample_table_changed()
            self.assertEqual(app.results_table.rows[0]['hplc_repeat'], 'repeat3')
            self.assertEqual(app._result_row_for_export(app.results[0])['hplc_repeat'], 'repeat3')
        finally:
            root.destroy()

    def test_gui_export_and_results_roundtrip(self):
        from tkinter import Tk
        from app.gui_app import ProductScopeApp
        root = Tk()
        root.withdraw()
        try:
            app = ProductScopeApp(root)
            parsed = self.parse_repeats()
            app.measurements = parsed['rows']
            app.sample_inputs = parsed['sample_inputs']
            app.dilution_factor.set(1)
            app._refresh_all()
            app.sample_table.rows[0]['mea_name'] = 'MEA conditions'
            app.sample_table.rows[1]['mea_name'] = 'MEA conditions'
            app.prd_start_number.set('15')
            with tempfile.TemporaryDirectory() as directory:
                bo = Path(directory) / 'bo.csv'
                with patch('app.gui_app.filedialog.asksaveasfilename', return_value=str(bo)):
                    app.export_bo_objectives_csv()
                rows = list(csv.DictReader(io.StringIO(bo.read_text())))
                self.assertEqual(rows[0]['ID'], 'P005-PRD-015')
                self.assertEqual(rows[1]['Repeat'], 'repeat2')
                self.assertEqual(rows[0]['Name'], 'MEA conditions')
                self.assertEqual(app.bo_objectives_table.rows[1]['ID'], rows[1]['ID'])
                results = Path(directory) / 'results.csv'
                with patch('app.gui_app.filedialog.asksaveasfilename', return_value=str(results)):
                    app.export_results_csv()
                restored = parse_uploaded_table(results.name, results.read_bytes())
                self.assertEqual(set(restored['sample_inputs']), set(app.sample_inputs))
                for sample, cfg in app.sample_inputs.items():
                    for key, value in cfg.items():
                        actual = restored['sample_inputs'][sample][key]
                        if isinstance(value, float) and math.isnan(value):
                            self.assertTrue(math.isnan(actual))
                        else:
                            self.assertEqual(actual, value)
                self.assertEqual([r['sample'] for r in restored['rows']],
                                 [r['sample'] for r in parsed['rows']])
                # Changing charge immediately before export must update the values.
                old_fe = float(rows[0][HEADERS[-2]])
                app.sample_table.rows[0]['total_charge_c'] = '200'
                with patch('app.gui_app.filedialog.asksaveasfilename', return_value=str(bo)):
                    app.export_bo_objectives_csv()
                updated = list(csv.DictReader(io.StringIO(bo.read_text())))
                self.assertAlmostEqual(float(updated[0][HEADERS[-2]]), old_fe / 2)
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
