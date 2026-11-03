"""Reproducible edit of the owner's hardware photographs and continuous captures.

No acquisition commands are run. All animated measurements are the original PC
recording. Historical analysis is explicitly labelled. Run with --prepare,
--voice, --render, --finish (or --all). Requires Pillow, numpy, OpenCV, edge-tts
and a full FFmpeg build; originals are copied without modification.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import shutil
import subprocess
import wave
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/video_edit_20261103'
ASSETS = OUT / 'sources'
BUILD = OUT / 'build'
FFMPEG = Path('D:/天问Block/tools/ffmpeg.exe')
FFPROBE = Path('D:/wdz/Trae CN/resources/app/bin/ffprobe.exe')
W, H, FPS = 1920, 1080, 30
BG = '#0C1012'
WHITE = '#F4F0E8'
MUTED = '#A9B0AF'
ACCENT = '#D3AC76'
PHOTO_BASE = Path('C:/Users/wdz/Documents/xwechat_files/wxid_3uoh39q6eot722_a8f3/temp/RWTemp/2026-11/f54a8316248a0e912e95d638b306238f')
INPUTS = {
    'phone.mp4': Path('C:/Users/wdz/Desktop/d96d2193014b84e279adeb0d60d13a13.mp4'),
    'pc.mp4': Path('C:/Users/wdz/Desktop/PC.mp4'),
    'bench.jpg': PHOTO_BASE / '725d5b49d04fd2dd15890739d29545a0.jpg',
    'fpga.jpg': PHOTO_BASE / '4e947970954ba137afd4636fe0573c61.jpg',
    'pcb.jpg': PHOTO_BASE / 'c4e40f4c821491a0ca3e711b8e6ed0bf.jpg',
    'dac_sense.jpg': PHOTO_BASE / '2dcd4ffd05582b267be441583edd4c92.jpg',
    'adc.jpg': PHOTO_BASE / '8139155685bbb6399ccfa4935e53e1c2.jpg',
    'amp.jpg': PHOTO_BASE / '0a6006a9fae700584750110a2d15a059.jpg',
    'power.jpg': PHOTO_BASE / '6f57f02db3e4cd8b9c66fef840b6ab95.jpg',
}


def shot(kind, duration, title, body, narration, **kw):
    return dict(kind=kind, duration=duration, title=title, body=body,
                narration=narration, **kw)


SHOTS = [
    shot('hero', 10, '让曲线，\n有据可循。', '基于 FPGA 的 MOS 管特性测试平台',
         '一条曲线，如何证明来自真实测量？从这张测试台开始。', image='bench.jpg', eyebrow='MOS CHARACTERIZATION / PCB1'),
    shot('phone', 7, '从实物出发。', '板卡 · 模拟前端 · 可编程电源',
         '这是一套把激励、采集和分析连起来的器件测试平台。', start=0.3, span=6.3, eyebrow='01 / THE INSTRUMENT'),
    shot('photo', 7, '确定的时序。', 'AX7020 / Zynq\nFPGA 采集控制核心',
         '可编程逻辑负责采集时序，为每组数据保留状态与时间依据。', image='fpga.jpg', rotate=180, eyebrow='AX7020'),
    shot('photo', 7, '连接，成为系统。', 'PCB1 测试载板\n激励与检测链路集成',
         '测试载板连接各个模块，让器件、电源和采集链路形成一个系统。', image='pcb.jpg', eyebrow='PCB1 / INTEGRATION'),
    shot('photo', 8, '给出激励。\n读回变化。', 'MCP4725 / 栅压输出\nINA240A1 / 电流检测',
         '数模转换模块给出栅压激励，电流检测链路读取器件的响应。', image='dac_sense.jpg', eyebrow='EXCITATION / SENSING'),
    shot('photo', 7, '模拟链路，\n同样关键。', 'OPA192\n栅压模拟前端',
         '运算放大器构成栅压模拟前端，连接数字设定与实际测试节点。', image='amp.jpg', eyebrow='ANALOG FRONT END'),
    shot('photo', 8, '八通道。\n保留时间关系。', 'ADS8688 / 顺序扫描\n416 μs 每组 · 52 μs 通道间隔',
         '八个通道按顺序扫描，每组间隔四百一十六微秒，分析时保留通道之间的偏移。', image='adc.jpg', eyebrow='ACQUISITION / TIMESTAMPS'),
    shot('photo', 7, '供电，也是数据。', 'DPS3005 / 可编程电源\n设定、输出与关断状态回读',
         '可编程电源提供漏极供电，输出与关断状态也进入测试记录。', image='power.jpg', eyebrow='POWER / READBACK'),
    shot('pc_full', 8, '从 FPGA 工程开始。', 'Vivado / 配置下载与逻辑分析',
         '在原始录屏中，可以看到配置下载，以及逻辑分析仪里的实际信号。', start=4, span=8, eyebrow='02 / FROM DESIGN TO MEASUREMENT'),
    shot('phone', 6, '现场，留在镜头里。', '手机实拍 / Vivado 操作片段',
         '现场镜头记录台架操作，电脑录屏保留更清楚的测试过程。', start=18, span=6, eyebrow='ON THE BENCH'),
    shot('chapter', 5, '从启动，\n到测得。', '一次新的动态采集',
         '接下来，启动一次新的动态测试。', eyebrow='03 / THE MEASUREMENT'),
    shot('live', 8, '新的运行。\n从零开始。', '请求频率 1 / 5 / 10 Hz\n新运行编号 · 0 / 3 档',
         '命令启动后，网页生成新的运行编号。此时结果为空，等待本次采集。', start=26, span=8, eyebrow='LIVE CAPTURE / ORIGINAL RECORDING'),
    shot('live', 9, '等待，\n是测量的一部分。', '预检 → 激励 → ILA 采集\n结果按采集批次写入',
         '系统完成预检、施加激励，再保存采样。这里压缩了等待时间。', start=34, span=59, eyebrow='LIVE CAPTURE', speed_note=True),
    shot('live', 8, '第一档，出现。', '1 Hz / 8,192 组有效采样\n网页读取本次报告后更新',
         '第一档完成，波形出现。页面读取刚写入的报告，而不是预先填入曲线。', start=93, span=8, eyebrow='01 / 1 Hz'),
    shot('live', 6, '继续，改变频率。', '1 Hz → 5 Hz\n等待下一批真实采样',
         '随后切换到五赫兹，等待下一批真实采样。', start=101, span=35, eyebrow='LIVE CAPTURE', speed_note=True),
    shot('live', 7, '第二档，更新。', '5 Hz / 8,192 组有效采样\n完成档位随报告增加',
         '第二档完成，频率和波形随本次报告更新。', start=136, span=7, eyebrow='02 / 5 Hz'),
    shot('live', 7, '最后一档。', '5 Hz → 10 Hz\n连续录屏中的等待片段',
         '最后切换到十赫兹。采集等待继续加速呈现。', start=143, span=51, eyebrow='LIVE CAPTURE', speed_note=True),
    shot('live_done', 10, '三档，完成。', '3 / 3 档 · 每档 8,192 组\n终端日志与网页结果可对照',
         '三档测试全部完成。终端日志与网页结果一一对应，并记录漏极电源关闭。', start=194, span=10, eyebrow='03 / 10 Hz / COMPLETED'),
    shot('screen_still', 10, '从采样点，\n到输出特性。', '4 档固定栅压 × 7 个测试点\n圆点为实测 · 细线为经验拟合',
         '在历史实测结果中，四档固定栅压形成输出特性曲线。圆点来自测量，细线用于模型比较。', freeze=219.5, eyebrow='04 / ANALYSIS', historical=True),
    shot('screen_still', 10, '先满足条件，\n再接受结果。', '恒 VDS / 上位机反馈\n0.500 V ± 15 mV 验收窗口',
         '转移特性采用上位机反馈。系统读回漏源电压，调节电源，只接受进入目标窗口的点。', freeze=224, eyebrow='CLOSED-LOOP / ACCEPTANCE', historical=True),
    shot('screen_still', 8, '不止一张图。', '1 / 5 / 10 Hz 动态回放\n频率、占空比与采样状态',
         '动态回放支持不同频率对比，描述整机响应，并保留原始数据入口。', freeze=230, eyebrow='DYNAMIC / REPLAY', historical=True),
    shot('screen_still', 8, '检查数据，\n也检查结论。', '时间戳 · 序号 · 异常行\n验收窗口 · 电源回读',
         '质量检查覆盖时间戳、序号和异常行。电流仍按名义系数换算，精密标定需要继续完成。', freeze=234, eyebrow='QUALITY / TRACEABILITY', historical=True),
    shot('screen_still', 7, '实现，也有依据。', '50 MHz 目标时钟\n时序 PASS / 失败端点 0',
         '工程页面给出实现时序与交付文件，让软件结果能够对应到硬件工程。', freeze=240, eyebrow='ENGINEERING / IMPLEMENTATION', historical=True, engineering=True),
    shot('hero', 9, '测得清楚。\n解释有据。', '激励 · 采集 · 反馈 · 分析',
         '让激励、采集、反馈和分析连成一条可追溯的链路。这是这套平台的设计重点。', image='bench.jpg', eyebrow='FPGA / MOS CHARACTERIZATION'),
]


def font(size, bold=False):
    return ImageFont.truetype('C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc', size)


def run(args, log=None):
    result = subprocess.run([str(x) for x in args], cwd=OUT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, encoding='utf-8', errors='replace')
    if log:
        Path(log).write_text(result.stdout, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(result.stdout[-5000:])
    return result.stdout


def duration(path):
    if Path(path).suffix.lower()=='.wav':
        with wave.open(str(path),'rb') as wf:return wf.getnframes()/wf.getframerate()
    if Path(path).suffix.lower()=='.mp3':
        info=subprocess.run([str(FFMPEG),'-hide_banner','-i',str(path)],capture_output=True,encoding='utf-8',errors='replace').stderr
        m=re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)',info)
        if not m:raise RuntimeError(info)
        return int(m[1])*3600+int(m[2])*60+float(m[3])
    return float(run([FFPROBE, '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', path]).strip())


def draw_text(d, xy, text, size, fill=WHITE, bold=False, spacing=15):
    d.multiline_text(xy, text, font=font(size, bold), fill=fill, spacing=spacing)


def snapshot(source, time):
    c = cv2.VideoCapture(str(source)); c.set(cv2.CAP_PROP_POS_MSEC, time * 1000)
    ok, frame = c.read(); c.release()
    if not ok:
        raise RuntimeError(f'Cannot read {source} at {time}')
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def prepare():
    for p in [OUT, ASSETS, BUILD]: p.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, source in INPUTS.items():
        target = ASSETS / name
        if not target.exists(): shutil.copy2(source, target)
        manifest.append(dict(name=name, original=str(source), bytes=target.stat().st_size,
                             sha256=hashlib.file_digest(target.open('rb'), 'sha256').hexdigest()))
    (OUT / 'source_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    for name, source in [('experiment_analysis.json', ROOT/'demo/data/experiment_analysis.json'),
                         ('engineering_report.json', ROOT/'demo/data/engineering_report.json'),
                         ('dynamic_report.json', ROOT/'output/pcb1/dynamic/run_20261103_194724_993590/dynamic_report.json')]:
        shutil.copy2(source, ASSETS/name)
    start = 0
    for i, s in enumerate(SHOTS):
        s['id'] = i; s['timeline_start'] = start; start += s['duration']
        base = Image.new('RGB', (W,H), BG)
        overlay = Image.new('RGBA', (W,H), (0,0,0,0)); d=ImageDraw.Draw(overlay)
        kind = s['kind']
        if kind == 'hero':
            photo=ImageOps.fit(ImageOps.exif_transpose(Image.open(ASSETS/s['image'])),(W,H),centering=(.5,.52))
            photo.save(BUILD/f'{i:02}_photo.png')
            grad=np.zeros((H,W,4),np.uint8); grad[:,:,:3]=[7,10,12]
            grad[:,:,3]=np.clip(225*(1-np.arange(W)/W)**1.1+35,0,255).astype(np.uint8)[None,:]
            overlay=Image.alpha_composite(overlay,Image.fromarray(grad));d=ImageDraw.Draw(overlay)
            draw_text(d,(100,158),s['eyebrow'],23,ACCENT)
            draw_text(d,(94,280),s['title'],92,bold=True,spacing=20)
            draw_text(d,(102,575),s['body'],30)
            d.line((102,669,185,669),fill=ACCENT,width=3)
            draw_text(d,(102,708),'AX7020  /  PCB1  /  2N7000',23,MUTED)
        elif kind == 'photo':
            im=ImageOps.exif_transpose(Image.open(ASSETS/s['image'])).convert('RGB')
            if s.get('rotate'): im=im.rotate(s['rotate'],expand=True)
            im=ImageOps.fit(im,(1050,850),centering=(.5,.5));im.save(BUILD/f'{i:02}_photo.png')
            draw_text(d,(90,145),s['eyebrow'],22,ACCENT)
            draw_text(d,(86,263),s['title'],57,bold=True,spacing=20)
            draw_text(d,(92,515),s['body'],27,MUTED,spacing=20)
            d.line((92,685,165,685),fill=ACCENT,width=3)
            draw_text(d,(92,731),'实物摄影 / 项目台架',21,MUTED)
        elif kind == 'chapter':
            draw_text(d,(135,185),s['eyebrow'],23,ACCENT)
            draw_text(d,(127,310),s['title'],104,bold=True,spacing=15)
            draw_text(d,(137,647),s['body'],32,MUTED)
            d.line((137,761,1760,761),fill='#454845',width=1)
            draw_text(d,(138,801),'原始录屏 · 新运行编号 · 按批次更新',24,MUTED)
        elif kind in ('phone','pc_full'):
            draw_text(d,(74,36),s['eyebrow'],22,ACCENT)
            draw_text(d,(1110,35),s['title'].replace('\n',''),27)
            draw_text(d,(74,946),s['body'].replace('\n',' / '),23,MUTED)
        else:
            draw_text(d,(80,123),s['eyebrow'],21,ACCENT)
            draw_text(d,(75,230),s['title'],54,bold=True,spacing=17)
            draw_text(d,(82,460),s['body'],26,MUTED,spacing=20)
            d.line((82,636,151,636),fill=ACCENT,width=3)
            if s.get('speed_note'):
                speed=s['span']/s['duration'];draw_text(d,(82,687),f'等待片段加速 ×{speed:.2f}',26,ACCENT)
                draw_text(d,(82,735),'波形与状态均来自原始录屏',22,MUTED)
            elif s.get('historical'):
                draw_text(d,(82,687),'FPGA 工程报告' if s.get('engineering') else '历史实测数据回放',27,ACCENT)
                draw_text(d,(82,738),'PC 原始录屏定格' if s.get('engineering') else 'PC 原始录屏定格 / 非本次新采集',21,MUTED)
                screen=snapshot(ASSETS/'pc.mp4',s['freeze'])
                # Keep navigation, plots, axes and measured-data caveats visible.
                screen=screen.crop((0,350,1270,1598));screen=ImageOps.contain(screen,(1000,900))
                base.paste(screen,(840+(1000-screen.width)//2,74+(900-screen.height)//2))
            elif kind == 'live_done':
                draw_text(d,(82,687),'实际运行 / 2026.11.03',23,ACCENT)
                screen=snapshot(ASSETS/'pc.mp4',203).crop((1278,1260,2558,1598))
                screen=ImageOps.contain(screen,(710,205));base.paste(screen,(82,765))
            else:
                draw_text(d,(82,687),'实际运行 / 2026.11.03',23,ACCENT)
                draw_text(d,(82,738),'run_20261103_194724_993590',21,MUTED)
                draw_text(d,(82,800),'FPGA ILA → CSV → 报告 → 网页',23,MUTED)
        if kind != 'hero':
            draw_text(d,(80,1007),'MOS / PCB1',17,'#777F7D')
            draw_text(d,(1763,1007),f'{i+1:02d} / {len(SHOTS):02d}',17,'#777F7D')
        base.save(BUILD/f'{i:02}_base.png');overlay.save(BUILD/f'{i:02}_overlay.png')
    (OUT/'edit_timeline.json').write_text(json.dumps(SHOTS,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'配音稿.txt').write_text('\n\n'.join(f"{s['timeline_start']:03d}s / {s['title'].replace(chr(10),' ')}\n{s['narration']}" for s in SHOTS),encoding='utf-8')
    print(f'Prepared {len(SHOTS)} shots / {start} seconds',flush=True)


async def make_voice():
    import edge_tts
    for i,s in enumerate(SHOTS):
        path=BUILD/f'{i:02}_voice.mp3'
        if path.exists() and path.stat().st_size>1000: continue
        print(f'Voice {i+1}/{len(SHOTS)}',flush=True)
        await asyncio.wait_for(edge_tts.Communicate(s['narration'],'zh-CN-YunxiNeural',rate='+4%',pitch='-2Hz').save(str(path)),timeout=45)
    (OUT/'voice_provider.txt').write_text('Microsoft Edge TTS / zh-CN-YunxiNeural / rate +4% / pitch -2Hz',encoding='utf-8')


def encode_args():
    return ['-an','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-r',str(FPS),'-threads','4','-movflags','+faststart']


def render():
    for i,s in enumerate(SHOTS):
        target=BUILD/f'{i:02}_picture.mp4'
        if target.exists() and target.stat().st_size>3000: continue
        kind=s['kind'];dur=s['duration'];args=[FFMPEG,'-hide_banner','-loglevel','warning','-y']
        args+=['-loop','1','-framerate',str(FPS),'-i',BUILD/f'{i:02}_base.png']
        if kind in ('photo','hero'):
            args+=['-loop','1','-framerate',str(FPS),'-i',BUILD/f'{i:02}_photo.png','-loop','1','-framerate',str(FPS),'-i',BUILD/f'{i:02}_overlay.png']
            pw,ph=(W,H) if kind=='hero' else (1050,850);x,y=(0,0) if kind=='hero' else (790,100)
            # Upscale first so subpixel push-in does not produce visible stepping.
            filt=f"[1:v]scale={pw*2}:{ph*2},zoompan=z='1+0.035*on/{dur*FPS}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={pw}x{ph}:fps={FPS}[p];[0:v][p]overlay={x}:{y}[b];[b][2:v]overlay=0:0[v]"
        elif kind in ('live','live_done','phone','pc_full'):
            source=ASSETS/('phone.mp4' if kind=='phone' else 'pc.mp4')
            # Phone was encoded landscape with an erroneous rotation tag.
            args+=['-noautorotate','-ss',str(s['start']),'-t',str(s['span']),'-i',source,'-loop','1','-framerate',str(FPS),'-i',BUILD/f'{i:02}_overlay.png']
            speed=s['span']/dur
            if kind in ('live','live_done'):
                crop='crop=1270:1110:0:480,scale=1000:874';x,y=840,100
            else:
                crop='scale=1440:810' if kind=='phone' else 'crop=2558:1470:0:128,scale=1440:828'
                x,y=(240,115) if kind=='phone' else (240,100)
            filt=f'[1:v]setpts=(PTS-STARTPTS)/{speed:.8f},fps={FPS},{crop},setsar=1[p];[0:v][p]overlay={x}:{y}:eof_action=repeat[b];[b][2:v]overlay=0:0[v]'
        else:
            args+=['-loop','1','-framerate',str(FPS),'-i',BUILD/f'{i:02}_overlay.png']
            filt='[0:v][1:v]overlay=0:0[v]'
        # Short optical fades around section changes; direct cuts within capture.
        if kind in ('hero','chapter','photo'):
            filt=filt.replace('[v]','[raw]')+f';[raw]fade=t=in:st=0:d=0.28,fade=t=out:st={dur-.25}:d=0.25[v]'
        args+=['-filter_complex_threads','1','-filter_complex',filt,'-map','[v]','-t',str(dur),*encode_args(),target]
        print(f'Render {i+1}/{len(SHOTS)}: {s["title"].replace(chr(10)," ")}',flush=True)
        run(args,BUILD/f'{i:02}_render.log')
    listing=BUILD/'pictures.txt';listing.write_text(''.join(f"file '{(BUILD/f'{i:02}_picture.mp4').as_posix()}'\n" for i in range(len(SHOTS))),encoding='utf-8')
    run([FFMPEG,'-hide_banner','-loglevel','warning','-y','-f','concat','-safe','0','-i',listing,'-c','copy',BUILD/'picture_master.mp4'],BUILD/'concat.log')


def srt_time(t):
    ms=round(t*1000);return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'


def ass_time(t):
    cs=round(t*100);return f'{cs//360000}:{cs//6000%60:02d}:{cs//100%60:02d}.{cs%100:02d}'


def finish():
    total=sum(s['duration'] for s in SHOTS);sr=48000;voice=np.zeros(total*sr,np.float32);entries=[];cursor=0;vmeta=[]
    for i,s in enumerate(SHOTS):
        src=BUILD/f'{i:02}_voice.mp3'
        if not src.exists(): src=BUILD/f'{i:02}_voice.wav'
        if not src.exists(): raise RuntimeError(f'Missing narration {i}')
        available=s['duration']-.65;original=duration(src);speed=max(1.,original/available)
        pcm=BUILD/f'{i:02}_voice_pcm.wav'
        run([FFMPEG,'-hide_banner','-loglevel','warning','-y','-i',src,'-af',f'atempo={speed:.6f},loudnorm=I=-18:TP=-2:LRA=8','-ar',sr,'-ac','1','-c:a','pcm_s16le',pcm])
        with wave.open(str(pcm),'rb') as wf: a=np.frombuffer(wf.readframes(wf.getnframes()),np.int16).astype(np.float32)/32768
        start=cursor+.35;pos=round(start*sr);voice[pos:pos+len(a)]+=a
        # Phrase subtitles follow narration duration; never animate measured data.
        pieces=[x for x in re.split('[，。？！]',s['narration']) if x]
        units=sum(len(x) for x in pieces);t=start
        for text in pieces:
            dt=len(a)/sr*len(text)/units;entries.append((t,t+dt,text));t+=dt
        vmeta.append(dict(shot=i,source_duration_s=original,atempo=speed,placed_at_s=start));cursor+=s['duration']
    # Original subdued score. No commercial recordings or external music assets.
    n=total*sr;t=np.arange(n,dtype=np.float32)/sr;music=np.zeros(n,np.float32)
    chords=[(110,164.8138,220,261.6256),(98,146.8324,196,246.9417),(130.8128,164.8138,196,261.6256),(110,146.8324,220,293.6648)]
    for k in range(math.ceil(total/12)):
        st=k*12;lo=st*sr;hi=min(n,(st+14)*sr);q=t[lo:hi]-st;env=np.minimum(q/2,1)*np.minimum((14-q)/3,1);env=np.clip(env,0,1)
        for j,freq in enumerate(chords[k%4]):
            music[lo:hi]+=.008*env*np.sin(2*np.pi*freq*q+0.2*np.sin(2*np.pi*.13*q+j))
        for beat in (0,6):
            q2=q-beat;mask=q2>=0;pl=np.maximum(q2,0);music[lo:hi]+=.011*mask*np.exp(-pl*1.8)*np.sin(2*np.pi*chords[k%4][-1]*2*pl)
    fade=np.minimum(t/3,1)*np.minimum((total-t)/4,1);music*=fade
    # Duck the score during speech; maintain natural pauses and low peaks.
    envelope=np.abs(voice).reshape(-1,480).max(axis=1);env=np.repeat(np.minimum(envelope*9,1),480)
    music*=1-.55*env
    mixed=voice+music;peak=float(np.max(np.abs(mixed)))
    if peak>.94:mixed*=.94/peak
    def wav(path,data):
        with wave.open(str(path),'wb') as wf:
            wf.setnchannels(1);wf.setsampwidth(2);wf.setframerate(sr);wf.writeframes((np.clip(data,-1,1)*32767).astype(np.int16).tobytes())
    wav(OUT/'narration.wav',voice);wav(OUT/'original_ambient_score.wav',music);wav(BUILD/'final_mix.wav',mixed)
    (OUT/'voice_timing.json').write_text(json.dumps(vmeta,indent=2),encoding='utf-8')
    srt='\n\n'.join(f'{i+1}\n{srt_time(a)} --> {srt_time(b)}\n{text}' for i,(a,b,text) in enumerate(entries))+'\n'
    (OUT/'MOS_showcase.srt').write_text(srt,encoding='utf-8-sig')
    header='[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 2\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Microsoft YaHei,31,&H00F4F0E8,&H000000FF,&H00100C08,&H90100C08,0,0,0,0,100,100,0,0,3,9,0,2,90,90,26,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    (OUT/'film.ass').write_text(header+''.join(f'Dialogue: 0,{ass_time(a)},{ass_time(b)},Default,,0,0,0,,{text}\n' for a,b,text in entries),encoding='utf-8-sig')
    # Optional narration-free cut retains editorial titles and honest source labels.
    run([FFMPEG,'-hide_banner','-loglevel','warning','-y','-i',BUILD/'picture_master.mp4','-i',OUT/'original_ambient_score.wav','-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',OUT/'MOS_showcase_clean.mp4'],BUILD/'clean_export.log')
    run([FFMPEG,'-hide_banner','-loglevel','warning','-y','-i',BUILD/'picture_master.mp4','-i',BUILD/'final_mix.wav','-vf','ass=film.ass','-map','0:v','-map','1:a','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-threads','6','-c:a','aac','-b:a','192k','-movflags','+faststart',OUT/'MOS_showcase_final.mp4'],BUILD/'final_export.log')
    print(f'Exported {total}s film',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();[parser.add_argument('--'+x,action='store_true') for x in ['prepare','voice','render','finish','all']];a=parser.parse_args()
    if a.prepare or a.all:prepare()
    if a.voice or a.all:asyncio.run(make_voice())
    if a.render or a.all:render()
    if a.finish or a.all:finish()
