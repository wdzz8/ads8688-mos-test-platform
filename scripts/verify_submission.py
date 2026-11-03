"""Verify a frozen delivery and recompute its evidence offline; never control hardware."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inside(relative):
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f'Path escapes submission: {relative}')
    return path


def compare(actual, expected, context='metrics'):
    if isinstance(expected, dict):
        for key, value in expected.items():
            compare(actual[key], value, f'{context}.{key}')
    elif isinstance(expected, list):
        if len(actual) != len(expected):
            raise ValueError(f'{context}: length mismatch')
        for i, (a, b) in enumerate(zip(actual, expected)):
            compare(a, b, f'{context}[{i}]')
    elif isinstance(expected, float):
        if not math.isclose(float(actual), expected, rel_tol=1e-8, abs_tol=1e-9):
            raise ValueError(f'{context}: {actual} != {expected}')
    elif actual != expected:
        raise ValueError(f'{context}: {actual} != {expected}')


def recompute(evidence):
    from scripts.analyze_experiments import (
        analyze_static, analyze_dynamic, analyze_transfer, check_off, validate_power,
    )
    from scripts.experiment_data import load_capture
    from scripts.build_engineering_report import build_report
    os.chdir(ROOT)
    static = analyze_static()
    transfer_path = inside(evidence['reports']['transfer'])
    transfer = analyze_transfer(transfer_path)
    dynamics = {}
    for label in ('dynamic_report', 'dynamic_video'):
        data = analyze_dynamic(inside(evidence['reports'][label]))
        dynamics[label] = [r['metrics'] for r in data['results']]
        if sum(r['valid_rows'] for r in dynamics[label]) != 24576:
            raise ValueError('Dynamic row count differs from frozen submission')
    if static['valid_rows'] != 3584 or sum(len(c['points']) for c in static['curves']) != 28:
        raise ValueError('Static dataset is incomplete')
    if len(transfer['points']) != 9:
        raise ValueError('Transfer dataset is incomplete')
    failure = read(inside(evidence['reports']['failed_transfer']))
    accepted_count = sum(r.get('success') is True for r in failure['results'])
    if failure['success'] is not False or accepted_count != 3 or not failure.get('error'):
        raise ValueError('Historical failed run identity mismatch')
    check_off(failure['final_off'])
    raw = read(transfer_path)
    point = next(p for p in raw['results'] if p['dac_code'] == 2752)
    observations = []
    for i, item in enumerate(point['iterations']):
        validate_power(item['power'])
        zero = load_capture(inside(point['zero']['csv']), 128, {2752})
        rows = load_capture(inside(item['power']['csv']), 128, {2752})
        mean = lambda data, ch: sum(r[f'CH{ch}_V'] for r in data) / len(data)
        vds = mean(rows, 1) - (mean(rows, 2) - mean(zero, 2))
        if not math.isclose(vds, item['VDS_V'], abs_tol=1e-9):
            raise ValueError('Convergence report differs from original CSV')
        observations.append({'supply_set_V': item['supply_set_V'], 'VDS_V': vds,
                             'accepted': abs(vds-.5) <= .015})
    if [v['accepted'] for v in observations] != [False, False, False, True]:
        raise ValueError('Convergence acceptance sequence differs')
    implementation = build_report()
    bit_hash = digest(inside(implementation['implementation']['bitstream']))
    video_report = read(inside(evidence['reports']['dynamic_video']))
    if bit_hash != evidence['bit_sha256'] or bit_hash != video_report['bit_sha256']:
        raise ValueError('Bitstream does not match new dynamic run')
    sim = inside('output/mos_experiment_sim/xsim.log').read_text(encoding='utf-8', errors='replace')
    if 'PASS: mos_experiment' not in sim:
        raise ValueError('Recorded simulation PASS missing')
    return {
        'static_rows': static['valid_rows'],
        'static_curves': [{'code': c['code'], 'VGS_V': c['VGS_V'], 'model': c['model']} for c in static['curves']],
        'transfer_points': len(transfer['points']),
        'VDS_range_V': [min(p['VDS_V'] for p in transfer['points']), max(p['VDS_V'] for p in transfer['points'])],
        'max_gm_mS': transfer['max_gm_mS'], 'VGS_at_1mA_V': transfer['VGS_at_1mA_V'],
        'dynamic': dynamics, 'failed_run_accepted_points': accepted_count,
        'convergence': observations, 'timing': implementation['timing'], 'bit_sha256': bit_hash,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hash-only', action='store_true')
    args = parser.parse_args()
    manifest = read(ROOT/'submission_manifest.json')
    files = manifest['files']
    for entry in files:
        path = inside(entry['path'])
        if not path.is_file() or path.stat().st_size != entry['bytes'] or digest(path) != entry['sha256']:
            raise ValueError(f"File missing or changed: {entry['path']}")
    result = {'success': True, 'hardware_access': False, 'hash_checked_files': len(files)}
    if not args.hash_only:
        evidence = read(ROOT/'submission_evidence.json')
        result['recomputed'] = recompute(evidence)
        compare(result['recomputed'], evidence['expected_metrics'])
    target = ROOT/'output/offline_recheck/verification.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'success': True, 'files': len(files), 'recomputed': not args.hash_only,
                      'hardware_access': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
