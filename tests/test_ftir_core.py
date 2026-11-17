import numpy as np
from ftir_core import read_spectrum, fit_spectrum, gaussian_components

def test_read_tsv_with_header():
    txt='Wavenumber\tAbsorbance\n'+'\n'.join(f'{x}\t{x/1000}' for x in range(1600,1701))
    x,y=read_spectrum(txt.encode(), 'example.txt')
    assert len(x)==101 and y[0]==1.6

def test_five_gaussian_fit():
    x=np.linspace(1600,1700,201)
    p=np.array([.09,.02,.01,.015,.035,9,7,5,8,12])
    y=gaussian_components(x,p).sum(axis=0)
    r=fit_spectrum(x,y)
    assert np.isfinite(r.r2)
    assert abs(r.percentages.sum()-100)<1e-7
    assert np.all(r.areas>=0)

def test_reject_missing_amide_window():
    x=np.linspace(1400,1500,100)
    try:fit_spectrum(x,np.ones_like(x))
    except ValueError:pass
    else:raise AssertionError('Expected ValueError')
