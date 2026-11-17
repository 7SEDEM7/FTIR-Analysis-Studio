from io import BytesIO
import zipfile
import numpy as np
import pytest
from openpyxl import load_workbook
from advanced_pipeline import peak_table_default, validate_peak_table, fit_seven, components
from advanced_export import build_seven_zip


def test_seven_settings_validation():
    t=peak_table_default()
    assert len(validate_peak_table(t)) == 7
    invalid=t.copy()
    invalid.loc[0,'FWHM min (cm-1)']=60
    with pytest.raises(ValueError, match='FWHM'):
        validate_peak_table(invalid)
    invalid=t.copy()
    invalid.loc[2,'Center max (cm-1)']=1620
    with pytest.raises(ValueError, match='center'):
        validate_peak_table(invalid)


def test_seven_peak_fit_and_complete_export():
    t=peak_table_default()
    x=np.linspace(1550,1760,440)
    y=components(x,[.03,.04,.07,.06,.04,.03,.025],
           t['Initial center (cm-1)'],t['Initial FWHM (cm-1)']).sum(axis=0)
    y+=.002+.00001*(x-1550)
    r=fit_seven(x,y,'Synthetic',t)
    assert r.r2 > .99
    assert np.all(r.fwhm >= t['FWHM min (cm-1)'].to_numpy()-1e-8)
    assert np.all(r.fwhm <= t['FWHM max (cm-1)'].to_numpy()+1e-8)
    settings={'spectral_window_cm-1':[1550,1760],
              'model':'provisional constrained seven-Gaussian',
              'atr_correction':'NOT PERFORMED', 'review_r2_threshold':.95,
              'peak_configuration':t.to_dict('records')}
    out=build_seven_zip([r],settings)
    with zipfile.ZipFile(BytesIO(out)) as z:
        assert z.testzip() is None
        names=z.namelist()
        assert 'summary/FTIR_Study_Report.xlsx' in names
        assert 'FTIR_Complete_Analysis_Report.pdf' in names
        assert any('baseline_corrected_region.txt' in n for n in names)
        assert len([n for n in names if n.endswith('.png')])==5
        assert z.read('FTIR_Complete_Analysis_Report.pdf').startswith(b'%PDF')
        w=load_workbook(BytesIO(z.read('summary/FTIR_Study_Report.xlsx')))
        assert 'Peak Configuration' in w.sheetnames
        assert 'Quality Review' in w.sheetnames
