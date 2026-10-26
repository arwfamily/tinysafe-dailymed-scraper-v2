#!/usr/bin/env python3
"""Render the Sunscreen Check card (arwhouse.com/sunscreen-check) for every product (no option selected, and all four selected) from a local
copy of the site, and fail if any card errors or any item lacks its 'Why this matters · sources' panel.

Usage: card_render_check.py <arwhouse checkout>     (needs Python playwright; Chromium is preinstalled)
"""
import functools
import http.server
import json
import sys
import threading

from playwright.sync_api import sync_playwright

site = sys.argv[1]


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=site))
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_address[1]}/sunscreen-check/"
JS = """async([lo,hi])=>{const src=[...document.scripts].map(s=>s.textContent).find(t=>t.includes('function render(p){window.lastP=p;'));
  const a='function render(p){window.lastP=p;',z="res.classList.add('show');sug.innerHTML='';}";
  const i=src.indexOf(a),j=src.indexOf(z,i)+z.length;const R=(0,eval)('('+src.slice(i,j).replace('function render(p)','function(p)')+')');
  let bad=[],n=0,items=0,noWhy=0;const res=document.getElementById('res');
  for(const mode of [[],['eczema','psoriasis','food','young']]){concern.clear();mode.forEach(k=>concern.add(k));
    for(const p of DB.p.slice(lo,hi)){try{R(p);n++;const its=res.querySelectorAll('.ni');items+=its.length;
      its.forEach(x=>{if(!x.querySelector('details.nw')&&!/SPF booster/.test(x.textContent))noWhy++})}catch(e){bad.push([p.id,String(e)])}}}
  return {renders:n,items,errors:bad.length,examples:bad.slice(0,5),items_without_sources:noWhy,evidence_loaded:!!EV}}"""
with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url)
    pg.wait_for_timeout(1000)
    pg.evaluate("loadDB()")
    pg.wait_for_function("DB.p.length>0 && EV!==null", timeout=60000)
    # in chunks of 400 products: one call over all ~9,400 can stall a cloud browser (2026-10-26 weekly run)
    total = pg.evaluate("DB.p.length")
    r = {"renders": 0, "items": 0, "errors": 0, "examples": [], "items_without_sources": 0, "evidence_loaded": True}
    for lo in range(0, total, 400):
        x = pg.evaluate(JS, [lo, lo + 400])
        for k in ("renders", "items", "errors", "items_without_sources"):
            r[k] += x[k]
        r["examples"] = (r["examples"] + x["examples"])[:5]
        r["evidence_loaded"] = r["evidence_loaded"] and x["evidence_loaded"]
    r["page_errors"] = errs[:5]
    b.close()
srv.shutdown()
print(json.dumps(r))
sys.exit(1 if r["errors"] or r["items_without_sources"] or r["page_errors"] or not r["evidence_loaded"] else 0)
