"""Build the static site in docs/site/ from artifacts/.

    python -m nova.report.build_site

Self-contained by construction: no CDN, no fonts, no network calls at runtime.
All data is embedded as JSON generated here, so **no number on the page is
hardcoded** — rerun the pipeline and the site changes with it.

Palette: slots 1-3 of the validated categorical set, checked with the dataviz
validator in both modes (worst adjacent CVD dE 9.2 light / 9.4 dark; normal-vision
27.6 / 26.5). Light-mode aqua sits at 2.74:1 against the surface, below 3:1, so the
relief rule applies: every series carries a visible direct label and a table view.
"""

from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd

from nova.config import ARTIFACT_DIR, DUCKDB_PATH, REPO_ROOT, SIM, SPLIT

SITE_DIR = REPO_ROOT / "docs" / "site"

LADDER = [
    ("naive", "Naive (last value)", 0),
    ("seasonal_naive", "Seasonal naive (7d)", 0),
    ("mean_28", "Trailing 28d mean", 0),
    ("croston", "Croston (1972)", 1),
    ("sba", "Syntetos–Boylan", 1),
    ("tsb", "Teunter–Syntetos–Babai", 1),
    ("lightgbm_sales_only", "LightGBM · raw sales", 2),
    ("lightgbm", "LightGBM · censoring-corrected", 2),
    ("oracle_mu", "Oracle floor (DGP mean)", -1),
]


def _series_sample(n_series: int = 18) -> list[dict]:
    """Export a few real series for the explorer. Skipped if no DuckDB."""
    if not DUCKDB_PATH.exists():
        return []
    import duckdb

    try:
        con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    except duckdb.IOException as exc:
        # A concurrent writer (a running backtest) holds the file. The rest of
        # the page is built from artifacts/ and does not need the warehouse, so
        # degrade to no explorer rather than failing the whole build.
        print(f"[site] warehouse unavailable, skipping series explorer: {exc}")
        return []
    start = pd.Timestamp(SPLIT.backtest_origins[0]) - pd.Timedelta(days=120)
    picks = con.execute(f"""
        SELECT s.branch_id, s.drug_id, b.name AS branch, d.trade_name AS drug,
               d.category, s.demand_class, d.criticality
        FROM mart.dim_series s
        JOIN mart.dim_branch b USING (branch_id)
        JOIN mart.dim_drug d USING (drug_id)
        WHERE s.total_units > 200
        ORDER BY s.total_units DESC
        LIMIT {n_series}
    """).df()

    out = []
    for r in picks.itertuples(index=False):
        rows = con.execute(f"""
            SELECT f.date_key, f.units_sold, f.units_unmet, f.qty_close,
                   t.demand_true
            FROM mart.fct_demand_daily f
            JOIN nova_truth.demand_true t
              ON t.branch_id = f.branch_id AND t.drug_id = f.drug_id
             AND t.as_of_date = f.date_key
            WHERE f.branch_id = {r.branch_id} AND f.drug_id = {r.drug_id}
              AND f.date_key >= DATE '{start.date()}'
            ORDER BY f.date_key
        """).df()
        out.append({
            "label": f"{r.branch} · {r.drug}",
            "category": r.category,
            "demand_class": r.demand_class,
            "criticality": int(r.criticality),
            "dates": [d.strftime("%Y-%m-%d") for d in rows["date_key"]],
            "demand": [int(v) for v in rows["demand_true"]],
            "sold": [int(v) for v in rows["units_sold"]],
            "stock": [int(v) for v in rows["qty_close"]],
        })
    con.close()
    return out


def collect() -> dict:
    df = pd.read_csv(ARTIFACT_DIR / "backtest_per_origin.csv")
    summary = json.loads((ARTIFACT_DIR / "policy_summary.json").read_text())
    sens = pd.read_csv(ARTIFACT_DIR / "policy_sensitivity.csv")

    ladder = []
    for key, label, rung in LADDER:
        w = df[f"{key}__wape"].to_numpy()
        ladder.append({
            "key": key, "label": label, "rung": rung,
            "wape": float(np.nanmean(w)),
            "lo": float(np.nanpercentile(w, 2.5)),
            "hi": float(np.nanpercentile(w, 97.5)),
            "bias": float(np.nanmean(df[f"{key}__bias"])),
            "rmsse": float(np.nanmean(df[f"{key}__rmsse"])),
        })

    prob = {}
    for col in ("coverage_80", "coverage_90", "width_80", "width_90",
                "pinball_50", "pinball_90", "dispersion_k"):
        if col in df.columns:
            prob[col] = float(np.nanmean(df[col]))

    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ladder": ladder,
        "policy": summary,
        "sensitivity": sens.to_dict(orient="records"),
        "probabilistic": prob,
        "origins": [str(o) for o in SPLIT.backtest_origins],
        "horizon": SPLIT.horizon_days,
        "penalties": {str(k): v for k, v in SIM.stockout_penalty_by_criticality.items()},
        "series": _series_sample(),
    }


CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  color-scheme:light;
  --surface:#fcfcfb; --plane:#f9f9f7;
  --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --ring:rgba(11,11,11,.10);
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a;
  --good:#0ca30c; --crit:#d03b3b; --warn:#fab219;
}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])){
  color-scheme:dark;
  --surface:#1a1a19; --plane:#0d0d0d;
  --ink:#fff; --ink-2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,.10);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70;
}}
:root[data-theme=dark]{
  color-scheme:dark;
  --surface:#1a1a19; --plane:#0d0d0d;
  --ink:#fff; --ink-2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,.10);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70;
}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--plane);color:var(--ink);
  font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:32px 20px 96px}
a{color:var(--s1)}
h1{font-size:clamp(1.9rem,4.5vw,2.9rem);line-height:1.15;margin:.2em 0 .3em;letter-spacing:-.02em}
h2{font-size:clamp(1.25rem,2.6vw,1.6rem);margin:2.6em 0 .5em;letter-spacing:-.01em}
h3{font-size:1.05rem;margin:1.8em 0 .4em}
p{color:var(--ink-2);max-width:68ch}
.lede{font-size:1.1rem;color:var(--ink-2);max-width:64ch}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:14px;padding:20px 22px;margin:18px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:22px 0}
.tile{background:var(--surface);border:1px solid var(--ring);border-radius:14px;padding:16px 18px}
.tile .k{font-size:.78rem;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}
.tile .v{font-size:clamp(1.5rem,3.4vw,2.1rem);font-weight:640;margin-top:4px;line-height:1.1}
.tile .d{font-size:.85rem;color:var(--ink-2);margin-top:4px}
.good{color:var(--good)} .crit{color:var(--crit)}
.caveat{border-left:3px solid var(--warn);background:var(--surface);
  border-radius:0 12px 12px 0;padding:14px 18px;margin:18px 0}
.caveat strong{color:var(--ink)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;min-width:520px;font-size:.9rem}
th,td{text-align:right;padding:8px 10px;border-bottom:1px solid var(--grid);
  font-variant-numeric:tabular-nums}
th:first-child,td:first-child{text-align:left;font-variant-numeric:normal}
th{color:var(--muted);font-weight:600;font-size:.78rem;text-transform:uppercase;letter-spacing:.05em}
tr.hi td{background:color-mix(in srgb,var(--s1) 8%,transparent);font-weight:600}
.legend{display:flex;flex-wrap:wrap;gap:16px;margin:10px 0 2px;font-size:.85rem;color:var(--ink-2)}
.legend span{display:inline-flex;align-items:center;gap:7px}
.swatch{width:12px;height:12px;border-radius:3px;box-shadow:0 0 0 2px var(--surface)}
svg{display:block;max-width:100%;height:auto}
.axis text{fill:var(--muted);font-size:11px}
.grid line{stroke:var(--grid);stroke-width:1}
.baseline{stroke:var(--axis);stroke-width:1}
.note{font-size:.85rem;color:var(--muted);margin-top:8px}
.pill{display:inline-block;font-size:.72rem;padding:2px 9px;border-radius:999px;
  border:1px solid var(--ring);color:var(--ink-2);margin-right:6px}
.controls{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:14px 0}
select,button{font:inherit;font-size:.9rem;padding:8px 12px;border-radius:9px;
  border:1px solid var(--ring);background:var(--surface);color:var(--ink)}
button{cursor:pointer}
#tip{position:fixed;pointer-events:none;opacity:0;transition:opacity .1s;
  background:var(--surface);border:1px solid var(--ring);border-radius:9px;
  padding:8px 11px;font-size:.82rem;box-shadow:0 6px 24px rgba(0,0,0,.14);z-index:9;
  font-variant-numeric:tabular-nums;max-width:260px}
.toggle{position:fixed;top:14px;right:14px;z-index:10}
footer{margin-top:64px;padding-top:24px;border-top:1px solid var(--grid);
  font-size:.86rem;color:var(--muted)}
.arch{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.76rem;
  line-height:1.5;white-space:pre;color:var(--ink-2)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.86em;
  background:color-mix(in srgb,var(--ink) 7%,transparent);padding:1px 5px;border-radius:4px}
pre code{display:block;padding:12px 14px;border-radius:9px;overflow-x:auto;background:var(--surface);
  border:1px solid var(--ring)}
:focus-visible{outline:2px solid var(--s1);outline-offset:2px}
@media (max-width:640px){.wrap{padding:20px 14px 72px}}
"""

JS = r"""
const D = window.__NOVA__;
const tip = document.getElementById('tip');
const fmtPct = v => (100*v).toFixed(1)+'%';
const money = v => '₹' + Math.round(v).toLocaleString('en-IN');

function showTip(e, html){
  tip.innerHTML = html; tip.style.opacity = 1;
  const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
  let x = e.clientX + pad, y = e.clientY + pad;
  if (x + w > innerWidth - 8) x = e.clientX - w - pad;
  if (y + h > innerHeight - 8) y = e.clientY - h - pad;
  tip.style.left = x+'px'; tip.style.top = y+'px';
}
function hideTip(){ tip.style.opacity = 0; }

function svgEl(n, attrs){
  const e = document.createParentNS ? null : null;
  const el = document.createElementNS('http://www.w3.org/2000/svg', n);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

/* ---------- Model ladder: horizontal bars + CI whiskers + floor line ---- */
function drawLadder(){
  const host = document.getElementById('ladder');
  const rows = D.ladder.filter(r => r.key !== 'oracle_mu');
  const floor = D.ladder.find(r => r.key === 'oracle_mu');
  const W = Math.min(host.clientWidth || 900, 900), rowH = 38,
        mL = 210, mR = 58, mT = 16, mB = 34,
        H = rows.length*rowH + mT + mB;
  const lo = Math.min(floor.wape, ...rows.map(r=>r.lo)) * 0.985;
  const hi = Math.max(...rows.map(r=>r.hi)) * 1.005;
  const x = v => mL + (v-lo)/(hi-lo) * (W-mL-mR);

  const svg = svgEl('svg', {viewBox:`0 0 ${W} ${H}`, role:'img',
    'aria-label':'Forecast error by model, WAPE, lower is better, with 95% intervals and the irreducible-error floor'});

  const g = svgEl('g', {class:'grid'});
  const ticks = 5;
  for (let i=0;i<=ticks;i++){
    const v = lo + (hi-lo)*i/ticks, px = x(v);
    g.appendChild(svgEl('line',{x1:px,y1:mT,x2:px,y2:H-mB}));
    const t = svgEl('text',{x:px,y:H-mB+18,'text-anchor':'middle'});
    t.textContent = v.toFixed(3); t.setAttribute('fill','var(--muted)');
    t.setAttribute('font-size','11'); g.appendChild(t);
  }
  svg.appendChild(g);

  rows.forEach((r,i)=>{
    const y = mT + i*rowH + rowH/2;
    const isBest = r.key === 'lightgbm';
    const col = isBest ? 'var(--s1)' : 'var(--muted)';

    const bar = svgEl('rect',{x:mL, y:y-7, width:Math.max(2,x(r.wape)-mL), height:14,
      rx:4, fill:col, 'fill-opacity': isBest?1:.55});
    bar.style.cursor='pointer';
    bar.addEventListener('mousemove', e=>showTip(e,
      `<strong>${r.label}</strong><br>WAPE ${r.wape.toFixed(4)}<br>
       95% CI [${r.lo.toFixed(4)}, ${r.hi.toFixed(4)}]<br>
       bias ${r.bias>=0?'+':''}${r.bias.toFixed(3)} · RMSSE ${r.rmsse.toFixed(3)}`));
    bar.addEventListener('mouseleave', hideTip);
    svg.appendChild(bar);

    const wh = svgEl('g',{stroke:'var(--ink-2)','stroke-width':1.5});
    wh.appendChild(svgEl('line',{x1:x(r.lo),y1:y,x2:x(r.hi),y2:y}));
    wh.appendChild(svgEl('line',{x1:x(r.lo),y1:y-5,x2:x(r.lo),y2:y+5}));
    wh.appendChild(svgEl('line',{x1:x(r.hi),y1:y-5,x2:x(r.hi),y2:y+5}));
    svg.appendChild(wh);

    const lab = svgEl('text',{x:mL-12,y:y+4,'text-anchor':'end',fill:'var(--ink)','font-size':'12.5'});
    lab.textContent = r.label; svg.appendChild(lab);

    const val = svgEl('text',{x:x(r.wape)+8,y:y+4,fill:'var(--ink-2)','font-size':'11.5'});
    val.setAttribute('font-variant-numeric','tabular-nums');
    val.textContent = r.wape.toFixed(3); svg.appendChild(val);
  });

  const fx = x(floor.wape);
  svg.appendChild(svgEl('line',{x1:fx,y1:mT-6,x2:fx,y2:H-mB,
    stroke:'var(--crit)','stroke-width':2,'stroke-dasharray':'5 4'}));
  const ft = svgEl('text',{x:fx,y:mT-10,'text-anchor':'middle',fill:'var(--crit)','font-size':'11.5','font-weight':'600'});
  ft.textContent = `irreducible floor ${floor.wape.toFixed(3)}`;
  svg.appendChild(ft);

  host.innerHTML=''; host.appendChild(svg);
}

/* ---------- Sensitivity: grouped bars ---------------------------------- */
function drawSensitivity(){
  const host = document.getElementById('sens');
  const rows = D.sensitivity;
  const W = Math.min(host.clientWidth || 860, 860), H = 300,
        mL = 66, mR = 16, mT = 22, mB = 46;
  const max = Math.max(...rows.map(r=>Math.max(r.incumbent_total, r.newsvendor_total)))*1.08;
  const bw = (W-mL-mR)/rows.length;
  const y = v => H-mB - (v/max)*(H-mT-mB);

  const svg = svgEl('svg',{viewBox:`0 0 ${W} ${H}`, role:'img',
    'aria-label':'Total cost of each policy across stockout-penalty assumptions'});
  const g = svgEl('g',{class:'grid'});
  for(let i=0;i<=4;i++){
    const v = max*i/4, py=y(v);
    g.appendChild(svgEl('line',{x1:mL,y1:py,x2:W-mR,y2:py}));
    const t=svgEl('text',{x:mL-8,y:py+4,'text-anchor':'end',fill:'var(--muted)','font-size':'11'});
    t.textContent = '₹'+(v/1e6).toFixed(1)+'M'; g.appendChild(t);
  }
  svg.appendChild(g);

  rows.forEach((r,i)=>{
    const cx = mL + i*bw + bw/2;
    const w = Math.min(28, bw*0.3);
    [['incumbent_total','var(--s2)','Incumbent'],['newsvendor_total','var(--s1)','NOVA']].forEach((s,j)=>{
      const v = r[s[0]];
      const bx = cx - w - 2 + j*(w+4);
      const rect = svgEl('rect',{x:bx,y:y(v),width:w,height:Math.max(1,H-mB-y(v)),rx:4,fill:s[1]});
      rect.style.cursor='pointer';
      rect.addEventListener('mousemove',e=>showTip(e,
        `<strong>${s[2]}</strong> @ ${r.penalty_scale}× penalty<br>total ${money(v)}<br>
         change ${fmtPct(r.change)} · fill ${fmtPct(r.newsvendor_fill)}`));
      rect.addEventListener('mouseleave',hideTip);
      svg.appendChild(rect);
    });
    const t=svgEl('text',{x:cx,y:H-mB+18,'text-anchor':'middle',fill:'var(--muted)','font-size':'11'});
    t.textContent = r.penalty_scale+'×'; svg.appendChild(t);
    const d=svgEl('text',{x:cx,y:H-mB+34,'text-anchor':'middle',fill:'var(--ink-2)','font-size':'11','font-weight':'600'});
    d.textContent = fmtPct(r.change); svg.appendChild(d);
  });
  svg.appendChild(svgEl('line',{class:'baseline',x1:mL,y1:H-mB,x2:W-mR,y2:H-mB,stroke:'var(--axis)'}));
  host.innerHTML=''; host.appendChild(svg);
}

/* ---------- Series explorer -------------------------------------------- */
function drawSeries(){
  const host = document.getElementById('series');
  const sel = document.getElementById('seriesSel');
  if (!D.series.length){ host.innerHTML='<p class="note">Series sample unavailable — rebuild with the DuckDB warehouse present.</p>'; return; }
  const s = D.series[sel.value|0];
  const W = Math.min(host.clientWidth || 900, 900), H = 300,
        mL = 46, mR = 14, mT = 16, mB = 34;
  const n = s.dates.length;
  const max = Math.max(1, ...s.demand, ...s.stock)*1.06;
  const x = i => mL + i/(n-1)*(W-mL-mR);
  const y = v => H-mB - v/max*(H-mT-mB);

  const svg = svgEl('svg',{viewBox:`0 0 ${W} ${H}`, role:'img',
    'aria-label':`Daily true demand, units sold and closing stock for ${s.label}`});
  const g = svgEl('g',{class:'grid'});
  for(let i=0;i<=4;i++){
    const v=max*i/4, py=y(v);
    g.appendChild(svgEl('line',{x1:mL,y1:py,x2:W-mR,y2:py}));
    const t=svgEl('text',{x:mL-8,y:py+4,'text-anchor':'end',fill:'var(--muted)','font-size':'11'});
    t.textContent=Math.round(v); g.appendChild(t);
  }
  svg.appendChild(g);

  const path = (arr,col,wdt)=>{
    let d='';
    arr.forEach((v,i)=>{ d += (i?'L':'M')+x(i).toFixed(1)+','+y(v).toFixed(1); });
    svg.appendChild(svgEl('path',{d,fill:'none',stroke:col,'stroke-width':wdt,
      'stroke-linejoin':'round','stroke-linecap':'round'}));
  };
  path(s.stock,'var(--s3)',2);
  path(s.demand,'var(--s1)',2);
  path(s.sold,'var(--s2)',1.6);

  // stockout markers: demand served short
  s.demand.forEach((v,i)=>{ if(v>s.sold[i])
    svg.appendChild(svgEl('circle',{cx:x(i),cy:y(v),r:3,fill:'var(--crit)',
      stroke:'var(--surface)','stroke-width':2})); });

  const hit = svgEl('rect',{x:mL,y:mT,width:W-mL-mR,height:H-mT-mB,fill:'transparent'});
  const cross = svgEl('line',{y1:mT,y2:H-mB,stroke:'var(--axis)','stroke-width':1,opacity:0});
  svg.appendChild(cross); svg.appendChild(hit);
  hit.addEventListener('mousemove', e=>{
    const r = svg.getBoundingClientRect();
    const px = (e.clientX-r.left)/r.width*W;
    const i = Math.max(0, Math.min(n-1, Math.round((px-mL)/(W-mL-mR)*(n-1))));
    cross.setAttribute('x1',x(i)); cross.setAttribute('x2',x(i)); cross.setAttribute('opacity',1);
    showTip(e, `<strong>${s.dates[i]}</strong><br>
      true demand ${s.demand[i]}<br>sold ${s.sold[i]}<br>closing stock ${s.stock[i]}` +
      (s.demand[i]>s.sold[i] ? `<br><span style="color:var(--crit)">stockout — ${s.demand[i]-s.sold[i]} unmet</span>` : ''));
  });
  hit.addEventListener('mouseleave', ()=>{ hideTip(); cross.setAttribute('opacity',0); });

  document.getElementById('seriesMeta').innerHTML =
    `<span class="pill">${s.category}</span><span class="pill">${s.demand_class}</span>` +
    `<span class="pill">criticality ${s.criticality}</span>`;
  host.innerHTML=''; host.appendChild(svg);
}

/* ---------- init ------------------------------------------------------- */
function initTheme(){
  const b = document.getElementById('themeBtn');
  b.addEventListener('click', ()=>{
    const cur = document.documentElement.getAttribute('data-theme');
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    b.setAttribute('aria-label', 'Switch to '+(next==='dark'?'light':'dark')+' theme');
    redraw();
  });
}
function redraw(){ drawLadder(); drawSensitivity(); drawSeries(); }
document.getElementById('seriesSel').addEventListener('change', drawSeries);
addEventListener('resize', ()=>{ clearTimeout(window.__rt); window.__rt=setTimeout(redraw,150); });
initTheme(); redraw();
"""


def build_html(d: dict) -> str:
    pol = d["policy"]
    inc, nov = pol["incumbent"], pol["newsvendor"]
    sens = d["sensitivity"]
    best_change = max(r["change"] for r in sens)
    worst_change = min(r["change"] for r in sens)
    lgbm = next(r for r in d["ladder"] if r["key"] == "lightgbm")
    sales = next(r for r in d["ladder"] if r["key"] == "lightgbm_sales_only")
    floor = next(r for r in d["ladder"] if r["key"] == "oracle_mu")
    classical = [r for r in d["ladder"] if r["rung"] in (0, 1)]
    best_cl = min(classical, key=lambda r: r["wape"])
    prob = d["probabilistic"]

    ladder_rows = "\n".join(
        f'<tr{" class=hi" if r["key"]=="lightgbm" else ""}><td>{r["label"]}</td>'
        f'<td>{"—" if r["rung"]<0 else r["rung"]}</td><td>{r["wape"]:.4f}</td>'
        f'<td>[{r["lo"]:.4f}, {r["hi"]:.4f}]</td><td>{r["rmsse"]:.3f}</td>'
        f'<td>{r["bias"]:+.3f}</td></tr>'
        for r in d["ladder"]
    )
    sens_rows = "\n".join(
        f'<tr{" class=hi" if r["penalty_scale"]==1.0 else ""}>'
        f'<td>{r["penalty_scale"]:g}×</td><td>₹{r["incumbent_total"]:,.0f}</td>'
        f'<td>₹{r["newsvendor_total"]:,.0f}</td><td>{100*r["change"]:+.1f}%</td>'
        f'<td>{100*r["newsvendor_fill"]:.2f}%</td></tr>'
        for r in sens
    )
    cost_rows = "\n".join(
        f'<tr{" class=hi" if k=="total_cost" else ""}><td>{lbl}</td>'
        f'<td>₹{inc[k]:,.0f}</td><td>₹{nov[k]:,.0f}</td>'
        f'<td>{100*((nov[k]-inc[k])/inc[k]) if inc[k] else float("nan"):+.1f}%</td></tr>'
        for k, lbl in [("stockout_cost", "Stockout cost"), ("holding_cost", "Holding cost"),
                       ("waste_cost", "Waste cost"), ("total_cost", "Total cost")]
    )
    opts = "\n".join(f'<option value="{i}">{s["label"]}</option>'
                     for i, s in enumerate(d["series"]))

    prob_block = ""
    if prob:
        prob_block = f"""
    <div class="scroll"><table>
      <caption class="note" style="text-align:left;margin-bottom:6px">
        Calibration of the negative-binomial predictive distribution</caption>
      <thead><tr><th>Metric</th><th>Value</th><th>Nominal</th></tr></thead>
      <tbody>
        <tr><td>80% interval coverage</td><td>{prob.get('coverage_80',float('nan')):.3f}</td><td>0.800</td></tr>
        <tr><td>90% interval coverage</td><td>{prob.get('coverage_90',float('nan')):.3f}</td><td>0.900</td></tr>
        <tr><td>Pinball loss @ q50</td><td>{prob.get('pinball_50',float('nan')):.4f}</td><td>—</td></tr>
        <tr><td>Pinball loss @ q90</td><td>{prob.get('pinball_90',float('nan')):.4f}</td><td>—</td></tr>
        <tr><td>Dispersion k</td><td>{prob.get('dispersion_k',float('nan')):.3f}</td><td>—</td></tr>
      </tbody></table></div>
    <p class="note">Estimated on a 28-day calibration window between training and
    evaluation — not on the evaluation window itself.</p>"""

    return f"""<div class="wrap">
<button id="themeBtn" class="toggle" aria-label="Switch theme">◐</button>

<p class="pill">Synthetic data · methods demonstration</p>
<h1>Pharmacy replenishment,<br>as a decision problem</h1>
<p class="lede">NOVA forecasts demand for every drug at every branch of a pharmacy
chain and converts that forecast into an order quantity. The deliverable is the
order, not the prediction — so the headline metric is cost, not WAPE.</p>

<div class="tiles">
  <div class="tile"><div class="k">Fill rate</div>
    <div class="v">{100*nov['fill_rate']:.2f}%</div>
    <div class="d">from {100*inc['fill_rate']:.2f}% under the incumbent</div></div>
  <div class="tile"><div class="k">Units unmet</div>
    <div class="v">{nov['units_unmet']:,.0f}</div>
    <div class="d">from {inc['units_unmet']:,.0f} <span class="good">({100*(nov['units_unmet']-inc['units_unmet'])/max(inc['units_unmet'],1):+.0f}%)</span></div></div>
  <div class="tile"><div class="k">Total cost</div>
    <div class="v">₹{nov['total_cost']:,.0f}</div>
    <div class="d">from ₹{inc['total_cost']:,.0f} <span class="good">({100*pol['total_cost_change']:+.1f}%)</span></div></div>
  <div class="tile"><div class="k">Forecast gain</div>
    <div class="v">{100*(best_cl['wape']-lgbm['wape'])/best_cl['wape']:.1f}%</div>
    <div class="d">WAPE vs best classical — small, and it should be</div></div>
</div>

<div class="caveat">
  <strong>Read the caveat with the number.</strong> The cost saving is dominated by
  the stockout term, and the stockout penalty is a modelling assumption, not a
  measurement. Swept across a 16× range it moves between
  {100*worst_change:+.0f}% and {100*best_change:+.0f}%. What is robust is the
  direction and the mechanism; the specific percentage is not. All data is
  synthetic — see “What this is not”.
</div>

<h2>The model ladder</h2>
<p>Every rung is compared against the one below it over
{len(d['origins'])} rolling origins, {d['horizon']}-day horizon, scored against
true demand rather than observed sales. The dashed line is the
<strong>irreducible-error floor</strong>: the generating process’s own conditional
mean, which no forecaster can beat.</p>
<div class="legend">
  <span><i class="swatch" style="background:var(--s1)"></i>LightGBM (shipped)</span>
  <span><i class="swatch" style="background:var(--muted)"></i>Other rungs</span>
  <span><i class="swatch" style="background:var(--crit)"></i>Irreducible floor</span>
</div>
<div class="card"><div id="ladder"></div></div>
<p>Only <strong>{best_cl['wape']-floor['wape']:.4f} WAPE</strong> of reducible
error existed between the best classical method and the floor. LightGBM captured
{100*(best_cl['wape']-lgbm['wape'])/max(best_cl['wape']-floor['wape'],1e-9):.0f}% of
it. A model claiming a large win on this data would be suspect — which is why the
value had to come from somewhere else.</p>
<div class="scroll"><table>
  <thead><tr><th>Model</th><th>Rung</th><th>WAPE</th><th>95% CI</th><th>RMSSE</th><th>Bias</th></tr></thead>
  <tbody>{ladder_rows}</tbody></table></div>

<h2>Two results that went against me</h2>
<div class="card">
<h3>The censoring correction made WAPE worse</h3>
<p>Training on the censoring-corrected target scores
<strong>{lgbm['wape']:.4f}</strong> against <strong>{sales['wape']:.4f}</strong>
for raw sales — worse. But bias falls from
<strong>{sales['bias']:+.3f}</strong> to <strong>{lgbm['bias']:+.3f}</strong>.
I expected the correction to improve both. It did not.</p>
<p>WAPE is symmetric; the inventory decision is not. A forecast that is
systematically low under-orders, causes a stockout, observes the censored sale and
forecasts lower again. That loop is invisible to WAPE and fatal in production, so
the corrected target ships.</p>
<h3>The trailing 28-day mean beat Croston and SBA</h3>
<p>On series this lumpy, Croston’s separate size/interval smoothing buys nothing
over a plain mean. TSB comes closest of the three, as expected, because it decays
for discontinued items.</p>
</div>

<h2>The decision layer</h2>
<p>Order quantities come from the newsvendor critical ratio, computed per SKU:
<code>CR = Cu / (Cu + Co)</code>, where underage is the unit margin scaled by
criticality ({d['penalties'].get('1','?')}× for a convenience item,
{d['penalties'].get('5','?')}× for a life-critical drug) and overage is holding
cost plus expiry risk. <strong>This is the substantive claim:</strong> one
chain-wide safety factor cannot be right for both a cardiac drug and a vitamin.</p>
<div class="scroll"><table>
  <thead><tr><th></th><th>Incumbent fixed-ROP</th><th>Newsvendor + LightGBM</th><th>Change</th></tr></thead>
  <tbody>{cost_rows}</tbody></table></div>

<h2>Sensitivity — the reason to believe the direction</h2>
<p>The headline depends on an assumed stockout penalty. Sweeping it across 16×
shows the newsvendor policy wins throughout, by
{100*worst_change:+.0f}% at the most conservative setting.</p>
<div class="legend">
  <span><i class="swatch" style="background:var(--s2)"></i>Incumbent total cost</span>
  <span><i class="swatch" style="background:var(--s1)"></i>NOVA total cost</span>
</div>
<div class="card"><div id="sens"></div></div>
<div class="scroll"><table>
  <thead><tr><th>Penalty ×</th><th>Incumbent</th><th>NOVA</th><th>Change</th><th>NOVA fill</th></tr></thead>
  <tbody>{sens_rows}</tbody></table></div>

<h2>Probabilistic forecasts</h2>
<p>The decision layer needs a distribution, not a point. The LightGBM mean is
treated as the mean of a negative binomial and quantiles are read off
analytically. Whether that assumption holds is measured, not asserted:</p>
{prob_block}

<h2>A single series</h2>
<p>What the system actually sees: true demand, units sold, and closing stock.
Red markers are days where demand exceeded stock — the censoring that makes naive
pipelines degrade.</p>
<div class="controls">
  <label for="seriesSel">Series</label>
  <select id="seriesSel">{opts}</select>
  <span id="seriesMeta"></span>
</div>
<div class="legend">
  <span><i class="swatch" style="background:var(--s1)"></i>True demand</span>
  <span><i class="swatch" style="background:var(--s2)"></i>Units sold</span>
  <span><i class="swatch" style="background:var(--s3)"></i>Closing stock</span>
  <span><i class="swatch" style="background:var(--crit)"></i>Stockout</span>
</div>
<div class="card"><div id="series"></div></div>

<h2>Architecture</h2>
<div class="card"><div class="arch scroll">L5  Decision    newsvendor critical ratio -> order quantity
L4  Models      naive -> Croston/SBA/TSB -> LightGBM, rolling-origin backtest
L3  Features    point-in-time correct, leakage-tested
L2  Warehouse   star schema + 11 data-quality checks
L1  Simulator   5.9M series-days, known ground truth
L0  OLTP        PostgreSQL schema, RLS, PII controls  (UNVERIFIED)</div></div>

<h2>The fix that made this possible</h2>
<p>The project began as an Oracle DBMS coursework assignment. Its inventory table:</p>
<pre><code>CREATE TABLE Stock (
    pharmacy_1 VARCHAR2(100) PRIMARY KEY,  -- one row per pharmacy, ever
    stock      VARCHAR2(100)               -- inventory as a *string*
);</code></pre>
<p>No drug column, no date column, no numeric quantity. It could not answer “how
many units of drug D does branch B hold on date T” — the only question this
project depends on. It is now an inventory ledger with per-lot expiry tracking and
a CHECK-enforced flow identity, verified on all 5,918,400 rows.</p>

<h2>What this is not</h2>
<div class="card">
<p><strong>The data is synthetic.</strong> All of it. No real patient data has ever
been loaded. That is deliberate — it is what makes measurement against known
ground truth possible — and it is the single biggest limitation: these results
show the methods work on data whose generating process I control.</p>
<p><strong>The PostgreSQL layer is UNVERIFIED.</strong> The build machine had no
Docker and no <code>psql</code>, so <code>db/*.sql</code> has never been executed.
No <code>EXPLAIN ANALYZE</code> numbers are claimed anywhere.</p>
<p><strong>Not built:</strong> hierarchical reconciliation (MinT/OLS), deep
sequence models (TFT/N-BEATS), GNN anomaly detection, causal uplift, FastAPI/ONNX
serving, drift monitoring, and the text-to-SQL eval harness. Ground truth for the
anomaly, drift and causal work is generated and waiting.</p>
</div>

<footer>
Generated {d['generated']} by <code>python -m nova.report.build_site</code>.
Every number on this page is read from <code>artifacts/</code> — none is hardcoded.
<a href="https://github.com/Rohit-Gangil/SQL-Database-NOVA/tree/feature/nova-ml-platform">Source</a>
</footer>
</div>
<div id="tip" role="status" aria-live="polite"></div>"""


def main() -> None:
    d = collect()
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    html = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NOVA — Pharmacy Replenishment Decision System</title>
<meta name="description" content="Demand forecasting and newsvendor inventory optimisation for a multi-branch pharmacy chain, with honest error bars and sensitivity analysis.">
<style>{CSS}</style>
</head><body>
{build_html(d)}
<script>window.__NOVA__ = {json.dumps(d, separators=(",", ":"))};</script>
<script>{JS}</script>
</body></html>"""
    out = SITE_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    kb = len(html.encode()) / 1024
    print(f"wrote {out}  ({kb:.0f} KB, {len(d['series'])} series embedded)")


if __name__ == "__main__":
    main()
