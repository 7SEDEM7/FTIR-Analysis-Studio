import numpy as np
import pytest
from ftir_core import fit_spectrum, gaussian_components, validate_sigma_bounds


def _synthetic():
    x=np.linspace(1600,1700,201)
    p=np.array([0.08,0.04,0.03,0.03,0.05,8,11,6,7,10],dtype=float)
    return x, gaussian_components(x,p).sum(axis=0)


def test_independent_sigma_limits_are_respected():
    x,y=_synthetic()
    lo=[3,4,2,3,5]
    hi=[9,12,8,9,12]
    fit=fit_spectrum(x,y,sigma_min=lo,sigma_max=hi,initial_sigma=10)
    assert np.all(fit.parameters[5:] >= np.array(lo)-1e-7)
    assert np.all(fit.parameters[5:] <= np.array(hi)+1e-7)


def test_scalar_original_defaults_remain_supported():
    x,y=_synthetic()
    fit=fit_spectrum(x,y)
    assert np.isfinite(fit.r2)


@pytest.mark.parametrize('lo,hi', [([5,5,5,5,5],[5,6,6,6,6]),([-1,0,0,0,0],[9]*5),([1]*4,[8]*5),([1]*5,[8,8,8,float('nan'),8])])
def test_invalid_limits_rejected(lo,hi):
    with pytest.raises(ValueError):
        validate_sigma_bounds(lo,hi)


def test_report_quality_flags_include_bounds():
    from enhanced_reports import qc_records
    x,y=_synthetic()
    result=fit_spectrum(x,y,sigma_min=[3]*5,sigma_max=[8]*5)
    settings={'minimum_sigma_cm-1':[3]*5,'maximum_sigma_per_peak_cm-1':[8]*5}
    records=qc_records([result],settings)
    assert len(records)==1
    assert isinstance(records[0][1],list)
