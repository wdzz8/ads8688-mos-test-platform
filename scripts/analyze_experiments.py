"""Revalidate hardware evidence, extract parameters and build a portable demo dataset."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.experiment_data import load_capture
from scripts.analyze_fixed_vgs_family import analyze_report

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def portable(value):
    """Strip this workstation's absolute project prefix from release JSON."""
    if isinstance(value, str):
        root_text = str(ROOT.resolve())
        if value.startswith(root_text):
            return value[len(root_text):].lstrip('\\/').replace('\\', '/')
        return value
    if isinstance(value, list): return [portable(item) for item in value]
    if isinstance(value, dict): return {key: portable(item) for key, item in value.items()}
    return value

def write(path,value):
    Path(path).write_text(json.dumps(portable(value),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def latest_success(folder,name):
    paths=sorted((ROOT/folder).glob('run_*/'+name),reverse=True)
    return next((p for p in paths if read(p).get('success') is True),None)
def check_off(status):
    if status.get('output_enabled') is not False or status.get('voltage_out_V')!=0:
        raise ValueError('Missing verified drain OFF evidence')
def validate_power(power):
    if power.get('success') is not True:raise ValueError('Unsuccessful powered capture')
    check_off(power['configured_off']);check_off(power['off_after'])
    observations=[power['output_on_verified']]+power['samples']
    for s in observations:
        if s.get('model')!=3005 or not s.get('output_enabled') or s.get('protection_raw')!=0:
            raise ValueError('Invalid DPS powered readback')
        if s['voltage_set_V']>3 or s['current_limit_A']>0.020:
            raise ValueError('DPS outside experiment envelope')

def knee_fit(vds,current):
    """Nonnegative empirical saturation law I=A*V/(V+K); no Vth claim."""
    x=np.asarray(vds,float);y=np.asarray(current,float)
    if len(x)<3 or np.any(x<=0):raise ValueError('Need positive VDS points')
    knees=np.geomspace(0.0001,2,2400)
    basis=x[None,:]/(x[None,:]+knees[:,None])
    amplitudes=np.maximum(basis@y/np.sum(basis*basis,axis=1),0)
    predictions=amplitudes[:,None]*basis
    mse=np.mean((predictions-y)**2,axis=1);best=int(np.argmin(mse))
    return {'A_mA':float(amplitudes[best]),'K_V':float(knees[best]),
            'RMSE_mA':float(mse[best]**0.5),'boundary_hit':best in (0,len(knees)-1)}
def knee_predict(fit,x):
    x=np.asarray(x,float);return fit['A_mA']*x/(x+fit['K_V'])

def analyze_static():
    family=ROOT/'output/pcb1/fixed_vgs_20261102/family_20261102_173244/analysis/fixed_vgs_output_analysis.json'
    cached=read(family);points=[];curves=[]
    for curve in cached['curves']:
        rows,summary=analyze_report(curve['report'],curve['zero_csv'])
        points.extend(rows);curves.append(summary)
    result=[]
    for c in sorted(curves,key=lambda c:c['dac_code']):
        p=sorted([r for r in points if r['dac_code']==c['dac_code']],key=lambda r:r['VDS_source_zero_corrected_V'])
        x=np.array([r['VDS_source_zero_corrected_V'] for r in p]);y=np.array([r['ID_nominal_mA'] for r in p])
        fit=knee_fit(x,y);held=[]
        for index in range(len(x)):
            keep=np.arange(len(x))!=index;f=knee_fit(x[keep],y[keep]);held.append(float(knee_predict(f,x[index])))
        fit['leave_one_point_out_RMSE_mA']=float(np.mean((np.array(held)-y)**2)**0.5)
        grid=np.linspace(0,max(x),160)
        result.append({'code':c['dac_code'],'VGS_V':c['VGS_source_zero_corrected_mean_V'],
            'points':[{'VDS_V':float(a),'ID_mA':float(b),'repeat_SD_mA':p[i]['ID_repeat_SD_mA'],
                       'held_out_prediction_mA':held[i],'csv':p[i]['csv']} for i,(a,b) in enumerate(zip(x,y))],
            'model':fit,'fit_curve':[[float(a),float(b)] for a,b in zip(grid,knee_predict(fit,grid))]})
    return {'valid_rows':sum(c['valid_rows'] for c in curves),'curves':result,
            'model_formula':'ID = A * VDS / (VDS + K)',
            'model_scope':'Empirical compact fit per measured gate level; not a MOS intrinsic parameter model.',
            'validation':'Each held-out point is predicted using the other six points of the same curve.'}

def threshold_edges(t,y):
    low,high=np.percentile(y,[10,90]);threshold=(low+high)/2
    if high-low<0.1:raise ValueError('Gate swing missing')
    state=np.asarray(y)>=threshold
    at=np.flatnonzero(np.diff(state.astype(int)))+1
    events=[]
    for i in at:
        fraction=(threshold-y[i-1])/(y[i]-y[i-1])
        events.append((float(t[i-1]+fraction*(t[i]-t[i-1])),bool(state[i])))
    return events

def analyze_dynamic(path):
    report=read(path)
    if report.get('success') is not True:raise ValueError('Dynamic run incomplete')
    check_off(report['final_off']);results=[]
    for item in report['results']:
        if item.get('success') is not True:raise ValueError('Incomplete frequency')
        power=item['powered'];validate_power(power)
        low,high=report['low_code'],report['high_code']
        zero=load_capture(item['zero']['csv'],8192,{low,high})
        rows=load_capture(power['csv'],8192,{low,high})
        t=np.array([r['time_CH0_s'] for r in rows]);vg=np.array([r['CH0_V'] for r in rows])
        z={}
        for code in (low,high):
            q=[r for r in zero if not r['row_transition'] and r['vg_code']==code]
            z[code]={c:float(np.median([r[f'CH{c}_V'] for r in q])) for c in (0,2,7)}
        blend=np.clip((vg-z[low][0])/(z[high][0]-z[low][0]),0,1)
        source_zero=z[low][2]+blend*(z[high][2]-z[low][2])
        source_delta=np.array([r['CH2_V'] for r in rows])-source_zero
        vgs=vg-source_delta
        vds=np.array([r['CH1_V'] for r in rows])-source_delta
        baseline=z[low][7]+blend*(z[high][7]-z[low][7])
        current=(np.array([r['CH7_V'] for r in rows])-baseline)*500
        events=threshold_edges(t,vg);rises=np.array([a for a,b in events if b])
        if len(rises)<3:raise ValueError('Not enough complete periods')
        periods=np.diff(rises);duties=[]
        for a,b in zip(rises[:-1],rises[1:]):
            falls=[e for e,s in events if not s and a<e<b]
            if len(falls)==1:duties.append((falls[0]-a)/(b-a))
        metric={'frequency_requested_Hz':item['frequency_Hz'],
            'frequency_measured_Hz':float(1/np.mean(periods)),
            'complete_periods':len(periods),'period_SD_s':float(np.std(periods,ddof=1)) if len(periods)>1 else 0,
            'duty_mean':float(np.mean(duties)),'valid_rows':len(rows),
            'transition_rows':sum(r['row_transition'] for r in rows),'plateaus':{}}
        distance=np.min(np.abs(t[:,None]-np.array([e for e,_ in events])[None,:]),axis=1)
        for code in (low,high):
            mask=np.array([r['vg_code']==code and not r['row_transition'] for r in rows]) & (distance>0.005)
            metric['plateaus'][str(code)]={'samples':int(sum(mask)),'VGS_V':float(np.median(vgs[mask])),
                'VDS_V':float(np.median(vds[mask])),'ID_nominal_mA':float(np.median(current[mask])),
                'ID_repeat_SD_mA':float(np.std(current[mask],ddof=1))}
        # Keep all raw time samples in the offline demo; metrics never use downsampling.
        trace={'time_VG_s':t.tolist(),'time_VD_s':[r['time_CH1_s'] for r in rows],
               'time_INA_s':[r['time_CH7_s'] for r in rows],
               'VG_V':vg.tolist(),'VD_V':[r['CH1_V'] for r in rows],
               'ID_nominal_mA':current.tolist()}
        results.append({'metrics':metric,'trace':trace,'csv':power['csv'],'zero_csv':item['zero']['csv']})
    return {'report':str(path),'results':results,'row_period_s':0.000416,
        'channel_interval_s':0.000052,'CH0_to_CH7_skew_s':0.000364,
        'notes':['Each channel is sampled sequentially, not simultaneously.',
                 'VG and VD traces retain raw ADC voltages; current subtracts a gate-dependent matched OFF baseline.',
                 'Platform metrics use source-zero correction, exclude transition rows and a 5 ms edge guard.',
                 'Low-frequency acquisition characterizes the whole instrument; no intrinsic MOS switching time claim.']}

def analyze_transfer(path):
    report=read(path)
    if report.get('success') is not True:raise ValueError('Transfer run incomplete')
    check_off(report['final_off']);points=[]
    for item in report['results']:
        if not item['success']:raise ValueError('Transfer point incomplete')
        accepted=item['iterations'][item['accepted_iteration']]
        power=accepted['power'];validate_power(power);code=item['dac_code']
        zero=load_capture(item['zero']['csv'],128,{code});rows=load_capture(power['csv'],128,{code})
        mean=lambda data,c:float(np.mean([r[f'CH{c}_V'] for r in data]))
        vs=mean(rows,2)-mean(zero,2);vgs=mean(rows,0)-vs;vds=mean(rows,1)-vs
        if abs(vds-report['target_VDS_V'])>report['tolerance_V']:raise ValueError('VDS outside accepted tolerance')
        current=(mean(rows,7)-mean(zero,7))*500
        points.append({'code':code,'VGS_V':vgs,'VDS_V':vds,'ID_nominal_mA':current,
            'repeat_SD_mA':float(np.std([r['CH7_V']*500 for r in rows],ddof=1)),
            'iterations':len(item['iterations']),'csv':power['csv'],'zero_csv':item['zero']['csv']})
    points.sort(key=lambda p:p['VGS_V']);x=np.array([p['VGS_V'] for p in points]);y=np.array([p['ID_nominal_mA'] for p in points])
    gm=np.gradient(y,x)
    for i,p in enumerate(points):p['gm_finite_difference_mS']=float(gm[i])
    crossing=None
    if min(y)<=1<=max(y):
        order=np.argsort(y);crossing=float(np.interp(1,y[order],x[order]))
    use=y>=0.2
    fit=None
    if sum(use)>=4:
        slope,intercept=np.polyfit(x[use],np.sqrt(y[use]),1);pred=(slope*x[use]+intercept)**2
        sensitivity=[]
        for cutoff in (0.1,0.2,0.4):
            m=y>=cutoff
            if sum(m)>=4:
                a,b=np.polyfit(x[m],np.sqrt(y[m]),1);sensitivity.append({'min_current_mA':cutoff,'Vth_proxy_V':float(-b/a),'n':int(sum(m))})
        fit={'method':'linear sqrt(ID) versus VGS for ID >= 0.2 mA',
             'Vth_proxy_V':float(-intercept/slope),'coefficient_mA_per_V2':float(slope*slope),
             'RMSE_mA':float(np.mean((pred-y[use])**2)**0.5),'fit_samples':int(sum(use)),
             'range_sensitivity':sensitivity,
             'scope':'Finite VDS=0.5 V, nominal current scale and limited gate range: trend proxy only, not datasheet VGS(th).'}
    return {'report':str(path),'target_VDS_V':report['target_VDS_V'],
        'tolerance_V':report['tolerance_V'],'points':points,'VGS_at_1mA_V':crossing,
        'max_gm_mS':float(max(gm)),'threshold_trend_fit':fit}

def make_plots(data,out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,ax=plt.subplots(figsize=(9,5))
    for c in data['static']['curves']:
        p=c['points'];line=ax.errorbar([r['VDS_V'] for r in p],[r['ID_mA'] for r in p],
            yerr=[r['repeat_SD_mA'] for r in p],fmt='o',ms=4,label=f"VGS {c['VGS_V']:.3f} V (measured)")
        f=np.array(c['fit_curve']);ax.plot(f[:,0],f[:,1],color=line[0].get_color(),lw=1.3)
    ax.set(xlabel='VDS, source-zero corrected / V',ylabel='ID, nominal scaling / mA',title='Real PCB1 output curves and empirical saturation fits')
    ax.grid(alpha=.2);ax.legend(fontsize=8);fig.tight_layout();fig.savefig(out/'output_model.png',dpi=170);plt.close(fig)
    fig,axes=plt.subplots(3,1,figsize=(10,8))
    for ax,r in zip(axes,data['dynamic']['results']):
        tr=r['trace'];m=r['metrics'];t=np.array(tr['time_VG_s']);mask=(t>=0)&(t<=min(3/m['frequency_requested_Hz'],3.3))
        ax.plot(t[mask],np.array(tr['VG_V'])[mask],label='VG raw / V',color='#327bba')
        ax.plot(np.array(tr['time_VD_s'])[mask],np.array(tr['VD_V'])[mask],label='VD raw / V',color='#cb8430')
        ax.set(xlabel='Time from first CH7 sample / s',ylabel='Voltage / V',title=f"{m['frequency_requested_Hz']:g} Hz requested; {m['frequency_measured_Hz']:.5f} Hz measured")
        ax.grid(alpha=.2);ax.legend(fontsize=8,loc='upper right')
    fig.tight_layout();fig.savefig(out/'dynamic_waveforms.png',dpi=160);plt.close(fig)
    if data.get('transfer'):
        p=data['transfer']['points'];fig,axes=plt.subplots(1,2,figsize=(11,4.5))
        x=[r['VGS_V'] for r in p]
        axes[0].errorbar(x,[r['ID_nominal_mA'] for r in p],yerr=[r['repeat_SD_mA'] for r in p],fmt='o-',capsize=3)
        axes[0].set(xlabel='VGS, source-zero corrected / V',ylabel='ID, nominal scaling / mA',title='Transfer curve: VDS controlled near 0.5 V')
        axes[1].plot(x,[r['gm_finite_difference_mS'] for r in p],'o-');axes[1].set(xlabel='VGS / V',ylabel='Finite-difference gm / mS',title='Measured local transconductance trend')
        for a in axes:a.grid(alpha=.2)
        fig.tight_layout();fig.savefig(out/'transfer_gm.png',dpi=170);plt.close(fig)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,default=ROOT/'demo/data');args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    dynamic=latest_success('output/pcb1/dynamic','dynamic_report.json')
    if dynamic is None:raise ValueError('No successful real dynamic run')
    data={'source':'revalidated real PCB1 CSV and DPS readback; no synthetic traces',
        'scaling':{'ina_gain_nominal':20,'shunt_nominal_ohm':0.1,'absolute_calibration_complete':False},
        'static':analyze_static(),'dynamic':analyze_dynamic(dynamic)}
    transfer=latest_success('output/pcb1/transfer','transfer_report.json')
    if transfer:data['transfer']=analyze_transfer(transfer)
    write(out/'experiment_analysis.json',data);make_plots(data,out)
    print(json.dumps({'out':str(out),'static_rows':data['static']['valid_rows'],
        'dynamic_rows':sum(r['metrics']['valid_rows'] for r in data['dynamic']['results']),
        'transfer_points':len(data.get('transfer',{}).get('points',[]))},ensure_ascii=False))

if __name__=='__main__':main()
