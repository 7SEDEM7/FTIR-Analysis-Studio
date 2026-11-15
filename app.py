"""FTIR Analysis Studio — guided upload → configure → run → review → export."""
from pathlib import Path
from io import BytesIO, StringIO
import json
import re
import zipfile

import matplotlib
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ftir_core import LABELS, COLORS, CENTERS, read_spectrum, fit_spectrum, gaussian_components, results_excel
from enhanced_reports import build_excel, build_pdf, qc_records
from report_exports import (report_xlsx, residual_png, preprocessing_png, component_bars_png,
    stacked_comparison_png, grouped_beta_png, fit_quality_png)

st.set_page_config(page_title='FTIR Analysis Studio', page_icon='🔬', layout='wide')
st.markdown('''<style>
.block-container{max-width:1300px;padding-top:2rem;padding-bottom:3rem}
h1{letter-spacing:-.045em;font-weight:750} h2{font-size:1.42rem}
[data-testid="stMetric"]{border:1px solid rgba(130,145,160,.22);padding:14px;border-radius:12px}
[data-testid="stSidebar"]{border-right:1px solid rgba(130,145,160,.2)}
div.stButton>button[kind="primary"]{font-weight:700}
</style>''', unsafe_allow_html=True)

ROOT=Path(__file__).resolve().parent
PREV=ROOT/'data'/'Example_previous_study_summary.xlsx'
STEPS=['1 · Upload data','2 · Configure','3 · Run analysis','4 · View results','5 · Download ZIP']
if 'stage' not in st.session_state: st.session_state.stage=0
if 'results' not in st.session_state: st.session_state.results=[]
if 'errors' not in st.session_state: st.session_state.errors=[]
if 'run_signature' not in st.session_state: st.session_state.run_signature=None
if 'spectra_files' not in st.session_state: st.session_state.spectra_files=[]
if 'upload_errors' not in st.session_state: st.session_state.upload_errors=[]
if 'export_archive' not in st.session_state: st.session_state.export_archive=None
if 'export_error' not in st.session_state: st.session_state.export_error=None


def change_stage(n):
    st.session_state.stage=n

def reset_analysis():
    st.session_state.results=[]
    st.session_state.errors=[]
    st.session_state.run_signature=None
    st.session_state.export_archive=None
    st.session_state.export_error=None


def cache_uploads():
    """Persist file bytes across workflow pages (widgets do not persist if hidden)."""
    spectra, issues = [], []
    seen = set()
    for uploaded in st.session_state.get('incoming_files') or []:
        raw = uploaded.getvalue()
        if uploaded.name.lower().endswith('.zip'):
            try:
                with zipfile.ZipFile(BytesIO(raw)) as archive:
                    for entry in archive.infolist():
                        if entry.is_dir() or not entry.filename.lower().endswith(('.txt', '.csv')):
                            continue
                        if entry.file_size > 20 * 1024 * 1024:
                            issues.append(f'{entry.filename}: file exceeds 20 MB limit')
                            continue
                        name = Path(entry.filename.replace('\\', '/')).name
                        if name in seen:
                            issues.append(f'{name}: duplicate filename skipped')
                            continue
                        spectra.append((name, archive.read(entry)))
                        seen.add(name)
            except (zipfile.BadZipFile, RuntimeError, ValueError) as exc:
                issues.append(f'{uploaded.name}: could not read ZIP ({exc})')
        else:
            if uploaded.name in seen:
                issues.append(f'{uploaded.name}: duplicate filename skipped')
                continue
            spectra.append((uploaded.name, raw))
            seen.add(uploaded.name)
    st.session_state.spectra_files = spectra
    st.session_state.upload_errors = issues
    reset_analysis()


def plot_spectrum(r, selected=None):
    selected=selected if selected is not None else list(LABELS)
    fig=go.Figure()
    fig.add_scatter(x=r.x,y=r.corrected,mode='markers',name='Measured (corrected)',marker=dict(size=4,color='#222222'),hovertemplate='%{x:.1f} cm⁻¹<br>%{y:.5f}<extra></extra>')
    dense=np.linspace(float(r.x.min()),float(r.x.max()),700)
    comps=gaussian_components(dense,r.parameters)
    for i,(label,color) in enumerate(zip(LABELS,COLORS)):
        if label in selected: fig.add_scatter(x=dense,y=comps[i],name=label,line=dict(color=color,dash='dash',width=2))
    fig.add_scatter(x=r.x,y=r.fitted,name='Total fit',line=dict(color='#f04452',width=3))
    fig.update_layout(height=470,margin=dict(l=10,r=10,t=20,b=10),xaxis_title='Wavenumber (cm⁻¹)',yaxis_title='Baseline-corrected absorbance',legend=dict(orientation='h',y=-.27))
    fig.update_xaxes(autorange='reversed')
    return fig


def comparison_plot(results):
    fig=go.Figure()
    for i,(label,color) in enumerate(zip(LABELS,COLORS)):
        fig.add_bar(x=[r.sample for r in results],y=[float(r.percentages[i]) for r in results],name=label,marker_color=color)
    fig.update_layout(barmode='stack',height=450,margin=dict(l=0,r=0,t=10,b=10),yaxis_title='Relative Gaussian area (%)',legend=dict(orientation='h',y=-.3))
    fig.update_yaxes(range=[0,105])
    return fig


def png_spectrum(r):
    fig,ax=plt.subplots(figsize=(11,6))
    ax.plot(r.x,r.corrected,'k.',markersize=3,label='Measured (corrected)')
    dense=np.linspace(float(r.x.min()),float(r.x.max()),650)
    for label,color,component in zip(LABELS,COLORS,gaussian_components(dense,r.parameters)):
        ax.plot(dense,component,'--',color=color,label=label)
    ax.plot(r.x,r.fitted,color='red',linewidth=2.4,label='Total fit')
    ax.invert_xaxis();ax.set(xlabel='Wavenumber (cm⁻¹)',ylabel='Corrected absorbance',title=r.sample)
    ax.legend(fontsize=8);ax.grid(alpha=.15);fig.tight_layout()
    bio=BytesIO();fig.savefig(bio,format='png',dpi=220);plt.close(fig)
    return bio.getvalue()


def safe_name(s):
    return re.sub(r'[^A-Za-z0-9_-]+','_',s).strip('_')[:70] or 'sample'


def summary_frame(results):
    records=[]
    for r in results:
        record={'Sample':r.sample,'R squared':r.r2,'RMSE':r.rmse,'Unique wavenumbers':len(r.x)}
        record.update({f'{lab} relative area (%)':float(p) for lab,p in zip(LABELS,r.percentages)})
        record['Total beta sheet relative area (%)']=float(r.percentages[1]+r.percentages[2])
        records.append(record)
    return pd.DataFrame(records)


def export_settings():
    return {'model':'five fixed-center Gaussians',
            'peak_centers_cm-1':CENTERS.tolist(), 'spectral_window_cm-1':[1600,1700],
            'baseline':'linear endpoint',
            'maximum_amplitude':float(st.session_state.get('amplitude_max',1.)),
            'maximum_sigma_cm-1':float(st.session_state.get('sigma_max',100.)),
            'initial_sigma_cm-1':float(st.session_state.get('initial_sigma',10.)),
            'review_r2_threshold':float(st.session_state.get('review_r2_threshold',0.95)),
            'scientific_caution':'Relative fitted areas are not independently validated secondary-structure fractions.'}


def generate_full_export():
    """Build all Excel, PNG, HTML and tabular outputs from current fitted TXT/CSV data."""
    st.session_state.export_archive=None
    st.session_state.export_error=None
    if not st.session_state.results:
        return
    try:
        st.session_state.export_archive=make_zip(st.session_state.results, export_settings())
    except Exception as exc:
        st.session_state.export_error=f'Export generation failed: {exc}'



def create_formatted_excel(results):
    """Style the existing export without requiring optional artifact_tool_v2."""
    workbook = load_workbook(BytesIO(results_excel(results)))
    for sheet in workbook.worksheets:
        sheet.freeze_panes = 'B2'
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.fill = PatternFill('solid', fgColor='17365D')
            cell.font = Font(bold=True, color='FFFFFF')
            cell.alignment = Alignment(horizontal='center', wrap_text=True)
        for column in sheet.columns:
            letter = get_column_letter(column[0].column)
            max_length = max(len(str(cell.value or '')) for cell in column)
            sheet.column_dimensions[letter].width = min(max(max_length + 3, 14), 42)
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value, float):
                    cell.number_format = '0.0000'
    out = BytesIO()
    workbook.save(out)
    return out.getvalue()


def create_complete_pdf(archive, results):
    """Create title page followed by every PNG already present in the archive."""
    out = BytesIO()
    doc = canvas.Canvas(out, pagesize=A4)
    page_width, page_height = A4
    doc.setTitle('FTIR Complete Analysis Report')
    doc.setFont('Helvetica-Bold', 22)
    doc.drawString(44, page_height - 75, 'FTIR Analysis Report')
    doc.setFont('Helvetica', 12)
    doc.drawString(44, page_height - 112, f'Analyzed samples: {len(results)}')
    doc.drawString(44, page_height - 135, 'Five-Gaussian Amide I analysis | 1600-1700 cm-1')
    doc.setFont('Helvetica', 10)
    doc.drawString(44, page_height - 184, 'All results are computed from uploaded TXT/CSV spectra.')
    doc.drawString(44, page_height - 204, 'Relative fitted areas are not validated structure percentages.')
    doc.showPage()

    image_paths = sorted(n for n in archive.namelist() if n.lower().endswith('.png'))
    for page_number, name in enumerate(image_paths, 1):
        image = ImageReader(BytesIO(archive.read(name)))
        iw, ih = image.getSize()
        scale = min((page_width - 70) / iw, (page_height - 140) / ih)
        dw, dh = iw * scale, ih * scale
        doc.setFont('Helvetica-Bold', 10)
        # Helvetica does not support arbitrary Unicode sample names; use safe ASCII here.
        header = name.replace('_', ' ').encode('ascii', errors='replace').decode('ascii')
        doc.drawString(35, page_height - 42, header[:95])
        doc.drawImage(image, (page_width - dw) / 2, (page_height - dh) / 2 - 8,
                      width=dw, height=dh, preserveAspectRatio=True)
        doc.setFont('Helvetica', 9)
        doc.drawRightString(page_width - 35, 25, f'Figure {page_number} of {len(image_paths)}')
        doc.showPage()
    doc.save()
    return out.getvalue()

def make_zip(results,settings,include_png=True,include_html=True,include_excel=True):
    buffer=BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as z:
        summary=summary_frame(results)
        z.writestr('summary/results_summary.csv',summary.to_csv(index=False,float_format='%.8g'))
        z.writestr('summary/results_summary.txt',summary.to_csv(index=False,sep='\t',float_format='%.8g'))
        z.writestr('analysis_settings.json',json.dumps(settings,indent=2,ensure_ascii=False))
        z.writestr('README.txt','FTIR Analysis Studio — complete research analysis package\n\nOriginal source: uploaded raw TXT/CSV FTIR spectra only. Original study Excel or PNG images are NOT used in the fit.\n\nThe five fixed-center Gaussian model computes relative fitted areas, NOT independently validated secondary-structure percentages. Inspect fit residuals and R² before interpretation.\n\nsummary/: study table (CSV, TXT, informative Excel report)\ncharts/: all-sample stacked component bars, grouped beta-sheet bars, quality comparison (PNG)\nsamples/: each sample\'s Gaussian fit, residual plot, baseline correction and component bar PNG; full calculated data and parameters (CSV/TXT); interactive plot (HTML).\nanalysis_settings.json: fitting parameters used.\n')
        if include_png:
            z.writestr('charts/composition_stacked_bar.png',stacked_comparison_png(results))
            z.writestr('charts/beta_sheet_grouped_bar.png',grouped_beta_png(results))
            z.writestr('charts/fit_quality_R2_RMSE.png',fit_quality_png(results))
        if include_excel:
            chart_assets={
                'composition_stacked_bar.png':stacked_comparison_png(results),
                'beta_sheet_grouped_bar.png':grouped_beta_png(results),
                'fit_quality_R2_RMSE.png':fit_quality_png(results),
            }
            z.writestr('summary/FTIR_Study_Report.xlsx',
                       build_excel(results,settings,chart_assets,results_excel(results)))
        z.writestr('summary/quality_review.csv',
                   pd.DataFrame([{'Sample':r.sample,'R_squared':r.r2,'RMSE':r.rmse,
                   'Review':'; '.join(notes) if notes else 'No automatic flags'}
                   for r,notes in qc_records(results,settings)]).to_csv(index=False))
        used=set()
        for idx,r in enumerate(results,1):
            folder=f'samples/{idx:02d}_{safe_name(r.sample)}/'
            z.writestr(folder+'fitted_spectrum.csv',r.spectrum_table().to_csv(index=False))
            z.writestr(folder+'fitted_spectrum.txt',r.spectrum_table().to_csv(index=False,sep='\t'))
            z.writestr(folder+'peak_parameters.csv',r.parameters_table().to_csv(index=False))
            z.writestr(folder+'peak_parameters.txt',r.parameters_table().to_csv(index=False,sep='\t'))
            if include_png:
                z.writestr(folder+'gaussian_fit.png',png_spectrum(r))
                z.writestr(folder+'fit_residuals.png',residual_png(r))
                z.writestr(folder+'baseline_correction.png',preprocessing_png(r))
                z.writestr(folder+'component_area_bar.png',component_bars_png(r))
            if include_html: z.writestr(folder+'interactive_fit.html',plot_spectrum(r).to_html(full_html=True,include_plotlyjs=True))
        if include_png:
            pdf_bytes = build_pdf(z, results, settings)
            z.writestr('FTIR_Complete_Analysis_Report.pdf', pdf_bytes)
    return buffer.getvalue()


st.title('🔬 FTIR Analysis Studio')
st.caption('Analyze your own spectra · Amide I · Five-Gaussian fitting · Export complete analysis packages')
st.progress((st.session_state.stage+1)/5,text=f'Step {st.session_state.stage+1} of 5')
with st.sidebar:
    st.subheader('Input spectra')
    st.file_uploader('Upload TXT, CSV or ZIP', type=['txt','csv','zip'], accept_multiple_files=True, key='incoming_files', on_change=cache_uploads, help='Selected spectra remain available while navigating the workflow.')
    st.caption(f"{len(st.session_state.spectra_files)} spectral file(s) stored for this session")
    st.divider()
    st.subheader('Analysis workflow')
    for i,label in enumerate(STEPS):
        st.button(label,key=f'nav_{i}',on_click=change_stage,args=(i,),use_container_width=True,type='primary' if st.session_state.stage==i else 'secondary')
    st.divider()
    st.caption('Start with your raw TXT/CSV measurements. Your previous Excel workbook is only a reference and is never used as a substitute for raw spectra.')
    with st.expander('About the fitting method'):
        st.write('Five fixed centers: 1652, 1630, 1679, 1671 and 1645 cm⁻¹. Linear endpoint baseline correction. Default analysis range: 1600–1700 cm⁻¹.')
        st.warning('Relative fitted Gaussian areas are not independently validated structural percentages.')

stage=st.session_state.stage
if stage==0:
    st.header('Upload your FTIR data')
    st.write('**Select original spectra** (TXT, CSV or a ZIP archive) using the sidebar. Each spectrum needs two numeric columns: wavenumber and absorbance. Header rows are allowed.')
    st.info('Choose TXT/CSV files or a ZIP archive in the left sidebar. Your files will remain available throughout all five steps.')
    files=st.session_state.spectra_files
    for message in st.session_state.upload_errors: st.warning(message)
    if files:
        rows=[];errors=[]
        for filename, content in files:
            try:
                x,y=read_spectrum(content,filename)
                n=int(np.count_nonzero((x>=1600)&(x<=1700)))
                rows.append({'File':filename,'Total points':len(x),'Amide I points':n,'Wavenumber min':float(np.min(x)),'Wavenumber max':float(np.max(x)),'Status':'Ready' if n>=15 else 'Insufficient Amide I points'})
            except Exception as e: errors.append(f'{filename}: {e}')
        st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
        for error in errors:st.error(error)
        if rows and all(row['Amide I points']>=15 for row in rows):
            st.success(f'{len(rows)} spectrum/spectra available for analysis.')
            st.button('Next: Configure analysis →',on_click=change_stage,args=(1,),type='primary')
    else:
        st.info('No spectra uploaded yet. Choose a TXT or CSV file above to begin.')
        with st.expander('See an example of the required file format'):
            st.code('Wavenumber\tAbsorbance\n1600\t0.0054\n1601\t0.0061\n1602\t0.0070\n...',language='text')
        st.caption('Your previous study summary is not raw spectrum data, so it cannot be re-fitted. It is available as an optional reference below.')
    with st.expander('Optional: view previous study summary (reference only)'):
        if PREV.exists():
            try:
                df=pd.read_excel(PREV,sheet_name='Summary')
                st.dataframe(df.round(4),hide_index=True,use_container_width=True)
            except Exception as e:st.error(f'Cannot load example summary: {e}')

elif stage==1:
    st.header('Configure analysis')
    files=st.session_state.spectra_files
    if not files: st.warning('Upload spectra using the sidebar first.')
    st.write('The defaults match the original notebook. For a first analysis, keep these settings unchanged.')
    st.markdown('**Model:** 5 Gaussian bands, fixed peak positions, linear endpoint baseline')
    st.markdown('**Peak centers:** 1652, 1630, 1679, 1671, 1645 cm⁻¹')
    with st.expander('Advanced fitting parameters',expanded=False):
        st.number_input('Maximum amplitude',min_value=.01,max_value=100.,value=1.,step=.1,key='amplitude_max')
        st.number_input('Maximum Gaussian width σ (cm⁻¹)',min_value=1.,max_value=200.,value=100.,step=5.,key='sigma_max')
        st.number_input('Initial Gaussian width σ (cm⁻¹)',min_value=.1,max_value=100.,value=10.,step=1.,key='initial_sigma')
        st.number_input('QC review threshold (R²)',min_value=0.0,max_value=1.0,value=0.95,step=0.01,key='review_r2_threshold',help='Screening threshold only; not scientific validation.')
    c1,c2=st.columns([1,2]);c1.button('← Back',on_click=change_stage,args=(0,))
    if files: c2.button('Next: Run analysis →',on_click=change_stage,args=(2,),type='primary')

elif stage==2:
    st.header('Run Gaussian analysis')
    files=st.session_state.spectra_files
    if not files:
        st.warning('Please upload your spectra first.');st.button('← Upload data',on_click=change_stage,args=(0,))
    else:
        st.write(f'**{len(files)} file(s) selected.** This step will apply baseline correction and fit the five Gaussian components to each file.')
        st.info('Press Run analysis to calculate the results. The app will not silently rerun fits while you browse your results.')
        if st.button('▶ Run analysis',type='primary'):
            rs=[];errs=[]
            for filename, content in files:
                try:
                    x,y=read_spectrum(content,filename)
                    rs.append(fit_spectrum(x,y,Path(filename).stem,amplitude_max=float(st.session_state.get('amplitude_max',1.)),sigma_max=float(st.session_state.get('sigma_max',100.)),initial_sigma=min(float(st.session_state.get('initial_sigma',10.)),float(st.session_state.get('sigma_max',100.)))))
                except Exception as e:errs.append({'File':filename,'Error':str(e)})
            st.session_state.results=rs;st.session_state.errors=errs
            st.session_state.run_signature=tuple((filename,len(content)) for filename,content in files)
            if rs:
                with st.spinner('Creating Excel report and all PNG/HTML figures...'):
                    generate_full_export()
                st.success(f'Analysis completed for {len(rs)} sample(s).')
                if st.session_state.export_error:
                    st.error(st.session_state.export_error)
                else:
                    st.info('The complete results ZIP is ready, including the Excel workbook and all charts.')
            if errs:st.error(f'{len(errs)} file(s) failed. See details below.')
        if st.session_state.errors:st.dataframe(pd.DataFrame(st.session_state.errors),hide_index=True,use_container_width=True)
        if st.session_state.results:st.button('Next: View results →',on_click=change_stage,args=(3,),type='primary')

elif stage==3:
    st.header('Review analysis results')
    results=st.session_state.results
    if not results:
        st.warning('No results yet. Run analysis in Step 3 first.');st.button('← Run analysis',on_click=change_stage,args=(2,))
    else:
        st.success(f'{len(results)} analyzed sample(s).')
        sm=summary_frame(results)
        st.dataframe(sm.style.format(precision=4),hide_index=True,use_container_width=True)
        flags=qc_records(results,export_settings())
        flagged=[(r.sample, notes) for r,notes in flags if notes]
        if flagged:
            st.warning(f'{len(flagged)} sample(s) flagged for review; see Quality Review sheet in the Excel report.')
            with st.expander('Quality review details'):
                st.dataframe(pd.DataFrame([{'Sample':name,'Notes':'; '.join(notes)} for name,notes in flagged]),hide_index=True)
        st.subheader('Compare samples')
        st.plotly_chart(comparison_plot(results),use_container_width=True)
        st.subheader('Inspect an individual spectrum')
        selected=st.selectbox('Choose sample',list(range(len(results))),format_func=lambda i:results[i].sample)
        r=results[selected]
        a,b,c=st.columns(3);a.metric('R²',f'{r.r2:.4f}');b.metric('RMSE',f'{r.rmse:.5f}');c.metric('Data points',str(len(r.x)))
        visible=st.multiselect('Show Gaussian components',list(LABELS),default=list(LABELS))
        st.plotly_chart(plot_spectrum(r,visible),use_container_width=True)
        with st.expander('Residual plot',expanded=True):
            fig=go.Figure();fig.add_scatter(x=r.x,y=r.residuals,name='Residual',line=dict(color='#22a4af'))
            fig.add_hline(y=0,line_dash='dash');fig.update_xaxes(autorange='reversed',title='Wavenumber (cm⁻¹)');fig.update_yaxes(title='Residual');fig.update_layout(height=250,margin=dict(l=10,r=10,t=10,b=10))
            st.plotly_chart(fig,use_container_width=True)
        with st.expander('Peak parameters and fitted data'):
            st.dataframe(r.parameters_table().style.format(precision=5),hide_index=True,use_container_width=True)
            st.dataframe(r.spectrum_table().head(30),hide_index=True,use_container_width=True)
        st.warning('Component percentages are relative fitted peak areas, not validated secondary-structure proportions. Evaluate residuals and model assumptions.')
        if st.session_state.export_archive:
            st.download_button('⬇ Download complete results (Excel + PNG + HTML + CSV/TXT)',
                data=st.session_state.export_archive,file_name='FTIR_Analysis_Results.zip',
                mime='application/zip',type='primary')
        st.button('Next: Download everything →',on_click=change_stage,args=(4,))

elif stage==4:
    st.header('Download complete analysis package')
    results=st.session_state.results
    if not results:
        st.warning('No fitted results yet. Upload spectra and run analysis first.');st.button('← Upload data',on_click=change_stage,args=(0,))
    else:
        st.write(f'**{len(results)} analyzed samples.** Your complete research package is generated automatically from the uploaded raw spectra.')
        st.markdown('**Included:** Excel dashboard with editable native QC chart, summary and Quality Review, complete PDF with all figures, four PNG plots per sample, three comparison figures, interactive HTML plots, fitted CSV/TXT data and analysis settings.')
        if not st.session_state.export_archive and not st.session_state.export_error:
            with st.spinner('Generating complete export...'):
                generate_full_export()
        if st.session_state.export_error:
            st.error(st.session_state.export_error)
            st.button('Try generating ZIP again',on_click=generate_full_export)
        if st.session_state.export_archive:
            archive=st.session_state.export_archive
            st.download_button('⬇ Download complete results ZIP',data=archive,
                file_name='FTIR_Analysis_Results.zip',mime='application/zip',type='primary')
            with zipfile.ZipFile(BytesIO(archive)) as packaged:
                names=packaged.namelist()
            png_count=sum(n.lower().endswith('.png') for n in names)
            xlsx_count=sum(n.lower().endswith('.xlsx') for n in names)
            pdf_count=sum(n.lower().endswith('.pdf') for n in names)
            st.success(f'ZIP ready: {len(names)} files · {xlsx_count} Excel · {pdf_count} PDF · {png_count} PNG figures · {len(archive)/1024/1024:.1f} MB')

st.divider()
st.caption('Research tool based on the supplied notebook, which credits anastasia-ragulskaya/FTIR_code. Verify original license before redistributing adapted code. No structure assignments are independently validated.')
