"""Self-contained reports for provisional seven-peak method, using raw spectra only."""
from io import BytesIO
import json
import re
import zipfile
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import plotly.graph_objects as go
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, Reference
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from preprocessing import save_preprocessing_to_archive
from baseline_review import seven_peak_diagnostics


def safe(s):
    return re.sub(r'[^A-Za-z0-9_-]+', '_', s).strip('_')[:65] or 'sample'


def summary_df(results):
    return pd.DataFrame([{"Sample": r.sample, "R squared": r.r2, "RMSE": r.rmse,
                          **{f"{name} relative area (%)": float(p) for name, p in zip(r.names, r.percentages)}}
                         for r in results])


def render_png(r, mode='fit'):
    fig, ax = plt.subplots(figsize=(11, 6))
    if mode == 'fit':
        ax.plot(r.x, r.corrected, 'k.', ms=2.5, label='Measured (baseline-corrected)')
        for i, comp in enumerate(r.components):
            ax.plot(r.x, comp, '--', lw=1.6, label=r.names[i])
        ax.plot(r.x, r.fitted, 'r-', lw=2.5, label='Total fit')
        ax.set_ylabel('Baseline-corrected absorbance')
        ax.legend(fontsize=7, ncol=2)
    elif mode == 'baseline':
        ax.plot(r.x, r.original, label='Measured');
        ax.plot(r.x, r.baseline, '--', label='Selected baseline')
        ax.plot(r.x, r.corrected, label='Baseline-corrected')
        ax.set_ylabel('Absorbance');
        ax.legend(fontsize=8)
    elif mode == 'residual':
        ax.plot(r.x, r.residuals, label='Residual');
        ax.axhline(0, color='gray', ls='--')
        ax.set_ylabel('Residual absorbance')
    else:
        n = len(r.names)
        ax.bar(range(n), r.percentages)
        ax.set_xticks(
            range(n),
            [f'P{i + 1}' for i in range(n)]
        )
        ax.set_ylabel('Relative fitted area (%)')
    if mode != 'bars': ax.invert_xaxis()
    ax.set_xlabel('Wavenumber (cm$^{-1}$)' if mode != 'bars' else 'Peak')
    ax.set_title(f'{r.sample} — {mode}')
    ax.grid(alpha=.15);
    fig.tight_layout()
    b = BytesIO();
    fig.savefig(b, format='png', dpi=180);
    plt.close(fig)
    return b.getvalue()


def comparison_png(results):
    fig, ax = plt.subplots(figsize=(11, 6))
    bottom = [0.] * len(results)
    for j, name in enumerate(results[0].names):
        v = [float(r.percentages[j]) for r in results]
        ax.bar([r.sample for r in results], v, bottom=bottom, label=name)
        bottom = [a + b for a, b in zip(bottom, v)]
    ax.set_ylim(0, 105);
    ax.set_ylabel('Relative fitted area (%)')
    ax.legend(fontsize=7, ncol=2);
    ax.tick_params(axis='x', rotation=45)
    fig.tight_layout();
    b = BytesIO();
    fig.savefig(b, format='png', dpi=180);
    plt.close(fig)
    return b.getvalue()


def _style(ws):
    ws.freeze_panes = 'B2';
    ws.auto_filter.ref = ws.dimensions
    for cell in ws[1]:
        cell.fill = PatternFill('solid', fgColor='16324B')
        cell.font = Font(bold=True, color='FFFFFF')
    for col in ws.columns:
        width = max(len(str(c.value or '')) for c in list(col)[:75]) + 2
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(45, max(15, width))
    for row in ws.iter_rows(min_row=2):
        for c in row:
            if isinstance(c.value, float): c.number_format = '0.00000'


def xlsx_report(results, settings):
    wb = Workbook();
    dashboard = wb.active;
    dashboard.title = 'Dashboard'
    for row in [['FTIR Analysis Studio | Exploratory 7-peak report'],
                ['Samples analyzed', len(results)], ['Model', 'Provisional constrained seven-Gaussian'],
                ['Spectral window', str(settings['spectral_window_cm-1'])],
                ['Baseline', settings.get('baseline', 'linear_endpoints')],
                ['Advanced ATR correction', 'NOT IMPLEMENTED; see Method and Settings for simple mode'],
                ['Interpretation', 'Relative fitted peak areas are not validated protein structure fractions'],
                ['Review', 'Peak identities, centers, widths and sample preparation with supervisor']]:
        dashboard.append(row)
    dashboard.column_dimensions['A'].width = 30;
    dashboard.column_dimensions['B'].width = 100
    dashboard['A1'].font = Font(size=18, bold=True, color='16324B')
    summary = wb.create_sheet('Summary')
    sm = summary_df(results)
    for row in [sm.columns.tolist()] + sm.values.tolist(): summary.append(list(row))
    _style(summary)
    p = wb.create_sheet('Peak Configuration')
    for row in [list(results[0].peak_settings.columns)] + results[0].peak_settings.values.tolist():
        p.append(list(row))
    _style(p)
    params = wb.create_sheet('Fitted Peak Parameters')
    params.append(['Sample'] + list(results[0].parameters_table().columns))
    for r in results:
        for record in r.parameters_table().itertuples(index=False, name=None):
            params.append([r.sample] + list(record))
    _style(params)
    qc = wb.create_sheet('Quality Review')
    qc.append(['Sample', 'R squared', 'RMSE', 'Peak-level flags', 'Review status'])
    for r in results:
        flag_rows = seven_peak_diagnostics(r, r2_review_threshold=settings.get('review_r2_threshold', .95))
        flag_text = '; '.join(sorted(set(v for v in flag_rows['Flags'] if v)))
        if r.r2 < settings.get('review_r2_threshold', .95):
            flag_text = ('R² below review threshold; ' + flag_text).strip('; ')
        qc.append([r.sample, r.r2, r.rmse, flag_text, 'REVIEW' if flag_text else 'No automatic flags'])
    _style(qc)
    all_diagnostics = pd.concat(
        [seven_peak_diagnostics(r, r2_review_threshold=settings.get('review_r2_threshold', .95)) for r in results],
        ignore_index=True)
    detail = wb.create_sheet('Peak Diagnostics')
    detail.append(list(all_diagnostics.columns))
    for row in all_diagnostics.itertuples(index=False, name=None): detail.append(list(row))
    _style(detail)
    comparisons = [r.shared_comparison for r in results if hasattr(r, 'shared_comparison')]
    if comparisons:
        comparison = wb.create_sheet('Common Window Comparison')
        tab = pd.concat(comparisons, ignore_index=True)
        comparison.append(list(tab.columns))
        for row in tab.itertuples(index=False, name=None): comparison.append(list(row))
        _style(comparison)
    chart = BarChart();
    chart.title = 'R squared by sample';
    chart.width = 20;
    chart.height = 10
    chart.add_data(Reference(qc, min_col=2, min_row=1, max_row=qc.max_row), titles_from_data=True)
    chart.set_categories(Reference(qc, min_col=1, min_row=2, max_row=qc.max_row));
    qc.add_chart(chart, 'F3')
    method = wb.create_sheet('Method and Settings')
    method.append(['Parameter', 'Value'])
    for k, v in settings.items(): method.append(
        [k, json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)])
    _style(method)
    for j, r in enumerate(results, 1):
        ws = wb.create_sheet(f'S{j:02d}_Spectrum')
        df = r.spectrum_table()
        ws.append(list(df.columns))
        for record in df.itertuples(index=False, name=None): ws.append(list(record))
        _style(ws)
    b = BytesIO();
    wb.save(b);
    return b.getvalue()


def pdf_report(z, results, settings):
    b = BytesIO();
    pdf = Canvas(b, pagesize=A4);
    w, h = A4
    pdf.setTitle('FTIR seven-peak exploratory report')
    pdf.setFont('Helvetica-Bold', 18);
    pdf.drawString(40, h - 60, 'FTIR Analysis Studio - Exploratory report')
    pdf.setFont('Helvetica', 11)
    for i, line in enumerate([f'Samples: {len(results)}', 'Seven constrained Gaussian peaks',
                              f"Spectral window: {settings['spectral_window_cm-1']} cm-1",
                              'Baseline: ' + str(settings.get('baseline', 'linear_endpoints')),
                              'ATR mode: ' + str(settings.get('preprocessing', {}).get('atr_mode', 'none')),
                              'Advanced ATR: NOT implemented (simple scaling is exploratory)',
                              'Peak bounds are provisional - confirm with supervisor',
                              'Relative peak areas are not validated structural fractions']):
        pdf.drawString(40, h - 102 - 22 * i, line)
    pdf.setFont('Helvetica-Bold', 12);
    pdf.drawString(40, h - 305, 'Quality overview')
    pdf.setFont('Helvetica', 10)
    for i, r in enumerate(results[:18]): pdf.drawString(40, h - 335 - 20 * i,
                                                        f'{r.sample[:38]}   R2={r.r2:.5f}   RMSE={r.rmse:.5g}')
    pdf.showPage()
    imgs = sorted(n for n in z.namelist() if n.endswith('.png'))
    for i, name in enumerate(imgs, 1):
        im = ImageReader(BytesIO(z.read(name)));
        iw, ih = im.getSize()
        scale = min((w - 65) / iw, (h - 125) / ih);
        dw, dh = iw * scale, ih * scale
        pdf.setFont('Helvetica-Bold', 10);
        pdf.drawString(35, h - 40, name.split('/')[-1][:80])
        pdf.drawImage(im, (w - dw) / 2, (h - dh) / 2 - 8, dw, dh)
        pdf.setFont('Helvetica', 9);
        pdf.drawRightString(w - 35, 25, f'Figure {i}/{len(imgs)}')
        pdf.showPage()
    pdf.save();
    return b.getvalue()


def build_seven_zip(results, settings):
    out = BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        df = summary_df(results)
        z.writestr('summary/results_summary.csv', df.to_csv(index=False))
        z.writestr('summary/FTIR_Study_Report.xlsx', xlsx_report(results, settings))
        z.writestr('analysis_settings.json', json.dumps(settings, indent=2, ensure_ascii=False))
        z.writestr('summary/peak_configuration.csv', results[0].peak_settings.to_csv(index=False))
        diagnostics = pd.concat(
            [seven_peak_diagnostics(r, r2_review_threshold=settings.get('review_r2_threshold', 0.95)) for r in results],
            ignore_index=True)
        z.writestr('summary/peak_diagnostics.csv', diagnostics.to_csv(index=False))

        comparisons_6v7 = [
            r.comparison_6v7
            for r in results
            if hasattr(r, "comparison_6v7")
        ]

        if comparisons_6v7:
            comparison_table = pd.concat(
                comparisons_6v7,
                ignore_index=True
            )

            z.writestr(
                "summary/comparison_6_vs_7.csv",
                comparison_table.to_csv(index=False)
            )

        comparisons = [r.shared_comparison for r in results if hasattr(r, 'shared_comparison')]
        if comparisons:
            z.writestr('summary/model_comparison_shared_1600_1700.csv',
                       pd.concat(comparisons, ignore_index=True).to_csv(index=False))
        z.writestr('charts/comparison_stacked_bar.png', comparison_png(results))
        z.writestr('README.txt',
                   'Exploratory seven-peak model. Baseline selection and optional simple ATR scaling recorded in settings. Optional simple ATR scaling may have been applied; see settings. The output named baseline_corrected_region.txt is LINEAR BASELINE-CORRECTED after any optional preprocessing. Peak bounds/assignments require supervisor validation. Relative areas are not validated structural fractions.')
        for i, r in enumerate(results, 1):
            base = f'samples/{i:02d}_{safe(r.sample)}/'
            z.writestr(base + 'fitted_spectrum.csv', r.spectrum_table().to_csv(index=False))
            save_preprocessing_to_archive(z, base, r)
            z.writestr(base + 'peak_parameters.csv', r.parameters_table().to_csv(index=False))
            z.writestr(base + 'peak_diagnostics.csv', seven_peak_diagnostics(r).to_csv(index=False))
            if hasattr(r, 'shared_predictions'):
                z.writestr(base + 'shared_window_predictions.csv', r.shared_predictions.to_csv(index=False))
                fig2, ax2 = plt.subplots(figsize=(11, 5))
                comparison = r.shared_predictions
                ax2.plot(comparison['Wavenumber (cm-1)'], comparison['Observed preprocessed absorbance'], 'k.', ms=2,
                         label='Observed')
                ax2.plot(comparison['Wavenumber (cm-1)'], comparison['5-peak predicted absorbance'], lw=2,
                         label='5-peak')
                ax2.plot(comparison['Wavenumber (cm-1)'], comparison['7-peak predicted absorbance'], lw=2,
                         label='7-peak')
                ax2.set(xlabel='Wavenumber (cm⁻¹)', ylabel='Processed absorbance',
                        title=r.sample + ' — shared interval (not model validation)')
                ax2.invert_xaxis();
                ax2.legend();
                fig2.tight_layout()
                image = BytesIO();
                fig2.savefig(image, format='png', dpi=170);
                plt.close(fig2)
                z.writestr(base + 'shared_window_comparison.png', image.getvalue())
            z.writestr(base + 'baseline_corrected_region.txt',
                       pd.DataFrame({'Wavenumber (cm-1)': r.x, 'Baseline-corrected absorbance': r.corrected}).to_csv(
                           index=False, sep='\t'))
            fig = go.Figure()
            fig.add_scatter(x=r.x, y=r.corrected, name='Baseline-corrected measured', mode='markers')
            for name, comp in zip(r.names, r.components):
                fig.add_scatter(x=r.x, y=comp, name=name, line=dict(dash='dash'))
            fig.add_scatter(x=r.x, y=r.fitted, name='Total fit', line=dict(color='red'))
            fig.update_xaxes(autorange='reversed', title='Wavenumber (cm-1)')
            z.writestr(base + 'interactive_fit.html', fig.to_html(full_html=True, include_plotlyjs=True))
            for name in ['fit', 'baseline', 'residual', 'bars']:
                z.writestr(base + name + '.png', render_png(r, name))
        z.writestr('FTIR_Complete_Analysis_Report.pdf', pdf_report(z, results, settings))
    return out.getvalue()
