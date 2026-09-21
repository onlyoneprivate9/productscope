"""Convert the editable sample grid to and from calculation rows."""
import math

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
