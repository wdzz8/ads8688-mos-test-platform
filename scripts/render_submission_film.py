"""Second editorial cut using original footage and explicitly labelled report extracts."""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import shutil
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_showcase_film as film
from build_engineering_report import build_report

ROOT = film.ROOT
OLD = ROOT / 'output/video_edit_20261103'
film.OUT = ROOT / 'output/submission_20261103/video'
film.ASSETS = film.OUT / 'sources'
film.BUILD = film.OUT / 'build'
TRANSFER = ROOT / 'output/pcb1/transfer/run_20261102_222410_092311/transfer_report.json'
REPORT = json.loads(TRANSFER.read_text(encoding='utf-8'))
POINT = next(p for p in REPORT['results'] if p['dac_code'] == 2752)
ENGINEERING = build_report()
BIT_HASH = hashlib.sha256((ROOT / 'output/mos_experiment/mos_experiment.bit').read_bytes()).hexdigest()
shot = film.shot
film.SHOTS = [
    shot('hero', 7, 'MOS 管\n闭环特性测试', 'AX7020 FPGA · 实物台架 · 可追溯测量',
         '这套平台测量 MOS 管特性，并记录每个结果是怎样得到的。', image='bench.jpg', eyebrow='FPGA / MOS CHARACTERIZATION'),
    shot('phone', 6, '完整测试台架', '现场实拍 / FPGA、测试载板、模拟模块和可编程电源',
         '可编程栅压提供激励，漏极电源供电，多通道采集读取器件响应。', start=.3, span=6, eyebrow='01 / HARDWARE'),
    shot('photo', 6, 'FPGA 组织\n激励与采样', 'AX7020 / 50 MHz\n采样行保留时间戳和切换标记',
         'FPGA 统一采样和激励的时间参考，保留栅压切换发生的位置。', image='fpga.jpg', rotate=180, eyebrow='AX7020 / PL'),
    shot('photo', 6, '测试载板\n连接模拟链路', 'MCP4725 → OPA192 → MOS 栅极\nINA240 → ADS8688 → FPGA',
         '载板连接模拟链路，八通道顺序采样，每行四百一十六微秒。', image='pcb.jpg', eyebrow='PCB / SIGNAL PATH'),
    shot('problem', 8, '为什么需要\n恒 VDS 反馈', '串联限流电阻产生压降\n电源设定值 ≠ 器件两端电压',
         '电流变化时，串联电阻上的压降也会变化。只固定电源设定，无法保证器件两端电压。', eyebrow='02 / CLOSED-LOOP TEST'),
    shot('convergence', 19, '读取 VDS\n逐次修正电源', '目标 0.500 V\n进入 ±15 mV 回读窗口才接受',
         '这是历史实测中一个栅压点的完整记录。四次观测，漏源电压从零点一七伏逐步接近目标。第三次仍在窗口外，第四次进入窗口，系统才接受该点。', eyebrow='HISTORICAL REPORT / DAC 2752'),
    shot('screen_still', 9, '九个测试点\n均通过回读窗口', 'VDS 回读范围 0.4922—0.5086 V\n±15 mV 是接受窗口，非绝对精度',
         '九个测试点均进入回读窗口，形成转移曲线。这里的窗口是接受条件，绝对精度仍需标定。', freeze=224, historical=True, eyebrow='TRANSFER / MEASURED RESULTS'),
    shot('pc_full', 6, '配置下载与 ILA', '原始电脑录屏 / FPGA 配置和信号观测',
         '原始录屏保留了 FPGA 配置下载和逻辑分析过程。', start=4, span=6, eyebrow='03 / NEW ACQUISITION'),
    shot('live', 8, '启动新采集\n结果从零开始', '1 / 5 / 10 Hz\n本次运行 0 / 3 档',
         '接着看一次新的动态测试。运行编号生成时，结果为空，等待本次采集。', start=26, span=8, eyebrow='LIVE CAPTURE / ORIGINAL RECORDING'),
    shot('live', 8, '预检与采样', '零点 → 激励 → ILA 采集\n采集完成后写入报告',
         '系统先采零点，再施加激励。网页按采集批次更新，这里的等待已加速。', start=34, span=59, speed_note=True, eyebrow='LIVE CAPTURE / WAIT'),
    shot('live', 7, '1 Hz 采集完成', '1 / 3 档\n8,192 行有效采样',
         '第一档完成，波形随本次报告出现，保存八千一百九十二行有效采样。', start=93, span=7, eyebrow='01 / 1 Hz'),
    shot('live', 6, '切换到 5 Hz', '等待下一批采样\n保留实际运行编号',
         '切换到五赫兹，等待下一批采样。', start=101, span=35, speed_note=True, eyebrow='LIVE CAPTURE / WAIT'),
    shot('live', 7, '5 Hz 采集完成', '2 / 3 档\n频率、波形与进度更新',
         '第二档完成。页面更新频率和波形，已完成档位增加到两档。', start=136, span=7, eyebrow='02 / 5 Hz'),
    shot('live', 7, '切换到 10 Hz', '最后一批采样\n等待片段加速呈现',
         '最后采集十赫兹，继续保留本次运行的进度变化。', start=143, span=51, speed_note=True, eyebrow='LIVE CAPTURE / WAIT'),
    shot('live_done', 10, '三档测试完成', '3 / 3 档 · 共 24,576 行\n终端日志与结果可对照',
         '三档全部完成，终端日志与网页结果对应。报告同时保存漏极电源关闭的回读。', start=194, span=10, eyebrow='03 / 10 Hz / COMPLETED'),
    shot('screen_still', 10, '四档栅压\n形成输出曲线', '4 × 7 个实测点 / 共 3,584 行\n圆点为测量值，细线为经验拟合',
         '历史输出特性包含四档栅压、二十八个测试点。圆点来自测量，细线用于比较趋势。', freeze=219.5, historical=True, eyebrow='04 / OUTPUT CHARACTERISTICS'),
    shot('failure', 12, '失败数据\n同样保留', '真实失败运行 / 3 个通过点\n报告保留异常与关断回读',
         '这次历史运行在三个通过点后失败。系统保留失败原因和关断回读，未通过的点不会补成曲线。', eyebrow='QUALITY / FAILED RUN'),
    shot('engineering_panel', 11, '实现版本\n与报告对应', 'Vivado 2022.2 / 50 MHz\n当前冻结构建：2026-11-03',
         '最终交付冻结同一构建的配置文件、探针和时序报告。实现时序通过，原始数据可离线复算。', eyebrow='05 / IMPLEMENTATION EVIDENCE'),
    shot('hero', 10, '从激励到结果\n每一步可复核', '恒 VDS 反馈 · FPGA 采样标记 · 原始记录',
         '当前已完成低压小电流原型验证。下一步继续标定和独立重复测试，让测量更可靠。', image='bench.jpg', eyebrow='FPGA / MOS CHARACTERIZATION'),
]


def txt(d, xy, value, size=28, color=film.WHITE, bold=False):
    film.draw_text(d, xy, value, size, color, bold=bold)


def panel(s, path):
    im = Image.new('RGB', (1920,1080), film.BG); d = ImageDraw.Draw(im)
    txt(d,(80,78),s['eyebrow'],22,film.ACCENT)
    txt(d,(76,180),s['title'],58,bold=True)
    txt(d,(82,420),s['body'],26,film.MUTED)
    kind=s['kind']
    if kind=='problem':
        nodes=[(790,230,'DPS 电源'),(1150,230,'R1 ≈ 990 Ω'),(1510,230,'MOS 管')]
        for x,y,label in nodes:
            d.rectangle((x,y,x+290,y+100),outline='#64726F',width=2)
            txt(d,(x+22,y+29),label,31)
        for x in (1080,1440):
            d.line((x,280,x+70,280),fill=film.ACCENT,width=3)
        txt(d,(800,415),'VDS = 漏极回读 − 源极扣零后电压',32)
        txt(d,(800,510),'回读 → 修正电源 → 再采集 → 检查窗口',29,film.ACCENT)
        txt(d,(800,605),'上位机逐点反馈 / FPGA 负责采样时序',26,film.MUTED)
    elif kind=='convergence':
        txt(d,(800,173),'历史实测报告摘录 / 非现场录屏',25,film.ACCENT)
        headers=['观测','电源设定','实测 VDS','是否接受']
        xs=[800,975,1270,1560]
        for x,h in zip(xs,headers):txt(d,(x,282),h,29,film.MUTED)
        for j,r in enumerate(POINT['iterations']):
            y=365+j*101
            accepted=abs(r['error_V'])<=REPORT['tolerance_V']
            vals=[str(j+1),f"{r['supply_set_V']:.2f} V",f"{r['VDS_V']:.4f} V",'接受' if accepted else '窗口外']
            for x,v in zip(xs,vals):txt(d,(x,y),v,35,film.ACCENT if accepted else film.WHITE)
            d.line((800,y+72,1810,y+72),fill='#35413E',width=1)
        txt(d,(800,815),'目标窗口 0.485—0.515 V / 每次观测后均关断回读',25,film.MUTED)
        txt(d,(82,720),'数据批次：2026-11-02\nDAC 2752 / 第 4 次观测接受',23,film.ACCENT)
    elif kind=='failure':
        src=Image.open(ROOT/'demo/live_dashboard_check.png').convert('RGB')
        # Actual saved failure monitor; leave run identity, status and accepted points intact.
        src=src.crop((115,230,1325,1300));src=ImageOps.contain(src,(1000,840))
        im.paste(src,(830+(1000-src.width)//2,110+(840-src.height)//2))
        txt(d,(82,690),'历史实测失败记录\n2026-11-03 / 非本次动态采集',23,film.ACCENT)
    else:
        tm=ENGINEERING['timing']
        txt(d,(805,185),'最终冻结构建 / 原始实现报告摘要',26,film.ACCENT)
        for j,(k,v) in enumerate([
            ('目标时钟','50 MHz'),('Setup WNS',f"{tm['setup_WNS_ns']:.3f} ns"),
            ('Hold WHS',f"{tm['hold_WHS_ns']:.3f} ns"),('失败端点',str(tm['failing_endpoints'])),
            ('报告时间','2026-11-03 11:52:45'),('Bit SHA-256',BIT_HASH[:20]+'…')]):
            y=290+j*82;txt(d,(810,y),k,28,film.MUTED);txt(d,(1190,y),v,31)
            d.line((805,y+57,1810,y+57),fill='#35413E',width=1)
        txt(d,(805,830),'完整 SHA-256 与证据索引随交付包提供',25,film.MUTED)
    txt(d,(80,1007),'MOS / PCB1',17,'#777F7D')
    im.save(path)


def prepare():
    timeline=film.OUT/'edit_timeline.json'
    old_shots=json.loads(timeline.read_text(encoding='utf-8')) if timeline.exists() else []
    for i,s in enumerate(film.SHOTS):
        if i<len(old_shots) and old_shots[i]['narration']!=s['narration']:
            (film.BUILD/f'{i:02}_voice.mp3').unlink(missing_ok=True)
    film.prepare()
    for i,s in enumerate(film.SHOTS):
        if s['kind'] in ('problem','convergence','failure','engineering_panel'):
            panel(s,film.BUILD/f'{i:02}_base.png')
            Image.new('RGBA',(1920,1080),(0,0,0,0)).save(film.BUILD/f'{i:02}_overlay.png')
            (film.BUILD/f'{i:02}_picture.mp4').unlink(missing_ok=True)
    # Reveal actual rows progressively; no simulated instruments or invented curve animation.
    idx=next(i for i,s in enumerate(film.SHOTS) if s['kind']=='convergence')
    base=Image.open(film.BUILD/f'{idx:02}_base.png')
    for stage in range(4):
        im=base.copy();d=ImageDraw.Draw(im)
        if stage<3:d.rectangle((790,365+(stage+1)*101-8,1840,775),fill=film.BG)
        im.save(film.BUILD/f'convergence_{stage}.png')
    # Reuse byte-identical TTS phrases when available.
    previous_file=OLD/'edit_timeline.json'
    previous=json.loads(previous_file.read_text(encoding='utf-8')) if previous_file.exists() else []
    for i,s in enumerate(film.SHOTS):
        for old in previous:
            if s['narration']==old['narration']:
                source=OLD/'build'/f"{old['id']:02}_voice.mp3"
                if source.exists():shutil.copy2(source,film.BUILD/f'{i:02}_voice.mp3')
    evidence={'transfer_report':str(TRANSFER.relative_to(ROOT)).replace('\\','/'),
              'convergence_point':POINT,'engineering':ENGINEERING,'bit_sha256':BIT_HASH,
              'dynamic_run':'run_20261103_194724_993590',
              'report_dynamic_run':'run_20261102_215847_036499',
              'note':'Report extracts are labelled; phone and PC footage are not claimed synchronized.'}
    (film.OUT/'editorial_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')


def convergence():
    idx=next(i for i,s in enumerate(film.SHOTS) if s['kind']=='convergence')
    listing=film.BUILD/'convergence.txt'
    listing.write_text(''.join(f"file '{(film.BUILD/f'convergence_{i}.png').as_posix()}'\nduration {v}\n" for i,v in enumerate([4,4,4,7]))+f"file '{(film.BUILD/'convergence_3.png').as_posix()}'\n",encoding='utf-8')
    film.run([film.FFMPEG,'-hide_banner','-loglevel','warning','-y','-f','concat','-safe','0','-i',listing,
              '-vf','fps=30','-t','19',*film.encode_args(),film.BUILD/f'{idx:02}_picture.mp4'],film.BUILD/'convergence_render.log')


if __name__=='__main__':
    p=argparse.ArgumentParser();[p.add_argument('--'+x,action='store_true') for x in ['prepare','voice','render','finish','all']];a=p.parse_args()
    if a.prepare or a.all:prepare()
    if a.voice or a.all:asyncio.run(film.make_voice())
    if a.render or a.all:convergence();film.render()
    if a.finish or a.all:
        # The shared exporter resolves its ASS path from the current directory.
        import os
        os.chdir(film.OUT);film.finish()
