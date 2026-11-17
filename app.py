"""FTIR Analysis Studio — guided upload → configure → run → review → export."""
from pathlib import Path
from io import BytesIO, StringIO
import json
import re
import zipfile

import matplotlib
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ftir_core import LABELS, COLORS, CENTERS, read_spectrum, fit_spectrum, gaussian_components, results_excel, \
    validate_sigma_bounds
from enhanced_reports import build_excel, build_pdf, qc_records
from advanced_pipeline import peak_table_default, validate_peak_table, fit_seven
from baseline_review import seven_peak_diagnostics, common_window_comparison
from advanced_export import build_seven_zip, summary_df as seven_summary_df
from preprocessing import validate_options, preprocess, attach_provenance, save_preprocessing_to_archive
from report_exports import (report_xlsx, residual_png, preprocessing_png, component_bars_png,
                            stacked_comparison_png, grouped_beta_png, fit_quality_png)

st.set_page_config(page_title='FTIR Analysis Studio', page_icon='🔬', layout='wide')
st.markdown('''<style>
.block-container{max-width:1300px;padding-top:2rem;padding-bottom:3rem}
h1{letter-spacing:-.045em;font-weight:750} h2{font-size:1.42rem}
[data-testid="stMetric"]{border:1px solid rgba(130,145,160,.22);padding:14px;border-radius:12px}
[data-testid="stSidebar"]{border-right:1px solid rgba(130,145,160,.2)}
div.stButton>button[kind="primary"]{font-weight:700}
</style>''', unsafe_allow_html=True)

ROOT = Path(__file__).resolve().parent
PREV = ROOT / 'data' / 'Example_previous_study_summary.xlsx'
STEPS = ['1 · Upload data', '2 · Configure', '3 · Run analysis', '4 · View results', '5 · Download ZIP']
if 'stage' not in st.session_state: st.session_state.stage = 0
if 'model_mode' not in st.session_state: st.session_state.model_mode = 'Exploratory 7-peak (supervisor review required)'
if 'peak_table_7' not in st.session_state: st.session_state.peak_table_7 = peak_table_default()
if 'results' not in st.session_state: st.session_state.results = []
if 'errors' not in st.session_state: st.session_state.errors = []
if 'run_signature' not in st.session_state: st.session_state.run_signature = None
if 'spectra_files' not in st.session_state: st.session_state.spectra_files = []
if 'upload_errors' not in st.session_state: st.session_state.upload_errors = []
if 'export_archive' not in st.session_state: st.session_state.export_archive = None
if 'export_error' not in st.session_state: st.session_state.export_error = None


def change_stage(n):
    st.session_state.stage = n


def reset_analysis():
    st.session_state.results = []
    st.session_state.errors = []
    st.session_state.run_signature = None
    st.session_state.export_archive = None
    st.session_state.export_error = None


def cache_uploads():
    """Persist file bytes across workflow pages (widgets do not persist if hidden)."""
    spectra, issues = [], []
    seen = set()
    for uploaded in st.session_state.get('incoming_files') or []:
        raw = uploaded.getvalue()
        if uploaded.name.lower().endswith('.zip'):
            try:
                with zipfile.ZipFile(BytesIO(raw)) as archive:
                    for entry in archive.infolist():
                        if entry.is_dir() or not entry.filename.lower().endswith(('.txt', '.csv')):
                            continue
                        if entry.file_size > 20 * 1024 * 1024:
                            issues.append(f'{entry.filename}: file exceeds 20 MB limit')
                            continue
                        name = Path(entry.filename.replace('\\', '/')).name
                        if name in seen:
                            issues.append(f'{name}: duplicate filename skipped')
                            continue
                        spectra.append((name, archive.read(entry)))
                        seen.add(name)
            except (zipfile.BadZipFile, RuntimeError, ValueError) as exc:
                issues.append(f'{uploaded.name}: could not read ZIP ({exc})')
        else:
            if uploaded.name in seen:
                issues.append(f'{uploaded.name}: duplicate filename skipped')
                continue
            spectra.append((uploaded.name, raw))
            seen.add(uploaded.name)
    st.session_state.spectra_files = spectra
    st.session_state.upload_errors = issues
    reset_analysis()


def plot_spectrum(r, selected=None):
    selected = selected if selected is not None else list(LABELS)
    fig = go.Figure()
    fig.add_scatter(x=r.x, y=r.corrected, mode='markers', name='Measured (corrected)',
                    marker=dict(size=4, color='#222222'), hovertemplate='%{x:.1f} cm⁻¹<br>%{y:.5f}<extra></extra>')
    dense = np.linspace(float(r.x.min()), float(r.x.max()), 700)
    comps = gaussian_components(dense, r.parameters)
    for i, (label, color) in enumerate(zip(LABELS, COLORS)):
        if label in selected: fig.add_scatter(x=dense, y=comps[i], name=label,
                                              line=dict(color=color, dash='dash', width=2))
    fig.add_scatter(x=r.x, y=r.fitted, name='Total fit', line=dict(color='#f04452', width=3))
    fig.update_layout(height=470, margin=dict(l=10, r=10, t=20, b=10), xaxis_title='Wavenumber (cm⁻¹)',
                      yaxis_title='Baseline-corrected absorbance', legend=dict(orientation='h', y=-.27))
    fig.update_xaxes(autorange='reversed')
    return fig


def comparison_plot(results):
    fig = go.Figure()
    for i, (label, color) in enumerate(zip(LABELS, COLORS)):
        fig.add_bar(x=[r.sample for r in results], y=[float(r.percentages[i]) for r in results], name=label,
                    marker_color=color)
    fig.update_layout(barmode='stack', height=450, margin=dict(l=0, r=0, t=10, b=10),
                      yaxis_title='Relative Gaussian area (%)', legend=dict(orientation='h', y=-.3))
    fig.update_yaxes(range=[0, 105])
    return fig


def png_spectrum(r):
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(r.x, r.corrected, 'k.', markersize=3, label='Measured (corrected)')
    dense = np.linspace(float(r.x.min()), float(r.x.max()), 650)
    for label, color, component in zip(LABELS, COLORS, gaussian_components(dense, r.parameters)):
        ax.plot(dense, component, '--', color=color, label=label)
    ax.plot(r.x, r.fitted, color='red', linewidth=2.4, label='Total fit')
    ax.invert_xaxis();
    ax.set(xlabel='Wavenumber (cm⁻¹)', ylabel='Corrected absorbance', title=r.sample)
    ax.legend(fontsize=8);
    ax.grid(alpha=.15);
    fig.tight_layout()
    bio = BytesIO();
    fig.savefig(bio, format='png', dpi=220);
    plt.close(fig)
    return bio.getvalue()


def safe_name(s):
    return re.sub(r'[^A-Za-z0-9_-]+', '_', s).strip('_')[:70] or 'sample'


def summary_frame(results):
    records = []
    for r in results:
        record = {'Sample': r.sample, 'R squared': r.r2, 'RMSE': r.rmse, 'Unique wavenumbers': len(r.x)}
        record.update({f'{lab} relative area (%)': float(p) for lab, p in zip(LABELS, r.percentages)})
        record['Total beta sheet relative area (%)'] = float(r.percentages[1] + r.percentages[2])
        records.append(record)
    return pd.DataFrame(records)


def sigma_constraints():
    """Read and validate the five independent component width intervals."""
    lower = [float(st.session_state.get(f'sigma_min_{i}', 0.0)) for i in range(5)]
    upper = [float(st.session_state.get(f'sigma_max_{i}', 100.0)) for i in range(5)]
    return validate_sigma_bounds(lower, upper)


def preprocessing_options():
    return validate_options({
        'atr_mode': st.session_state.get('atr_mode', 'none'),
        'reference_wavenumber': st.session_state.get('reference_wavenumber', 1650.),
        'crystal_refractive_index': st.session_state.get('crystal_refractive_index', 2.4),
        'sample_refractive_index': st.session_state.get('sample_refractive_index', 1.5),
        'incidence_angle_degrees': st.session_state.get('incidence_angle_degrees', 45.),
        'savgol_enabled': st.session_state.get('savgol_enabled', False),
        'savgol_window': st.session_state.get('savgol_window', 11),
        'savgol_polynomial': st.session_state.get('savgol_polynomial', 3),
    })


def export_settings():
    sigma_lo, sigma_hi = sigma_constraints()
    return {'model': 'five fixed-center Gaussians',
            'peak_centers_cm-1': CENTERS.tolist(), 'spectral_window_cm-1': [1600, 1700],
            'baseline': 'linear endpoint', 'preprocessing': preprocessing_options(),
            'sample_preparation_notes': st.session_state.get('sample_preparation_notes', ''),
            'maximum_amplitude': float(st.session_state.get('amplitude_max', 1.)),
            'maximum_sigma_cm-1': float(np.max(sigma_hi)),
            'minimum_sigma_cm-1': sigma_lo.tolist(),
            'maximum_sigma_per_peak_cm-1': sigma_hi.tolist(),
            'sigma_constraints_by_peak': [
                {'component': label, 'center_cm-1': float(center), 'minimum_sigma_cm-1': float(lo),
                 'maximum_sigma_cm-1': float(hi)} for label, center, lo, hi in
                zip(LABELS, CENTERS, sigma_lo, sigma_hi)],
            'initial_sigma_cm-1': float(st.session_state.get('initial_sigma', 10.)),
            'review_r2_threshold': float(st.session_state.get('review_r2_threshold', 0.95)),
            'scientific_caution': 'Relative fitted areas are not independently validated secondary-structure fractions.'}


def active_peak_table():
    table = st.session_state.peak_table_7.copy()

    if not st.session_state.get("include_peak_7", True):
        table = table.iloc[:6].copy()

    return validate_peak_table(
        table, 1550., 1760.
    )


def seven_export_settings():
    table = active_peak_table()
    return {'model': f'Exploratory constrained {len(table)}-peak (NOT validated)',
            'spectral_window_cm-1': [1550, 1760],
            'baseline': st.session_state.get('baseline_mode_7', 'robust_edge_fit'),
            'baseline_edge_fraction': float(st.session_state.get('baseline_edge_fraction_7', 0.12)),
            'preprocessing': preprocessing_options(),
            'sample_preparation_notes': st.session_state.get('sample_preparation_notes', ''),
            'atr_correction': preprocessing_options()['atr_method_note'],
            'peak_configuration': table.to_dict('records'),
            'maximum_amplitude': float(st.session_state.get('amplitude_max_7', 1.)),
            'review_r2_threshold': 0.95,
            'scientific_caution': 'Provisional peak assignments. Relative areas are not validated structural fractions.'}


def plot_seven(r, selected):
    fig = go.Figure()
    fig.add_scatter(x=r.x, y=r.corrected, mode='markers', name='Measured (baseline-corrected)',
                    marker=dict(size=3, color='black'))
    for name, comp in zip(r.names, r.components):
        if name in selected: fig.add_scatter(x=r.x, y=comp, name=name, line=dict(dash='dash'))
    fig.add_scatter(x=r.x, y=r.fitted, name='Total fit', line=dict(color='red', width=3))
    fig.update_xaxes(autorange='reversed', title='Wavenumber (cm⁻¹)')
    fig.update_yaxes(title='Baseline-corrected absorbance')
    fig.update_layout(height=480, legend=dict(orientation='h', y=-.3))
    return fig


def generate_full_export():
    """Build all Excel, PNG, HTML and tabular outputs from current fitted TXT/CSV data."""
    st.session_state.export_archive = None
    st.session_state.export_error = None
    if not st.session_state.results:
        return
    try:
        if st.session_state.model_mode.startswith('Original'):
            st.session_state.export_archive = make_zip(st.session_state.results, export_settings())
        else:
            st.session_state.export_archive = build_seven_zip(st.session_state.results, seven_export_settings())
    except Exception as exc:
        st.session_state.export_error = f'Export generation failed: {exc}'


def create_formatted_excel(results):
    """Style the existing export without requiring optional artifact_tool_v2."""
    workbook = load_workbook(BytesIO(results_excel(results)))
    for sheet in workbook.worksheets:
        sheet.freeze_panes = 'B2'
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.fill = PatternFill('solid', fgColor='17365D')
            cell.font = Font(bold=True, color='FFFFFF')
            cell.alignment = Alignment(horizontal='center', wrap_text=True)
        for column in sheet.columns:
            letter = get_column_letter(column[0].column)
            max_length = max(len(str(cell.value or '')) for cell in column)
            sheet.column_dimensions[letter].width = min(max(max_length + 3, 14), 42)
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value, float):
                    cell.number_format = '0.0000'
    out = BytesIO()
    workbook.save(out)
    return out.getvalue()


def create_complete_pdf(archive, results):
    """Create title page followed by every PNG already present in the archive."""
    out = BytesIO()
    doc = canvas.Canvas(out, pagesize=A4)
    page_width, page_height = A4
    doc.setTitle('FTIR Complete Analysis Report')
    doc.setFont('Helvetica-Bold', 22)
    doc.drawString(44, page_height - 75, 'FTIR Analysis Report')
    doc.setFont('Helvetica', 12)
    doc.drawString(44, page_height - 112, f'Analyzed samples: {len(results)}')
    doc.drawString(44, page_height - 135, 'Five-Gaussian Amide I analysis | 1600-1700 cm-1')
    doc.setFont('Helvetica', 10)
    doc.drawString(44, page_height - 184, 'All results are computed from uploaded TXT/CSV spectra.')
    doc.drawString(44, page_height - 204, 'Relative fitted areas are not validated structure percentages.')
    doc.showPage()

    image_paths = sorted(n for n in archive.namelist() if n.lower().endswith('.png'))
    for page_number, name in enumerate(image_paths, 1):
        image = ImageReader(BytesIO(archive.read(name)))
        iw, ih = image.getSize()
        scale = min((page_width - 70) / iw, (page_height - 140) / ih)
        dw, dh = iw * scale, ih * scale
        doc.setFont('Helvetica-Bold', 10)
        # Helvetica does not support arbitrary Unicode sample names; use safe ASCII here.
        header = name.replace('_', ' ').encode('ascii', errors='replace').decode('ascii')
        doc.drawString(35, page_height - 42, header[:95])
        doc.drawImage(image, (page_width - dw) / 2, (page_height - dh) / 2 - 8,
                      width=dw, height=dh, preserveAspectRatio=True)
        doc.setFont('Helvetica', 9)
        doc.drawRightString(page_width - 35, 25, f'Figure {page_number} of {len(image_paths)}')
        doc.showPage()
    doc.save()
    return out.getvalue()


def make_zip(results, settings, include_png=True, include_html=True, include_excel=True):
    from preprocessing import save_preprocessing_to_archive
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        summary = summary_frame(results)
        z.writestr('summary/results_summary.csv', summary.to_csv(index=False, float_format='%.8g'))
        z.writestr('summary/results_summary.txt', summary.to_csv(index=False, sep='\t', float_format='%.8g'))
        z.writestr('analysis_settings.json', json.dumps(settings, indent=2, ensure_ascii=False))
        z.writestr('summary/sigma_constraints.csv',
                   pd.DataFrame(settings.get('sigma_constraints_by_peak', [])).to_csv(index=False))
        z.writestr('README.txt',
                   'FTIR Analysis Studio — complete research analysis package\n\nOriginal source: uploaded TXT/CSV FTIR spectra only. Optional preprocessing is recorded in analysis_settings.json and per-sample preprocessing_settings.json. Reference Excel/PNG images are NOT used in the fit.\n\nThe five fixed-center Gaussian model computes relative fitted areas, NOT independently validated secondary-structure percentages. Inspect fit residuals and R² before interpretation.\n\nsummary/: study table (CSV, TXT, informative Excel report)\ncharts/: all-sample stacked component bars, grouped beta-sheet bars, quality comparison (PNG)\nsamples/: each sample\'s Gaussian fit, residual plot, baseline correction and component bar PNG; full calculated data and parameters (CSV/TXT); interactive plot (HTML).\nanalysis_settings.json: fitting parameters used.\n')
        if include_png:
            z.writestr('charts/composition_stacked_bar.png', stacked_comparison_png(results))
            z.writestr('charts/beta_sheet_grouped_bar.png', grouped_beta_png(results))
            z.writestr('charts/fit_quality_R2_RMSE.png', fit_quality_png(results))
        if include_excel:
            chart_assets = {
                'composition_stacked_bar.png': stacked_comparison_png(results),
                'beta_sheet_grouped_bar.png': grouped_beta_png(results),
                'fit_quality_R2_RMSE.png': fit_quality_png(results),
            }
            z.writestr('summary/FTIR_Study_Report.xlsx',
                       build_excel(results, settings, chart_assets, results_excel(results)))
        z.writestr('summary/quality_review.csv',
                   pd.DataFrame([{'Sample': r.sample, 'R_squared': r.r2, 'RMSE': r.rmse,
                                  'Review': '; '.join(notes) if notes else 'No automatic flags'}
                                 for r, notes in qc_records(results, settings)]).to_csv(index=False))
        used = set()
        for idx, r in enumerate(results, 1):
            folder = f'samples/{idx:02d}_{safe_name(r.sample)}/'
            z.writestr(folder + 'fitted_spectrum.csv', r.spectrum_table().to_csv(index=False))
            z.writestr(folder + 'fitted_spectrum.txt', r.spectrum_table().to_csv(index=False, sep='\t'))
            z.writestr(folder + 'baseline_corrected_region.txt',
                       pd.DataFrame({'Wavenumber (cm-1)': r.x, 'Baseline-corrected absorbance': r.corrected}).to_csv(
                           index=False, sep='\t'))
            save_preprocessing_to_archive(z, folder, r)
            z.writestr(folder + 'peak_parameters.csv', r.parameters_table().to_csv(index=False))
            z.writestr(folder + 'peak_parameters.txt', r.parameters_table().to_csv(index=False, sep='\t'))
            if include_png:
                z.writestr(folder + 'gaussian_fit.png', png_spectrum(r))
                z.writestr(folder + 'fit_residuals.png', residual_png(r))
                z.writestr(folder + 'baseline_correction.png', preprocessing_png(r))
                z.writestr(folder + 'component_area_bar.png', component_bars_png(r))
            if include_html: z.writestr(folder + 'interactive_fit.html',
                                        plot_spectrum(r).to_html(full_html=True, include_plotlyjs=True))
        if include_png:
            pdf_bytes = build_pdf(z, results, settings)
            z.writestr('FTIR_Complete_Analysis_Report.pdf', pdf_bytes)
    return buffer.getvalue()


st.title('🔬 FTIR Analysis Studio')
st.caption(
    'Raw spectra → optional exploratory ATR scaling / smoothing → baseline correction → constrained Gaussian fitting → full reports')
st.progress((st.session_state.stage + 1) / 5, text=f'Step {st.session_state.stage + 1} of 5')
with st.sidebar:
    st.subheader('Input spectra')
    st.file_uploader('Upload TXT, CSV or ZIP', type=['txt', 'csv', 'zip'], accept_multiple_files=True,
                     key='incoming_files', on_change=cache_uploads,
                     help='Selected spectra remain available while navigating the workflow.')
    st.caption(f"{len(st.session_state.spectra_files)} spectral file(s) stored for this session")
    st.divider()
    st.subheader('Analysis workflow')
    for i, label in enumerate(STEPS):
        st.button(label, key=f'nav_{i}', on_click=change_stage, args=(i,), use_container_width=True,
                  type='primary' if st.session_state.stage == i else 'secondary')
    st.divider()
    st.caption(
        'Start with your raw TXT/CSV measurements. Your previous Excel workbook is only a reference and is never used as a substitute for raw spectra.')
    with st.expander('About the fitting method'):
        st.write(
            'Original: five fixed centers, 1600–1700 cm⁻¹. Exploratory: seven center-constrained peaks, 1550–1760 cm⁻¹. Both apply a linear endpoint baseline.')
        st.warning(
            'Instrument-grade Advanced ATR correction is not implemented. Optional simple scaling is exploratory.')
        st.warning('Relative fitted Gaussian areas are not independently validated structural percentages.')

stage = st.session_state.stage
if stage == 0:
    st.header('Upload your FTIR data')
    st.write(
        '**Select original spectra** (TXT, CSV or a ZIP archive) using the sidebar. Each spectrum needs two numeric columns: wavenumber and absorbance. Header rows are allowed.')
    st.info(
        'Choose TXT/CSV files or a ZIP archive in the left sidebar. Your files will remain available throughout all five steps.')
    files = st.session_state.spectra_files
    for message in st.session_state.upload_errors: st.warning(message)
    if files:
        rows = [];
        errors = []
        for filename, content in files:
            try:
                x, y = read_spectrum(content, filename)
                seven = not st.session_state.model_mode.startswith('Original')
                lo, hi = (1550, 1760) if seven else (1600, 1700)
                n = int(np.count_nonzero((x >= lo) & (x <= hi)))
                rows.append({'File': filename, 'Total points': len(x), 'Fitting-window points': n,
                             'Wavenumber min': float(np.min(x)), 'Wavenumber max': float(np.max(x)),
                             'Status': 'Ready' if n >= 15 else 'Insufficient Amide I points'})
            except Exception as e:
                errors.append(f'{filename}: {e}')
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        for error in errors: st.error(error)
        if rows and all(row['Fitting-window points'] >= 15 for row in rows):
            st.success(f'{len(rows)} spectrum/spectra available for analysis.')
            st.button('Next: Configure analysis →', on_click=change_stage, args=(1,), type='primary')
    else:
        st.info('No spectra uploaded yet. Choose a TXT or CSV file above to begin.')
        with st.expander('See an example of the required file format'):
            st.code('Wavenumber\tAbsorbance\n1600\t0.0054\n1601\t0.0061\n1602\t0.0070\n...', language='text')
        st.caption(
            'Your previous study summary is not raw spectrum data, so it cannot be re-fitted. It is available as an optional reference below.')
    with st.expander('Optional: view previous study summary (reference only)'):
        if PREV.exists():
            try:
                df = pd.read_excel(PREV, sheet_name='Summary')
                st.dataframe(df.round(4), hide_index=True, use_container_width=True)
            except Exception as e:
                st.error(f'Cannot load example summary: {e}')

elif stage == 1:
    st.header('Configure analysis')
    st.radio('Analysis model', ['Original 5-peak (reference method)',
                                'Exploratory 7-peak (supervisor review required)'],
             key='model_mode', on_change=reset_analysis)
    st.subheader('Preprocessing')
    st.info(
        '5-peak: original linear-endpoint baseline. 7-peak: choose baseline method (robust edges recommended for investigation, not validated).')
    st.warning(
        'Advanced ATR correction is NOT implemented. Optional simplified ATR scaling is an exploratory approximation, not an instrument-equivalent correction.')
    st.text_area('Sample preparation / water / drying notes (metadata only)', key='sample_preparation_notes',
                 on_change=reset_analysis,
                 help='Record treatment such as hydration or drying. This does not modify the spectrum.')
    with st.expander('Optional spectral preprocessing — research / exploratory', expanded=False):
        st.selectbox('ATR handling', ['none', 'simple_wavenumber_scaling'], key='atr_mode', on_change=reset_analysis,
                     help='Simple mode multiplies absorbance by wavenumber / reference wavenumber. No dispersion or instrument-specific correction.')
        st.number_input('Reference wavenumber (cm⁻¹)', min_value=100.0, max_value=5000.0,
                        value=1650.0, step=10.0, key='reference_wavenumber', on_change=reset_analysis)
        st.number_input('ATR crystal refractive index n1', min_value=1.01, max_value=10.0,
                        value=2.4, step=0.1, key='crystal_refractive_index', on_change=reset_analysis)
        st.number_input('Assumed sample refractive index n2', min_value=1.0, max_value=5.0,
                        value=1.5, step=0.1, key='sample_refractive_index', on_change=reset_analysis)
        st.number_input('Angle of incidence (degrees)', min_value=10.0, max_value=85.0,
                        value=45.0, step=1.0, key='incidence_angle_degrees', on_change=reset_analysis)
        st.checkbox('Optional Savitzky–Golay smoothing (may alter peak areas)', value=False,
                    key='savgol_enabled', on_change=reset_analysis)
        if st.session_state.get('savgol_enabled'):
            st.number_input('Smoothing window (odd number of points)', min_value=5, max_value=101,
                            value=11, step=2, key='savgol_window', on_change=reset_analysis)
            st.number_input('Smoothing polynomial order', min_value=1, max_value=5,
                            value=3, key='savgol_polynomial', on_change=reset_analysis)
        try:
            options = preprocessing_options()
            st.success('Preprocessing parameters are internally consistent.')
            st.caption(options['atr_method_note'])
        except ValueError as exc:
            st.error(str(exc))
    if st.session_state.model_mode.startswith('Original'):
        files = st.session_state.spectra_files
        if not files: st.warning('Upload spectra using the sidebar first.')
        st.write('The defaults match the original notebook. For a first analysis, keep these settings unchanged.')
        st.markdown('**Model:** 5 Gaussian bands, fixed peak positions, linear endpoint baseline')
        st.markdown('**Peak centers:** 1652, 1630, 1679, 1671, 1645 cm⁻¹')
        with st.expander('Advanced fitting parameters', expanded=False):
            st.number_input('Maximum amplitude', min_value=.01, max_value=100., value=1., step=.1, key='amplitude_max',
                            on_change=reset_analysis)
            st.markdown('**Independent Gaussian width limits (σ, cm⁻¹)**')
            st.caption(
                'Initial defaults reproduce the original unconstrained-width model. Consult your supervisor before tightening bounds.')
            for i, (label, center) in enumerate(zip(LABELS, CENTERS)):
                st.markdown(f'**{label} — {center:g} cm⁻¹**')
                min_col, max_col = st.columns(2)
                min_col.number_input('Minimum σ (cm⁻¹)', min_value=0.0, max_value=199.99,
                                     value=0.0, step=0.5, key=f'sigma_min_{i}',
                                     on_change=reset_analysis)
                max_col.number_input('Maximum σ (cm⁻¹)', min_value=0.01, max_value=200.0,
                                     value=100.0, step=0.5, key=f'sigma_max_{i}',
                                     on_change=reset_analysis)
            try:
                sigma_constraints()
            except ValueError as exc:
                st.error(str(exc))
            st.number_input('Initial Gaussian width σ (cm⁻¹)', min_value=.1, max_value=100., value=10., step=1.,
                            key='initial_sigma', on_change=reset_analysis)
            st.number_input('QC review threshold (R²)', min_value=0.0, max_value=1.0, value=0.95, step=0.01,
                            key='review_r2_threshold', on_change=reset_analysis,
                            help='Screening threshold only; not scientific validation.')
        c1, c2 = st.columns([1, 2]);
        c1.button('← Back', on_click=change_stage, args=(0,))
        try:
            sigma_constraints()
            bounds_valid = True
        except ValueError as exc:
            bounds_valid = False
            st.error(f'Correct the sigma constraints to continue: {exc}')
        if files: c2.button('Next: Run analysis →', on_click=change_stage, args=(2,), type='primary',
                            disabled=not bounds_valid)
    else:
        st.markdown('**Exploratory 7-peak model** · fitting window 1550–1760 cm⁻¹')
        st.warning(
            'The positions and FWHM values below are a provisional transcription of handwritten notes. Check all values with the supervisor before scientific use.')
        st.number_input('Maximum peak amplitude', min_value=0.01, max_value=100.0,
                        value=1.0, step=0.1, key='amplitude_max_7', on_change=reset_analysis)
        st.subheader('7-peak baseline correction')
        st.selectbox('Baseline method (seven-peak only)',
                     ['robust_edge_fit', 'linear_endpoints'], key='baseline_mode_7',
                     on_change=reset_analysis,
                     help='Robust edge fit uses multiple points near the two ends of the fitting region. Check that these regions do not contain genuine bands.')
        if st.session_state.get('baseline_mode_7', 'robust_edge_fit') == 'robust_edge_fit':
            st.slider('Fraction of points from each spectrum edge', 0.05, 0.25,
                      value=0.12, step=0.01, key='baseline_edge_fraction_7', on_change=reset_analysis)
        st.checkbox('Compute common-window 5 vs 7 model comparison (1600–1700 cm⁻¹)',
                    value=True, key='compare_both_models', on_change=reset_analysis,
                    help='Independently fitted models evaluated against the same preprocessed absorbance points; not a model-selection validation.')

        st.checkbox(
            "Include Peak 7 (1730 cm-1)",
            value=True,
            key="include_peak_7",
            on_change=reset_analysis,
            help="Disable to fit 6 peaks instead of 7."
        )

        edited = st.data_editor(st.session_state.peak_table_7, hide_index=True,
                                num_rows='fixed', use_container_width=True, key='editable_peaks_7')
        # Edits are held in Session State; no fitting starts without validation.
        if not edited.equals(st.session_state.peak_table_7):
            st.session_state.peak_table_7 = edited.copy()
            reset_analysis()
        try:
            validate_peak_table(st.session_state.peak_table_7, 1550., 1760.)
            valid = True
            st.success('Seven-peak center and FWHM limits are valid.')
        except ValueError as exc:
            valid = False
            st.error(str(exc))
        st.button('← Back', on_click=change_stage, args=(0,))
        st.button('Next: Run analysis →', on_click=change_stage, args=(2,),
                  type='primary', disabled=not bool(st.session_state.spectra_files) or not valid)

elif stage == 2:
    st.header('Run Gaussian analysis')
    files = st.session_state.spectra_files
    if not files:
        st.warning('Please upload your spectra first.');
        st.button('← Upload data', on_click=change_stage, args=(0,))
    else:
        st.write(
            f'**{len(files)} file(s) selected.** Selected baseline correction and Gaussian fitting will be applied.')
        seven_mode = not st.session_state.model_mode.startswith('Original')
        if seven_mode: st.warning('EXPLORATORY 7-peak mode: confirm peak constraints with your supervisor.')
        st.info(
            'Press Run analysis to calculate the results. The app will not silently rerun fits while you browse your results.')
        try:
            preprocessing_options()
            if seven_mode:
                validate_peak_table(st.session_state.peak_table_7, 1550., 1760.)
            else:
                sigma_constraints()
            bounds_valid = True
        except ValueError as exc:
            bounds_valid = False
            st.error(f'Invalid peak constraints: {exc}')
        if st.button('▶ Run analysis', type='primary', disabled=not bounds_valid):
            rs = [];
            errs = []
            for filename, content in files:
                try:
                    x, y = read_spectrum(content, filename)
                    prep_opts = preprocessing_options()
                    processed = preprocess(x, y, prep_opts)
                    if seven_mode:
                        result = fit_seven(x, processed, Path(filename).stem,
                                           active_peak_table(),
                                           amplitude_max=float(st.session_state.get('amplitude_max_7', 1.)),
                                           baseline_method=st.session_state.get('baseline_mode_7', 'robust_edge_fit'),
                                           edge_fraction=float(st.session_state.get('baseline_edge_fraction_7', 0.12)))

                        table7 = validate_peak_table(
                            st.session_state.peak_table_7,
                            1550., 1760.
                        )
                        table6 = table7.iloc[:6].copy()

                        fitting_options = dict(
                            amplitude_max=float(
                                st.session_state.get(
                                    "amplitude_max_7", 1.
                                )
                            ),
                            baseline_method=st.session_state.get(
                                "baseline_mode_7",
                                "robust_edge_fit"
                            ),
                            edge_fraction=float(
                                st.session_state.get(
                                    "baseline_edge_fraction_7",
                                    0.12
                                )
                            )
                        )

                        fit6 = fit_seven(
                            x, processed, Path(filename).stem,
                            table6, **fitting_options
                        )

                        fit7 = fit_seven(
                            x, processed, Path(filename).stem,
                            table7, **fitting_options
                        )

                        result.comparison_6v7 = pd.DataFrame([
                            {
                                "Sample": Path(filename).stem,
                                "Model": "6 peaks",
                                "R2": fit6.r2,
                                "RMSE": fit6.rmse,
                                "SSE": float(
                                    np.sum(fit6.residuals ** 2)
                                )
                            },
                            {
                                "Sample": Path(filename).stem,
                                "Model": "7 peaks",
                                "R2": fit7.r2,
                                "RMSE": fit7.rmse,
                                "SSE": float(
                                    np.sum(fit7.residuals ** 2)
                                )
                            }
                        ])

                        if st.session_state.get('compare_both_models', True):
                            original_fit = fit_spectrum(x, processed, Path(filename).stem)
                            result.shared_comparison, result.shared_predictions = common_window_comparison(original_fit,
                                                                                                           result)
                    else:
                        sigma_lo, sigma_hi = sigma_constraints()
                        result = fit_spectrum(x, processed, Path(filename).stem,
                                              amplitude_max=float(st.session_state.get('amplitude_max', 1.)),
                                              sigma_min=sigma_lo, sigma_max=sigma_hi,
                                              initial_sigma=float(st.session_state.get('initial_sigma', 10.)))
                    rs.append(attach_provenance(result, x, y, processed, prep_opts))
                except Exception as e:
                    errs.append({'File': filename, 'Error': str(e)})
            st.session_state.results = rs;
            st.session_state.errors = errs
            st.session_state.run_signature = tuple((filename, len(content)) for filename, content in files)
            if rs:
                with st.spinner('Creating Excel report and all PNG/HTML figures...'):
                    generate_full_export()
                st.success(f'Analysis completed for {len(rs)} sample(s).')
                if st.session_state.export_error:
                    st.error(st.session_state.export_error)
                else:
                    st.info('The complete results ZIP is ready, including the Excel workbook and all charts.')
            if errs: st.error(f'{len(errs)} file(s) failed. See details below.')
        if st.session_state.errors: st.dataframe(pd.DataFrame(st.session_state.errors), hide_index=True,
                                                 use_container_width=True)
        if st.session_state.results: st.button('Next: View results →', on_click=change_stage, args=(3,), type='primary')

elif stage == 3:
    st.header('Review analysis results')
    results = st.session_state.results
    if not results:
        st.warning('No results yet. Run analysis in Step 3 first.');
        st.button('← Run analysis', on_click=change_stage, args=(2,))
    else:
        st.success(f'{len(results)} analyzed sample(s).')
        seven_mode = not st.session_state.model_mode.startswith('Original')
        sm = seven_summary_df(results) if seven_mode else summary_frame(results)
        st.dataframe(sm.style.format(precision=4), hide_index=True, use_container_width=True)
        if seven_mode:
            quality = pd.concat([seven_peak_diagnostics(item) for item in results], ignore_index=True)
            flagged = quality[(quality['Flags'] != '') | (quality['Sample-level flag'] != '')]
            if not flagged.empty:
                st.warning(
                    f'{len(flagged)} component-level diagnostic rows need review (heuristic, not validated pass/fail).')
                with st.expander('7-peak diagnostics: centers, widths and small areas'):
                    st.dataframe(flagged, hide_index=True, use_container_width=True)
            compare_rows = [r.shared_comparison for r in results if hasattr(r, 'shared_comparison')]
            if compare_rows:
                st.subheader('Shared-window comparison: 1600–1700 cm⁻¹')
                st.caption(
                    'Both predictions scored against the SAME measured points. Each model was independently fitted over its own region; this comparison alone does not validate either method.')
                st.dataframe(pd.concat(compare_rows, ignore_index=True), hide_index=True, use_container_width=True)
        flags = [] if seven_mode else qc_records(results, export_settings())
        flagged = [(r.sample, notes) for r, notes in flags if notes]
        if flagged:
            st.warning(f'{len(flagged)} sample(s) flagged for review; see Quality Review sheet in the Excel report.')
            with st.expander('Quality review details'):
                st.dataframe(pd.DataFrame([{'Sample': name, 'Notes': '; '.join(notes)} for name, notes in flagged]),
                             hide_index=True)
        st.subheader('Compare samples')
        if seven_mode:
            st.bar_chart(sm.set_index('Sample')[[c for c in sm.columns if 'relative area' in c]])
        else:
            st.plotly_chart(comparison_plot(results), use_container_width=True)
        st.subheader('Inspect an individual spectrum')
        selected = st.selectbox('Choose sample', list(range(len(results))), format_func=lambda i: results[i].sample)
        r = results[selected]
        a, b, c = st.columns(3);
        a.metric('R²', f'{r.r2:.4f}');
        b.metric('RMSE', f'{r.rmse:.5f}');
        c.metric('Data points', str(len(r.x)))
        names = list(r.names) if seven_mode else list(LABELS)
        visible = st.multiselect('Show Gaussian components', names, default=names)
        st.plotly_chart(plot_seven(r, visible) if seven_mode else plot_spectrum(r, visible), use_container_width=True)
        with st.expander('Residual plot', expanded=True):
            fig = go.Figure();
            fig.add_scatter(x=r.x, y=r.residuals, name='Residual', line=dict(color='#22a4af'))
            fig.add_hline(y=0, line_dash='dash');
            fig.update_xaxes(autorange='reversed', title='Wavenumber (cm⁻¹)');
            fig.update_yaxes(title='Residual');
            fig.update_layout(height=250, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        with st.expander('Peak parameters and fitted data'):
            st.dataframe(r.parameters_table().style.format(precision=5), hide_index=True, use_container_width=True)
            st.dataframe(r.spectrum_table().head(30), hide_index=True, use_container_width=True)
        st.warning(
            'Component percentages are relative fitted peak areas, not validated secondary-structure proportions. Evaluate residuals and model assumptions.')
        if st.session_state.export_archive:
            st.download_button('⬇ Download complete results (Excel + PNG + HTML + CSV/TXT)',
                               data=st.session_state.export_archive, file_name='FTIR_Analysis_Results.zip',
                               mime='application/zip', type='primary')
        st.button('Next: Download everything →', on_click=change_stage, args=(4,))

elif stage == 4:
    st.header('Download complete analysis package')
    results = st.session_state.results
    if not results:
        st.warning('No fitted results yet. Upload spectra and run analysis first.');
        st.button('← Upload data', on_click=change_stage, args=(0,))
    else:
        st.write(
            f'**{len(results)} analyzed samples.** Your complete research package is generated automatically from the uploaded raw spectra.')
        st.markdown(
            '**Included:** Excel, PDF with all PNG charts, baseline-corrected TXT, separate raw/preprocessed full-spectrum TXT and per-sample processing settings. Both models also export interactive HTML and fitted tables.')
        st.warning(
            'Instrument-grade Advanced ATR correction is NOT implemented. If simplified ATR scaling was selected, it is exploratory; inspect the recorded preprocessing settings.')
        if not st.session_state.export_archive and not st.session_state.export_error:
            with st.spinner('Generating complete export...'):
                generate_full_export()
        if st.session_state.export_error:
            st.error(st.session_state.export_error)
            st.button('Try generating ZIP again', on_click=generate_full_export)
        if st.session_state.export_archive:
            archive = st.session_state.export_archive
            st.download_button('⬇ Download complete results ZIP', data=archive,
                               file_name='FTIR_Analysis_Results.zip', mime='application/zip', type='primary')
            with zipfile.ZipFile(BytesIO(archive)) as packaged:
                names = packaged.namelist()
            png_count = sum(n.lower().endswith('.png') for n in names)
            xlsx_count = sum(n.lower().endswith('.xlsx') for n in names)
            pdf_count = sum(n.lower().endswith('.pdf') for n in names)
            st.success(
                f'ZIP ready: {len(names)} files · {xlsx_count} Excel · {pdf_count} PDF · {png_count} PNG figures · {len(archive) / 1024 / 1024:.1f} MB')

st.divider()
st.caption(
    'Research tool based on the supplied notebook, which credits anastasia-ragulskaya/FTIR_code. Verify original license before redistributing adapted code. No structure assignments are independently validated.')
