"""Apply local corrections to the existing competition report, preserving its template."""
from pathlib import Path
import hashlib
import io
import json
from copy import deepcopy
from docx import Document
from docx.shared import Cm, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/submission_20261103'


def replace(paragraph, text):
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ''
    else:
        paragraph.add_run(text)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'output/technical_report/技术文档_完整版.docx'
    doc = Document(source)
    changes = []
    replacements = {
        126: '工程公开地址为https://github.com/wdzz8/ads8688-mos-test-platform。本次提交同时提供独立交付包，冻结本报告采用的数据、实现文件与源代码快照；复核以交付包内清单为准，不依赖网络仓库是否更新。以下命令从解压后的工程根目录执行。硬件工具为Vivado 2022.2，Python依赖见requirements.txt。换机时需调整Vivado安装路径及串口。',
        130: '可直接打开demo/index.html浏览历史结果。原始CSV、关断零点、供电记录和指定报告均随包保存。离线复核脚本固定选择本报告及新版视频所用批次，不随新增实验改变；它不连接串口、不启动Vivado，也不打开电源。',
        131: 'python scripts/verify_submission.py\npython scripts/verify_submission.py --hash-only',
        132: '第一条命令先检查文件SHA-256，再从原始CSV重算四条输出曲线、九点转移特性及两批动态实验；第二条只核对文件完整性。结果写入output/offline_recheck/verification.json。视频中的11月3日新动态采集与本报告11月2日动态批次分别验证，不能混用其频率末位。',
        133: '冻结入口：submission_evidence.json\n完整性清单：submission_manifest.json\n原始JSON存档：provenance/original_json/\n路径处理记录：provenance/path_transforms.json',
        155: '本作品已完成单只2N7000的低压小电流测试流程，尚未建立完整的绝对精度校准。后续需用独立仪表逐通道多点标定，并在多次上电、插拔和不同器件上重复测试。FFFF根因仍在排查；新增PL栅压回退已仿真并完成实现，ADC失效与行超时的板级故障注入仍待完成。USB断开或PC掉电时的独立关断未验证。±15 mV仅是ADC回读接受窗口，不能写成仪器绝对精度。',
        166: '下列路径相对于解压后的工程根目录。图7至图9使用11月2日完整数据；图10使用11月3日失败运行；图6使用实拍照片。新版视频另展示11月3日新动态采集。各批次独立保存；构建版本与一个测试点的完整反馈过程见附页。',
    }
    for index, value in replacements.items():
        changes.append({'paragraph': index, 'before': doc.paragraphs[index].text, 'after': value})
        replace(doc.paragraphs[index], value)

    montage = ROOT / 'tmp/technical_report/hardware_montage.jpg'
    original = montage.read_bytes()
    image = Image.open(io.BytesIO(original)).convert('RGB')
    image.paste(image.crop((15, 15, 735, 485)).rotate(180), (15, 15))
    buf = io.BytesIO(); image.save(buf, format='JPEG', quality=95)
    replaced = 0
    for part in doc.part.package.parts:
        if part.content_type.startswith('image/') and hashlib.sha256(part.blob).digest() == hashlib.sha256(original).digest():
            part._blob = buf.getvalue(); replaced += 1
    if replaced != 1:
        raise ValueError(f'Expected one montage image, found {replaced}')

    doc.add_page_break()
    doc.add_heading('交付版本与闭环复核', level=1)
    doc.add_heading('一个测试点的完整反馈记录', level=3)
    doc.add_paragraph('以下摘录11月2日完整转移实验的DAC 2752点。目标VDS为0.500 V，接受窗口为0.485至0.515 V。每次观测后均记录漏极关断回读，下一次观测重新设定供电。')
    report = json.loads((ROOT / 'output/pcb1/transfer/run_20261102_222410_092311/transfer_report.json').read_text(encoding='utf-8'))
    point = next(p for p in report['results'] if p['dac_code'] == 2752)
    table = doc.add_table(rows=1, cols=5)
    table._tbl.replace(table._tbl.tblPr, deepcopy(doc.tables[0]._tbl.tblPr))
    table.autofit = False
    widths = [1.25, 3.1, 3.1, 3.2, 3.5]
    for cell, text in zip(table.rows[0].cells, ['观测', '电源设定 / V', '实测VDS / V', '误差 / mV', '接受判断']):
        cell.text = text
    for i, row in enumerate(point['iterations']):
        vals = [str(i+1), f"{row['supply_set_V']:.2f}", f"{row['VDS_V']:.4f}", f"{row['error_V']*1000:.2f}", '接受' if i == point['accepted_iteration'] else '窗口外']
        for cell, text in zip(table.add_row().cells, vals):
            cell.text = text
    for i, row in enumerate(table.rows):
        for cell, width in zip(row.cells, widths):
            cell.width = Cm(width)
            cell.vertical_alignment = 1
            for p in cell.paragraphs:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.first_line_indent = Cm(0)
                p.paragraph_format.left_indent = Cm(0)
                p.paragraph_format.right_indent = Cm(0)
                p.paragraph_format.space_before = Pt(5)
                p.paragraph_format.space_after = Pt(5)
                for run in p.runs:
                    run.font.size = Pt(10.5); run.bold = i == 0
        if i == 0:
            mark = OxmlElement('w:tblHeader'); row._tr.get_or_add_trPr().append(mark)
    doc.add_paragraph('第三次误差16.38 mV，仍超出窗口；第四次误差5.39 mV才接受。此处验证的是逐点接受逻辑。ADC、电流增益和分流电阻未完成精密标定，不能据此推导绝对测量精度。')
    doc.add_heading('冻结构建与影像版本', level=3)
    doc.add_paragraph('冻结实现报告时间为2026年11月3日11:52:45，目标时钟50 MHz，Setup WNS为7.640 ns，Hold WHS为0.048 ns。bit、LTX、时序与DRC报告随同一目录交付，完整SHA-256见清单。')
    bit_hash = hashlib.sha256((ROOT / 'output/mos_experiment/mos_experiment.bit').read_bytes()).hexdigest()
    p = doc.add_paragraph('mos_experiment.bit SHA-256\n' + bit_hash[:32] + '\n' + bit_hash[32:])
    for run in p.runs:
        run.font.name = 'Consolas'; run.font.size = Pt(9)
    doc.add_paragraph('原始PC录屏的旧工程页面曾显示WNS 11.446 ns及WHS 0.053 ns，属于较早构建。新版视频改用明确标注的冻结实现报告摘要，不将旧画面的数字替换成新测量。历史静态及11月2日实验用于对应版本的测量流程验证，不替代11月3日新增保护逻辑的板级验证。')
    doc.add_heading('离线复核与保留原件', level=3)
    doc.add_paragraph('交付包保留报告引用的原始CSV、供电JSON及日志。可运行副本仅将本机工程绝对路径转换为包内相对路径，测量数值不变；未经转换的JSON另存provenance目录，并在完整性清单中校验。代码为本次工作区快照，未宣称全部文件已发布到远端。')
    target = OUT / '技术文档_修订版.docx'
    doc.save(target)
    (OUT / 'report_changes.json').write_text(json.dumps({'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'changes': changes, 'photo_rotated': 'AX7020', 'added': '交付版本与闭环复核'}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(target)


if __name__ == '__main__':
    main()
