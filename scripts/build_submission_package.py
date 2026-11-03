"""Freeze measured evidence, sources and revised media into a portable submission."""
from __future__ import annotations
import argparse
from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'output/submission_20261103'
DEST = OUT/'MOS_FPGA_submission_20261103'
sys.path.insert(0, str(ROOT))
REPORTS = {
    'static': 'output/pcb1/fixed_vgs_20261102/family_20261102_173244/analysis/fixed_vgs_output_analysis.json',
    'transfer': 'output/pcb1/transfer/run_20261102_222410_092311/transfer_report.json',
    'dynamic_report': 'output/pcb1/dynamic/run_20261102_215847_036499/dynamic_report.json',
    'dynamic_video': 'output/pcb1/dynamic/run_20261103_194724_993590/dynamic_report.json',
    'failed_transfer': 'output/pcb1/transfer/run_20261103_174139_900328/transfer_report.json',
}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def strings(value):
    if isinstance(value, str): yield value
    elif isinstance(value, dict):
        for item in value.values(): yield from strings(item)
    elif isinstance(value, list):
        for item in value: yield from strings(item)


def local_path(text):
    # Only real project paths; do not interpret arbitrary log text as a filename.
    if len(text)>500 or '\n' in text: return None
    prefix = str(ROOT).replace('\\','/')
    normalized = text.replace('\\','/')
    if normalized.lower().startswith(prefix.lower()+'/'):
        return ROOT/normalized[len(prefix)+1:]
    if normalized.startswith(('output/','demo/','rtl/','scripts/','constr/','tests/')):
        return ROOT/normalized
    return None


def portable(value):
    if isinstance(value, str):
        # Also remove the old root in embedded error messages; preserve all measured values.
        if str(ROOT)+'\\' in value or ROOT.as_posix()+'/' in value:
            return value.replace(str(ROOT)+'\\', '').replace(ROOT.as_posix()+'/', '').replace('\\','/')
        if value.startswith(('output\\','demo\\','rtl\\','scripts\\','constr\\','tests\\')):
            return value.replace('\\','/')
        return value
    if isinstance(value, dict): return {k: portable(v) for k,v in value.items()}
    if isinstance(value, list): return [portable(v) for v in value]
    return value


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n',encoding='utf-8')


def collect():
    paths=set(); pending=deque(ROOT/p for p in REPORTS.values()); visited=set()
    while pending:
        path=pending.popleft().resolve()
        if path in visited: continue
        visited.add(path)
        if not path.is_file(): raise FileNotFoundError(path)
        paths.add(path)
        if path.suffix.lower()=='.json':
            data=json.loads(path.read_text(encoding='utf-8'))
            for text in strings(data):
                candidate=local_path(text)
                if candidate and candidate.is_file(): pending.append(candidate)
            # Keep capture context and failure logs beside raw CSVs/reports.
            if path.name.endswith('_report.json'):
                for other in path.parent.rglob('*'):
                    if other.is_file() and other.suffix.lower() in ('.csv','.json','.log','.txt'):
                        pending.append(other)
    for folder in ('rtl','constr','scripts','tests','demo'):
        for path in (ROOT/folder).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix.lower() in ('.v','.sv','.xdc','.py','.tcl','.ps1','.md','.txt','.html','.css','.js','.json','.png','.jpg','.svg'):
                paths.add(path)
    paths.update(p for p in ROOT.iterdir() if p.is_file() and p.suffix.lower() in ('.md','.txt'))
    for name in ('mos_experiment.bit','mos_experiment.ltx','timing_summary.rpt','drc.rpt','bus_skew.rpt','build.log'):
        paths.add(ROOT/'output/mos_experiment'/name)
    paths.add(ROOT/'output/mos_experiment_sim/xsim.log')
    for name in ('技术文档_修订版.docx','技术文档_修订版.pdf','report_changes.json','交付说明.md','media_verification.json'):
        paths.add(OUT/name)
    for path in (OUT/'video').iterdir():
        if path.is_file() and not path.name.startswith(('review_','contact_')):
            paths.add(path)
    paths.update(p for p in (OUT/'video/sources').iterdir() if p.is_file())
    paths.update((OUT/'video/build').glob('*_voice.mp3'))
    paths.add(ROOT/'output/technical_report/技术文档_完整版.docx')
    paths.add(ROOT/'tmp/technical_report/hardware_montage.jpg')
    # Explicit supplemental diagnostics referenced by the report, if available.
    for p in (ROOT/'output/pcb1/adc_fault_diagnostic').rglob('*'):
        if p.is_file() and p.suffix.lower() in ('.json','.csv','.log','.txt'):paths.add(p)
    return paths


def build():
    paths=collect()
    print(json.dumps({'files':len(paths),'source_MB':round(sum(p.stat().st_size for p in paths)/1e6,1),
                      'extensions':dict(Counter(p.suffix.lower() for p in paths))}),flush=True)
    DEST.mkdir(parents=True,exist_ok=True)
    transforms=[]
    for source in sorted(paths):
        relative=source.relative_to(ROOT); target=DEST/relative; target.parent.mkdir(parents=True,exist_ok=True)
        if source.suffix.lower()=='.json':
            data=json.loads(source.read_text(encoding='utf-8')); normalized=portable(data)
            if data!=normalized:
                archive=DEST/'provenance/original_json'/relative
                archive.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,archive)
                write(target,normalized)
                transforms.append({'path':relative.as_posix(),'original_sha256':sha(source),
                                   'portable_sha256':sha(target),'original_copy':archive.relative_to(DEST).as_posix()})
            else:shutil.copy2(source,target)
        else:shutil.copy2(source,target)
    write(DEST/'provenance/path_transforms.json',{'rule':'Only workstation path text is made relative; numeric and boolean values are unchanged.', 'files':transforms})
    import scripts.verify_submission as verify
    evidence={'frozen_on':'2026-11-03','reports':REPORTS,
              'bit_sha256':sha(ROOT/'output/mos_experiment/mos_experiment.bit'),
              'historical_static_and_transfer_firmware':'Historical corresponding builds; not proof of new protection logic.',
              'calibration_complete':False,'board_fault_injection_complete':False,
              'independent_repeated_runs_complete':False}
    # Compute the expected metrics from the original, unmodified workstation records.
    evidence['expected_metrics']=verify.recompute(evidence)
    write(DEST/'submission_evidence.json',evidence)
    git_head=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
    dirty=subprocess.run(['git','status','--porcelain','-uno'],cwd=ROOT,capture_output=True,text=True,check=True).stdout
    write(DEST/'provenance/source_snapshot.json',{'base_git_head':git_head,'tracked_worktree_dirty':bool(dirty),
          'snapshot':'Files copied from the current workspace; not claimed identical to the remote commit.',
          'source_files':[p.relative_to(ROOT).as_posix() for p in sorted(paths) if p.parts[len(ROOT.parts)] in ('rtl','constr','scripts','tests')]})
    shutil.copy2(OUT/'交付说明.md',DEST/'先读我.md')
    # Remove only stale files inside this generated package, never source workspace files.
    # The manifest is rebuilt from the complete package actually being submitted.
    manifest=[]
    for path in sorted(DEST.rglob('*')):
        if path.is_file() and path.name!='submission_manifest.json' and 'offline_recheck' not in path.parts:
            manifest.append({'path':path.relative_to(DEST).as_posix(),'bytes':path.stat().st_size,'sha256':sha(path)})
    write(DEST/'submission_manifest.json',{'format_version':1,'algorithm':'SHA-256','manifest_self_excluded':True,'files':manifest})
    print(f'Frozen {len(manifest)} files at {DEST}',flush=True)


def archive():
    target=OUT/'MOS_FPGA_修订交付包_20261103.zip'
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=5) as z:
        for p in sorted(DEST.rglob('*')):
            if p.is_file() and 'offline_recheck' not in p.parts:
                z.write(p,p.relative_to(DEST.parent).as_posix())
    (OUT/'MOS_FPGA_修订交付包_20261103.sha256.txt').write_text(sha(target)+'  '+target.name+'\n',encoding='utf-8')
    print(json.dumps({'archive':str(target),'bytes':target.stat().st_size,'sha256':sha(target)},ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--zip-only',action='store_true');args=parser.parse_args()
    if not args.zip_only:build()
    archive()
