#!/usr/bin/env python3
"""Render every Sunscreen Check card and fail on any broken invariant (summary counts, Within only when all limits are met, a present active never listed as clear, face-and-body not face, propellant sprays never within the EU homosalate rule, label date = FDA date, a flag never naming the label's own actives). Usage: card_invariants.py <arwhouse checkout>"""
import sys
import functools,http.server,threading,json
from playwright.sync_api import sync_playwright
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*a):pass
srv=http.server.ThreadingHTTPServer(("127.0.0.1",0),functools.partial(Q,directory=sys.argv[1]));threading.Thread(target=srv.serve_forever,daemon=True).start()
base=f"http://127.0.0.1:{srv.server_address[1]}/sunscreen-check/"
JS=r"""()=>{const out={n:0,err:[],bad:{},ex:{}};const B=(k,id,t)=>{(out.bad[k]=out.bad[k]||[]);if(out.bad[k].length<4)out.bad[k].push(id+' | '+t);out.bad[k+'#']=(out.bad[k+'#']||0)+1};
 const X=(k,id)=>{if(!out.ex[k])out.ex[k]=id};
 for(const p of DB.p){if(p.st!=='active')continue;try{render(p)}catch(e){out.err.push(p.id+' '+e);continue}out.n++;
  const card=document.querySelector('#res .ncard');const sm=card.querySelector('.nsum');
  const nums=[...sm.querySelectorAll('button[data-j]')].map(b=>parseInt(b.textContent));const tot=parseInt(sm.querySelector('b').textContent);
  if(nums.reduce((a,b)=>a+b,0)!==tot)B('sum',p.id,tot+' vs '+nums);
  const box=card.querySelector('.nlim');const bs=box?box.querySelector('summary .small').textContent:'';
  const cells=box?[...box.querySelectorAll('.nlc')].map(x=>[x.className,x.textContent]):[];
  if(/Within/.test(bs)&&cells.some(([c,t])=>/over/.test(c)||(c==='nlc '&&!/up to [\d.]+%$/.test(t))))B('within',p.id,bs+' || '+cells.map(c=>c[1]).join(';'));
  const nf=[...card.querySelectorAll('.nnone2 span')].map(x=>x.textContent).join(' · ');
  if(box&&box.dataset.k&&/Above a limit, or not an allowed/.test(nf))B('limitcheck',p.id,bs);
  if(box&&!box.dataset.k&&!/Above a limit, or not an allowed/.test(nf)&&!(p.thin))B('limitmiss',p.id,bs);
  const hom=[...card.querySelectorAll('.ni b')].find(b=>/^Homosalate/.test(b.textContent));
  if(hom){const sub=hom.parentElement.querySelector('.nsub').textContent;const cell=cells.find(([c,t])=>/^EU /.test(t)&&box.innerHTML.includes('Homosalate'));const hc=[...box.querySelectorAll('.nlr')].find(r=>/^Homosalate/.test(r.textContent));const eu=hc?[...hc.querySelectorAll('.nlc')].map(x=>x.textContent).find(t=>t.startsWith('EU ')):'';
    if(eu&&!sub.includes(eu.slice(3)))B('homosalate',p.id,sub+' || '+eu);X('hom_'+(eu||'').slice(3,20),p.id)}
  const txt=card.textContent;
  const A=p.z.map(z=>String(z[0]).toUpperCase());
  for(const [act,chk] of [['OXYBENZONE','Oxybenzone'],['HOMOSALATE','Homosalate'],['OCTOCRYLENE','Octocrylene']])if(A.includes(act)&&nf.split(' · ').includes(chk))B('clear_but_present',p.id,act);
  if(A.includes('HYDROQUINONE')&&nf.split(' · ').includes('Hydroquinone'))B('clear_but_present',p.id,'HQ');
  const f=formOf(p);if(f.face&&/\bBODY\b/i.test(p.n))B('facebody',p.id,p.n);
  if(f.prop&&cells.some(([c,t])=>/^EU within/.test(t))&&box.innerHTML.includes('Homosalate')){const hc=[...box.querySelectorAll('.nlr')].find(r=>/^Homosalate/.test(r.textContent));if(hc&&/EU within/.test(hc.textContent))B('prop_hom',p.id,p.n)}
  const sm2=card.querySelector('.rht .small').textContent;if(p.d&&!sm2.includes(fmtD(p.d)))B('date',p.id,sm2);if(!p.d&&/Label on file [A-Z]/.test(sm2))B('date0',p.id,sm2);
  const stops=[...card.querySelectorAll('.ni.stop b')].map(b=>b.textContent);stops.forEach(t=>{if(!/FDA recall on record|PABA|Hydroquinone|insect repellent|methylbenzylidene/i.test(t))B('stop',p.id,t)});
  if(/Chemical UV filter listed as inactive/.test(txt)){const li=[...card.querySelectorAll('.ni b')].find(b=>/Chemical UV filter listed as inactive|chemical UV filter is listed as inactive/.test(b.textContent));const sub=li&&li.parentElement.querySelector('.nsub');if(sub&&A.some(a=>sub.textContent.toUpperCase().includes(a)&&!p.i.some(k=>String(DB.names[k]).toUpperCase()===a)))B('cfi_active',p.id,sub.textContent)}

  if(p.rd&&p.rd.every(r=>r[7]==='store')){X('store',p.id);if(/No FDA recall found/.test(txt))B('store',p.id,'no recall shown')}
  if(/not on the US, EU or Australian UV-filter lists/.test(txt))X('none',p.id);
  if(/Australia not checked/.test(bs))X('extra',p.id);
  if(/Depends on use/.test(bs))X('dep',p.id);
  if(/Same ingredient list as/.test(txt))X('same',p.id);
  if(/Outside a rule/.test(bs))X('out_'+box.dataset.k,p.id);
  if(p.fc)X('fc',p.id);
  if(/undefined|NaN|\[object/.test(txt))B('junk',p.id,txt.match(/.{30}(undefined|NaN|\[object).{20}/)?.[0]);
 }return out}"""
with sync_playwright() as pw:
    b=pw.chromium.launch();errs=[]
    pg=b.new_page(viewport={'width':420,'height':900});pg.on('pageerror',lambda e:errs.append(str(e)))
    pg.goto(base);pg.wait_for_timeout(800);pg.evaluate("loadDB()");pg.wait_for_function("DB.p.length>0&&EV")
    r=pg.evaluate(JS);print(json.dumps(r,indent=1)[:6000]);bad=sum(v for k,v in r['bad'].items() if k.endswith('#') and k!='stop#');print('violations',bad);sys.exit(1 if bad or r['err'] else 0)
    print('pageerrors',errs[:3]);b.close()
srv.shutdown()
