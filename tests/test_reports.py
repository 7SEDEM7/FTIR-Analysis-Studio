"""Smoke test for one-click report outputs without starting Streamlit UI."""
import ast
from pathlib import Path
import zipfile
from io import BytesIO

import numpy as np
from openpyxl import load_workbook
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from ftir_core import fit_spectrum, read_spectrum, gaussian_components, results_excel, LABELS, COLORS, CENTERS
from enhanced_reports import build_excel, build_pdf, qc_records
from report_exports import residual_png, preprocessing_png, component_bars_png, stacked_comparison_png, \
    grouped_beta_png, fit_quality_png
import matplotlib.pyplot as plt
import pandas as pd
import plotly.graph_objects as go
import json, re

# Extract pure functions from app.py to avoid initializing Streamlit during tests
app_path = Path(__file__).parents[1] / 'app.py'
module = ast.parse(app_path.read_text(encoding='utf-8'))
functions = ['png_spectrum', 'safe_name', 'summary_frame', 'plot_spectrum', 'make_zip']
program = ast.Module(body=[n for n in module.body if isinstance(n, ast.FunctionDef) and n.name in functions],
                     type_ignores=[])
exec(compile(program, str(app_path), 'exec'), globals())


def test_complete_reports_from_raw_data():
    rng = np.linspace(1600, 1700, 208)
    signal = gaussian_components(rng, [0.06, 0.02, 0.03, 0.01, 0.02, 12, 9, 10, 8, 13]).sum(axis=0)
    # linear baseline ensures correction produces a meaningful actual fit
    raw = signal + 0.002 + 0.00001 * (rng - 1600)
    r = fit_spectrum(rng, raw, 'Synthetic_test')
    settings = {'model': 'five fixed-center Gaussians', 'maximum_amplitude': 1.0, 'maximum_sigma_cm-1': 100.0,
                'review_r2_threshold': 0.95}
    data = make_zip([r], settings)
    with zipfile.ZipFile(BytesIO(data)) as z:
        names = z.namelist()
        assert 'summary/FTIR_Study_Report.xlsx' in names
        assert 'FTIR_Complete_Analysis_Report.pdf' in names
        assert 'summary/quality_review.csv' in names
        assert sum(n.endswith('.png') for n in names) == 7
        wb = load_workbook(BytesIO(z.read('summary/FTIR_Study_Report.xlsx')), read_only=False)
        assert {'Dashboard', 'Summary', 'Quality Review', 'Method & Notes'} <= set(wb.sheetnames)
        assert len(wb['Dashboard']._images) == 3
        assert len(wb['Quality Review']._charts) == 1
        assert z.read('FTIR_Complete_Analysis_Report.pdf').startswith(b'%PDF')
