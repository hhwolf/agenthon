"""Render auditable Phase 2.5 tables; PDF source has exactly five chapters."""
import json
from pathlib import Path
import pandas as pd
from t2eval.phase2_5 import OUT, partitions


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join(['---']*len(headers))+' |',
                      *['| '+' | '.join(map(str, row))+' |' for row in rows]])+'\n'


def main():
    records = json.loads((OUT/'ablations.json').read_text())
    frozen = json.loads((OUT/'frozen-selection.json').read_text())
    selected = next(r for r in records if r['name'] == frozen['winner'])
    baseline = records[0]
    before = pd.read_csv(OUT/'cards-numeric_v1.csv'); after = pd.read_csv(OUT/'cards-selected.csv')
    merged = after.merge(before[['unit_id','score']], on='unit_id', suffixes=('', '_v1'), validate='one_to_one')
    changed = merged.loc[(merged.score >= 8) != (merged.score_v1 >= 8)].copy()
    changed['change'] = changed.score.ge(8).map({True:'new', False:'removed'})
    changed['partition'] = ['practice' if d == 'practice' else 'CV' if 2009 <= y <= 2018 else 'held-out' if y >= 2019 else 'warm-up' for d, y in zip(changed.dataset, changed.year)]
    changed['assets'] = ''
    rosters = {}
    for path in (Path('.eval/runs/backtest-m0-a9a5d3fc5371/roster.json'), Path('.eval/runs/eval-practice-numeric_v1-743299aa1923/roster.json')):
        for row in json.loads(path.read_text()): rosters[Path(row['unit']).name] = row['unit']
    from t2agent.io import read_card
    for idx, row in changed.iterrows():
        changed.loc[idx, 'assets'] = ','.join(read_card(Path(rosters[row.unit_id])/'card.toml')['targets']['asset_ids'])
    changed.to_csv(OUT/'capped-changes.csv', index=False)
    flat = []
    for r in records:
        for part, dimensions in r['breakdowns'].items():
            for dimension, rows in dimensions.items():
                for row in rows: flat.append({'candidate':r['name'], 'partition':part, 'dimension':dimension, **row})
    pd.DataFrame(flat).to_csv(OUT/'ablation-breakdowns.csv', index=False)
    ablation_rows = []
    summary_rows = []
    for r in records:
        decision = 'Baseline' if r == baseline else 'Kept' if r['accepted'] else 'Veto' if r['eligible_c1'] and any(r['veto'].values()) else 'Reject'
        vals = []
        summary = {'candidate':r['name'], 'previous':r['previous'], 'decision':decision}
        for part in ('cv', 'practice', 'heldout', 'historical'):
            m = r['metrics'][part]; summary.update({part+'_'+k:v for k,v in m.items()})
            vals.extend([f"{m['mean']:.6f}", m['capped']])
        summary_rows.append(summary)
        ablation_rows.append([r['name'], *vals[:6], decision])
    pd.DataFrame(summary_rows).to_csv(OUT/'ablation-summary.csv', index=False)
    names = {'cv':'CV 2009–2018', 'practice':'Practice proxies', 'heldout':'Report-only 2019–2024', 'historical':'All historical'}
    overview = []; cis=[]
    for part in names:
        b = baseline['metrics'][part]; s = selected['metrics'][part]; ci = selected['paired_numeric_v1'][part]
        overview.append([names[part], s['cards'], f"{b['mean']:.6f}", f"{s['mean']:.6f}", f"{b['capped']} → {s['capped']}", f"{s['median']:.6f}"])
        cis.append([names[part], f"{ci['delta']:+.6f}", f"[{ci['ci95'][0]:+.6f}, {ci['ci95'][1]:+.6f}]", f"{ci['year_wins']}/{ci['years']}"])
    cv_improvement = 100*(1-selected['metrics']['cv']['mean']/baseline['metrics']['cv']['mean'])
    page1 = f'''# Agenthon Track 2: numeric_v1.1

Phase 2.5 • 15 October 2026 • 2,000 draws • Lower scores are better

## Decision

Frozen selection: **{frozen['winner']}**. CV mean improves by **{cv_improvement:.2f}%** versus numeric_v1.
The fixed C1 rule and held-out major-group veto determine acceptance, with no added candidates after scoring.
Practice proxies participate in selection; they are not independent validation.
**The gain is not statistically established: every paired 95% CI includes zero.**
Historical caps rise from 23 to 24; the known monthly and rate-trend weaknesses remain unresolved.

{table(['Partition','Cards','numeric_v1','numeric_v1.1','Caps v1 → v1.1','v1.1 median'], overview)}

## Paired year-block bootstrap

{table(['Partition','Mean difference','95% percentile CI','Year wins'], cis)}

10,000 whole-year resamples, seed 20261015, pooled card-weighted means. Negative differences favor v1.1.
Intervals include dependence within each year but do not correct for selecting models on these same data.
Previously inspected 2019–2024 is report-only except for a fixed >15% group-regression veto.
'''
    page2 = f'''# Fixed-menu ablations

Each stage compares alternatives with the best entering that stage. All candidates are retained, including rejected ones.
Full previous-best identifiers, medians, errors, CIs, and breakdowns are in ablations.json and the companion CSVs.

{table(['Candidate','CV mean','Caps','Practice mean','Caps','2019–24 mean','Caps','Decision'],ablation_rows)}

## Acceptance and ordering

C1 requires a lower CV mean, or at most +0.005 worse with fewer combined CV+practice caps;
practice mean must not worsen, combined caps cannot rise, and no major CV/practice group may worsen >10%.
Major means ≥40 cards, or ≥20 for monthly macro. The reserved-year veto is >15% against either previous best or numeric_v1.
Ties within 0.0005 prefer fewer changed knobs. Year groups themselves are descriptive.

A1 isolates tail shape by normalizing variance. A2 uses exp(−h/τ) recent/long-run variance weights.
A3 floors variance. A4 changes only monthly handling. A5 pools whole joint draws 50/50; A6 replaces daily drift with momentum-sign drift.
'''
    yearly=[]; major=[]
    for dimension in ('year','panel','family','horizon_bucket','shape'):
        old_groups={x['group']:x for x in baseline['breakdowns']['heldout'][dimension]}
        for row in selected['breakdowns']['heldout'][dimension]:
            b=old_groups[row['group']]
            values=[row['group'],row['cards'],f"{b['mean']:.4f}",f"{row['mean']:.4f}",f"{100*(row['mean']/b['mean']-1):+.1f}%",f"{b['capped']} → {row['capped']}"]
            (yearly if dimension=='year' else major).append(values)
    page3=f'''# Reserved-year behavior

The precommitted veto checks major family, panel, horizon and single/joint groups.
These results did not rank candidate performance or expand the menu.

{table(['As-of year','Cards','v1 mean','v1.1 mean','Change','Caps'],yearly)}

{table(['Group','Cards','v1 mean','v1.1 mean','Change','Caps'],major)}

All smaller groups are shown, even when below the veto threshold. Full CV and practice group tables are in ablation-breakdowns.csv.
'''
    caprows=[]
    for row in changed.itertuples():
        label=row.unit_id.removeprefix('synthetic-20261014-')
        caprows.append([row.partition,row.change,label,row.assets,row.asof,f'{row.score_v1:.3f} → {row.score:.3f}'])
    (OUT/'CAPPED_CARDS.md').write_text('# Capped-card changes versus numeric_v1\n\n'+table(['Partition','Change','Card','Assets','As-of','Scores v1 → v1.1'],caprows))
    # Entire inventory is in CAPPED_CARDS.md and CSV; keep PDF page bounded if many changes.
    displayed=caprows[:18]
    focus=[]
    for title, mask in [('Monthly macro, 2022',(merged.panel=='macro_monthly') & (merged.year==2022) & (merged.dataset=='historical')),
                        ('Rates, 2022',(merged.panel=='rates_daily') & (merged.year==2022) & (merged.dataset=='historical')),
                        ('All historical, 2022',(merged.year==2022) & (merged.dataset=='historical'))]:
        g=merged.loc[mask];focus.append([title,len(g),f'{g.score_v1.mean():.4f}',f'{g.score.mean():.4f}',f'{int(g.score_v1.ge(8).sum())} → {int(g.score.ge(8).sum())}'])
    event = merged.loc[merged.unit_id.str.endswith('-00895') & (merged.dataset == 'historical')].iloc[0]
    event_text = f'The flagged CPI card synthetic-…-00895 stays capped: {event.score_v1:.3f} → {event.score:.3f}.'
    page4=f'''# Capped cards and known weaknesses

**{sum(changed.change=='removed')} removed, {sum(changed.change=='new')} new** capped evaluation rows across historical and practice.
Overlapping practice/historical outcomes are separate rows, not independent events.

{table(['Partition','Change','Card suffix / unit','Assets','As-of','v1 → v1.1'],displayed)}

{'Full inventory: CAPPED_CARDS.md and capped-changes.csv ('+str(len(caprows))+' rows).' if len(caprows)>18 else 'Full card identifiers and horizon labels: capped-changes.csv.'}

## Previously identified 2022 regressions

{table(['Historical subset','Cards','v1 mean','v1.1 mean','Caps'],focus)}

{event_text} The frozen winner keeps the original monthly trend and 25% trailing drift.
Monthly damping and the 36-change window were tested, but worsened practice mean and combined cap counts.
Momentum-sign drift reduced some practice losses but failed the CV tradeoff. None can be retained under C1.

These are post-selection diagnostics. Late-2021 zero-bound rates, 2008 and COVID transitions remain important stress cases.
The monthly series use revised historical vintages; improvements here do not establish real-time macro accuracy.
'''
    operational=OUT/'operational.json';op=json.loads(operational.read_text()) if operational.exists() else {}
    publication=OUT/'publication.json';pub=json.loads(publication.read_text()) if publication.exists() else {}
    page5=f'''# Reproducibility and delivery

## Frozen rules

```json
{json.dumps({k:frozen['config'][k] for k in ('drift','volatility','tails','monthly','joint','width')},indent=2)}
```

Only the tail law changes from numeric_v1. FHS uses five-change blocks and a lagged 60-change half-life filter.
The immutable Phase 2 numeric_config.json and frozen-selection.json are unchanged.
New configuration: reports/phase2_5/numeric_v1_1_config.json; runtime copy: t2agent/numeric_v1_1_config.json.
The protocol was committed as da26396 before scores. All 55,005 archived evaluation files matched their published manifest.

## Operational validation

{op.get('summary','Operational validation is pending; this draft is not a completed delivery.')}

{pub.get('summary','Image publication and anonymous-pull verification are pending.')}

## Limits and reproduction

CV and practice were used for selection. Year-block CIs do not remove that selection bias.
Practice includes 85 inferred business-day target sets and three explicit monthly sets.
Macro values include revisions; EM shapes can use G10 substitutes; historical calendars are approximations.
No sealed outcomes or organizer feedback were used. No competition pack or submission upload was run.

Restore data per reports/EVALUATION_DATA.md. Run `.venv/bin/python -m t2eval.phase2_5` in a fresh output copy;
it refuses to overwrite a freeze. Then run `make test`, `make admissibility FORECASTER=numeric_v1_1`, and
`make backtest FORECASTER=numeric_v1_1`. Every ablation calls the pinned official scoring implementation.
'''
    pages=[page1,page2,page3,page4,page5]
    (OUT/'RESULTS.md').write_text('\n\n'.join(pages))
    decisions=['# Candidate decisions\n']
    for r in records[1:]:
        decisions.append(f"## {r['name']} versus {r['previous']}\n\nAccepted: {r['accepted']}. C1 eligible: {r['eligible_c1']}.\n\nReasons: {', '.join(r['reasons']) or 'C1 passes'}. Veto: `{json.dumps(r['veto'])}`.\n")
    (OUT/'DECISIONS.md').write_text('\n'.join(decisions))
    (OUT/'pdf-pages.json').write_text(json.dumps(pages,indent=2)+'\n')
    print(json.dumps({'winner':frozen['winner'],'cap_changes':len(changed),'metrics':frozen['metrics']},indent=2))


if __name__=='__main__':main()
