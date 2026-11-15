# FTIR Analysis Studio — Guided workflow (V3)
**Without download the app, you can use this link:** https://ftir-analysis-studio-wrvgqyukb3sajjxbibckj8.streamlit.app/  
**Upload spectra → Configure model → Run analysis → Review results → Download complete ZIP**.

## Launch (Windows / PyCharm)

1. Unzip this project and open the `ftir_analysis_studio` directory in PyCharm.
2. Open the built-in Terminal (with your Python virtual environment active).
3. Install the dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Start the application:

   ```powershell
   python -m streamlit run app.py
   ```

5. Open the local URL shown in the terminal (usually http://localhost:8501).

## Workflow

- **1 · Upload data:** Choose original `.txt` or `.csv` spectra, 2 numeric columns (wavenumber, absorbance); headers allowed. Upload multiple files to batch-process.
- **2 · Configure:** Leave the original notebook's model settings in place or adjust advanced sigma/amplitude bounds.
- **3 · Run analysis:** Explicitly fit all uploaded files and review any per-file errors.
- **4 · View results:** Explore summary, interactive spectral fits, residual plots, Gaussian parameters and comparisons.
- **5 · Download ZIP:** Download **one ZIP** with CSV/TXT per sample, summary, model settings and (optionally) Excel, PNG, and self-contained interactive HTML.

> **Important:** `data/Example_previous_study_summary.xlsx` is a previous-study summary for reference, **not** the raw spectra needed to fit a new measurement. The real original spectra must be uploaded to obtain experimental curves and fitted parameters.

## Analysis model and research limitations

The Python core retains the model from the supplied notebook: 1600–1700 cm⁻¹ Amide I, linear baseline from endpoints, five Gaussian functions at fixed positions 1652, 1630, 1679, 1671 and 1645 cm⁻¹, nonnegative amplitudes and sigmas, and relative areas from amplitude × sigma × sqrt(2π). The fixed-center model may not be appropriate for all samples or solvents. **Relative areas are not independently validated biological secondary-structure percentages.** Always inspect residuals and scientific suitability before interpretation.

The user's supplied notebook attributes the method to https://github.com/anastasia-ragulskaya/FTIR_code. Check the upstream license and conditions before publishing adaptations.

## Tests

```powershell
python -m pytest -q
```

## V4: file persistence fix

The file uploader now stays visible in the sidebar on every workflow step.
On upload, the app copies the spectrum bytes into `st.session_state.spectra_files`,
so Streamlit widget cleanup on page changes cannot erase the selected data.
It also accepts ZIP archives containing TXT/CSV spectra, such as `Re__FTIR.zip`.
When the upload selection changes, previous fits are invalidated to prevent stale results.

**Recommended launch:** `python -m streamlit run app.py`.
**Tests:** `python -m pytest -q`.

## Expanded reporting (V5)

On **Step 5 — Download ZIP**, the archive now includes:

- `summary/FTIR_Study_Report.xlsx`: a single workbook with a study dashboard, summary, all Gaussian peak parameters, settings and one fitted-spectrum sheet per sample. If the optional rich-workbook engine is absent, the existing basic Excel workbook is exported instead and a note is included.
- `charts/composition_stacked_bar.png`: five-component relative-area comparison across samples.
- `charts/beta_sheet_grouped_bar.png`: side-by-side fitted beta-sheet components across samples.
- `charts/fit_quality_R2_RMSE.png`: R² and RMSE across samples.
- `samples/<sample>/gaussian_fit.png`, `fit_residuals.png`, `baseline_correction.png` and `component_area_bar.png`.
- Per-sample fitted spectra, peak parameters (CSV/TXT), HTML interactive plots and analysis settings.

All numbers and charts come **only from the uploaded raw TXT/CSV data**. Existing reference Excel workbooks and prior PNGs are never passed into the fitting model.

### Optional polished Excel workbook

The formatted XLSX is produced by `artifact_tool_v2` when this optional package is available. Because this engine may not be available on all Windows Python installations, the app automatically falls back to the original plain but complete Excel export. All PNG graphs and CSV/TXT data remain available in either case. The fallback is noted in `summary/EXCEL_FORMATTING_NOTE.txt`.

## Automatic export (V6)
After **Run analysis**, the complete study archive is prepared automatically.
Open **View results** or **Download ZIP** and click the download button.
All Excel, PNG, interactive HTML, CSV/TXT and settings files are included by default.
Newly uploaded spectra invalidate the previous archive so old and new analyses cannot be mixed.
The Excel report uses `artifact_tool` if it is installed; otherwise the application
exports a basic Excel workbook with all fitted values via the existing compatibility fallback.\n\n## Attribution\n\nThis project was inspired by and adapted from the work of **N. Labajová**, whose FTIR analysis code was itself adapted from the work of **Anastasia Ragulskaya**.\n\n- N. Labajová: [FTIR](https://github.com/NLabajova/FTIR)\n- Anastasia Ragulskaya: [FTIR_code](https://github.com/anastasia-ragulskaya/FTIR_code)\n\nRedistribution of adapted source code is subject to the licensing terms of the original projects.\n