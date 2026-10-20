"""Merge every full-check source into data/corrections/full_check_2026-10-19.jsonl."""
import json, glob, sys, re, difflib, collections
R='/home/claude/tinysafe-dailymed-scraper-v2/'
sys.path.insert(0, R+'scripts'); import inactive_union as U
S='/tmp/claude-0/-home-claude/9b5aeac5-1a72-5d56-8b8a-b8464195bd51/scratchpad/fc/'
db=json.load(open('/home/claude/arwhouse/sunnytime/db.json')); P={p['id']:p for p in db['p']}

def akeys(sid):
    ak=set()
    for z in P[sid]['z']:
        k=U.key(z[0]); ak.add(k); ak|=U._ACTIVE_SYN.get(k,set())
    return ak

def clean(lst, sid):
    ak=akeys(sid)
    out=[]
    for x in U.resplit(lst or []):
        if U.is_active(x, ak): continue
        if not any(U.key(x)==U.key(o) for o in out): out.append(x)
    return out

def m1(x, y):
    kx, ky = U.key(re.sub(r'\s*\[\?\]','',x)), U.key(re.sub(r'\s*\[\?\]','',y))
    return kx==ky or (min(len(kx),len(ky))>=5 and difflib.SequenceMatcher(None,kx,ky).ratio()>=0.9) or U.same(x,y)

def compare(a, b):
    used=set(); matched=[]
    for x in a:
        for j,y in enumerate(b):
            if j not in used and m1(x,y):
                used.add(j); matched.append(x); break
    return matched

VALID=set(P)
def fix(sid):
    if sid in VALID: return sid
    best=max(VALID,key=lambda v: difflib.SequenceMatcher(None,sid,v).ratio())
    return best if difflib.SequenceMatcher(None,sid,best).ratio()>0.9 else sid

STRUCT={}
for l in open(R+'data/views/inactive_union.jsonl'):
    r=json.loads(l); STRUCT[r['setid']]=r['struct']
RAW={}
for f in glob.glob(S+'tb/*.json'):
    for x in json.load(open(f)): RAW[x['setid']]=x['label_text']

def in_raw(x, sid):
    t=re.sub(r'[^A-Z0-9]+',' ',RAW.get(sid,'').upper())
    ws=[w for w in re.sub(r'[^A-Z0-9]+',' ',re.sub(r'\s*\[\?\]','',x).upper()).split() if len(w)>=3]
    return bool(ws) and all((' '+w+' ') in (' '+t+' ') or w in t.replace(' ','') for w in ws)

def two_reads(prefix_a, prefix_b, kind):
    A={}; B={}
    for f in glob.glob(S+f'res/{prefix_a}_*.json'):
        for r in json.load(open(f)): A[fix(r['setid'])]=r
    for f in glob.glob(S+f'res/{prefix_b}_*.json'):
        for r in json.load(open(f)): B[fix(r['setid'])]=r
    out={}
    for sid in set(A)|set(B):
        a, b = A.get(sid), B.get(sid)
        if not a or not b:
            out[sid]={'status':'missing_pass'}; continue
        mis = a.get('mismatch') or b.get('mismatch')
        raw_all=(a.get('inactives') or [])+(b.get('inactives') or [])
        if raw_all and sum(bool(re.search(r'[\u3131-\ud7a3\u4e00-\u9fff\u3040-\u30ff]',x)) for x in raw_all) > len(raw_all)*0.3:
            out[sid]={'status':'non_english_label','source':'label_image_two_reads' if kind=='img' else 'spl_text_two_reads',
                      'note':'label printed in Korean/CJK only; the English structured filing is kept'}; continue
        la = clean(a.get('inactives'), sid) if a.get('found') else []
        lb = clean(b.get('inactives'), sid) if b.get('found') else []
        src = 'label_image_two_reads' if kind=='img' else 'spl_text_two_reads'
        if mis and kind=='img':
            out[sid]={'status':'label_image_mismatch','source':src,'note':(a.get('note') or '')+' | '+(b.get('note') or '')}; continue
        if not la and not lb:
            unread = kind=='img' and 'unreadable' in ((a.get('legibility') or '')+(b.get('legibility') or ''))
            out[sid]={'status':'image_unreadable' if unread else ('no_list_on_label_images' if kind=='img' else 'no_list_in_text'),
                      'source':src,'note':(a.get('note') or '')[:200]}; continue
        if not la or not lb:
            out[sid]={'status':'one_read_only','A':la,'B':lb,'source':src}; continue
        mt = compare(la, lb)
        agreed=[x for x in mt if '[?]' not in x]
        if kind=='text':   # an item only one reader split out still counts if every word of it is in the label text
            for x in la+lb:
                if not any(m1(x,y) for y in agreed) and '[?]' not in x and in_raw(x, sid):
                    agreed.append(x)
        if len(mt)==len(la)==len(lb):
            st='confirmed' if len(agreed)==len(mt) else 'partial'
        elif len(mt)>=max(len(la),len(lb))-2:
            st='partial'
        else:
            out[sid]={'status':'reads_disagree','A':la,'B':lb,'source':src}; continue
        # an item only one reader saw is kept when the filing or the current list has it too
        ref=[db['names'][i] for i in P[sid]['i']]+STRUCT.get(sid,[])
        for x in la+lb:
            if not any(m1(x,y) for y in agreed) and '[?]' not in x and any(U.same(x,y) for y in ref):
                agreed.append(x)
        # the two readers split a name differently ("Crambe Abyssinica Seed Oil Phytosterol Esters"):
        # a legible item one reader gave is kept
        for x in la+lb:
            if not any(m1(x,y) for y in agreed) and '[?' not in x and len(re.sub(r'[^A-Za-z]','',x))>=6:
                agreed.append(x)
        left=[x for x in la+lb if not any(m1(x,y) for y in agreed)]
        if st=='partial' and not [x for x in left if '[?]' not in x]: st='confirmed' if not left else 'partial'
        out[sid]={'status':st,'source':src,'inactives':agreed,'one_reader_only':left,
                  'n_read_a':len(la),'n_read_b':len(lb),'dropped':[x for x in la if x not in agreed]}
    return out

if __name__=='__main__':
    rows={}
    for l in open(R+'data/corrections/full_check_text_2026-10-19.jsonl'):
        r=json.loads(l); rows[r['setid']]=r
    for l in open(S+'img_text.jsonl'):
        r=json.loads(l)
        if r['status']!='no_text' or r['setid'] not in rows: rows[r['setid']]=r
    for f in glob.glob(S+'retry/thin_check/*.json'):
        r=json.load(open(f))
        if r.get('error') and '404' in r['error']:
            rows[r['setid']]={'setid':r['setid'],'status':'fetch_error','note':r['error']}
    T=two_reads('TA','TB','text'); I=two_reads('IA','IB','img')
    auto=set(json.load(open(S+'auto.json'))) if __import__('os').path.exists(S+'auto.json') else set()
    final=[]; c=collections.Counter()
    for sid,r in rows.items():
        base={'setid':sid,'title':r.get('title',''),'checked':'2026-10-19','spl_version':r.get('spl_version')}
        st=r['status']
        if sid in I and (sid not in T or T[sid]['status'] in ('no_list_in_text','missing_pass')): base.update(I[sid])
        elif sid in T: base.update(T[sid])
        elif st=='same_as_db': base.update(status='text_confirms_current',source='spl_text')
        elif st=='fresh_text': base.update(status='confirmed',source='spl_text',inactives=r['inactives'],added=r['added'])
        elif st=='fetch_error' and '404' in (r.get('note') or ''): base.update(status='spl_not_on_dailymed',source='dailymed_api')
        else: base.update(status='unresolved_'+st)
        c[base['status']]+=1; final.append(base)
    def tidy(x):
        x=re.sub(r'(?i)^fragrance\s*product formulated.*$','Fragrance',x)
        x=re.sub(r'\b((?:[A-Z] ){3,}[A-Z])\b',lambda m:m.group(1).replace(' ',''),x)
        x=re.sub(r'\bDIM\s+ETHICONE','DIMETHICONE',x)
        return x.strip()
    JUNK=re.compile(r'(?i)learn about|product formulated|composants naturels|natural com-? ?ponents|our ingredients')
    for b in final:
        if b.get('inactives'):
            b['inactives']=[tidy(x) for x in b['inactives'] if not JUNK.search(x)]
            cur=[db['names'][i] for i in P[b['setid']]['i']]
            if len(b['inactives'])<0.6*len(cur) and len(cur)-len(b['inactives'])>=4:
                # the label text holds only part of the list: keep what the DB already had
                keep=[y for y in cur if not any(U.same(y,x) for x in b['inactives'])]
                b['inactives']=b['inactives']+keep; b['kept_db_items']=keep
    with open(R+'data/corrections/full_check_2026-10-19.jsonl','w') as f:
        for x in final: f.write(json.dumps(x,ensure_ascii=False)+'\n')
    print(sorted(c.items(), key=lambda x:-x[1]))
