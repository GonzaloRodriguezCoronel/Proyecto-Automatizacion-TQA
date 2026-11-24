"""Generación real de PDF detallado y HTML autónomo a partir de los casos ejecutados."""
import base64
import html
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, Image as PDFImage,
)


PALETTE = {
    'PASS': '#15803D', 'FAIL': '#B91C1C', 'SKIPPED': '#A16207', 'NOT RUN': '#64748B'
}


def metrics(cases):
    counts = {name: sum(c['status'] == name for c in cases)
              for name in ('PASS', 'FAIL', 'SKIPPED', 'NOT RUN')}
    counts['total'] = len(cases)
    counts['success_rate'] = round(counts['PASS'] / len(cases) * 100, 1) if cases else 0
    return counts


def generate_html(run, cases, evidence_dir: Path, output: Path):
    counts = metrics(cases)
    cards = ''.join(
        f'<div class="metric"><span>{html.escape(k)}</span><strong>{counts[k]}</strong></div>'
        for k in ('total', 'PASS', 'FAIL', 'SKIPPED', 'NOT RUN')
    )
    rows = []
    for case in cases:
        details = []
        for st in case.get('steps', []):
            details.append('<li><strong>' + html.escape(st['action']) + '</strong><br>Esperado: ' +
                           html.escape(st['expected']) + '<br>Obtenido: ' + html.escape(st['observed']) + '</li>')
        inline_images = []
        for filename in case.get('evidence', []):
            path = evidence_dir / filename
            if path.is_file() and path.suffix.lower() == '.png':
                data = base64.b64encode(path.read_bytes()).decode('ascii')
                inline_images.append(f'<img alt="Evidencia {html.escape(filename)}" '
                                     f'src="data:image/png;base64,{data}">')
        xpath_lines = [f'<li><strong>XPath verificado paso {int(loc.get("step", 0))}:</strong> '
                       f'<code>{html.escape(str(loc.get("xpath", "")))}</code></li>'
                       for loc in case.get('locators', []) if loc.get('xpath')]
        video_info = ('<p><strong>Video de evidencias:</strong> ' + html.escape(case['video']) +
                      ' (reproducción disponible desde la aplicación TQA; no se adjunta en HTML).</p>') if case.get('video') else ''
        detail_html = ''.join(details) + ''.join(xpath_lines) + video_info + ''.join(inline_images)
        rows.append(f'''<tr><td>{html.escape(case['id'])}</td>
<td>{html.escape(case['name'])}</td><td>{html.escape(case['kind'])} / {html.escape(case['suite'])}</td>
<td><span class="status {case['status'].replace(' ', '-')}">{case['status']}</span></td>
<td>{case['duration_s']:.3f} s</td><td>{html.escape(case['observation'])}</td></tr>
<tr class="detail"><td colspan="6"><details><summary>Pasos y evidencias - {html.escape(case['id'])}</summary>
<ol>{detail_html}</ol></details></td></tr>''')
    code = f'''<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reporte {html.escape(run['id'])} | TQA Automation Center</title><style>
body{{background:#f6f8fc;color:#172239;font:15px/1.6 system-ui,sans-serif;margin:0;padding:36px}}
main{{max-width:1200px;margin:auto}}header{{background:#12233c;color:#fff;padding:30px;border-radius:18px}}
h1{{margin:0;font-size:27px}}p{{margin:7px 0}}.meta{{opacity:.85}}.cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:24px 0}}
.metric{{background:#fff;border:1px solid #dfe5ef;border-radius:12px;padding:18px}}.metric span{{display:block;color:#6a768e}}
.metric strong{{display:block;font-size:26px}}table{{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden}}
th,td{{text-align:left;border-bottom:1px solid #e5eaf1;padding:13px;vertical-align:top}}th{{background:#e9eef5;font-size:13px}}
.status{{font-weight:800;padding:5px 9px;border-radius:7px;display:inline-block;background:#e2e8f0;color:#475569;white-space:nowrap}}
.status.PASS{{background:#dcfce7;color:#166534}}.status.FAIL{{background:#fee2e2;color:#991b1b}}
.status.SKIPPED{{background:#fef3c7;color:#92400e}}.detail td{{background:#f8fafc;padding:6px 14px}}
details{{font-size:13px}}details ol{{padding-left:22px}}details img{{display:block;max-width:660px;width:95%;margin:14px 0;border:1px solid #ddd;border-radius:9px}}
footer{{color:#64748b;margin:30px 0}}@media(max-width:720px){{.cards{{grid-template-columns:repeat(2,1fr)}}body{{padding:12px}}table{{font-size:12px}}}}
</style></head><body><main><header><h1>TQA Automation Center</h1><p>Reporte HTML de ejecución real</p>
<p class="meta">ID: {html.escape(run['id'])} · Aplicación: {html.escape(run['target'])} · {html.escape(run['kind'])} / {html.escape(run['suite'])}</p>
<p class="meta">Inicio: {html.escape(str(run.get('started_at') or ''))} · Fin: {html.escape(str(run.get('finished_at') or ''))} · Duración: {float(run.get('duration_s') or 0):.2f} s</p>
<p class="meta">Correo destinatario: {html.escape(run['email'])} · Estado: {html.escape(run['status'])}</p></header>
<div class="cards">{cards}</div><p><strong>Tasa de éxito:</strong> {counts['success_rate']}% (PASS / total de casos seleccionados).</p>
<table><thead><tr><th>ID</th><th>Nombre</th><th>Tipo / suite</th><th>Estado</th><th>Duración</th><th>Observación</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<footer>Los estados provienen de pruebas ejecutadas. Los errores de infraestructura se distinguen como NOT RUN. Documento HTML autónomo.</footer>
</main></body></html>'''
    output.write_text(code, encoding='utf-8')


def generate_pdf(run, cases, evidence_dir: Path, output: Path):
    counts = metrics(cases)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='TqaTitle', parent=styles['Title'], textColor=colors.HexColor('#13253c'), fontSize=21, leading=26, spaceAfter=14))
    styles.add(ParagraphStyle(name='TqaH', parent=styles['Heading2'], textColor=colors.HexColor('#143f68'), fontSize=12, leading=16, spaceBefore=13, spaceAfter=8))
    styles.add(ParagraphStyle(name='TqaSmall', parent=styles['Normal'], fontSize=8.7, leading=13, spaceAfter=5))
    styles.add(ParagraphStyle(name='TqaMuted', parent=styles['TqaSmall'], textColor=colors.HexColor('#546176')))
    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
                            topMargin=18*mm, bottomMargin=18*mm, title=f'TQA {run["id"]}')
    story = [Paragraph('TQA Automation Center', styles['TqaTitle']),
             Paragraph('Informe detallado de ejecución automatizada', styles['TqaH'])]
    def paragraph(content, style='TqaSmall'):
        return Paragraph(escape(str(content)).replace('\n', '<br/>'), styles[style])
    details = [
        ('Identificador', run['id']), ('Aplicación', run['target']),
        ('Tipo y suite', f"{run['kind']} / {run['suite']}"),
        ('Ambiente', 'Local / pruebas'), ('Correo', run['email']),
        ('Inicio', run.get('started_at') or ''), ('Fin', run.get('finished_at') or ''),
        ('Duración', f"{float(run.get('duration_s') or 0):.2f} segundos"),
        ('Resultado global', run['status']),
    ]
    table = Table([[paragraph(a), paragraph(b)] for a, b in details], colWidths=[46*mm, 124*mm])
    table.setStyle(TableStyle([('BACKGROUND', (0,0), (0,-1), colors.HexColor('#edf3f9')),
                               ('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),8),
                               ('TOPPADDING',(0,0),(-1,-1),8),('LINEBELOW',(0,0),(-1,-2),.4,colors.HexColor('#dce5ee'))]))
    story.extend([table, Spacer(1, 10), Paragraph('Resumen de resultados', styles['TqaH'])])
    summary = f"Total: {counts['total']} | PASS: {counts['PASS']} | FAIL: {counts['FAIL']} | SKIPPED: {counts['SKIPPED']} | NOT RUN: {counts['NOT RUN']} | Éxito: {counts['success_rate']}%"
    story.append(paragraph(summary))
    story.append(paragraph('Un FAIL es un incumplimiento de la expectativa; NOT RUN es un fallo de infraestructura o ejecución.', 'TqaMuted'))
    for i, case in enumerate(cases, 1):
        story.append(Paragraph(f'{i}. {escape(case["id"])} - {escape(case["name"])}', styles['TqaH']))
        data = [
            ('Tipo / suite', f"{case['kind']} / {case['suite']}"),
            ('Objetivo', case['objective']), ('Precondiciones', case['preconditions']),
            ('Resultado esperado', case['expected']),
            ('Estado', case['status']), ('Duración', f"{case['duration_s']:.3f} s"),
            ('Observación / error', case['observation']),
        ]
        for name, value in data:
            story.append(paragraph(f'{name}: {value}'))
        story.append(paragraph('Pasos previstos:', 'TqaMuted'))
        for n, planned in enumerate(case['planned_steps'], 1):
            story.append(paragraph(f'{n}. {planned}'))
        story.append(paragraph('Pasos ejecutados y resultados:', 'TqaMuted'))
        if not case['steps']:
            story.append(paragraph('No hubo pasos ejecutados.', 'TqaMuted'))
        for n, st in enumerate(case['steps'], 1):
            story.append(paragraph(f"{n}. {st['action']} | Esperado: {st['expected']} | Obtenido: {st['observed']} | {st['status']}"))
        locators = [loc for loc in case.get('locators', []) if loc.get('xpath')]
        if locators:
            story.append(paragraph('XPath verificados contra el navegador:', 'TqaMuted'))
            for loc in locators[:30]:
                story.append(paragraph(f"Paso {loc['step']}: {loc['xpath']} (selector grabado: {loc['selector']})"))
        if case.get('video'):
            story.append(paragraph('Video de evidencia por pasos: ' + case['video'] +
                         '. Reproducir y descargar desde Historial o Selenium IDE en TQA; '
                         'el video no se adjunta al correo. No es una grabación continua.'))
        story.append(paragraph('Evidencias:', 'TqaMuted'))
        for file in case.get('evidence', []):
            file_path = evidence_dir / file
            if not file_path.is_file():
                story.append(paragraph(f'{file} (no disponible)'))
            elif file_path.suffix.lower() == '.png':
                try:
                    pic = PDFImage(str(file_path))
                    scale = min((165*mm) / pic.imageWidth, (90*mm) / pic.imageHeight, 1)
                    pic.drawWidth = pic.imageWidth * scale
                    pic.drawHeight = pic.imageHeight * scale
                    story.extend([paragraph(file), pic, Spacer(1, 7)])
                except Exception:
                    story.append(paragraph(f'{file}: no pudo incrustarse la imagen'))
            else:
                story.append(paragraph(f'{file} - registro de pasos y resultados en archivo de evidencia.'))
    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawString(18*mm, 11*mm, 'TQA Automation Center - Evidencias de ejecución')
        canvas.drawRightString(192*mm, 11*mm, str(document.page))
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
