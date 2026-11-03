"""Measure a real constant-VDS transfer curve using bounded host feedback."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import serial

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_mos_demo import capture, powered_capture, save
from scripts.capture_fixed_vgs_output import verified_off
from scripts.dps_control import DpsController


def resume_state(previous, default_supply=0.5):
    successful = [point for point in previous.get('results', [])
                  if point.get('success') is True]
    supply = default_supply
    if successful:
        iterations = successful[-1].get('iterations', [])
        if not iterations:
            raise ValueError('Last successful point has no feedback iteration')
        last = iterations[-1]
        supply = round(last['supply_set_V'] + last['error_V'], 2)
    if not 0.05 <= supply <= 3.0:
        raise ValueError('Resume supply outside envelope')
    return successful, supply


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',default='COM3')
    parser.add_argument('--resume',type=Path)
    args=parser.parse_args()
    target,tolerance=0.5,0.015
    out=ROOT/'output/pcb1/transfer'/datetime.now().strftime('run_%Y%m%d_%H%M%S_%f')
    out.mkdir(parents=True)
    report={'source':'real_PCB1_constant_VDS_host_feedback','success':False,
        'started_at_utc':datetime.now(timezone.utc).isoformat(),
        'target_VDS_V':target,'tolerance_V':tolerance,'max_supply_V':3.0,
        'current_limit_A':0.020,'codes':list(range(2304,2817,64)),'results':[],
        'notes':['Nominal ADC/INA scaling; source-channel matched OFF correction.',
                 'Each feedback observation is followed by verified drain OFF.',
                 'This is host feedback between captures, not a fast FPGA servo.']}
    report_path=out/'transfer_report.json'
    if args.resume:
        previous=json.loads(args.resume.read_text(encoding='utf-8'))
        if (previous.get('source')!=report['source'] or previous.get('target_VDS_V')!=target
            or previous.get('tolerance_V')!=tolerance):
            raise ValueError('Resume report has incompatible settings')
        report['resumed_from']=str(args.resume.resolve())
        report['results'],supply=resume_state(previous,target)
    save(report_path,report)
    connection=serial.Serial(port=None,baudrate=9600,timeout=1.5,write_timeout=1.5)
    connection.port=args.port;connection.dtr=connection.rts=False
    if not args.resume:supply=target
    with connection:
        controller=DpsController(connection)
        try:
            report['off_before']=verified_off(controller)
            initial=out/'initial_low';initial.mkdir()
            report['initial_low']=capture(initial,1,256,256,restart=True,depth=128)
            for code in report['codes']:
                if any(p['dac_code']==code and p['success'] for p in report['results']):continue
                point={'dac_code':code,'success':False,'iterations':[]}
                report['results'].append(point)
                save(report_path,report)
                zero=out/f'code_{code}_zero';zero.mkdir()
                try:
                    point['zero']=capture(zero,1,code,code,depth=128)
                except ValueError as error:
                    point['rejected_zero']=str(error)
                    retry=out/f'code_{code}_zero_retry';retry.mkdir()
                    point['zero']=capture(retry,1,code,code,restart=True,depth=128)
                z=point['zero']['by_code'][str(code)]
                for iteration in range(6):
                    directory=out/f'code_{code}_iteration_{iteration}';directory.mkdir()
                    observation=powered_capture(controller,directory,1,code,code,supply,depth=128)
                    measured=observation['summary']['by_code'][str(code)]
                    vs=measured['CH2_V_mean']-z['CH2_V_mean']
                    vds=measured['CH1_V_mean']-vs
                    error=target-vds
                    item={'iteration':iteration,'supply_set_V':supply,'VDS_V':vds,
                          'VGS_V':measured['CH0_V_mean']-vs,
                          'ID_nominal_mA':(measured['CH7_V_mean']-z['CH7_V_mean'])*500,
                          'error_V':error,'power':observation}
                    point['iterations'].append(item)
                    save(report_path,report)
                    if abs(error)<=tolerance:
                        point.update(success=True,accepted_iteration=iteration)
                        print(f'TRANSFER DAC={code} VGS={item["VGS_V"]:.5f} VDS={vds:.5f} ID={item["ID_nominal_mA"]:.5f} mA OFF',flush=True)
                        break
                    proposed=round(supply+error,2)
                    if not 0.05<=proposed<=3.0 or proposed==supply:
                        raise RuntimeError(f'VDS target unreachable inside supply envelope at DAC {code}')
                    supply=proposed
                if not point['success']:raise RuntimeError(f'VDS did not converge at DAC {code}')
                save(report_path,report)
            report['success']=True
        except BaseException as error:
            report['error']=f'{type(error).__name__}: {error}'
            raise
        finally:
            try:
                report['final_off']=verified_off(controller)
                restore=out/'restore_low';restore.mkdir(exist_ok=True)
                try:
                    report['final_low']=capture(restore,1,256,256,depth=128)
                except ValueError as error:
                    report['rejected_final_low']=str(error)
                    retry=out/'restore_low_retry';retry.mkdir(exist_ok=True)
                    report['final_low']=capture(retry,1,256,256,restart=True,depth=128)
            except BaseException as error:
                report['success']=False;report['cleanup_error']=f'{type(error).__name__}: {error}'
                raise
            finally:
                report['finished_at_utc']=datetime.now(timezone.utc).isoformat()
                save(report_path,report)
                print(report_path,flush=True)

if __name__=='__main__':main()
