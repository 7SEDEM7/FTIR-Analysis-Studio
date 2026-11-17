"""Traceable FTIR preprocessing; never label an approximation as advanced ATR correction."""
from io import BytesIO
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def validate_options(options):
    mode = options.get("atr_mode", "none")
    if mode not in ("none", "simple_wavenumber_scaling"):
        raise ValueError("Unsupported ATR correction mode")
    ref = float(options.get("reference_wavenumber", 1650.0))
    n1 = float(options.get("crystal_refractive_index", 2.4))
    n2 = float(options.get("sample_refractive_index", 1.5))
    theta = float(options.get("incidence_angle_degrees", 45.0))
    if not np.all(np.isfinite([ref, n1, n2, theta])) or ref <= 0 or not (0 < theta < 90) or n1 <= n2 or n2 <= 0:
        raise ValueError("Invalid ATR parameters: require positive reference, n1 > n2 > 0 and 0 < angle < 90")
    if np.sin(np.deg2rad(theta)) <= n2 / n1:
        raise ValueError("No total internal reflection with these refractive indices and incidence angle")
    smoothing = bool(options.get("savgol_enabled", False))
    window = int(options.get("savgol_window", 11))
    poly = int(options.get("savgol_polynomial", 3))
    if smoothing and (window < 5 or window % 2 == 0 or not 1 <= poly < window):
        raise ValueError("Savitzky-Golay window must be odd (>=5), with 1 <= polynomial < window")
    return {"atr_mode": mode, "reference_wavenumber": ref,
            "crystal_refractive_index": n1, "sample_refractive_index": n2,
            "incidence_angle_degrees": theta, "savgol_enabled": smoothing,
            "savgol_window": window, "savgol_polynomial": poly,
            "advanced_atr_implemented": False,
            "atr_method_note": ("No ATR correction performed" if mode == "none" else
               "Exploratory wavenumber-only penetration-depth compensation; NOT advanced ATR correction. "
               "Assumes constant refractive indices, angle and contact, and ignores dispersion and optical distortions.")}


def preprocess(x, y, options):
    """Return x and processed absorbance (before downstream baseline subtraction)."""
    settings = validate_options(options)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.ndim != 1 or y.shape != x.shape or len(x) < 5 or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)) or np.any(x <= 0):
        raise ValueError("Spectrum must contain matching, finite, positive-wavenumber arrays")
    processed = y.copy()
    if settings["atr_mode"] == "simple_wavenumber_scaling":
        # Only a relative wavelength-dependence compensation: d_p proportional to 1 / nu
        # for constant n1, n2 and theta, hence A_corrected=A_raw * nu / nu_ref.
        processed = processed * (x / settings["reference_wavenumber"])
    if settings["savgol_enabled"]:
        from scipy.signal import savgol_filter
        if len(x) < settings["savgol_window"]:
            raise ValueError("Not enough points for requested smoothing window")
        order = np.argsort(x)
        smooth = savgol_filter(processed[order], settings["savgol_window"], settings["savgol_polynomial"])
        processed[order] = smooth
    return processed


def attach_provenance(result, x, raw, processed, options):
    result.preprocess_x = np.asarray(x, float).copy()
    result.preprocess_raw = np.asarray(raw, float).copy()
    result.preprocess_processed = np.asarray(processed, float).copy()
    result.preprocess_settings = validate_options(options)
    return result


def preparation_table(result):
    return pd.DataFrame({"Wavenumber (cm-1)":result.preprocess_x,
                         "Raw measured absorbance": result.preprocess_raw,
                         "After optional preprocessing (before baseline)":result.preprocess_processed})


def preparation_png(result):
    fig, ax = plt.subplots(figsize=(10,5))
    ax.plot(result.preprocess_x, result.preprocess_raw, label="Raw measured", lw=1)
    if result.preprocess_settings["atr_mode"] != "none" or result.preprocess_settings["savgol_enabled"]:
        ax.plot(result.preprocess_x, result.preprocess_processed, label="Preprocessed (exploratory)", lw=1)
    ax.set(xlabel="Wavenumber (cm$^{-1}$)", ylabel="Absorbance", title=f"{result.sample} — full-spectrum preprocessing")
    ax.invert_xaxis(); ax.legend(); ax.grid(alpha=.15); fig.tight_layout()
    out=BytesIO();fig.savefig(out,format="png",dpi=180);plt.close(fig)
    return out.getvalue()


def save_preprocessing_to_archive(archive, folder, result):
    if not hasattr(result, "preprocess_x"):
        return
    archive.writestr(folder+"preprocessing_full_spectrum.txt", preparation_table(result).to_csv(index=False, sep="\t", float_format="%.10g"))
    archive.writestr(folder+"preprocessing_settings.json", json.dumps(result.preprocess_settings, indent=2))
    archive.writestr(folder+"preprocessing_full_spectrum.png", preparation_png(result))
