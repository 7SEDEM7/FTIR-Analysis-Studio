"""Verify audit files survive both complete report pipelines."""
import ast
from io import BytesIO
from pathlib import Path
import zipfile
import numpy as np
from preprocessing import preprocess, attach_provenance
from ftir_core import fit_spectrum, gaussian_components
from advanced_pipeline import fit_seven, peak_table_default
from advanced_export import build_seven_zip


def test_seven_with_preprocessing_audit_export():
    x=np.linspace(1550,1760,250)
    y=0.1*np.exp(-.5*((x-1650)/14)**2)+0.003
    settings={'atr_mode':'simple_wavenumber_scaling','reference_wavenumber':1650.0}
    result=fit_seven(x,preprocess(x,y,settings),'synthetic',peak_table_default())
    attach_provenance(result,x,y,preprocess(x,y,settings),settings)
    archive=build_seven_zip([result],{'model':'seven exploratory','spectral_window_cm-1':[1550,1760],
                                     'preprocessing':result.preprocess_settings,'review_r2_threshold':0.95})
    with zipfile.ZipFile(BytesIO(archive)) as z:
        names=z.namelist()
        assert any(n.endswith('preprocessing_full_spectrum.txt') for n in names)
        assert any(n.endswith('preprocessing_settings.json') for n in names)
        assert any(n.endswith('preprocessing_full_spectrum.png') for n in names)
        assert 'FTIR_Complete_Analysis_Report.pdf' in names


def test_default_no_atr_changes_original_fit():
    x=np.linspace(1600,1700,208)
    y=gaussian_components(x,[.1,.02,.015,.03,.01,12,10,8,8,13]).sum(axis=0)+0.001
    orig=fit_spectrum(x,y,'original')
    again=fit_spectrum(x,preprocess(x,y,{}),'default')
    assert np.allclose(orig.parameters,again.parameters)
