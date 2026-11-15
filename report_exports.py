"""Additional scientific report graphics and a polished XLSX workbook.

All reported values come from FitResult objects computed from uploaded raw spectra.
The original study-summary workbook is never used as an analysis input.
"""
from io import BytesIO
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ftir_core import LABELS, COLORS, CENTERS

CAUTION = ('Gaussian relative areas reflect fitted component areas, not independently '
           'validated secondary-structure fractions. Review fit residuals, especially for low R².')


def _save(fig):
    fig.tight_layout()
    bio=BytesIO()
    fig.savefig(bio,format='png',dpi=220,bbox_inches='tight',facecolor='white')
    plt.close(fig)
    return bio.getvalue()


def residual_png(r):
    fig,ax=plt.subplots(figsize=(10,3.9))
    ax.plot(r.x,r.residuals,color='#15618c',lw=1.5)
    ax.axhline(0,color='#b91c1c',linestyle='--',lw=1)
    ax.set(xlim=(1700,1600),xlabel='Wavenumber (cm⁻¹)',ylabel='Residual (absorbance)',title=f'{r.sample} — fit residuals (R²={r.r2:.5f}, RMSE={r.rmse:.5g})')
    ax.grid(alpha=.2)
    return _save(fig)


def preprocessing_png(r):
    fig,axs=plt.subplots(1,2,figsize=(11,4))
    axs[0].plot(r.x,r.original,color='#34495e',label='Original absorbance')
    axs[0].plot(r.x,r.baseline,color='#de6f35',linestyle='--',label='Linear baseline')
    axs[1].plot(r.x,r.corrected,color='#137e91',label='Baseline corrected')
    for ax in axs:
        ax.set_xlim(1700,1600);ax.set_xlabel('Wavenumber (cm⁻¹)');ax.set_ylabel('Absorbance');ax.grid(alpha=.2);ax.legend(fontsize=8)
    axs[0].set_title('Before baseline correction');axs[1].set_title('After baseline correction')
    fig.suptitle(r.sample)
    return _save(fig)


def component_bars_png(r):
    fig,ax=plt.subplots(figsize=(9,4.4))
    names=['α-helix','β-sheet 1630','β-sheet 1679','Loop','Disordered']
    bars=ax.bar(names,r.percentages,color=COLORS)
    ax.bar_label(bars,fmt='%.2f%%',padding=3,fontsize=9)
    ax.set_ylim(0,max(12,float(np.max(r.percentages))*1.23));ax.set_ylabel('Relative Gaussian area (%)')
    ax.set_title(f'{r.sample} — fitted component areas');ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)
    ax.tick_params(axis='x',rotation=16)
    return _save(fig)


def stacked_comparison_png(results):
    fig,ax=plt.subplots(figsize=(max(11,len(results)*1.2),6))
    x=np.arange(len(results));bottom=np.zeros(len(results))
    for i,(label,col) in enumerate(zip(LABELS,COLORS)):
        values=np.array([float(r.percentages[i]) for r in results]);ax.bar(x,values,bottom=bottom,label=label,color=col)
        bottom+=values
    ax.set_xticks(x,labels=[r.sample for r in results],rotation=35,ha='right')
    ax.set_ylim(0,107);ax.set_ylabel('Relative Gaussian area (%)');ax.set_title('Fitted component area composition by sample')
    ax.legend(ncol=3,loc='upper center',bbox_to_anchor=(.5,-.22));ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    return _save(fig)


def grouped_beta_png(results):
    fig,ax=plt.subplots(figsize=(max(11,len(results)*1.15),5.5))
    x=np.arange(len(results));width=.35
    b1=np.array([float(r.percentages[1]) for r in results]);b2=np.array([float(r.percentages[2]) for r in results])
    ax.bar(x-width/2,b1,width,color=COLORS[1],label='β-sheet 1630')
    ax.bar(x+width/2,b2,width,color=COLORS[2],label='β-sheet 1679')
    ax.set_xticks(x,labels=[r.sample for r in results],rotation=35,ha='right')
    ax.set_ylabel('Relative Gaussian area (%)');ax.set_title('β-sheet component comparison');ax.legend()
    ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    return _save(fig)


def fit_quality_png(results):
    fig,axs=plt.subplots(1,2,figsize=(12,4.6))
    x=np.arange(len(results));names=[r.sample for r in results]
    axs[0].bar(x,[r.r2 for r in results],color='#267c99')
    axs[0].set_ylim(0,1.05);axs[0].set_ylabel('R²');axs[0].set_title('Fit quality — R²')
    axs[1].bar(x,[r.rmse for r in results],color='#d5803a')
    axs[1].set_ylabel('RMSE (absorbance)');axs[1].set_title('Fit error — RMSE')
    for ax in axs:
        ax.set_xticks(x,labels=names,rotation=60,ha='right',fontsize=8)
        ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    return _save(fig)


def report_xlsx(results,settings):
    """Create a formatted, multi-sheet, Excel-native chart report via artifact_tool.

    Requires optional `artifact_tool_v2` installation. Caller may use a basic fallback
    workbook if this dependency is not installed on the target machine.
    """
    from artifact_tool import Workbook, SpreadsheetFile
    from pathlib import Path
    import tempfile

    wb=Workbook.create()
    navy='#13324A';cyan='#107A91';pale='#EAF3F6';dark='#24364B'
    def header(ws, row, ncol):
        region=ws.get_range_by_indexes(row-1,0,1,ncol)
        region.format={'fill':navy,'font':{'bold':True,'color':'#FFFFFF'},'row_height':27,'vertical_alignment':'center'}
    def title(ws,text,end='H'):
        ws.merge_cells(f'A1:{end}1');ws.get_range('A1').values=[[text]]
        ws.get_range(f'A1:{end}1').format={'fill':navy,'font':{'bold':True,'color':'#FFFFFF','size':16},'row_height':36}
    def matrix(ws,head,rows,at=4):
        values=[list(head)]+[list(r) for r in rows]
        ws.get_range_by_indexes(at-1,0,len(values),len(head)).values=values
        header(ws,at,len(head));ws.freeze_panes.freeze_rows(at)
        if rows:
            ws.get_range_by_indexes(at,0,len(rows),len(head)).format.row_height=20
        return at+len(values)-1
    def column_widths(ws,cols,rows=30):
        for idx,width in enumerate(cols): ws.get_range_by_indexes(0,idx,rows,1).format.column_width=width
    def num(x):
        x=float(x)
        return x if np.isfinite(x) else None

    dashboard=wb.worksheets.add('Dashboard')
    title(dashboard,'FTIR ANALYSIS  |  Study dashboard','H')
    dashboard.get_range('A3:B7').values=[['Report type','Amide I five-Gaussian fitting'],['Samples analyzed',len(results)],['Spectral region (cm-1)','1600–1700'],['Peak centers (cm-1)',', '.join(str(int(c)) for c in CENTERS)],['Baseline','Linear endpoint correction']]
    dashboard.get_range('A3:A7').format={'font':{'bold':True,'color':dark},'fill':pale}
    dashboard.get_range('A9').values=[['Scientific interpretation']]
    dashboard.get_range('A9:H9').format={'fill':navy,'font':{'bold':True,'color':'#FFFFFF'}}
    dashboard.merge_cells('A10:H12')
    dashboard.get_range('A10').values=[[CAUTION]]
    dashboard.get_range('A10:H12').format.wrap_text=True
    dashboard.get_range('A14').values=[['Navigate to the Summary, Peak Parameters and per-sample sheets for detailed results.']]
    column_widths(dashboard,[30,22,16,16,16,16,16,16])

    sm=wb.worksheets.add('Summary')
    title(sm,'FTIR study results | relative fitted areas','J')
    heads=['Sample','Alpha helix (%)','Beta 1630 (%)','Beta 1679 (%)','Total beta (%)','Loop (%)','Disordered (%)','R squared','RMSE','Amide I points']
    rows=[]
    for r in results:
        p=r.percentages
        rows.append([r.sample,*[num(p[i]) for i in [0,1,2]],num(p[1]+p[2]),num(p[3]),num(p[4]),num(r.r2),num(r.rmse),len(r.x)])
    end=matrix(sm,heads,rows)
    column_widths(sm,[26,19,18,18,18,16,19,16,16,17],end+3)
    sm.get_range(f'B5:G{end}').set_number_format('0.00')
    sm.get_range(f'H5:H{end}').set_number_format('0.000000')
    sm.get_range(f'I5:I{end}').set_number_format('0.000000')
    sm.get_range(f'K4').values=[['Data source: fitted raw TXT/CSV spectra']]
    sm.get_range(f'K5').values=[['Relative areas are not validated structure fractions.']]
    try:
        chart=sm.charts.add('ColumnClustered',{'title':'Total β-sheet relative area (%)','has_legend':False})
        # Adjacent helper table for simple, reliable Excel-native chart source
        sm.get_range('L4:M4').values=[['Sample','Total beta (%)']]
        sm.get_range_by_indexes(4,11,len(results),2).values=[[r.sample,num(r.percentages[1]+r.percentages[2])] for r in results]
        chart.set_data(sm.get_range(f'L4:M{end}'));chart.set_position('L19','V35')
    except Exception: pass

    peaks=wb.worksheets.add('Peak Parameters')
    title(peaks,'Gaussian peak parameters — all samples','J')
    ph=['Sample','Component','Center (cm-1)','Amplitude','Amplitude SE','Sigma (cm-1)','Sigma SE','Gaussian area','Relative area (%)']
    pr=[]
    for r in results:
        for i,label in enumerate(LABELS):
            pr.append([r.sample,label,num(CENTERS[i]),num(r.parameters[i]),num(r.standard_errors[i]),num(r.parameters[5+i]),num(r.standard_errors[5+i]),num(r.areas[i]),num(r.percentages[i])])
    last=matrix(peaks,ph,pr)
    column_widths(peaks,[27,23,20,18,18,19,17,20,22],last+2)
    peaks.get_range(f'C5:I{last}').set_number_format('0.00000')

    methods=wb.worksheets.add('Analysis Settings')
    title(methods,'Method & analysis settings','D')
    settings_rows=[['Model','Five fixed-center Gaussian components'],['Baseline','Linear endpoint'],['Spectral region','1600–1700 cm-1'],['Component labeling','Assignments from the supplied notebook']]
    settings_rows.extend([[str(k),str(v)] for k,v in settings.items()])
    settings_rows.append(['Interpretation caution',CAUTION])
    matrix(methods,['Parameter','Value'],settings_rows,at=4)
    column_widths(methods,[34,100],len(settings_rows)+6)

    # Excel details per individual spectrum; keep names short and deterministic
    for index,r in enumerate(results,1):
        name=f'S{index:02d}_Spectrum'
        ws=wb.worksheets.add(name)
        title(ws,f'{index:02d}  |  {r.sample}  |  spectral fitting','K')
        heads=['Wavenumber','Original absorb.','Baseline','Corrected absorb.','Total fit','Residual']+list(LABELS)
        comp=r.components
        records=[]
        for k,x in enumerate(r.x):
            records.append([num(x),num(r.original[k]),num(r.baseline[k]),num(r.corrected[k]),num(r.fitted[k]),num(r.residuals[k])]+[num(comp[i,k]) for i in range(5)])
        lastrow=matrix(ws,heads,records)
        column_widths(ws,[17,20,18,20,18,18,20,19,19,16,19],lastrow+2)
        ws.get_range(f'A5:A{lastrow}').set_number_format('0.00')
        ws.get_range(f'B5:K{lastrow}').set_number_format('0.000000')
        ws.get_range('M4:N7').values=[['Sample',r.sample],['R squared',num(r.r2)],['RMSE',num(r.rmse)],['Total beta (%)',num(r.percentages[1]+r.percentages[2])]]
        ws.get_range('M4:M7').format={'fill':pale,'font':{'bold':True,'color':dark}}
        ws.get_range('M:M').format.column_width=22;ws.get_range('N:N').format.column_width=24

    with tempfile.TemporaryDirectory() as temp:
        p=Path(temp)/'ft_report.xlsx'
        SpreadsheetFile.export_xlsx(wb).save(str(p))
        return p.read_bytes()
