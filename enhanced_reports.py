"""Presentation-quality reports generated ONLY from the in-memory fitted spectra.

Quality flags are review prompts, NOT scientific pass/fail validation.
"""
from io import BytesIO
from datetime import datetime, timezone
import math

from openpyxl import load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader

NAVY = '16324B'
TEAL = '087D92'
PALE = 'EAF4F6'
AMBER = 'FFF2D9'
RED = 'FCE8E7'
WHITE = 'FFFFFF'


def review_flags(r, threshold=0.95, amplitude_max=1.0, sigma_max=100.0, sigma_min=None):
    """Heuristic QC prompts only. No false claims of fit validity."""
    issues=[]
    if not math.isfinite(float(r.r2)):
        issues.append('R² undefined')
    elif float(r.r2) < threshold:
        issues.append(f'R² below review threshold ({threshold:g})')
    if any(float(v) >= 0.995 * amplitude_max for v in r.parameters[:5]):
        issues.append('Amplitude close to upper bound')
    from ftir_core import validate_sigma_bounds, LABELS
    sigma_lower, sigma_upper = validate_sigma_bounds(sigma_min, sigma_max)
    for label, value, lo, hi in zip(LABELS, r.parameters[5:], sigma_lower, sigma_upper):
        tolerance = max(1e-7, 0.005 * (hi - lo))
        if hi - float(value) <= tolerance:
            issues.append(f'{label}: sigma near upper bound')
        if float(value) - lo <= tolerance:
            issues.append(f'{label}: sigma near lower bound')
    if any(float(v) <= 1e-5 for v in r.parameters[:5]):
        issues.append('Near-zero component amplitude')
    return issues


def qc_records(results, settings):
    threshold=float(settings.get('review_r2_threshold',0.95))
    return [(r, review_flags(r,threshold,
               float(settings.get('maximum_amplitude',1.0)),
               settings.get('maximum_sigma_per_peak_cm-1',settings.get('maximum_sigma_cm-1',100.0)),
               settings.get('minimum_sigma_cm-1',None))) for r in results]


def _style_table(ws, header_row=1, start_row=2, last_col=None, end_row=None):
    last_col=last_col or ws.max_column
    end_row=end_row or ws.max_row
    for cells in ws.iter_rows(min_row=header_row,max_row=header_row,min_col=1,max_col=last_col):
        for c in cells:
            c.fill=PatternFill('solid',fgColor=NAVY)
            c.font=Font(name='Aptos',size=10,bold=True,color=WHITE)
            c.alignment=Alignment(vertical='center',wrap_text=True)
    ws.row_dimensions[header_row].height=35
    ws.freeze_panes=f'B{start_row}'
    ws.auto_filter.ref=f'A{header_row}:{get_column_letter(last_col)}{end_row}'
    for row in ws.iter_rows(min_row=start_row,max_row=end_row,min_col=1,max_col=last_col):
        for c in row:
            if c.row%2==0:
                c.fill=PatternFill('solid',fgColor='F4F8FA')
            if isinstance(c.value,float):
                c.number_format='0.0000'
    for column in ws.columns:
        col=column[0].column
        width=min(36,max(15,max(len(str(c.value)) if c.value is not None else 0 for c in column[:100])+2))
        ws.column_dimensions[get_column_letter(col)].width=width


def _section(ws, cell, text):
    c=ws[cell]
    c.value=text
    c.font=Font(name='Aptos Display',size=13,bold=True,color=WHITE)
    c.fill=PatternFill('solid',fgColor=NAVY)
    ws.row_dimensions[c.row].height=27


def build_excel(results, settings, chart_png, basic_workbook_bytes):
    """Style all fitted data sheets and add informative Dashboard/QC/Excel charts."""
    book=load_workbook(BytesIO(basic_workbook_bytes))
    for ws in book.worksheets:
        _style_table(ws)
    dashboard=book.create_sheet('Dashboard',0)
    dashboard.sheet_view.showGridLines=False
    dashboard.merge_cells('A1:L2')
    c=dashboard['A1'];c.value='FTIR  |  ANALYSIS REPORT';c.fill=PatternFill('solid',fgColor=NAVY)
    c.font=Font(size=22,bold=True,color=WHITE)
    c.alignment=Alignment(vertical='center')
    dashboard.row_dimensions[1].height=32
    dashboard.row_dimensions[2].height=20
    metadata=[('Analyzed samples',len(results)),('Spectral window','1600–1700 cm⁻¹'),
              ('Model','5 fixed-center Gaussian components'),('Baseline','Linear endpoint'),
              ('Input','Uploaded raw TXT / CSV only'),('Status','Exploratory fit; review QC flags')]
    for index,(key,val) in enumerate(metadata,4):
        dashboard.cell(index,1,key);dashboard.cell(index,2,val)
        dashboard.cell(index,1).font=Font(bold=True,color=NAVY)
        dashboard.cell(index,1).fill=PatternFill('solid',fgColor=PALE)
    dashboard.merge_cells('A11:J12')
    dashboard['A11']='IMPORTANT: Component percentages represent relative fitted Gaussian areas, NOT independently validated secondary-structure fractions.'
    dashboard['A11'].alignment=Alignment(wrap_text=True,vertical='center')
    dashboard['A11'].fill=PatternFill('solid',fgColor=AMBER)
    dashboard['A11'].font=Font(bold=True,color='704500')
    _section(dashboard,'A14','STUDY AT A GLANCE')
    dashboard['A15']='Samples to review'
    dashboard['B15']=sum(bool(issues) for _,issues in qc_records(results,settings))
    dashboard['A16']='Median R²'
    vals=sorted(float(r.r2) for r in results if math.isfinite(float(r.r2)))
    dashboard['B16']=vals[len(vals)//2] if vals else None
    dashboard['A17']='QC review threshold'
    dashboard['B17']=float(settings.get('review_r2_threshold',0.95))
    dashboard['A19']='See Summary, Quality Review, Peak Parameters, and per-sample tabs for full numeric details.'
    for i in range(1,13):dashboard.column_dimensions[get_column_letter(i)].width=17
    dashboard.column_dimensions['A'].width=28
    dashboard.column_dimensions['B'].width=38
    for pos,name in [('A22','composition_stacked_bar.png'),('A46','beta_sheet_grouped_bar.png'),('A70','fit_quality_R2_RMSE.png')]:
        if name in chart_png:
            im=XLImage(BytesIO(chart_png[name])); im.width=710;im.height=345
            dashboard.add_image(im,pos)
    constraints=book.create_sheet('Sigma Constraints')
    constraints.append(['Component', 'Center (cm-1)', 'Minimum sigma (cm-1)', 'Maximum sigma (cm-1)'])
    for item in settings.get('sigma_constraints_by_peak', []):
        constraints.append([item['component'], item['center_cm-1'],
                            item['minimum_sigma_cm-1'], item['maximum_sigma_cm-1']])
    _style_table(constraints)

    quality=book.create_sheet('Quality Review',2)
    quality.append(['Sample','R²','RMSE','Review status','Review notes','N points'])
    for r,notes in qc_records(results,settings):
        quality.append([r.sample,float(r.r2),float(r.rmse),'REVIEW' if notes else 'No automatic flags',
                        '; '.join(notes) if notes else 'No flags at selected threshold',len(r.x)])
    _style_table(quality)
    quality.column_dimensions['A'].width=28
    quality.column_dimensions['D'].width=24
    quality.column_dimensions['E'].width=58
    for row in range(2,quality.max_row+1):
        if quality.cell(row,4).value=='REVIEW':
            for col in (4,5): quality.cell(row,col).fill=PatternFill('solid',fgColor=AMBER)
    quality['H1']='QUALITY REVIEW IS A SCREENING AID — NOT MODEL VALIDATION'
    quality['H2']='R² alone does not establish fit correctness; inspect residuals and parameter stability.'
    quality.column_dimensions['H'].width=67
    # Native editable Excel bar chart on QC tab
    chart=BarChart();chart.type='col';chart.title='R² by sample';chart.y_axis.title='R²';chart.x_axis.title='Sample'
    chart.width=23; chart.height=11
    chart.add_data(Reference(quality,min_col=2,min_row=1,max_row=quality.max_row),titles_from_data=True)
    chart.set_categories(Reference(quality,min_col=1,min_row=2,max_row=quality.max_row))
    quality.add_chart(chart,'H5')
    methods=book.create_sheet('Method & Notes',3)
    methods.append(['Setting','Value'])
    for key,value in settings.items():
        methods.append([str(key),str(value)])
    methods.append(['Interpretation','Relative Gaussian areas are NOT validated secondary-structure percentages.'])
    methods.append(['QC review flags','Heuristic; not a statistically validated pass/fail test.'])
    methods.append(['Input provenance','No reference Excel or PNG images used in computing fit.'])
    _style_table(methods)
    methods.column_dimensions['A'].width=35;methods.column_dimensions['B'].width=110
    # Prominent QC field in the summary without changing underlying computed values
    if 'Summary' in book:
        ws=book['Summary']
        c=ws.cell(1,ws.max_column+1,'Quality review')
        c.fill=PatternFill('solid',fgColor=NAVY);c.font=Font(bold=True,color=WHITE)
        for i,(r,notes) in enumerate(qc_records(results,settings),2):
            cell=ws.cell(i,c.column,'REVIEW' if notes else 'No automatic flags')
            if notes:cell.fill=PatternFill('solid',fgColor=AMBER)
        ws.column_dimensions[get_column_letter(c.column)].width=24
        ws.auto_filter.ref=ws.dimensions
    output=BytesIO();book.save(output);return output.getvalue()


def _p(doc,text,x,y,size=10,bold=False,color=(0.10,0.20,0.29)):
    doc.setFillColorRGB(*color)
    doc.setFont('Helvetica-Bold' if bold else 'Helvetica',size)
    doc.drawString(x,y,str(text).encode('ascii','replace').decode('ascii'))


def build_pdf(archive, results, settings):
    """A4 report: executive summary, methodology, QC table, then EVERY PNG image."""
    out=BytesIO();doc=Canvas(out,pagesize=A4);W,H=A4
    doc.setTitle('FTIR complete analysis report')
    doc.setFillColorRGB(0.09,0.20,0.30);doc.rect(0,H-155,W,155,fill=1,stroke=0)
    _p(doc,'FTIR ANALYSIS STUDIO',42,H-74,23,True,(1,1,1))
    _p(doc,'Amide I | Five-Gaussian analysis',42,H-103,12,False,(0.83,0.94,0.96))
    _p(doc,f'Samples analyzed: {len(results)}',42,H-205,12,True)
    _p(doc,'Source: uploaded raw TXT/CSV spectra',42,H-228,10)
    _p(doc,'Model: fixed centers, linear endpoint baseline, 1600-1700 cm-1',42,H-249,10)
    _p(doc,'ATR preprocessing: '+str(settings.get('preprocessing',{}).get('atr_mode','none')),42,H-268,9)
    _p(doc,'Relative peak areas are not validated structural percentages.',42,H-289,10,True,(0.65,0.26,0.14))
    _p(doc,'This report is descriptive. Fit flags require scientific review.',42,H-311,10)
    doc.setStrokeColorRGB(.82,.88,.90);doc.line(42,H-335,W-42,H-335)
    _p(doc,'SAMPLE QUALITY SUMMARY',42,H-367,13,True)
    y=H-392
    _p(doc,'Sample',44,y,9,True);_p(doc,'R squared',273,y,9,True);_p(doc,'RMSE',347,y,9,True);_p(doc,'QC',455,y,9,True)
    for r,notes in qc_records(results,settings):
        y-=18
        if y<80:doc.showPage();y=H-60
        name=r.sample[:35]
        _p(doc,name,44,y,9)
        _p(doc,f'{r.r2:.5f}',273,y,9)
        _p(doc,f'{r.rmse:.5g}',347,y,9)
        _p(doc,'REVIEW' if notes else 'No flags',455,y,8,bool(notes),(0.67,.33,.13) if notes else (.10,.45,.38))
    y-=42
    if y<85:doc.showPage();y=H-60
    _p(doc,'IMPORTANT METHODOLOGICAL NOTES',42,y,11,True)
    for line in [
        'The Gaussian model assumes five fixed peak centers (cm-1): 1652, 1630,',
        '1679, 1671, and 1645. Areas are computed from fitted amplitudes and widths.',
        f'QC screening threshold: R squared < {float(settings.get("review_r2_threshold",0.95)):.2f}, or near-bound parameters.',
        'QC flags are screening prompts, not definitive scientific quality criteria.',
        'Interpret component labels cautiously; alternative models require validation.',
        'Peak width constraints (sigma, cm-1) are stored in analysis_settings.json',
        'and in the Excel Sigma Constraints worksheet.'
    ]:
        y-=16;_p(doc,line,42,y,8.7)
    doc.showPage()
    images=sorted(n for n in archive.namelist() if n.lower().endswith('.png'))
    for i,name in enumerate(images,1):
        im=ImageReader(BytesIO(archive.read(name)))
        iw,ih=im.getSize();scale=min((W-65)/iw,(H-125)/ih)
        dw,dh=iw*scale,ih*scale
        _p(doc,name.replace('_',' ').split('/')[-1][:82],35,H-39,11,True)
        doc.drawImage(im,(W-dw)/2,(H-dh)/2-4,dw,dh,preserveAspectRatio=True)
        _p(doc,f'Figure {i}/{len(images)}',W-120,24,9)
        doc.showPage()
    doc.save();return out.getvalue()
