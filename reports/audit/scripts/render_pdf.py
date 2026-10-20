"""Render reports/audit/AUDIT_PDF.md to a letter PDF through the gstack browse tool."""
from pathlib import Path
import subprocess

import markdown

ROOT = Path(__file__).resolve().parents[3]
BROWSE = Path.home()/'.claude/skills/gstack/browse/dist/browse'
src = (ROOT/'reports/audit/AUDIT_PDF.md').read_text()
pages = [p.strip() for p in src.split('\n<!-- pagebreak -->\n')]
body = ''.join('<section class="page">'+markdown.markdown(p, extensions=['tables', 'fenced_code'])+'</section>' for p in pages)
css = '''
@page {size: letter; margin: 0.7in;}
body {font: 8.6pt/1.3 Helvetica, Arial, sans-serif; color:#1b2a33; margin:0;}
h1 {font-size:17pt; color:#163e51; margin:0 0 6pt;}
h2 {font-size:11pt; color:#246782; margin:9pt 0 4pt; break-after:avoid;}
h3 {font-size:9.5pt; margin:7pt 0 3pt; break-after:avoid;}
p, li {margin:3pt 0;} ul, ol {margin:3pt 0 3pt 14pt; padding:0;}
.page {break-after:page;} .page:last-child {break-after:auto;}
table {border-collapse:collapse; width:100%; font-size:7.3pt; line-height:1.2; margin:5pt 0;}
th {text-align:left; background:#eaf1f4; border-bottom:1pt solid #246782;}
th,td {padding:2pt 3pt; vertical-align:top;} td {border-bottom:.4pt solid #ccd8de;}
tr {break-inside:avoid;}
code {font:7.2pt/1.2 Menlo,monospace; overflow-wrap:anywhere;}
pre {white-space:pre-wrap; margin:4pt 0; padding:5pt; background:#f2f5f7;}
'''
html = ROOT/'.context/audit/audit.html'
html.parent.mkdir(parents=True, exist_ok=True)
html.write_text('<!doctype html><html><head><meta charset="utf-8"><title>Agenthon Track 2 pre-submission audit</title><style>'
                + css + '</style></head><body>' + body + '</body></html>')
out = ROOT/'reports/audit/Agenthon_Track2_PreSubmission_Audit_2026-10-16.pdf'
subprocess.run([str(BROWSE), 'goto', html.as_uri()], check=True)
subprocess.run([str(BROWSE), 'pdf', str(out), '--format', 'letter', '--margins', '0.7in', '--page-numbers',
                '--print-background', '--tagged', '--outline', '--prefer-css-page-size'], check=True)
print(out)
