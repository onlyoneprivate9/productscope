import csv
import io
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from measurement_grid import calculation_rows, grid_rows
from table_parser import parse_uploaded_table


class WideInputTests(unittest.TestCase):
    def test_product_choices_persist(self):
        from tkinter import Tk, Toplevel, ttk
        from gui_app import ProductScopeApp
        root = Tk()
        root.withdraw()
        try:
            with tempfile.TemporaryDirectory() as directory, patch('gui_app.BASE_DIR', Path(directory)):
                app = ProductScopeApp(root)
                app.choose_input_products()
                dialog = next(w for w in root.winfo_children() if isinstance(w, Toplevel))
                wanted = {'Glycerol', 'Glycolic acid'}
                for widget in dialog.winfo_children():
                    if isinstance(widget, ttk.Checkbutton):
                        widget.setvar(widget.cget('variable'), widget.cget('text') in wanted)
                next(w for w in dialog.winfo_children() if isinstance(w, ttk.Button)).invoke()
                self.assertEqual(set(app.input_products), wanted)
                second_window = Toplevel(root)
                second = ProductScopeApp(second_window)
                self.assertEqual(set(second.input_products), wanted)
        finally:
            root.destroy()

    def test_wide_import_preserves_blank_zero_repeat_and_metadata(self):
        data = b'sample,hplc_repeat,Glycerol,Glycolic acid,mea_name,total_charge_c,electrolyte_volume_l,initial_reactant_concentration_mol_l,dilution_factor\nP005-MEA-009,repeat1,.022,0,Conditions,36,.01,.05,2\nP005-MEA-009,repeat2,,.00016,Conditions,36,.01,.05,2\n'
        parsed = parse_uploaded_table('inputs.csv', data)
        self.assertEqual(len(parsed['sample_inputs']), 2)
        self.assertEqual(parsed['products'], ['Glycerol', 'Glycolic acid'])
        self.assertEqual(parsed['dilution_factor'], 2)
        self.assertEqual(parsed['rows'][1]['amount_mol_l'], 0)
        self.assertTrue(math.isnan(parsed['rows'][2]['amount_mol_l']))
        self.assertEqual(parsed['sample_inputs']['P005-MEA-009 [repeat2]']['total_charge_c'], 36)

    def test_blank_sample_and_duplicate_rows_are_rejected(self):
        for data in [b'sample,repeat,GA\n,repeat1,.01\n',
                     b'sample,repeat,GA\nP005-MEA-001,repeat1,.01\nP005-MEA-001,repeat1,.02\n']:
            with self.assertRaises(ValueError):
                parse_uploaded_table('inputs.csv', data)

    def test_grid_keeps_detector_signals_separate(self):
        rows = [{'sample': 'A', 'product': 'GA', 'signal': signal, 'amount_mol_l': value}
                for signal, value in [('UV', .01), ('RI', .02)]]
        products = ['GA | UV', 'GA | RI']
        wide = grid_rows(rows, {'A': {}}, products)
        self.assertEqual(calculation_rows(wide, products), rows)

    def test_gui_add_repeat_paste_export_reload_and_delete(self):
        from tkinter import Tk
        from gui_app import ProductScopeApp
        root = Tk()
        root.withdraw()
        try:
            app = ProductScopeApp(root)
            app._set_product_columns(['Glycerol', 'Glycolic acid'])
            app.mea_details = {'P005-MEA-014': {'mea_name': 'Conditions', 'total_charge_c': 28.8,
                'electrolyte_volume_l': .01, 'initial_reactant_concentration_mol_l': .05}}
            with patch('gui_app.simpledialog.askstring', return_value='P005-MEA-014'):
                app.add_measurement()
            self.assertEqual(len(app.measurement_table.rows), 1)
            self.assertEqual(app.measurement_table.rows[0]['Glycolic acid'], '')
            app.measurement_table.tree.selection_set('0')
            app.add_hplc_repeat()
            self.assertEqual([r['hplc_repeat'] for r in app.measurement_table.rows], ['repeat1', 'repeat2'])
            self.assertEqual(app.sample_inputs['P005-MEA-014 [repeat2]']['total_charge_c'], 28.8)
            app._paste_cell = (0, 2)
            with patch.object(root, 'clipboard_get', return_value='.022\t0\n\t.00016'):
                app.paste_measurements()
            self.assertEqual(app.measurement_table.rows[0]['Glycolic acid'], '0')
            self.assertEqual(app.measurement_table.rows[1]['Glycerol'], '')
            before = [dict(r) for r in app.measurement_table.rows]
            with patch.object(root, 'clipboard_get', return_value='bad\t0'), patch('gui_app.messagebox.showerror') as error:
                app.paste_measurements()
            error.assert_called_once()
            self.assertEqual(before, app.measurement_table.rows)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'input.csv'
                with patch('gui_app.filedialog.asksaveasfilename', return_value=str(path)):
                    app.export_input_csv()
                exported = list(csv.DictReader(io.StringIO(path.read_text(encoding='utf-8-sig'))))
                self.assertEqual(len(exported), 2)
                self.assertEqual(exported[0]['Glycolic acid'], '0')
                self.assertEqual(exported[1]['Glycerol'], '')
                with patch('gui_app.filedialog.askopenfilename', return_value=str(path)):
                    app.load_data_file()
                self.assertEqual(app.measurement_table.rows[1]['Glycerol'], '')
                self.assertEqual(app.sample_inputs['P005-MEA-014 [repeat1]']['mea_name'], 'Conditions')
                app.run_calculations()
                self.assertEqual(app.sample_summaries['P005-MEA-014 [repeat1]']['c2_c3_carbon_mmol'], 0)
                self.assertGreater(app.sample_summaries['P005-MEA-014 [repeat2]']['c2_c3_carbon_mmol'], 0)
            app.measurement_table.tree.selection_set('0')
            app.delete_measurement()
            self.assertEqual(len(app.sample_inputs), 1)
            self.assertEqual(len(app.measurement_table.rows), 1)
            self.assertEqual(app.measurement_table.rows[0]['hplc_repeat'], 'repeat2')
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
