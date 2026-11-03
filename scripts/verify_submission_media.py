"""Inspect the revised film and PDF; run no acquisition or hardware tools."""
from pathlib import Path
import json
import subprocess
import wave
import cv2
import numpy as np
from PIL import Image, ImageDraw
import pymupdf

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/submission_20261103'
VIDEO=OUT/'video'
FFMPEG=Path('D:/天问Block/tools/ffmpeg.exe')
FFPROBE=Path('D:/wdz/Trae CN/resources/app/bin/ffprobe.exe')


def main():
    film=VIDEO/'MOS_showcase_final.mp4'
    result=subprocess.run([str(FFPROBE),'-v','error','-show_format','-show_streams','-of','json',str(film)],capture_output=True,text=True,check=True)
    probe=json.loads(result.stdout)
    video=next(s for s in probe['streams'] if s['codec_type']=='video')
    audio=next(s for s in probe['streams'] if s['codec_type']=='audio')
    duration=float(probe['format']['duration'])
    assert (video['width'],video['height'])==(1920,1080)
    assert video['codec_name']=='h264' and audio['codec_name']=='aac' and duration<=180
    decode=subprocess.run([str(FFMPEG),'-hide_banner','-v','error','-i',str(film),'-f','null','-'],capture_output=True,text=True,check=True)
    assert not decode.stderr.strip(),decode.stderr
    decoded=VIDEO/'build/qa_audio.wav'
    subprocess.run([str(FFMPEG),'-hide_banner','-loglevel','error','-y','-i',str(film),'-vn','-ac','1','-ar','48000','-c:a','pcm_s16le',str(decoded)],check=True)
    with wave.open(str(decoded),'rb') as f:
        samples=np.frombuffer(f.readframes(f.getnframes()),dtype=np.int16)
    peak=float(np.max(np.abs(samples.astype(np.int32)))/32768)
    assert peak<.999
    shots=json.loads((VIDEO/'edit_timeline.json').read_text(encoding='utf-8'))
    timings=json.loads((VIDEO/'voice_timing.json').read_text(encoding='utf-8'))
    assert max(t['atempo'] for t in timings)<1.25
    frames=[]; cap=cv2.VideoCapture(str(film))
    for s in shots:
        t=s['timeline_start']+min(3,s['duration']/2)
        cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,frame=cap.read();assert ok
        im=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB));im.save(VIDEO/f"review_{s['id']:02}.jpg",quality=93)
        thumb=im.resize((576,324));d=ImageDraw.Draw(thumb);d.rectangle((0,0,155,26),fill='black');d.text((8,6),f"{s['id']+1} / {t:.0f}s",fill='white');frames.append(thumb)
    for t in (34,38,42,46):
        cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,frame=cap.read();assert ok
        Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)).save(VIDEO/f'convergence_{t}.jpg',quality=93)
    cap.release()
    for start in range(0,len(frames),9):
        sheet=Image.new('RGB',(1728,972),'#171717')
        for j,im in enumerate(frames[start:start+9]):sheet.paste(im,((j%3)*576,(j//3)*324))
        sheet.save(VIDEO/f'contact_{start//9+1}.jpg',quality=94)
    document=pymupdf.open(OUT/'技术文档_修订版.pdf')
    assert len(document)==21
    assert '第三次误差16.38' in document[20].get_text().replace(' ','')
    for i,page in enumerate(document):
        assert len(page.get_text().strip())>40,f'Blank page {i+1}'
    verification={'video':{'duration_s':duration,'width':video['width'],'height':video['height'],
                  'video_codec':video['codec_name'],'audio_codec':audio['codec_name'],'full_decode_errors':0,
                  'audio_peak':peak,'max_voice_speed':max(t['atempo'] for t in timings),'shots':len(shots)},
                  'pdf':{'pages':len(document),'blank_pages':0},
                  'source_note':'Historical report extracts are labelled; footage is not claimed synchronized.',
                  'hardware_acquisition_performed':False}
    (OUT/'media_verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(verification,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
