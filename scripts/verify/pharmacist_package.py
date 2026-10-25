import json, random, collections
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter
R='/home/claude/tinysafe-dailymed-scraper-v2'
d=json.load(open(R+'/data/site/sunnytime_db.json')); N=d['names']; meta=d['meta']
act=[p for p in d['p'] if p.get('st','active')=='active']
done=set(json.load(open(R+'/data/verification/audited_setids.json')))
pool=[p for p in act if p['id'] not in done]
rel={}
for l in open(R+'/data/releases/us/latest/us_all.jsonl'):
    x=json.loads(l); rel[x['setid']]=x
rnd=random.Random(20261025)
SAFE=('age_limit','adult_active','spray_powder','fragrance','not_broad_spectrum','insect_repellent','under3_restricted','retinoid')
bk=[p for p in pool if p.get('bk')]
spec=[p for p in pool if not p.get('bk') and (p.get('r') or any(f[0] in SAFE for f in p['v3']))]
pick=rnd.sample(bk,50); s1={p['id'] for p in pick}
pick+=rnd.sample([p for p in spec if p['id'] not in s1],50); s1={p['id'] for p in pick}
pick+=rnd.sample([p for p in pool if p['id'] not in s1],50)
json.dump([p['id'] for p in pick],open('/tmp/claude-0/-home-claude/9b5aeac5-1a72-5d56-8b8a-b8464195bd51/scratchpad/touro/sample.json','w'))
G1={'not_broad_spectrum','age_limit','spray_powder','talc_inhalable','insect_repellent','under3_restricted','ipbc','mi_mci','mdbgn','formaldehyde','d4'}
G3={'hidden_uv_booster','chemical_filter_in_inactives','fragrance_free_conflict','no_preservative_water_base'}
G2={'fragrance','eu_fragrance_allergen','essential_oil','peanut','tree_nut','soy','wheat','milk','egg','sesame','fish_shellfish','lanolin','latex','capb','propylene_glycol','alkyl_glucoside','sulfite','isobornyl_acrylate','formaldehyde_releaser','asteraceae','oat','propolis_beeswax','citrus_photosensitizer','retinoid','adult_active'}
def grp(k):
    if k in G1: return '1 Safety alert'
    if k in G2: return '2 Check for your child'
    if k in G3: return '3 Label check'
    if k=='water_resistant': return 'Label fact'
    return '4 Preference'
F='Arial'; H=Font(name=F,bold=True,color='FFFFFF'); HF=PatternFill('solid',fgColor='2F4858'); IN=PatternFill('solid',fgColor='FFF2CC')
B=Font(name=F); thin=Side(style='thin',color='BFBFBF'); BD=Border(left=thin,right=thin,top=thin,bottom=thin)
WR=Alignment(wrap_text=True,vertical='top')
wb=Workbook()
# --- How to review
ws=wb.active; ws.title='How to review'
lines=[('Sunscreen Check: pharmacist review',True),
('',False),
('What this is',True),
('Sunscreen Check (arwhouse.com/sunnytime) shows parents what each US sunscreen label says: SPF, Broad Spectrum, active ingredients, inactive ingredients, warnings and FDA recalls. Every fact comes from the FDA filing (DailyMed) and, for most labels, from two independent readings of the package artwork. We are asking licensed pharmacists to check a random sample so we can publish an error rate measured by people, not software.',False),
('',False),
('What we ask',True),
('1. Open the DailyMed link for a label (column C on the Labels sheet). It shows the filed label text and the package images.',False),
('2. Compare it with what the site shows (columns F to L).',False),
('3. Fill in the yellow columns M to U. Use the dropdowns. Write in Notes anything you are unsure of.',False),
('4. On the Warning rules sheet, tell us whether each warning rule is sound and whether it sits in the right group (yellow columns).',False),
('',False),
('How to judge',True),
('SPF, Broad Spectrum, actives: correct only if the label prints exactly that. "Not stated" for Broad Spectrum is never an error. A hidden % is not an error.',False),
('Inactive ingredients: a name missing or extra counts; spelling and case do not. Where the label text and the package print different lists, either is acceptable.',False),
('Warnings: is each one justified by the ingredient it cites? Is a safety warning clearly missing?',False),
('Worst error: high = could change a parent\'s safety choice (wrong SPF, wrong or missing active, a false or missing safety warning, a wrong or missing recall, a false Broad Spectrum claim). Medium or low otherwise.',False),
('',False),
('Sample',True),
('150 labels drawn at random on 2026-10-25 from 9,418 active labels, none checked in our earlier audits: 50 baby or kids labels, 50 labels with a recall or a safety warning, 50 from all labels. About 5 minutes per label.',False),
('Evidence grade: A = package read by two readers who agreed; B = read once and it matched the filing; C = FDA filing only.',False),
('',False),
('Return the file to Angela Lee, ARW House: angela@arwhouse.com',False),
('Row 2 of the Labels sheet is a filled-in example, not part of the sample.',False)]
for i,(t,b) in enumerate(lines,1):
    c=ws.cell(row=i,column=1,value=t); c.font=Font(name=F,bold=b,size=14 if i==1 else 11); c.alignment=WR
ws.column_dimensions['A'].width=110
# --- Labels
ws=wb.create_sheet('Labels')
cols=['#','Setid','DailyMed link','Brand','Product','Evidence grade','SPF shown','Broad Spectrum shown','Actives shown (%)','Inactive ingredients shown','Warnings shown (group: warning)','Recall shown',
      'SPF correct?','Broad Spectrum correct?','Actives and % correct?','Inactives match the label?','Every warning justified?','Safety warning missing?','Recall correct?','Worst error','Notes','Reviewer']
widths=[5,14,22,16,30,9,7,10,26,50,50,18,10,10,10,10,10,10,10,10,40,10]
for j,(h,w) in enumerate(zip(cols,widths),1):
    c=ws.cell(row=1,column=j,value=h); c.font=H; c.fill=HF; c.alignment=Alignment(wrap_text=True,vertical='center'); c.border=BD
    ws.column_dimensions[get_column_letter(j)].width=w
ex=['ex','(example)','https://dailymed.nlm.nih.gov/dailymed/','Example Brand','Example Kids Mineral Lotion SPF 50','A','50','Yes','ZINC OXIDE 20%','Water; Caprylic/Capric Triglyceride; ...','2 Check for your child: Contains fragrance','none',
    'Yes','Yes','Yes','No','Yes','No','Yes','low','Site lists Silica, not printed on the label','AB']
for j,v in enumerate(ex,1):
    c=ws.cell(row=2,column=j,value=v); c.font=Font(name=F,italic=True,color='7F7F7F'); c.alignment=WR; c.border=BD
for i,p in enumerate(pick,1):
    r=rel.get(p['id'],{}); rr=i+2
    recs=[x for x in r.get('recalls') or [] if x.get('status')=='matched']
    vals=[i,p['id'],r.get('dailymed_url') or f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={p['id']}",p.get('b'),p['n'],p.get('ev'),p.get('s'),
          {1:'Yes',0:'No'}.get(p.get('bs'),'Not stated'),
          '; '.join(f"{a} {('%g%%'%z) if z is not None else '(% not shown)'}" for a,z in p['z']),
          '; '.join(N[k] for k in p['i']),
          '\n'.join(f"{grp(f[0])}: {meta.get(f[0],{}).get('l',f[0])}" for f in sorted(p['v3'],key=lambda f:grp(f[0]))),
          '; '.join(x['recall_number'] for x in recs) or 'none']
    for j,v in enumerate(vals,1):
        c=ws.cell(row=rr,column=j,value=v); c.font=B; c.alignment=WR; c.border=BD
    ws.cell(row=rr,column=3).hyperlink=vals[2]; ws.cell(row=rr,column=3).font=Font(name=F,color='0563C1',underline='single')
    for j in range(13,23):
        c=ws.cell(row=rr,column=j); c.fill=IN; c.border=BD; c.font=B; c.alignment=WR
last=len(pick)+2
yn=DataValidation(type='list',formula1='"Yes,No,Can\'t tell"',allow_blank=True); ws.add_data_validation(yn); yn.add(f'M3:S{last}')
sv=DataValidation(type='list',formula1='"none,low,medium,high"',allow_blank=True); ws.add_data_validation(sv); sv.add(f'T3:T{last}')
ws.freeze_panes='C3'
# --- Warning rules
w2=wb.create_sheet('Warning rules')
cnt=collections.Counter(f[0] for p in act for f in p['v3'])
c2=['Warning key','Shown as','Proposed group','Labels (of 9,418)','What we tell parents','Source we cite','Basis','Rule sound?','Right group?','Comments','Reviewer']
wd=[22,34,20,10,60,60,10,12,12,40,10]
for j,(h,w) in enumerate(zip(c2,wd),1):
    c=w2.cell(row=1,column=j,value=h); c.font=H; c.fill=HF; c.alignment=Alignment(wrap_text=True); c.border=BD
    w2.column_dimensions[get_column_letter(j)].width=w
rows=sorted(meta.items(),key=lambda kv:(grp(kv[0]),-cnt.get(kv[0],0)))
for i,(k,m) in enumerate(rows,2):
    vals=[k,m.get('l'),grp(k),cnt.get(k,0),m.get('w'),m.get('s'),m.get('basis') or '']
    for j,v in enumerate(vals,1):
        c=w2.cell(row=i,column=j,value=v); c.font=B; c.alignment=WR; c.border=BD
    for j in range(8,12):
        c=w2.cell(row=i,column=j); c.fill=IN; c.border=BD
lr=len(rows)+1
ag=DataValidation(type='list',formula1='"Agree,Disagree,Unsure"',allow_blank=True); w2.add_data_validation(ag); ag.add(f'H2:I{lr}')
w2.freeze_panes='C2'
# --- Summary
s=wb.create_sheet('Summary')
s['A1']='Results (fills in as you review)'; s['A1'].font=Font(name=F,bold=True,size=14)
s['A3']='Labels reviewed'; s['B3']=f'=COUNTA(Labels!T3:T{last})'
s['A4']='Labels with a high error'; s['B4']=f'=COUNTIF(Labels!T3:T{last},"high")'
s['A5']='Share with a high error'; s['B5']='=IF(B3=0,0,B4/B3)'; s['B5'].number_format='0.0%'
s['A7']='By field'; s['B7']='No'; s['C7']="Can't tell"; s['D7']='Yes'
for i,(lab,col) in enumerate([('SPF correct','M'),('Broad Spectrum correct','N'),('Actives and % correct','O'),('Inactives match','P'),('Warnings justified','Q'),('Safety warning missing','R'),('Recall correct','S')],8):
    s[f'A{i}']=lab
    s[f'B{i}']=f'=COUNTIF(Labels!{col}3:{col}{last},"No")'; s[f'C{i}']=f'=COUNTIF(Labels!{col}3:{col}{last},"Can\'t tell")'; s[f'D{i}']=f'=COUNTIF(Labels!{col}3:{col}{last},"Yes")'
s['A16']='Warning rules: disagree'; s['B16']=f'=COUNTIF(\'Warning rules\'!H2:H{lr},"Disagree")'
s['A17']='Warning groups: disagree'; s['B17']=f'=COUNTIF(\'Warning rules\'!I2:I{lr},"Disagree")'
s['A18']='Note: "Safety warning missing" counts Yes as a problem.'
for row in s.iter_rows():
    for c in row:
        if c.value is not None and c.font.size!=14: c.font=Font(name=F,bold=c.column==1 and c.row in (7,) or c.font.bold)
s.column_dimensions['A'].width=34
for c in 'BCD': s.column_dimensions[c].width=12
out='/tmp/claude-0/-home-claude/9b5aeac5-1a72-5d56-8b8a-b8464195bd51/scratchpad/touro/Sunscreen_Check_pharmacist_review.xlsx'
wb.save(out); print(out, len(pick), collections.Counter(p.get('ev') for p in pick), len(rows))
