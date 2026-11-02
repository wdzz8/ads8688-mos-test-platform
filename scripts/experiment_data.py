"""Validate unaveraged experiment rows and reconstruct sequential channel times."""
import csv
from pathlib import Path
import statistics

from scripts.plot_mos_scan import normalize, parse_value, to_volts

RANGES=(0,6,0,6,0,0,0,6)
CLK_HZ=50_000_000

def load_capture(path, expected_rows=None, allowed_codes=None):
    with Path(path).open(encoding='utf-8-sig',newline='') as handle:
        table=list(csv.reader(handle))
    at=next(i for i,r in enumerate(table) if 'sample in buffer' in ','.join(r).lower())
    columns=[normalize(name) for name in table[at]]
    rows=[]
    for cells in table[at+1:]:
        if len(cells)!=len(columns): continue
        row={k:parse_value(v,16) for k,v in zip(columns,cells)}
        if row.get('row_valid')==1: rows.append(row)
    if not rows or expected_rows is not None and len(rows)!=expected_rows:
        raise ValueError(f'Expected {expected_rows} valid rows, got {len(rows)}: {path}')
    required={f'row_ch{i}' for i in range(8)}|{'timestamp_cycles','row_start_cycles','row_sequence',
        'configuration_id','row_bad','row_transition','vg_code','row_start_code',
        'init_done','init_error','dac_ready','dac_error'}
    elapsed=0
    for i,row in enumerate(rows):
        if any(row.get(k) is None for k in required): raise ValueError('Missing experiment signals')
        if row['row_bad'] or any(row[f'row_ch{c}']==65535 for c in range(8)):
            raise ValueError(f'Invalid ADC data at row {i}; retain evidence and reinitialize with drain OFF')
        if (row['init_done'],row['init_error'],row['dac_ready'],row['dac_error'])!=(1,0,1,0):
            raise ValueError(f'ADC/DAC communication not ready at row {i}')
        if allowed_codes and row['vg_code'] not in allowed_codes: raise ValueError('Unexpected applied DAC code')
        if i:
            previous=rows[i-1]
            delta=(row['timestamp_cycles']-previous['timestamp_cycles'])%(1<<32)
            if delta!=20800 or (row['row_sequence']-previous['row_sequence'])%(1<<32)!=1:
                raise ValueError('Missing or mis-timed ADC sweep')
            if row['configuration_id']!=previous['configuration_id']: raise ValueError('Configuration changed in capture')
            elapsed+=delta
        skew=(row['timestamp_cycles']-row['row_start_cycles'])%(1<<32)
        if skew!=18200: raise ValueError('Unexpected sequential channel skew')
        row['time_CH7_s']=elapsed/CLK_HZ
        row['time_CH0_s']=(elapsed-skew)/CLK_HZ
        for c in range(8):
            row[f'CH{c}_V']=to_volts(row[f'row_ch{c}'],RANGES[c])
            row[f'time_CH{c}_s']=(elapsed-skew+c*2600)/CLK_HZ
    return rows

def summarize(rows):
    stable=[r for r in rows if not r['row_transition']]
    by_code={}
    for code in sorted({r['vg_code'] for r in stable}):
        selected=[r for r in stable if r['vg_code']==code]
        by_code[str(code)]={'samples':len(selected),**{
            f'CH{c}_V_mean':statistics.fmean(r[f'CH{c}_V'] for r in selected) for c in range(8)}}
    return {'valid_rows':len(rows),'span_s':rows[-1]['time_CH7_s'],
        'row_period_s':20800/CLK_HZ,'channel_skew_s':2600/CLK_HZ,
        'transition_rows':sum(r['row_transition'] for r in rows),'by_code':by_code,
        'configuration_id':rows[0]['configuration_id']}
