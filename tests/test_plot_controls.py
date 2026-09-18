import math
import sys
import unittest
from pathlib import Path
from tkinter import Tcl, StringVar, BooleanVar, DoubleVar

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui_app import ProductScopeApp


class PlotControlTests(unittest.TestCase):
    def setUp(self):
        self.tk = Tcl()
        self.app = ProductScopeApp.__new__(ProductScopeApp)
        app = self.app
        app.sample_inputs = {name: {} for name in ['B', 'A', 'C']}
        app.selected_samples = None
        app.product_library = {'products': []}
        app.results = [
            {'sample': name, 'product': product, 'is_reactant': reactant,
             'adjusted_concentration_mol_l': conc, 'faradaic_efficiency_pct': fe}
            for name in ['A', 'B', 'C']
            for product, reactant, conc, fe in [('Feed', True, .04, 999),
                                               ('P1', False, .01, 20),
                                               ('P2', False, .02, 30)]
        ]
        app.sample_summaries = {name: {'total_charge_c': 120,
            'initial_reactant_concentration_mol_l': .1, 'reactant_name': 'Feed'}
            for name in ['A', 'B', 'C']}
        for key, value in {'plot_metric': 'Adjusted Concentration (mM)',
                           'sample_selection_text': '',
                           'plot_right_metric': 'Total FE (%)',
                           'plot_overlay_color': '#222222',
                           'plot_x_title': 'Sample', 'plot_y_title': 'Concentration (mM)',
                           'plot_grid_style': 'Solid', 'plot_label_mode': 'Off',
                           'plot_legend_position': 'Top'}.items():
            setattr(app, key, StringVar(self.tk, value=value))
        app.plot_grid_enabled = BooleanVar(self.tk, value=True)
        app.plot_width_in = DoubleVar(self.tk, value=7)
        app.plot_height_in = DoubleVar(self.tk, value=4.5)

    def test_selected_samples_keep_input_order_and_filter_bars(self):
        self.app.selected_samples = {'A', 'B'}
        data = self.app._plot_data()
        self.assertEqual(data['samples'], ['B', 'A'])
        self.assertEqual(set(data['matrix']), {'B', 'A'})
        self.assertEqual(data['matrix']['A']['P1'], 10)

    def test_empty_selection_does_not_mean_all(self):
        self.app.selected_samples = set()
        self.assertEqual(self.app._plot_data()['samples'], [])

    def test_refresh_preserves_subset_and_all_samples_state(self):
        self.app.selected_samples = {'A', 'removed'}
        self.app._refresh_sample_filter()
        self.assertEqual(self.app.selected_samples, {'A'})
        self.assertEqual(self.app.sample_selection_text.get(), 'Samples: 1 of 3')
        self.app.selected_samples = None
        self.app._refresh_sample_filter()
        self.assertIsNone(self.app.selected_samples)
        self.assertEqual(self.app.sample_selection_text.get(), 'Samples: 3 of 3')

    def test_sample_totals_exclude_reactant_and_do_not_multiply_charge(self):
        self.assertEqual(self.app._overlay_values(['B', 'A']), [50, 50])
        self.app.plot_right_metric.set('Total charge passed (C)')
        self.assertEqual(self.app._overlay_values(['B', 'A']), [120, 120])
        self.app.sample_inputs['B']['total_charge_c'] = 999
        self.assertEqual(self.app._overlay_values(['B']), [120])

    def test_conversion_uses_reactant_depletion_including_multiple_signals(self):
        self.app.plot_right_metric.set('Carbon conversion (%)')
        self.assertAlmostEqual(self.app._overlay_values(['A'])[0], 60)
        self.app.results.append({'sample': 'A', 'product': 'Feed', 'is_reactant': True,
                                 'adjusted_concentration_mol_l': .01})
        self.assertAlmostEqual(self.app._overlay_values(['A'])[0], 50)

    def test_unavailable_values_are_gaps_but_zero_is_retained(self):
        self.app.results[1]['faradaic_efficiency_pct'] = None
        self.assertTrue(math.isnan(self.app._overlay_values(['A'])[0]))
        self.app.plot_right_metric.set('Total charge passed (C)')
        self.app.sample_summaries['A']['total_charge_c'] = 0
        self.assertEqual(self.app._overlay_values(['A']), [0])
        self.assertTrue(math.isnan(self.app._overlay_values(['missing'])[0]))
        self.app.plot_right_metric.set('Carbon conversion (%)')
        self.app.sample_summaries['A']['initial_reactant_concentration_mol_l'] = 0
        self.assertTrue(math.isnan(self.app._overlay_values(['A'])[0]))

    def test_redraw_and_export_have_one_overlay_and_combined_legend(self):
        figure = Figure(figsize=(7, 4.5))
        FigureCanvasAgg(figure)
        axis = figure.add_subplot()
        self.app.selected_samples = {'B', 'C'}
        for export in [False, True, False]:
            self.app._draw_plot_on_axis(figure, axis, for_export=export)
            figure.canvas.draw()
            self.assertEqual(len(figure.axes), 2)
            self.assertEqual(list(figure.axes[1].lines[0].get_xdata()), [0, 1])
            self.assertEqual(list(figure.axes[1].lines[0].get_ydata()), [50, 50])
            self.assertIn('Total FE (%)', [t.get_text() for t in axis.get_legend().get_texts()])
        self.app.plot_right_metric.set('None')
        self.app._draw_plot_on_axis(figure, axis)
        self.assertEqual(len(figure.axes), 1)

    def test_overlay_colour_and_dots_match_in_preview_export_and_legend(self):
        for color in ['#0072b2', '#cc3366']:
            self.app.plot_overlay_color.set(color)
            for export in [False, True]:
                figure = Figure(figsize=(7, 4.5))
                FigureCanvasAgg(figure)
                axis = figure.add_subplot()
                self.app._draw_plot_on_axis(figure, axis, for_export=export)
                for line in [figure.axes[1].lines[0], axis.get_legend().get_lines()[0]]:
                    self.assertEqual(line.get_linestyle(), ':')
                    self.assertEqual(line.get_color(), color)
                    self.assertEqual(line.get_markeredgecolor(), color)

    def test_legends_fit_with_right_axis_and_off_hides_combined_legend(self):
        for position in ['Top', 'Right', 'Bottom', 'None']:
            with self.subTest(position=position):
                self.app.plot_legend_position.set(position)
                figure = Figure(figsize=(7, 4.5))
                FigureCanvasAgg(figure)
                axis = figure.add_subplot()
                self.app._draw_plot_on_axis(figure, axis, for_export=True)
                figure.canvas.draw()
                if position == 'None':
                    self.assertIsNone(axis.get_legend())
                else:
                    legend_box = axis.get_legend().get_window_extent(figure.canvas.get_renderer())
                    self.assertGreaterEqual(legend_box.x0, 0)
                    self.assertGreaterEqual(legend_box.y0, 0)
                    self.assertLessEqual(legend_box.x1, figure.bbox.width)
                    self.assertLessEqual(legend_box.y1, figure.bbox.height)

    def test_multirow_legend_clears_plot_and_axis_titles_after_resize(self):
        for product in ['Formic acid', 'Oxalic acid', 'Lactic acid', 'Acetic acid',
                        'Glycolic acid', 'Tartronic acid']:
            self.app.results.append({'sample': 'A', 'product': product,
                                     'adjusted_concentration_mol_l': .002,
                                     'faradaic_efficiency_pct': 2})
        for position in ['Top', 'Bottom', 'Right']:
            for export in [False, True]:
                with self.subTest(position=position, export=export):
                    self.app.plot_legend_position.set(position)
                    figure = Figure(figsize=(7, 4.5))
                    FigureCanvasAgg(figure)
                    axis = figure.add_subplot()
                    for size in [(7, 4.5), (6, 4), (9, 5)]:
                        figure.set_size_inches(*size)
                        self.app._draw_plot_on_axis(figure, axis, for_export=export)
                        figure.canvas.draw()
                        renderer = figure.canvas.get_renderer()
                        box = axis.get_legend().get_window_extent(renderer)
                        self.assertGreaterEqual(box.x0, 0)
                        self.assertGreaterEqual(box.y0, 0)
                        self.assertLessEqual(box.x1, figure.bbox.width)
                        self.assertLessEqual(box.y1, figure.bbox.height)
                        for plot_axis in figure.axes:
                            for artist in [plot_axis, plot_axis.xaxis.label, plot_axis.yaxis.label]:
                                self.assertFalse(box.overlaps(artist.get_window_extent(renderer)))


if __name__ == '__main__':
    unittest.main()
