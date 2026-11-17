"""Exploratory constrained seven-peak FTIR fitting; not a validated structural assignment.

ATR preprocessing is separate and optional, and an instrument-specific advanced ATR
correction is not implemented. Baseline fitting is explicitly configurable.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from baseline_review import baseline_for_window

FWHM_FACTOR = 2 * np.sqrt(2 * np.log(2))
# Transcribed from photographed supervisor notes; all limits require confirmation.
DEFAULT_PEAKS = (
    ("Peak 1 (provisional)", 1585., 1570., 1600., 30., 45.),
    ("Peak 2 (provisional)", 1615., 1610., 1620., 30., 45.),
    ("Peak 3 (provisional)", 1630., 1620., 1633., 30., 40.),
    ("Peak 4 (provisional)", 1654., 1652., 1655., 30., 45.),
    ("Peak 5 (provisional)", 1672., 1665., 1680., 20., 32.),
    ("Peak 6 (provisional)", 1690., 1680., 1695., 20., 30.),
    ("Peak 7 (provisional)", 1730., 1725., 1740., 20., 30.),
)


def peak_table_default():
    return pd.DataFrame(DEFAULT_PEAKS, columns=[
        "Component", "Initial center (cm-1)", "Center min (cm-1)",
        "Center max (cm-1)", "Initial FWHM (cm-1)", "FWHM max (cm-1)"]).assign(**{
        "FWHM min (cm-1)": 2.0})[["Component", "Initial center (cm-1)",
                                  "Center min (cm-1)", "Center max (cm-1)", "Initial FWHM (cm-1)",
                                  "FWHM min (cm-1)", "FWHM max (cm-1)"]]


def validate_peak_table(table, low=1550., high=1760.):
    if len(table) not in (6, 7):
        raise ValueError("The model requires 6 or 7 peaks.")
    cols = ["Initial center (cm-1)", "Center min (cm-1)", "Center max (cm-1)",
            "Initial FWHM (cm-1)", "FWHM min (cm-1)", "FWHM max (cm-1)"]
    t = table.copy().reset_index(drop=True)
    try:
        for col in cols:
            t[col] = pd.to_numeric(t[col], errors="raise").astype(float)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Peak settings must be numeric: {exc}") from exc
    v = t[cols].to_numpy()
    if not np.isfinite(v).all():
        raise ValueError("Peak settings contain non-finite numbers.")
    if low >= high or not np.isfinite([low, high]).all():
        raise ValueError("Invalid analysis window.")
    for i, row in t.iterrows():
        c, cmin, cmax, f, fmin, fmax = [float(row[k]) for k in cols]
        if not (low <= cmin < c < cmax <= high):
            raise ValueError(
                f"Peak {i + 1}: require window min <= center min < initial center < center max <= window max.")
        if not (0 < fmin < f < fmax):
            raise ValueError(f"Peak {i + 1}: require 0 < FWHM min < initial FWHM < FWHM max.")
    return t


def components(x, amplitudes, centers, fwhm):
    x = np.asarray(x, dtype=float)
    sigma = np.asarray(fwhm, dtype=float) / FWHM_FACTOR
    return np.asarray(amplitudes)[:, None] * np.exp(
        -.5 * ((x[None, :] - np.asarray(centers)[:, None]) / sigma[:, None]) ** 2)


@dataclass
class AdvancedResult:
    sample: str
    x: np.ndarray
    original: np.ndarray
    baseline: np.ndarray
    corrected: np.ndarray
    fitted: np.ndarray
    residuals: np.ndarray
    amplitudes: np.ndarray
    centers: np.ndarray
    fwhm: np.ndarray
    areas: np.ndarray
    percentages: np.ndarray
    r2: float
    rmse: float
    names: tuple
    peak_settings: pd.DataFrame

    @property
    def components(self):
        return components(self.x, self.amplitudes, self.centers, self.fwhm)

    def spectrum_table(self):
        d = pd.DataFrame({"Wavenumber (cm-1)": self.x,
                          "Original absorbance": self.original,
                          "Baseline": self.baseline,
                          "Baseline-corrected absorbance": self.corrected,
                          "Total fit": self.fitted, "Residual": self.residuals})
        for i, name in enumerate(self.names):
            d[name] = self.components[i]
        return d

    def parameters_table(self):
        d = pd.DataFrame({"Component": self.names, "Center (cm-1)": self.centers,
                          "Amplitude": self.amplitudes, "FWHM (cm-1)": self.fwhm,
                          "Sigma (cm-1)": self.fwhm / FWHM_FACTOR, "Gaussian area": self.areas,
                          "Relative area (%)": self.percentages})
        return d


def fit_seven(x, y, sample, peak_table, low=1550., high=1760., amplitude_max=1.,
              baseline_method="linear_endpoints", edge_fraction=0.12):
    t = validate_peak_table(peak_table, low, high)
    n = len(t)
    if not np.isfinite(amplitude_max) or amplitude_max <= 0:
        raise ValueError("Maximum amplitude must be positive.")
    x, y = np.asarray(x, float), np.asarray(y, float)
    mask = np.isfinite(x) & np.isfinite(y) & (x >= low) & (x <= high)
    xa, ya = x[mask], y[mask]
    order = np.argsort(xa)
    xa, ya = xa[order], ya[order]
    if len(xa) < 30 or len(np.unique(xa)) != len(xa):
        raise ValueError("Need at least 30 distinct wavenumbers within the 7-peak window.")
    # Baseline selected explicitly; ATR preprocessing, if any, is upstream.
    baseline = baseline_for_window(xa, ya, method=baseline_method, edge_fraction=edge_fraction)
    corrected = ya - baseline
    c0 = t["Initial center (cm-1)"].to_numpy()
    f0 = t["Initial FWHM (cm-1)"].to_numpy()

    lower = np.r_[
        np.zeros(n),
        t["Center min (cm-1)"].to_numpy(),
        t["FWHM min (cm-1)"].to_numpy()
    ].astype(float)

    upper = np.r_[
        np.full(n, amplitude_max),
        t["Center max (cm-1)"].to_numpy(),
        t["FWHM max (cm-1)"].to_numpy()
    ].astype(float)

    amps = np.clip(
        np.interp(c0, xa, corrected),
        1e-6,
        amplitude_max * 0.9
    )

    p0 = np.r_[amps, c0, f0]

    def residuals(p):
        return (
                components(
                    xa,
                    p[:n],
                    p[n:2 * n],
                    p[2 * n:3 * n]
                ).sum(axis=0) - corrected
        )

    fit = least_squares(
        residuals,
        p0,
        bounds=(lower, upper),
        max_nfev=25000,
        ftol=1e-10,
        xtol=1e-10,
        gtol=1e-10
    )

    if not fit.success:
        raise RuntimeError(
            f"Optimizer did not converge: {fit.message}"
        )

    a = fit.x[:n]
    c = fit.x[n:2 * n]
    f = fit.x[2 * n:3 * n]

    fitted = components(xa, a, c, f).sum(axis=0)
    resid = corrected - fitted
    areas = a * (f / FWHM_FACTOR) * np.sqrt(2 * np.pi)
    if areas.sum() <= 0:
        raise ValueError("All fitted peak areas are zero.")
    var = np.sum((corrected - corrected.mean()) ** 2)
    r2 = 1 - np.sum(resid ** 2) / var if var > 0 else np.nan
    return AdvancedResult(sample, xa, ya, baseline, corrected, fitted, resid,
                          a, c, f, areas, areas / areas.sum() * 100, float(r2),
                          float(np.sqrt(np.mean(resid ** 2))), tuple(t["Component"]), t)
