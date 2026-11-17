import numpy as np
import pytest
from baseline_review import baseline_for_window, seven_peak_diagnostics, common_window_comparison
from advanced_pipeline import fit_seven, peak_table_default, components
from ftir_core import fit_spectrum


def test_edge_baseline_outlier_resistance():
    x=np.linspace(1550,1760,440)
    truth=.008 + .000025*(x-1550)
    y=truth.copy()
    y[0]+=.035; y[-1]+=.022
    robust=baseline_for_window(x,y,'robust_edge_fit')
    endpoint=baseline_for_window(x,y,'linear_endpoints')
    assert np.mean(np.abs(robust-truth)) < np.mean(np.abs(endpoint-truth))/10
    with pytest.raises(ValueError): baseline_for_window(x,y,'robust_edge_fit',0.5)


def test_diagnostics_and_overlap():
    t=peak_table_default()
    x=np.linspace(1550,1760,440)
    y=components(x,[.015,.03,.04,.05,.03,.02,0.000001],
                t['Initial center (cm-1)'],t['Initial FWHM (cm-1)']).sum(axis=0)
    y=y+.005+0.00002*(x-1550)
    r7=fit_seven(x,y,'Synthetic',t,baseline_method='robust_edge_fit')
    diag=seven_peak_diagnostics(r7)
    assert len(diag)==7
    assert {'Flags','FWHM min (cm-1)','Center max (cm-1)'}.issubset(diag.columns)
    r5=fit_spectrum(x,y,'Synthetic')
    stats,pred=common_window_comparison(r5,r7)
    assert stats['Points'].min() > 100
    assert list(stats.Model)==['5-peak','7-peak']
    assert len(pred)==len(r5.x)
