"""Render five explicit report chapters through the existing Chromium browse tool."""
import argparse
import json
from pathlib import Path
import subprocess

import markdown

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--browse', required=True, type=Path, help='Path to gstack browse executable')
args = parser.parse_args()
root = Path('reports/phase2_5')
pages = json.loads((root/'pdf-pages.json').read_text())
assert len(pages) == 5
sections = []
for page in pages:
    body = markdown.markdown(page, extensions=['tables', 'fenced_code'])
    sections.append('<section class="page">'+body+'</section>')
css = '''
@page {size: letter; margin: 1in;}
body {font: 10pt/1.35 Helvetica, Arial, sans-serif; color:#182c39; margin:0;}
h1 {font-size:23pt; line-height:1.12; color:#163e51; margin:0 0 15pt;}
h2 {font-size:12.5pt; color:#246782; margin:14pt 0 6pt; break-after:avoid;}
p {margin:7pt 0; orphans:3; widows:3;}
.page {break-after:page;} .page:last-child {break-after:auto;}
table {border-collapse:collapse; width:100%; font-size:8pt; line-height:1.25; margin:10pt 0;}
th {text-align:left; background:#eaf1f4; border-bottom:1pt solid #246782;}
th,td {padding:4pt 3pt;} td {border-bottom:.4pt solid #ccd8de;}
tr {break-inside:avoid;} thead {display:table-header-group;}
code {font:8pt/1.2 Menlo,monospace; overflow-wrap:anywhere;}
pre {white-space:pre-wrap; margin:8pt 0; padding:7pt; background:#f2f5f7;}
a {color:#246782; text-decoration:none;}
'''
report = Path('.context/phase2_5/report.html').resolve()
report.parent.mkdir(parents=True, exist_ok=True)
report.write_text('<!doctype html><html><head><meta charset="utf-8"><title>Agenthon numeric_v1.1 — Phase 2.5</title><style>'+css+'</style></head><body>'+''.join(sections)+'</body></html>')
output = (root/'Agenthon_Track2_Phase2_5_Results.pdf').resolve()
subprocess.run([str(args.browse), 'goto', report.as_uri()], check=True)
subprocess.run([str(args.browse), 'pdf', str(output), '--format', 'letter', '--margins', '1in',
                '--page-numbers', '--print-background', '--tagged', '--outline', '--prefer-css-page-size'], check=True)
print(output)
