"""Scientific processing of FTIR Amide I data; based on the supplied notebook.

Centers are fixed according to the original D2O-oriented five-Gaussian model.
Relative fitted areas are NOT independently validated structural percentages.
"""
from dataclasses import dataclass
from io import BytesIO
import re
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

LABELS = ('Alpha helix', 'Beta sheet 1630', 'Beta sheet 1679', 'Loop', 'Disordered')
CENTERS = np.array([1652., 1630., 1679., 1671., 1645.])
COLORS = ('#2b79b9','#f28e2b','#2ca02c','#d62728','#9467bd')

@dataclass
class FitResult:
    sample: str
    x: np.ndarray
    original: np.ndarray
    baseline: np.ndarray
    corrected: np.ndarray
    fitted: np.ndarray
    residuals: np.ndarray
    parameters: np.ndarray
    standard_errors: np.ndarray
    areas: np.ndarray
    percentages: np.ndarray
    r2: float
    rmse: float

    @property
    def components(self):
        return gaussian_components(self.x, self.parameters)

    def parameters_table(self):
        return pd.DataFrame({'Component': LABELS, 'Center (cm-1)': CENTERS,
            'Amplitude': self.parameters[:5], 'Amplitude SE': self.standard_errors[:5],
            'Sigma (cm-1)': self.parameters[5:], 'Sigma SE': self.standard_errors[5:],
            'Gaussian area': self.areas, 'Relative area (%)': self.percentages})

    def spectrum_table(self):
        out = pd.DataFrame({'Wavenumber (cm-1)': self.x, 'Original absorbance': self.original,
            'Baseline': self.baseline, 'Corrected absorbance': self.corrected,
            'Total fit': self.fitted, 'Residual': self.residuals})
        for label, values in zip(LABELS, self.components):
            out[label] = values
        return out


def read_spectrum(blob: bytes, filename: str = 'spectrum.txt'):
    """Read tab, semicolon, comma or whitespace separated 2-column spectra.

    Skip comment/heading lines; accept decimal commas when delimiter is not comma.
    """
    text = blob.decode('utf-8-sig', errors='replace')
    rows = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(('#', '//')):
            continue
        if '\t' in line:
            parts = line.split('\t')
        elif ';' in line:
            parts = line.split(';')
        elif ',' in line and line.count(',') == 1:
            parts = line.split(',')
        else:
            parts = re.split(r'\s+', line)
        if len(parts) < 2:
            continue
        try:
            x, y = float(parts[0].strip().replace(',', '.')), float(parts[1].strip().replace(',', '.'))
        except ValueError:
            continue  # header
        if np.isfinite(x) and np.isfinite(y):
            rows.append((x,y))
    if len(rows) < 15:
        raise ValueError(f'{filename}: at least 15 numeric wavenumber–absorbance pairs are required.')
    values = np.array(rows, dtype=float)
    if len(np.unique(values[:, 0])) != len(values):
        raise ValueError(f'{filename}: duplicate wavenumber values detected.')
    return values[:,0], values[:,1]


def linear_baseline(x, y):
    return y[0] + (y[-1]-y[0]) * (x-x[0])/(x[-1]-x[0])


def gaussian_components(x, params, centers=CENTERS):
    x = np.asarray(x, float)
    a = np.asarray(params[:5], float)
    s = np.asarray(params[5:], float)
    return a[:, None] * np.exp(-((x[None, :] - np.asarray(centers)[:, None]) ** 2)/(2*s[:,None]**2))


def fit_spectrum(x, y, sample='Sample', low=1600., high=1700., amplitude_max=1., sigma_max=100., initial_sigma=10.):
    if not 0 < amplitude_max or not 0 < sigma_max or not 0 < initial_sigma <= sigma_max:
        raise ValueError('Invalid fitting bounds or initial sigma.')
    x, y = np.asarray(x,float), np.asarray(y,float)
    mask = np.isfinite(x) & np.isfinite(y) & (x >= low) & (x <= high)
    xa, ya = x[mask], y[mask]
    order = np.argsort(xa)
    xa, ya = xa[order], ya[order]
    if len(np.unique(xa)) < 15:
        raise ValueError('At least 15 unique points are required in the Amide I range.')
    if len(np.unique(xa)) != len(xa):
        raise ValueError('Duplicate wavenumber values in the Amide I range.')
    if low > np.min(CENTERS) or high < np.max(CENTERS):
        raise ValueError('The chosen range does not cover all five fixed peak centers.')
    baseline = linear_baseline(xa, ya)
    corrected = ya - baseline
    def model(wavenumber, *p):
        return gaussian_components(wavenumber, p).sum(axis=0)
    p0 = [min(0.1, amplitude_max / 2)] * 5 + [initial_sigma] * 5
    lower = [0.] * 10
    upper = [amplitude_max]*5 + [sigma_max]*5
    params, covariance = curve_fit(model, xa, corrected, bounds=(lower,upper),p0=p0,maxfev=20000)
    fitted = model(xa,*params)
    residuals = corrected - fitted
    errors = np.sqrt(np.maximum(np.diag(covariance),0))
    areas = params[:5] * params[5:] * np.sqrt(2*np.pi)
    if areas.sum() <= 0:
        raise ValueError('The total fitted component area is zero.')
    percentages = areas / areas.sum() * 100
    total_variance = np.sum((corrected - corrected.mean()) ** 2)
    r2 = float(1 - np.sum(residuals ** 2) / total_variance) if total_variance > 0 else np.nan
    rmse = float(np.sqrt(np.mean(residuals ** 2)))
    return FitResult(sample, xa, ya, baseline, corrected, fitted, residuals, params, errors, areas, percentages, r2, rmse)


def results_excel(results):
    """Export generated analyses as a new Excel file, no input workbook is changed."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        summary = []
        for r in results:
            row = {'Sample': r.sample, 'R squared': r.r2, 'RMSE': r.rmse, 'Unique wavenumbers': len(r.x)}
            row.update({f'{label} relative area (%)': val for label, val in zip(LABELS, r.percentages)})
            summary.append(row)
        pd.DataFrame(summary).to_excel(writer, sheet_name='Summary', index=False)
        for i, r in enumerate(results,1):
            prefix = f'S{i:02d}'
            r.parameters_table().to_excel(writer, sheet_name=prefix+'_Peaks', index=False)
            r.spectrum_table().to_excel(writer, sheet_name=prefix+'_Spectrum', index=False)
    return buffer.getvalue()
