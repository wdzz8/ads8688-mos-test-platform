"""Render a compact offline replay video from real experiment traces.

This is a data replay for software demonstration. It does not replace a camera
shot of the physical board and instruments.
"""
import json
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "demo/data/experiment_analysis.json"
OUT = ROOT / "demo/mos_data_replay.mp4"
W, H, FPS = 1280, 720, 30

def text(img, value, xy, size=0.7, color=(35, 45, 55), weight=1):
    cv2.putText(img, value, xy, cv2.FONT_HERSHEY_SIMPLEX, size, color, weight, cv2.LINE_AA)

def plot(img, points, box, color, label, xmin, xmax, ymin, ymax):
    x0, y0, x1, y1 = box
    cv2.rectangle(img, (x0, y0), (x1, y1), (225, 232, 237), 1)
    def xy(p):
        return (int(x0 + (p[0] - xmin) / (xmax - xmin) * (x1 - x0)),
                int(y1 - (p[1] - ymin) / (ymax - ymin) * (y1 - y0)))
    pts = [xy(p) for p in points]
    for a, b in zip(pts, pts[1:]): cv2.line(img, a, b, color, 2, cv2.LINE_AA)
    text(img, label, (x0 + 12, y0 + 26), .55, color, 2)

def make_frame(title, subtitle, left, right=None, right_title=''):
    img = np.full((H, W, 3), (248, 250, 251), np.uint8)
    cv2.rectangle(img, (0, 0), (W, 92), (20, 43, 58), -1)
    text(img, 'AX7020 MOS 实测平台 · 数据回放', (42, 42), .95, (255, 255, 255), 2)
    text(img, title, (42, 76), .58, (204, 225, 237), 1)
    text(img, subtitle, (50, 130), .7, (35, 45, 55), 1)
    if right is None:
        plot(img, left, (70, 190, 1210, 625), (32, 105, 170), '实测数据', 0, max(p[0] for p in left),
             min(p[1] for p in left) * 1.05, max(p[1] for p in left) * 1.1)
    else:
        plot(img, left, (55, 190, 610, 625), (32, 105, 170), 'VG / V', 0, max(p[0] for p in left), 0, 3.3)
        plot(img, right, (670, 190, 1225, 625), (200, 113, 43), right_title, 0, max(p[0] for p in right), 0, 3.3)
    return img

def main():
    data = json.loads(DATA.read_text(encoding='utf-8'))
    writer = cv2.VideoWriter(str(OUT), cv2.VideoWriter_fourcc(*'mp4v'), FPS, (W, H))
    if not writer.isOpened(): raise RuntimeError('OpenCV MP4 writer unavailable')
    # Opening card.
    frame = make_frame('真实 PCB1 数据 · 2026-11-02', '静态曲线、恒 VDS 转移曲线和 1/5/10 Hz 动态采样',
                       [[0, 0], [1, 1]], None)
    text(frame, '来源：原始 ILA CSV 重算 + DPS Modbus 关断回读', (74, 350), .8, (37, 83, 105), 2)
    text(frame, '电流使用名义 INA240 / 0.1 Ω 系数，精密标定状态已在报告中注明', (74, 395), .62, (95, 105, 115), 1)
    for _ in range(FPS * 3): writer.write(frame)
    # Output curves.
    allp = []
    for curve in data['static']['curves']:
        allp.extend([[p['VDS_V'], p['ID_mA']] for p in curve['points']])
    for i in range(FPS * 8):
        frame = np.full((H, W, 3), (248, 250, 251), np.uint8)
        cv2.rectangle(frame, (0, 0), (W, 92), (20, 43, 58), -1)
        text(frame, 'AX7020 MOS 实测平台 · 输出特性', (42, 42), .95, (255, 255, 255), 2)
        text(frame, '真实点：4 个固定 VGS；细线：ID=A·VDS/(VDS+K) 经验拟合', (42, 76), .55, (204, 225, 237), 1)
        ymax=max(p[1] for p in allp)*1.1; xmax=max(p[0] for p in allp)*1.05
        colors=[(32,105,170),(43,131,107),(121,83,165),(200,113,43)]
        for n,c in enumerate(data['static']['curves']):
            pts=[[p['VDS_V'],p['ID_mA']] for p in c['points']]
            plot(frame,pts,(70,190,1210,625),colors[n],f"VGS {c['VGS_V']:.3f} V",0,xmax,0,ymax)
            fit=[[q[0],q[1]] for q in c['fit_curve']]; plot(frame,fit,(70,190,1210,625),colors[n],'',0,xmax,0,ymax)
        for _ in range(1): writer.write(frame)
    # Dynamic traces, one frequency per segment.
    for result in data['dynamic']['results']:
        m=result['metrics']; tr=result['trace']; n=len(tr['time_VG_s']); duration=7; frames=FPS*duration
        for k in range(frames):
            end=max(2, int((k+1)/frames*n)); end=min(end,n)
            t0=tr['time_VG_s'][0]; t1=tr['time_VG_s'][end-1]
            left=[[tr['time_VG_s'][j]-t0,tr['VG_V'][j]] for j in range(end)]
            right=[[tr['time_VD_s'][j]-t0,tr['VD_V'][j]] for j in range(end)]
            frame=make_frame(f"动态回放 · {m['frequency_requested_Hz']:g} Hz", f"实测频率 {m['frequency_measured_Hz']:.5f} Hz · 占空比 {m['duty_mean']*100:.2f}%", left,right,'VD / V')
            text(frame, f"row_valid={m['valid_rows']} · transition_rows={m['transition_rows']} · 顺序采样 CH0→CH7", (56, 674), .55, (90,100,110), 1)
            writer.write(frame)
    writer.release()
    print(OUT, OUT.stat().st_size)

if __name__ == '__main__': main()
