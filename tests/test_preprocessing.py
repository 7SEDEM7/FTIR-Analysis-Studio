import numpy as np
import pytest
from preprocessing import validate_options, preprocess


def test_default_preserves_raw_spectrum():
    x=np.linspace(1500,1800,101)
    y=np.exp(-((x-1650)/20)**2)
    assert np.allclose(preprocess(x,y,{}),y)


def test_simple_atr_wavenumber_scaling():
    x=np.array([1000.,1650.,2000.,2200.,2500.]); y=np.ones_like(x)
    got=preprocess(x,y,{"atr_mode":"simple_wavenumber_scaling","reference_wavenumber":1650.})
    assert np.allclose(got, x/1650.)


def test_total_internal_reflection_validation():
    with pytest.raises(ValueError, match="total internal reflection"):
        validate_options({"crystal_refractive_index":1.6,"sample_refractive_index":1.5,"incidence_angle_degrees":20.})


def test_savgol_rejects_even_window():
    with pytest.raises(ValueError, match="odd"):
        validate_options({"savgol_enabled":True,"savgol_window":10})
