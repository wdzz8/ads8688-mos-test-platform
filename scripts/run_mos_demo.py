"""Acquire real PCB1 dynamics with bounded drain power and preserved raw data."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import serial

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.capture_fixed_vgs_output import DEFAULT_VIVADO, verified_off, check_enabled
from scripts.dps_control import DpsController
from scripts.experiment_data import load_capture, summarize
from scripts.manual_voltage_calibration import vivado

def save(path,data):
    path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')

def capture(directory,frequency,low,high,action='capture',restart=False,depth=8192):
    half=round(50_000_000/(2*frequency))
    vivado(DEFAULT_VIVADO,'control_mos_experiment.tcl',
           [directory,action,low,high,half,int(low!=high),depth,int(restart)],directory/'capture.log')
    rows=load_capture(directory/'rows.csv',depth,{low,high})
    result=summarize(rows)
    result.update(csv=str(directory/'rows.csv'),requested_frequency_Hz=frequency,
                  configured_frequency_Hz=50_000_000/(2*half))
    if low!=high and len(result['by_code'])!=2:
        raise ValueError('Both commanded gate levels must be present')
    return result

def powered_capture(controller,directory,frequency,low,high,voltage,depth=8192):
    half=round(50_000_000/(2*frequency))
    command=[os.environ.get('COMSPEC','cmd.exe'),'/d','/c',str(DEFAULT_VIVADO),
        '-mode','batch','-source',str(ROOT/'scripts/control_mos_experiment.tcl'),
        '-notrace','-nolog','-nojournal','-tclargs',str(directory),'capture',str(low),
        str(high),str(half),str(int(low!=high)),str(depth),'0']
    record={'success':False,'samples':[],'voltage_set_V':voltage}
    child=None
    started=None
    try:
        record['configured_off']=controller.configure(f'{voltage:.2f}','0.020')
        if record['configured_off']['protection_raw']:
            raise RuntimeError('DPS protection active before output enable')
        started=time.monotonic()
        controller._write_verified(9,1)
        time.sleep(0.25)
        enabled=controller.status('dynamic_output_on')
        check_enabled(enabled,voltage,'0.020')
        record['output_on_verified']=enabled
        env=os.environ.copy()
        env['PROCESSOR_ARCHITECTURE']='AMD64'
        with (directory/'capture.log').open('w',encoding='utf-8') as handle:
            child=subprocess.Popen(command,cwd=ROOT,env=env,stdout=handle,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            while child.poll() is None:
                if time.monotonic()-started>=45: raise TimeoutError('45 s drain window exceeded')
                status=controller.status('dynamic_output_sample')
                record['samples'].append({'elapsed_s':time.monotonic()-started,**status})
                check_enabled(status,voltage,'0.020')
                time.sleep(0.4)
            if child.returncode: raise RuntimeError(f'Vivado exited {child.returncode}')
    finally:
        try:
            record['off_after']=verified_off(controller)
            if started is not None: record['output_window_s']=time.monotonic()-started
        finally:
            if child is not None and child.poll() is None:
                subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True,timeout=10,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                child.wait(timeout=10)
            save(directory/'power.json',record)
    rows=load_capture(directory/'rows.csv',depth,{low,high})
    record['summary']=summarize(rows)
    if len(record['summary']['by_code'])!=len({low,high}): raise ValueError('Missing gate level')
    record.update(success=True,csv=str(directory/'rows.csv'))
    save(directory/'power.json',record)
    return record

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',default='COM3')
    parser.add_argument('--frequencies',type=float,nargs='+',default=[1,5,10])
    parser.add_argument('--voltage',type=float,default=3)
    parser.add_argument('--low-code',type=int,default=256)
    parser.add_argument('--high-code',type=int,default=2816)
    args=parser.parse_args()
    if (any(f not in (1,5,10) for f in args.frequencies) or not 0<args.voltage<=3
        or not 0<=args.low_code<args.high_code<=2944):
        parser.error('Use 1/5/10 Hz, drain <=3 V and 0<=LOW<HIGH<=2944')
    out=ROOT/'output/pcb1/dynamic'/datetime.now().strftime('run_%Y%m%d_%H%M%S_%f')
    out.mkdir(parents=True)
    bit=ROOT/'output/mos_experiment/mos_experiment.bit'
    report={'source':'real_PCB1_dynamic_ILA_and_DPS','success':False,
        'started_at_utc':datetime.now(timezone.utc).isoformat(),'bit':str(bit),
        'bit_sha256':hashlib.sha256(bit.read_bytes()).hexdigest(),
        'low_code':args.low_code,'high_code':args.high_code,'current_limit_A':0.020,'results':[],
        'notes':['Unaveraged sequential ADC data with per-channel times.',
                 'INA gain and shunt remain nominal; absolute calibration pending.',
                 'Low-frequency system response is not intrinsic MOS switching time.']}
    report_path=out/'dynamic_report.json'
    connection=serial.Serial(port=None,baudrate=9600,timeout=1.5,write_timeout=1.5)
    connection.port=args.port
    connection.dtr=connection.rts=False
    save(report_path,report)
    with connection:
        controller=DpsController(connection)
        try:
            report['off_before']=verified_off(controller)
            program=out/'program'; program.mkdir()
            report['initial_low_gate']=capture(program,1,256,256,'program',depth=128)
            save(report_path,report)
            for frequency in args.frequencies:
                point={'frequency_Hz':frequency,'success':False}
                report['results'].append(point)
                for attempt in range(2):
                    zero=out/f'zero_{frequency:g}Hz_{attempt}'; zero.mkdir()
                    try:
                        point['zero']=capture(zero,frequency,args.low_code,args.high_code,restart=bool(attempt))
                        break
                    except (ValueError,SystemExit) as error:
                        point.setdefault('rejected_preflight',[]).append(str(error))
                        if attempt: raise
                powered=out/f'powered_{frequency:g}Hz'; powered.mkdir()
                point['powered']=powered_capture(controller,powered,frequency,args.low_code,args.high_code,args.voltage)
                point['success']=True
                save(report_path,report)
                print(f'DYNAMIC {frequency:g} Hz: 8192 rows; drain OFF',flush=True)
            report['success']=True
        except BaseException as error:
            report['error']=f'{type(error).__name__}: {error}'
            raise
        finally:
            try:
                report['final_off']=verified_off(controller)
                restore=out/'restore_low'; restore.mkdir(exist_ok=True)
                report['final_low_gate']=capture(restore,1,256,256,depth=128)
            except BaseException as error:
                report['success']=False
                report['cleanup_error']=f'{type(error).__name__}: {error}'
                raise
            finally:
                report['finished_at_utc']=datetime.now(timezone.utc).isoformat()
                save(report_path,report)
                print(report_path,flush=True)

if __name__=='__main__': main()
