function metaWhy(id){const m=META[id]||{};if(!m.w)return'';
  const src=String(m.s||'').replace(/\s*\([^()]*(verif|fetch|mirror|checked|not read|title\/volume)[^()]*\)/gi,'').trim();
  return `<details class="why"><summary>Why this matters · sources</summary><ul class="facts"><li><span>${esc(m.w)}</span></li></ul>`+
   (src?`<div class="osh">Source</div><ul class="facts"><li><span>${esc(src)}</span></li></ul>`:'')+
   (m.basis==='judgment'?`<div class="osh">This flag is our own judgment, not an official rule.</div>`:'')+`</details>`}
const MITEM=(cls,ic,head,sub,id)=>`<div class="it ${cls}"><div class="ith"><i aria-hidden="true">${ic}</i><div><b>${head}</b>${sub?`<span class="sub">${sub}</span>`:''}</div></div>${metaWhy(id)}</div>`;
const words=s=>new Set(up(s).replace(/[^A-Z0-9-]+/g,' ').trim().split(/\s+/));
const neaMatch=(n)=>{const w=words(n);return NEA.filter(e=>[...words(e)].every(x=>w.has(x)))};
const listN=(arr,n)=>{n=n||4;const u=[...new Set(arr)];return u.slice(0,n).map(nice).join(', ')+(u.length>n?` and ${u.length-n} more`:'')};

function renderNew(p){
  const out={glance:[],filters:[],label:[]};const used=new Set();const use=(...ids)=>ids.forEach(i=>used.add(i));
  const A=actNames(p), I=ingU(p), F=id=>{const f=flag(p,id);if(f)used.add(id);return f};
  const thin=!p.ing.length||p.thin===true;
  const cf=F('chemical_filter_active'), cfi=F('chemical_filter_in_inactives');
  const spF=F('spray_powder'), spName=/\b(SPRAY|MIST|AEROSOL)\b/.test(up(p.n));
  const isSpray=spName||(spF&&!/\bPOWDER\b/.test(up(p.n)));
  const isPowder=!isSpray&&!!spF;
  // ---- at a glance
  if(p.r&&p.r.length){const why=p.r.filter(x=>x!=='other').map(x=>x==='contamination'?'Contamination':x==='benzene'?'Benzene':x).join(', ');
    out.glance.push(ITEM('stop','!','FDA recall on record',(why?esc(why)+'. ':'')+'Recalls usually cover specific lots; check the lot number on your package against the FDA notice','recall'))}
  else if(p.rk)out.glance.push(ITEM('ok','✓','No FDA recall found','FDA recalls we track, as of '+fmtD(D.as_of),'recall'));
  const nbs=F('not_broad_spectrum');
  out.glance.push(nbs||p.bs===0?ITEM('warn','!','Not Broad Spectrum, or below SPF 15','FDA requires these to say they only help prevent sunburn','broad_spectrum')
                 :p.bs===1?ITEM('ok','✓','Broad Spectrum'+(p.s?' SPF '+p.s:''),'Passed FDA’s UVA test as well as the SPF test','broad_spectrum')
                 :/BROAD SPECTRUM/.test(up(p.n))?ITEM('ok','✓','Says Broad Spectrum'+(p.s?' SPF '+p.s:''),'In the product name on the FDA label','broad_spectrum')
                 :ITEM('info','i','Broad Spectrum: not confirmed yet','We couldn’t read it from the FDA filing; check the front of the package','broad_spectrum'));
  if(cf)out.glance.push(ITEM('warn','!','Uses chemical UV filters',esc(names(cf,6))+'. AAP: mineral-based is preferable for children','filters'));
  else if(p.ft==='mineral_only'&&cfi)out.glance.push(MITEM('warn','!','Mineral actives, but a chemical UV filter is listed as inactive',esc(listN(cfi.m)),'chemical_filter_in_inactives'));
  else if(p.ft==='mineral_only')out.glance.push(ITEM('ok','✓','Mineral active ingredients only',esc(p.z.map(z=>nice(z[0])).join(', ')),'filters'));
  if(isSpray){const tl=F('talc_inhalable');out.glance.push(ITEM('warn','!','Spray','Never spray on the face; spray into hands, then apply'+(tl?'. Also contains talc':''),'spray'))}
  else if(isPowder){const tl=F('talc_inhalable');out.glance.push(ITEM('warn','!','Loose powder','Avoid breathing it in; apply away from the face'+(tl?'. Contains talc':''),'spray'))}
  else out.glance.push(ITEM('ok','✓','Not a spray or powder','Nothing to breathe in','spray'));
  if(F('insect_repellent'))out.glance.push(ITEM('stop','!','Combined with an insect repellent',esc(names(flag(p,'insect_repellent'),3)),'insect_repellent'));
  const al=F('age_limit'),ad=F('adult_active'),adm=ad?ad.m.filter(n=>!/SALICYLIC|RETIN|HYDROQUINONE/i.test(n)):[];
  out.glance.push(al?ITEM('warn','!','Age limit on the label','“'+esc(al.m[0]||'')+'”','age'):adm.length?MITEM('warn','!','Adult skincare active',esc(listN(adm,3)),'adult_active'):ITEM('ok','✓','No extra age limit','Only the “under 6 months: ask a doctor” line every US sunscreen must carry','age'));
  // fragrance
  const frF=F('fragrance'),eoF=F('essential_oil'),euF=F('eu_fragrance_allergen');
  const eoName=hasIng(p,/ESSENTIAL OILS?\b/i);
  const lav=hasIng(p,/(LAVAND|LAVENDER|MELALEUCA|TEA TREE).*\bOIL\b|\bOIL\b.*(LAVAND|LAVENDER|MELALEUCA|TEA TREE)/i);
  const euOnlyBA=!frF&&!eoF&&!eoName.length&&euF&&euF.m.every(n=>/BENZYL ALCOHOL/i.test(n));
  const frNames=[...(frF?frF.m:[]),...(eoF?eoF.m:[]),...eoName,...(euF&&!euOnlyBA?euF.m:[])];
  const hasFr=frNames.length>0;
  if(hasFr){const isFr=!!frF,isEo=!!(eoF||eoName.length);const h=isFr&&isEo?'Contains fragrance and essential oil':isFr?'Contains fragrance':isEo?'Contains essential oil':'Contains an EU-listed fragrance allergen';
    out.glance.push(ITEM('warn','!',h,esc(listN(frNames,3)),'fragrance'))}
  else if(euOnlyBA)out.glance.push(ITEM('info','i','Benzyl alcohol','A common preservative that is also on the EU fragrance-allergen list','fragrance'));
  else if(thin)out.glance.push(ITEM('info','i','No fragrance on the filed list','This ingredient list may be incomplete','fragrance'));
  else out.glance.push(ITEM('ok','✓','No fragrance listed','No fragrance, essential oil or EU fragrance allergen','fragrance'));
  // booster
  const hb=F('hidden_uv_booster');const bn=hb?hb.m.filter(n=>!BOOST_EXCL.test(up(n))):[];
  const bst=bn.map(n=>{const s=statusOf(n);return s?`${nice(n)}: US ${s[1].US}, EU ${s[1].EU} (on the EU list of UV filters or not), Australia ${s[1].AU}`:nice(n)}).join('; ');
  if(bn.length)out.glance.push(ITEM('info','i','Possible SPF booster listed as inactive',esc(listN(bn,4)),'uv_absorbing_inactive',{names:bn.map(nice).join(', '),status:'Permitted as a UV filter? '+bst+'.'}));
  else if(!hb&&!cfi){if(thin)out.glance.push(ITEM('info','i','No SPF booster on the filed list','This ingredient list may be incomplete',null));
    else out.glance.push(ITEM('ok','✓','No SPF booster listed as inactive','None of the ones we track',null))}
  // ---- about the UV filters
  if(A.includes('OXYBENZONE')){const op=actPct(p,'OXYBENZONE');const eu=op==null?(isSpray?'EU limit for sprays: 2.2%':'EU: 6% face, hand and lip; 2.2% body and sprays'):isSpray?(op>2.2?'Above the EU limit for sprays (2.2%)':'Within the EU limit for sprays (2.2%)'):op<=2.2?'Within EU limits (6% face, hand and lip; 2.2% body)':op<=6?'Above the EU limit for body products (2.2%); the EU allows up to 6% in face, hand and lip products':'Above the EU limit (6%)';
    out.filters.push(ITEM('warn','!','Oxybenzone '+(op!=null?op+'%':''),'AAP: avoid if possible. '+eu,'oxybenzone'))}
  if(A.includes('HOMOSALATE')){const hp=actPct(p,'HOMOSALATE');const pc=hp!=null?' '+hp+'%':'';
    if(isSpray)out.filters.push(ITEM('warn','!','Homosalate'+pc+', outside EU rules','The EU doesn’t allow it in propellant sprays; up to 7.34% in face products only. US allows 15%','homosalate_eu'));
    else if(hp!=null&&hp>7.34)out.filters.push(ITEM('warn','!','Homosalate'+pc+', above the EU limit','EU allows up to 7.34%, face products only. US allows 15%','homosalate_eu'));
    else out.filters.push(ITEM('info','i','Homosalate'+pc,'EU allows it only in face products, up to 7.34%. US allows 15%','homosalate_eu'))}
  if(A.includes('OCTOCRYLENE'))out.filters.push(ITEM('info','i','Octocrylene '+(actPct(p,'OCTOCRYLENE')!=null?actPct(p,'OCTOCRYLENE')+'%':''),'A 2021 study found benzophenone forming in it as products aged','octocrylene'));
  const HI=/OXYBENZONE|BENZOPHENONE-3|OCTINOXATE|ETHYLHEXYL METHOXYCINNAMATE|OCTYL METHOXYCINNAMATE/;
  if(A.some(a=>HI.test(a))||I.some(n=>HI.test(n)))out.filters.push(ITEM('info','i','Can’t be sold in Hawaii','State law bans oxybenzone and octinoxate (since 2021)','hawaii'));
  if(cf||cfi)out.filters.push(ITEM('info','i','Can’t be sold on Maui','County law allows only mineral sunscreens without a prescription (since Oct 2022)','maui_county'));
  if(A.some(a=>/^(AMINOBENZOIC ACID|PABA|TROLAMINE SALICYLATE)$/.test(a)))out.filters.push(ITEM('stop','!','PABA or trolamine salicylate','FDA final order (Sept 2026): not generally recognized as safe and effective; can’t be sold under the monograph from Sept 2027','paba_trolamine'));
  if(A.includes('HYDROQUINONE'))out.filters.push(ITEM('stop','!','Hydroquinone','FDA: over-the-counter skin-lightening products with hydroquinone can’t be legally sold without FDA approval','hydroquinone'));
  if(isFinite(p.s)&&p.s>50)out.filters.push(ITEM('info','i','SPF '+p.s,'AAP: SPF 15 to 50 is enough; it says more research is needed on higher SPFs. FDA has proposed (not final) capping labels at 60+','spf_over_50'));
  // ---- label check
  if(cfi&&p.ft!=='mineral_only')out.label.push(MITEM('warn','!','Chemical UV filter listed as inactive',esc(listN(cfi.m)),'chemical_filter_in_inactives'));
  if(I.some(n=>/METHYLBENZYLIDENE CAMPHOR/.test(n))||A.some(a=>/ENZACAMENE|METHYLBENZYLIDENE/.test(a)))out.label.push(ITEM('stop','!','4-methylbenzylidene camphor','Banned in EU cosmetics (off shelves since May 2026); not an FDA monograph active','mbc_eu_ban'));
  if(I.some(n=>/BIS-ETHYLHEXYLOXYPHENOL METHOXYPHENYL TRIAZINE|BEMOTRIZINOL/.test(n)))out.label.push(ITEM('info','i','Bemotrizinol listed as inactive','Added to FDA’s sunscreen monograph in Aug 2026 (up to 6%), but listed here as inactive','bemotrizinol_inactive'));
  if(F('fragrance_free_conflict'))out.label.push(ITEM('info','i','Says fragrance-free, but lists a fragrance',esc(names(flag(p,'fragrance_free_conflict'),2)),'fragrance'));
  if(/HYPOALLERGENIC/i.test(p.n))out.label.push(ITEM('info','i','“Hypoallergenic” in the name','No federal standard for this word','hypoallergenic'));
  [['mdbgn','warn'],['phthalate','warn'],['d4','warn'],['pfas','info'],['triclosan','info'],['no_preservative_water_base','info']].forEach(([id,c])=>{const f=F(id);if(f)out.label.push(MITEM(c,c==='warn'?'!':'i',esc((META[id]||{}).l||id),esc(names(f,3)),id))});
  if(thin)out.label.push(ITEM('info','i',p.ing.length?'Short ingredient list':'No ingredient list on file','The FDA filing may not list every ingredient; checks on this card only cover what is listed',null));
  // ---- check for your child
  const C=(id,cls,head,sub,tid,tags,meta)=>({id,cls,head,sub,tid,tags,meta});const ch=[];
  if(lav.length)ch.push(C('lav','warn','Lavender or tea tree oil',esc(listN(lav,3)),'essential_oil_lavender',['young']));
  if(F('mi_mci'))ch.push(C('mi','warn','MI or MCI preservative',esc(names(flag(p,'mi_mci'))),'mi_mci',['eczema']));
  if(F('formaldehyde_releaser'))ch.push(C('fo','warn','Formaldehyde-releasing preservative',esc(names(flag(p,'formaldehyde_releaser'))),'formaldehyde_releaser',['eczema']));
  if(F('propyl_butyl_paraben'))ch.push(C('pb','warn','Propyl- or butylparaben',esc(names(flag(p,'propyl_butyl_paraben'))),'parabens',['young']));
  if(F('ipbc'))ch.push(C('ip','warn','IPBC preservative',esc(names(flag(p,'ipbc'))),'ipbc',['young'],1));
  const rp=hasIng(p,/RETINYL|RETINOL/i).concat(A.filter(a=>/RETIN/.test(a)));if(rp.length||F('retinoid'))ch.push(C('rp','warn','Vitamin A (retinol or retinyl esters)',esc(listN(rp.length?rp:flag(p,'retinoid').m,3)),'retinyl_palmitate',['young']));
  const sal=hasIng(p,/^SALICYLIC ACID\b/i).concat(A.filter(a=>/^SALICYLIC ACID\b/.test(a)));if(sal.length){use('under3_restricted');ch.push(C('sa','warn','Salicylic acid','The EU doesn’t allow it in products for children under 3','salicylic_psoriasis',['psoriasis','young']))}
  else if(F('under3_restricted'))ch.push(C('u3','warn',esc(META.under3_restricted.l),esc(names(flag(p,'under3_restricted'))),'under3_restricted',['young'],1));
  const foodK=['peanut','tree_nut','soy','wheat','milk','egg','sesame','fish_shellfish','oat'];const food=foodK.map(k=>F(k)).filter(Boolean);
  if(food.length){const fn=food.flatMap(f=>f.m);ch.push(C('fd',fn.some(n=>/PROTEIN|PEANUT|ARACHIS/i.test(n))?'warn':'soft','Food-derived ingredients',esc(listN(fn,3)),'food_allergen_skin',['food','eczema']))}
  if(F('citrus_photosensitizer'))ch.push(C('ci','warn','Citrus peel oil',esc(names(flag(p,'citrus_photosensitizer'))),'citrus_photosensitizer',['eczema','psoriasis']));
  if(F('lanolin'))ch.push(C('la','soft','Lanolin',esc(names(flag(p,'lanolin'))),'lanolin',['eczema']));
  if(F('capb'))ch.push(C('cb','soft','Cocamidopropyl betaine','','capb',['eczema']));
  if(F('propylene_glycol'))ch.push(C('pg','soft','Propylene glycol','Mainly a concern for eczema-prone skin','propylene_glycol',['eczema']));
  if(F('drying_alcohol'))ch.push(C('al','soft','Alcohol',esc(names(flag(p,'drying_alcohol'),2)),'drying_alcohol',['eczema','psoriasis']));
  [['alkyl_glucoside','Alkyl glucoside'],['sulfite','Sulfite'],['isobornyl_acrylate','Isobornyl acrylate'],['asteraceae','Daisy-family plant'],['propolis_beeswax','Bee-derived ingredient']].forEach(([id,h])=>{const f=F(id);if(f)ch.push(C(id,'soft',h,esc(names(f,3)),id,['eczema'],1))});
  const neaHits=[...new Set(p.ing.flatMap(n=>neaMatch(n).length?[n]:[]))];
  // ---- profile topics
  const pr=[];
  if(prof.has('eczema')){pr.push(ITEM('info','i','For a child with eczema',p.ft==='mineral_only'&&!cfi?'Mineral filters only, as the AAD advises for eczema':'The AAD advises zinc oxide or titanium dioxide as the only actives','eczema_sunscreen'));
    const why=[];if(neaHits.length)why.push(listN(neaHits,4));if(cf||cfi)why.push('chemical UV filters (the NEA Seal allows only mineral filters)');if(hasFr&&!neaHits.length)why.push('fragrance');
    if(F('formaldehyde_releaser')&&!neaHits.length)why.push('a formaldehyde releaser');
    pr.push(why.length?ITEM('warn','!','Not what the National Eczema Association accepts',esc(why.join('; ')),'nea_exclusion',{names:esc(why.join('; '))})
      :thin?ITEM('info','i','Nothing from the NEA exclusion list on the filed list','This ingredient list may be incomplete','nea_exclusion',{names:'none'})
      :ITEM('ok','✓','None of the NEA-excluded ingredients we check for','This is not the NEA Seal; the Seal also requires testing','nea_exclusion',{names:'none'}));
    const ua=['OXYBENZONE','OCTOCRYLENE'].filter(x=>A.includes(x)||I.some(n=>n.includes(x)));
    if(ua.length)pr.push(ITEM('info','i','UV filters and skin allergy',esc(ua.map(nice).join(' and '))+(ua.length>1?' are':' is')+' among the most reported UV-filter allergens','uv_filter_allergy'));
    pr.push(ITEM('info','i','Common allergens in children','What patch tests find most often','pediatric_contact_allergens'))}
  if(prof.has('psoriasis'))pr.push(ITEM('info','i','For a child with psoriasis','Sunburn can trigger a flare 10 to 14 days later','psoriasis_sun'));
  // ---- preferences
  const pf=[];const pfi=(id,lab,tid)=>pf.push(`<div class="pfi"><span class="pill fact">${esc(lab)}</span>${tid?why(tid):''}</div>`);
  if(F('phenoxyethanol'))pfi('pe','Preservative: phenoxyethanol','phenoxyethanol');
  if(F('ethoxylated'))pfi('et','PEG / ethoxylated: '+names(flag(p,'ethoxylated'),2),'ethoxylated');
  if(F('bht_bha')){const bb=flag(p,'bht_bha').m.join(' ').toUpperCase();if(/\bBHA\b|HYDROXYANISOLE/.test(bb))pfi('bha','BHA','bha');if(/\bBHT\b|HYDROXYTOLUENE/.test(bb))pfi('bht','BHT','bht')}
  if(F('talc'))pfi('tc','Talc','talc');
  if(F('petrolatum_mineral_oil'))pfi('po','Petrolatum or mineral oil','petrolatum_mineral_oil');
  if(I.some(n=>/\bNANO\b/.test(n)&&!/NON[- ]?NANO/.test(n)))pfi('na','Nano mineral filter','nano_minerals');
  const PREF=['silicone','d5_d6','microplastic_polymer','botanical_count','iron_oxide_tint','synthetic_dye','coconut','shea','animal_derived','methyl_ethyl_paraben','sodium_benzoate','ethanolamines','sls_sles','oat'];
  (p.v3||[]).filter(f=>PREF.includes(f[0])&&!used.has(f[0])).forEach(f=>{used.add(f[0]);pfi(f[0],((D.lib_meta[f[0]]||{}).l||f[0])+(f[1].length&&f[0]!=='botanical_count'?': '+names({m:f[1]},2):''),null)});
  const wr=F('water_resistant');use('hidden_uv_booster','retinoid','adult_active','age_limit','talc_inhalable');
  // safety net: any T1/T2 flag no branch used
  (p.v3||[]).filter(f=>!used.has(f[0])&&['T1','T2'].includes((META[f[0]]||{}).t)).forEach(f=>out.label.push(MITEM('warn','!',esc((META[f[0]]||{}).l||f[0]),esc(names({m:f[1]},3)),f[0])));
  const ev=p.ev==='A'?'<span class="ev"><i></i>Checked against the package by two readers</span>':p.ev==='B'?'<span class="ev"><i></i>Checked against the package once</span>':'<span class="ev c"><i></i>From the FDA filing only</span>';
  const match=c=>[...prof].some(k=>c.tags.includes(k));
  const one=c=>{const m=prof.size&&match(c);const cl=c.cls==='soft'?(m?'warn':'info'):c.cls;const tagL=m?[...prof].filter(k=>c.tags.includes(k)).map(k=>({eczema:'Eczema',psoriasis:'Psoriasis',food:'Food allergy',young:'Under 3'}[k])).join(', '):'';
    return `<div class="it ${cl} ${prof.size?(m?'me':'dim'):''}"><div class="ith"><i aria-hidden="true">${cl==='info'?'i':'!'}</i><div><b>${c.head}${tagL?` <span class="tagm">${tagL}</span>`:''}</b>${c.sub?`<span class="sub">${c.sub}</span>`:''}</div></div>${c.meta?metaWhy(c.tid):why(c.tid)}</div>`};
  const strong=ch.filter(c=>c.cls!=='soft'||(prof.size&&match(c))), soft=ch.filter(c=>!strong.includes(c));
  const chHTML=(strong.length?strong.map(one).join(''):(soft.length?'':'<div class="none">Nothing on this label in this group.</div>'))+
    (soft.length?`<details class="more"><summary>${soft.length} more that matter mainly for sensitive or eczema-prone skin</summary>${soft.map(one).join('')}</details>`:'');
  const sec=(h,sub,arr)=>arr.length?`<div class="sec"><div class="gh"><h4>${h}</h4><span class="small">${sub}</span></div>${arr.join('')}</div>`:'';
  return `<div class="disc top">Made by ARW House, which also makes Sunnytime, a mineral baby sunscreen. The same rules apply to every product, including ours.</div>
   <div class="rc">${head(p)}${ev}<div class="small" style="margin-top:6px">Last checked against FDA: ${fmtD(p.ck)}${p.pr?' · Package read '+fmtD(p.pr):''}</div>
   <div class="glance">${out.glance.join('')}</div>
   ${sec('About the UV filters','facts and official limits',out.filters)}
   ${sec('Label check','facts, no judgment',out.label)}
   <div class="sec"><div class="gh"><h4>Check for your child</h4><span class="small">tap what applies</span></div>
     <div class="chips">${[['eczema','Eczema'],['psoriasis','Psoriasis'],['food','Food allergy'],['young','Under 3']].map(([k,l])=>`<button type="button" class="chip" data-k="${k}" aria-pressed="${prof.has(k)}">${l}</button>`).join('')}</div>
     ${pr.join('')}${chHTML}</div>
   <div class="act">${wr?'Water resistant · ':''}<span>${p.z.map(z=>nice(z[0])+(z[1]!=null?` ${z[1]}%`:'')).join(' · ')}</span></div>
   ${wr?why('water_resistant'):''}
  </div>
  ${pf.length?`<details class="rc fold"><summary><h4>Other ingredients some parents ask about</h4><span class="cnt">${pf.length}</span></summary><div class="small" style="margin-bottom:8px">We list these because parents ask about them. Official findings are under each, where we found them.</div>${pf.join('')}</details>`:''}
  ${ingFold(p)}
  <div class="rc report"><span>See something wrong? Send a photo of the package; two readers check it within 7 days.</span><button type="button" disabled title="Preview only">Report an error</button></div>
  <div class="disc">I also make Sunnytime, a sunscreen I created when I couldn’t find one I wanted for my son. It follows the same rules as everything here.</div>`}
