# FTIR Analysis Studio

**Interactive FTIR spectrum processing, constrained Gaussian deconvolution, fit diagnostics, and reproducible reporting.**

> **Research prototype — scientific validation pending.** This application is intended to support exploratory analysis and supervisor review. Relative Gaussian peak areas are **not independently validated percentages of protein secondary structures**. The seven-peak model, its bounds, and any structural assignments require experimental justification.

## Overview

FTIR Analysis Studio is a local Python/Streamlit application for processing FTIR spectra from TXT or CSV files (or a ZIP archive containing them). It helps researchers inspect spectral preprocessing, fit Gaussian peak models, evaluate fit quality, compare samples, and download numerical data and figures in one results archive.

The application was developed and tested using FTIR spectra of α-synuclein samples. **Experimental datasets are not distributed in this repository.**

## Features

- **Guided workflow:** Upload data → Configure analysis → Run analysis → View results → Download ZIP.
- **Input validation:** Read two-column wavenumber/absorbance spectra; batch-import TXT/CSV or ZIP.
- **Preprocessing:** Optional Savitzky–Golay smoothing, optional *exploratory* wavenumber-dependent ATR scaling, and baseline correction. Original and processed spectra are kept separately in the export.
- **Two core fitting methods:**
  - **Reference five-peak model:** fixed centers at 1652, 1630, 1679, 1671 and 1645 cm⁻¹, fitted on 1600–1700 cm⁻¹; adjustable σ constraints; original endpoint baseline.
  - **Exploratory seven-peak model:** initial centers near 1585, 1615, 1630, 1654, 1672, 1690 and 1730 cm⁻¹, fitted on 1550–1760 cm⁻¹; adjustable center and FWHM bounds; selectable baseline method.
- **Fit review:** Interactive Gaussian components and overall fit, residuals, R², RMSE, fitted peak parameters and relative integrated areas.
- **Quality diagnostics:** Warnings when a center/FWHM lies near its allowed limit or a component has negligible fitted area. These warnings require scientific assessment; they are not automatic rejection criteria.
- **Model comparisons:** Optional five- versus seven-peak predictions over common observed points (1600–1700 cm⁻¹). If the local code has the newer six-versus-seven component comparison enabled, its numerical output is additionally exported. These are exploratory comparisons, not model validation.
- **Batch export:** Excel tables, PDF report with figures, PNG charts, interactive HTML plots, TXT/CSV numeric files, and JSON analysis settings, bundled into one ZIP.

## Requirements and installation

Python 3.12 is recommended for the environment used in development. Install from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open the **Local URL** printed in the terminal (typically `http://localhost:8501`). On macOS/Linux, activate the virtual environment with `source .venv/bin/activate` instead.

## Quick start

1. **Upload data:** Select TXT/CSV spectra or a ZIP containing those files. Inputs should contain wavenumber (cm⁻¹) and absorbance as numerical columns.
2. **Configure:** Choose the five-peak reference method or exploratory seven-peak method. For the seven-peak model, inspect the center intervals, FWHM intervals, and baseline options. Do not assume defaults are validated.
3. **Run analysis:** Calculate fitted components and diagnostics for the uploaded samples.
4. **Review results:** Examine original/processed spectra, fitted curves, residuals, R²/RMSE and parameter warnings. Inspect low-area or boundary-limited components carefully.
5. **Download ZIP:** Export the full analysis record, figures and numerical results.

### Important note on peak width

For a Gaussian, **FWHM ≈ 2.35482 × σ**. Restricting FWHM or σ restricts *peak width*, **not directly its integrated area**. The seven-peak model's center and FWHM presets come from provisional supervisor notes and have **not** been validated as physical constraints. A component near zero area is not evidence that the associated physical structure is absent.

### Preprocessing and ATR correction

- **Baseline correction** removes an estimated spectral background. The exploratory seven-peak mode offers `linear_endpoints` and `robust_edge_fit` (fitted using the edges of the selected window); the edge fraction can be adjusted. Spectral bands near the edges can bias either estimate.
- **Simple ATR scaling** is an **optional wavenumber-only approximation**, **off by default**. It is **not advanced or instrument-grade ATR correction** and must not be represented as such.
- **Instrument-specific advanced ATR correction is NOT implemented.** Reproducing it requires a documented instrument/software algorithm and suitable measurement metadata (e.g., crystal, angle, optical assumptions).
- Optional smoothing may change peak width and area. Any use of preprocessing should be recorded and justified.
- Water exposure and drying are sample-preparation details, **not automatically inferable** from the spectral data.

For transparency, exported TXT files distinguish the input spectrum, the optionally preprocessed spectrum, and the baseline-corrected fitting region. Check `analysis_settings.json` and per-sample preprocessing settings to identify what was applied.

## Exported results

The archive typically contains:

| Item | Purpose |
| --- | --- |
| `summary/FTIR_Study_Report.xlsx` | Study summary, peak parameters, fit metrics and relevant diagnostic worksheets |
| `FTIR_Complete_Analysis_Report.pdf` | Consolidated report containing exported figures |
| `summary/*.csv` | Summary and available model/peak comparison tables |
| `samples/.../fitted_spectrum.csv` | Observed, baseline-corrected, fitted and residual values |
| `samples/.../peak_parameters.csv` | Fitted peak centers, widths, amplitudes and relative areas |
| `samples/.../preprocessing_full_spectrum.txt` | Original and optionally processed full-spectrum values |
| `samples/.../baseline_corrected_region.txt` | Data after fitting-window baseline subtraction |
| `samples/.../*.png` and `charts/*.png` | Gaussian fits, preprocessing, residual and comparison plots |
| `samples/.../*.html` | Interactive fit figures, when enabled |
| `analysis_settings.json` | Model and processing configuration used for reproducibility |

Exact filenames and sheets can differ between selected fitting methods and export options. Missing or failed spectra should be reviewed before interpreting a batch summary.

## Model interpretation and limitations

The five-peak and seven-peak models were originally designed for **different fitting windows** (1600–1700 versus 1550–1760 cm⁻¹) and can use **different baseline methods**. Consequently, their overall R² values should **not** be treated as directly comparable. Common-window metrics can support inspection but are not an independent validation of a preferred model. Models with more parameters also require consideration of complexity, parameter stability and experimental plausibility.

The peak near **1730 cm⁻¹** in the exploratory model has shown negligible fitted area in the investigated samples; whether it should be retained is an open methodological question for the supervisor. The program must not silently change scientific assumptions to maximize R².

**Before publication or biological interpretation**, confirm peak assignments, center/FWHM bounds, preprocessing order, ATR protocol and the interpretation of fitted areas with the supervisor. Review residuals and fit-bound warnings for each sample.

## Tests

Run automated tests from the project directory:

```powershell
python -m pytest -q
```

Automated tests check software behavior and exports; they **do not constitute chemical or biological validation**.

## Repository organization

```text
FTIR-Analysis-Studio/
├── app.py                   # Streamlit interface and workflow
├── ftir_core.py             # Reference five-peak computations
├── advanced_pipeline.py     # Exploratory constrained fitting
├── baseline_review.py       # Baseline methods and fit diagnostics
├── preprocessing.py         # Optional spectral preprocessing
├── report_exports.py        # Core figure/export utilities
├── enhanced_reports.py      # Excel/PDF reporting helpers
├── advanced_export.py       # Exploratory-model exports
├── requirements.txt
├── tests/
└── README.md
```

Do not commit `.venv/`, `.idea/`, `__pycache__/`, raw experimental data, private spreadsheets, generated results or secrets. These should be excluded via `.gitignore`. **Ignoring files does not remove them from earlier Git commits.**

## Attribution and sharing

The notebook used as a starting point credits [anastasia-ragulskaya/FTIR_code](https://github.com/anastasia-ragulskaya/FTIR_code). Review the upstream license and redistribution terms before making this adapted project public. Keep this repository **private** until the supervisor approves sharing both the code and the experimental methodology.

## Planned scientific validation

- Confirm the seven-peak model and whether six components are more appropriate for the studied samples.
- Agree on physically justified center and FWHM ranges.
- Obtain an instrument-specific ATR correction protocol and validated processing order.
- Examine parameter stability, residuals, uncertainty and fit-bound sensitivity.
- Document sample preparation and measurement metadata consistently.
