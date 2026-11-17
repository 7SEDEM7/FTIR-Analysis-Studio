"""Reproducible baseline alternatives and cautious, descriptive fit diagnostics.

Baseline corrections are methodological options, not instrument ATR corrections.
"""
import numpy as np
import pandas as pd
from scipy.optimize import least_squares

BASELINE_MODES = ('linear_endpoints', 'robust_edge_fit')


def baseline_for_window(x, y, method='linear_endpoints', edge_fraction=0.12):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.ndim != 1 or y.shape != x.shape or len(x) < 30 or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError('Baseline requires >=30 finite, matching data points.')
    if not np.all(np.diff(x) > 0):
        raise ValueError('Baseline expects strictly ascending wavenumbers.')
    if method not in BASELINE_MODES:
        raise ValueError(f'Unknown baseline method: {method}')
    if not (0.05 <= float(edge_fraction) <= 0.25):
        raise ValueError('Edge fraction must be between 0.05 and 0.25.')
    if method == 'linear_endpoints':
        return y[0] + (y[-1]-y[0])*(x-x[0])/(x[-1]-x[0])
    # Use two edge regions rather than two single, potentially noisy endpoints.
    n = max(5, int(np.ceil(len(x)*float(edge_fraction))))
    use = np.r_[np.arange(n), np.arange(len(x)-n,len(x))]
    xx = x[use]-x.mean()
    yy = y[use]
    slope = (np.median(y[-n:])-np.median(y[:n]))/(np.median(x[-n:])-np.median(x[:n]))
    offset = np.median(yy-slope*xx)
    noise = np.median(np.abs(yy-np.median(yy)))*1.4826
    result = least_squares(lambda p: p[0]+p[1]*xx-yy, [offset,slope],
                           loss='soft_l1',f_scale=max(noise,1e-8),max_nfev=1000)
    return result.x[0]+result.x[1]*(x-x.mean())


def seven_peak_diagnostics(result, center_tolerance=0.5, fwhm_tolerance=0.5,
                           area_threshold_percent=0.5, r2_review_threshold=0.95):
    """Heuristic flags only; not validated pass/fail decisions."""
    cfg = result.peak_settings.reset_index(drop=True)
    rows = []
    for i in range(len(result.centers)):
        center = float(result.centers[i]); fwhm = float(result.fwhm[i]); area = float(result.percentages[i])
        cmin,cmax = float(cfg.loc[i,'Center min (cm-1)']),float(cfg.loc[i,'Center max (cm-1)'])
        wmin,wmax = float(cfg.loc[i,'FWHM min (cm-1)']),float(cfg.loc[i,'FWHM max (cm-1)'])
        issues = []
        if min(center-cmin,cmax-center) <= center_tolerance: issues.append('Center near bound')
        if min(fwhm-wmin,wmax-fwhm) <= fwhm_tolerance: issues.append('FWHM near bound')
        if area < area_threshold_percent: issues.append('Very small relative area')
        rows.append({'Sample':result.sample,'Component':result.names[i],
                     'Center (cm-1)':center,'Center min (cm-1)':cmin,'Center max (cm-1)':cmax,
                     'FWHM (cm-1)':fwhm,'FWHM min (cm-1)':wmin,'FWHM max (cm-1)':wmax,
                     'Relative area (%)':area,'Flags':'; '.join(issues)})
    if result.r2 < r2_review_threshold:
        for row in rows: row['Sample-level flag']='R² below review threshold'
    else:
        for row in rows: row['Sample-level flag']=''
    return pd.DataFrame(rows)


def common_window_comparison(five, seven, x_min=1600., x_max=1700.):
    """Evaluate both *fitted models* on the same observed processed absorbance points.

    Models were independently fitted over differing windows and may use different
    baseline algorithms. Scores on shared points improve descriptive comparability
    but do not establish scientific superiority.
    """
    x = np.asarray(five.x)
    m=(x>=x_min)&(x<=x_max)
    x=x[m]
    if len(x)<20 or min(seven.x)>x.min() or max(seven.x)<x.max():
        raise ValueError('Models lack adequate overlapping wavenumbers.')
    y = np.asarray(five.original)[m]
    y7 = np.interp(x,seven.x,np.asarray(seven.baseline)+np.asarray(seven.fitted))
    y5 = np.asarray(five.baseline)[m]+np.asarray(five.fitted)[m]
    if not np.allclose(y,np.interp(x,seven.x,seven.original),rtol=1e-6,atol=1e-7):
        raise ValueError('Comparison requires both models fitted to the same preprocessed spectrum.')
    def score(pred):
        sse=np.sum((y-pred)**2)
        sst=np.sum((y-np.mean(y))**2)
        return float(1-sse/sst) if sst>0 else float('nan'),float(np.sqrt(np.mean((y-pred)**2)))
    r5,e5=score(y5);r7,e7=score(y7)
    table=pd.DataFrame([{'Model':'5-peak','Sample':five.sample,'Shared R²':r5,'Shared RMSE':e5,'Points':len(x)},
                        {'Model':'7-peak','Sample':seven.sample,'Shared R²':r7,'Shared RMSE':e7,'Points':len(x)}])
    return table, pd.DataFrame({'Wavenumber (cm-1)':x,'Observed preprocessed absorbance':y,
                                '5-peak predicted absorbance':y5,'7-peak predicted absorbance':y7})
