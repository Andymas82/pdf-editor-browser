#!/usr/bin/env python3
"""Stage 3.2: fidelity-first, line-scoped visual replacement. Does not save edited PDF."""
import argparse, base64, html, json
from pathlib import Path
import pymupdf
from detect_blocks import page_groups


def model_for(page, group):
    words = page.get_text('words')
    source = sorted(group['lines'], key=lambda l: (round((l['bbox'][1]+l['bbox'][3])/2,1),l['bbox'][0]))
    lines=[]
    for idx,l in enumerate(source):
        bbox=l['bbox']; cy=(bbox[1]+bbox[3])/2
        matched=[w for w in words if w[0]>=bbox[0]-2 and w[2]<=bbox[2]+2 and abs((w[1]+w[3])/2-cy)<=max(2,(bbox[3]-bbox[1])*.4)]
        matched.sort(key=lambda w:w[0]); reconstructed=' '.join(w[4] for w in matched)
        raw=''.join(s['text'] for s in l['spans'])
        valid=bool(matched and ''.join(reconstructed.split())==''.join(raw.split()))
        lines.append({'id':idx,'text':reconstructed if valid else raw,'bbox':bbox,'spans':l['spans'],'whitespace_from_geometry':valid})
    return {'name':group['name'],'kind':group['kind'],'bbox':group['bbox'],'editable_bbox':group.get('cell_bbox',group['bbox']),
            'lines':lines, 'geometry_whitespace_lines':sum(l['whitespace_from_geometry'] for l in lines)}

HTML=r'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Stage 3.2</title><style>
body{font:14px system-ui,sans-serif;background:#eef2f5;color:#20343f;margin:0}header{background:#fff;padding:18px 24px;font-size:20px;font-weight:700}main{display:grid;grid-template-columns:380px minmax(0,1fr);gap:14px;padding:14px}section{background:white;border-radius:10px;padding:16px;min-width:0}label{display:block;font-weight:600;margin:12px 0 7px}select,textarea{box-sizing:border-box;width:100%;border:1px solid #bac8d0;border-radius:5px;padding:8px}textarea{min-height:160px;font:14px/1.5 system-ui}button{border:0;border-radius:6px;padding:10px 12px;color:white;background:#087f77;cursor:pointer;margin:12px 8px 0 0}.sub{font-size:12px;color:#657681}.notice{padding:11px;background:#fff3d7;border-radius:7px;margin:12px 0;font-size:12px;line-height:1.5}pre{white-space:pre-wrap;font-size:12px;max-height:240px;overflow:auto}.images{display:grid;grid-template-columns:1fr 1fr;gap:12px}canvas{display:block;width:100%;height:auto;border:1px solid #ced9df}h4{margin:0 0 9px}@media(max-width:980px){main{grid-template-columns:1fr}}
</style></head><body><header>PDF Rich Text — Stage 3.2 <span class="sub">true text removal in preview · original PDF untouched</span></header><main><section>
<b id="title"></b><div class="sub" id="summary"></div><label for="line">Редактируемая строка</label><select id="line"></select><label for="edit">Новый текст</label><textarea id="edit" spellcheck="false"></textarea>
<button id="apply">Предпросмотр замены</button><button id="reset" style="background:#536d7a">Сброс</button>
<div class="notice">Старый текст удаляется из временной PDF-страницы; линии таблицы сохраняются. Изменение только одной строки за раз. Многострочный текст может перекрывать следующие строки или выходить из ячейки — это показывается в диагностике. Это предпросмотр, не экспорт PDF.</div><label>Диагностика</label><pre id="log"></pre><label>Исходные стили</label><pre id="styles"></pre></section>
<section><div class="images"><div><h4>Original</h4><canvas id="before"></canvas></div><div><h4>Preview</h4><canvas id="after"></canvas></div></div></section></main>
<script>
const M=__MODEL__, SCALE=__SCALE__, ORIG='original-page.png';
const sel=document.querySelector('#line'),ed=document.querySelector('#edit'),log=document.querySelector('#log'),styles=document.querySelector('#styles');
const a=document.querySelector('#after'),b=document.querySelector('#before');
document.querySelector('#title').textContent=M.name+' · '+M.kind;
document.querySelector('#summary').textContent=M.lines.length+' visual lines, whitespace recovered in '+M.geometry_whitespace_lines;
M.lines.forEach((l,i)=>{let o=document.createElement('option');o.value=i;o.textContent=(i+1)+': '+l.text.slice(0,80);sel.append(o)});
let original=new Image(),clean=new Image(),cleanReady=false,applied=false;original.src=ORIG;
function line(){return M.lines[Number(sel.value)||0]}
function show(){const l=line();ed.value=l.text;styles.textContent=JSON.stringify(l.spans,null,2);applied=false;loadClean();}
function loadClean(){cleanReady=false;const num=String(line().id).padStart(3,'0');clean=new Image();clean.onload=()=>{cleanReady=true;draw()};clean.src='clean/line-'+num+'.png';draw()}
function fmt(s){const n=s.font||'';return `${/Bold|SemiBold|Medium/i.test(n)?'bold ':''}${(s.size||10)*SCALE}px ${/Times|Serif|Plex/i.test(n)?'Georgia, serif':'Arial, sans-serif'}`}
function paintText(ctx,l,val){const span=l.spans[0]||{size:10,color:0,font:'Arial'};let [x0,y0,x1,y1]=l.bbox.map(v=>v*SCALE);
const left=(M.kind==='cell-candidate'?M.editable_bbox[0]+2:M.editable_bbox[0])*SCALE;
const right=(M.kind==='cell-candidate'?M.editable_bbox[2]-2:M.editable_bbox[2])*SCALE;
const bottom=(M.kind==='cell-candidate'?M.editable_bbox[3]-2:M.editable_bbox[3])*SCALE;
ctx.font=fmt(span);ctx.textBaseline='top';ctx.fillStyle='#'+((span.color||0)>>>0).toString(16).padStart(6,'0');
const startX=M.kind==='cell-candidate'?left:x0;let y=y0;const h=(span.size||10)*SCALE*1.23;
let count=0;const rows=[];
for(const para of val.split('\n')){let current='';for(const word of para.split(/\s+/)){if(!word)continue;let proposed=current?current+' '+word:word;
if(ctx.measureText(proposed).width>right-startX && current){rows.push(current);current=word}else current=proposed}
rows.push(current)}
for(const row of rows){const cx=M.kind==='cell-candidate'?left+Math.max(0,(right-left-ctx.measureText(row).width)/2):startX;
if(row)ctx.fillText(row,cx,y);y+=h;count++}
const other=M.lines.filter(other=>other.id!==l.id&&other.bbox[1]*SCALE<y&&other.bbox[3]*SCALE>y0&&other.bbox[2]*SCALE>startX&&other.bbox[0]*SCALE<right);
return {rendered_lines:count,overflows_container:y>bottom,overlaps_other_text:other.length>0,overlap_line_ids:other.map(x=>x.id),approximate_font:true};}
function draw(){if(!original.complete||!original.naturalWidth)return;for(const c of [a,b]){c.width=original.naturalWidth;c.height=original.naturalHeight;c.getContext('2d').drawImage(original,0,0)}
let diag={stage:'3.2',changed:false,source_pdf_modified:false};
if(applied&&ed.value!==line().text&&cleanReady){const l=line(),[bx0,by0,bx1,by1]=l.bbox;const sx=Math.max(0,Math.floor(bx0*SCALE)-1),sy=Math.max(0,Math.floor(by0*SCALE)),ex=Math.min(a.width,Math.ceil(bx1*SCALE)+1),ey=Math.min(a.height,Math.ceil(by1*SCALE));a.getContext('2d').drawImage(clean,sx,sy,ex-sx,ey-sy,sx,sy,ex-sx,ey-sy);diag={...diag,changed:true,original_text_removed_from_temporary_page:true,retained_original_pixels_outside_edit_rectangle:true,...paintText(a.getContext('2d'),l,ed.value)}}
else if(applied&&!cleanReady){diag.error='Waiting for clean background'}
log.textContent=JSON.stringify(diag,null,2)}
sel.onchange=show;document.querySelector('#apply').onclick=()=>{applied=true;draw()};document.querySelector('#reset').onclick=()=>{show()};original.onload=()=>{show()};
</script></body></html>'''


def main():
    p=argparse.ArgumentParser();p.add_argument('pdf',type=Path);p.add_argument('--mode',choices=['auto','columns','table'],default='auto');p.add_argument('--group',required=True);p.add_argument('--page',type=int,default=1);p.add_argument('--output',type=Path,default=Path('results/stage32'));z=p.parse_args()
    z.output.mkdir(parents=True,exist_ok=True);(z.output/'clean').mkdir(exist_ok=True)
    with pymupdf.open(z.pdf) as doc:
        page=doc[z.page-1]; mode,groups,_,_=page_groups(page,z.mode);group=next((g for g in groups if g['name']==z.group),None)
        if not group:raise SystemExit('Unknown group. Available: '+','.join(g['name'] for g in groups))
        model=model_for(page,group);scale=1.65
        (z.output/'original-page.png').write_bytes(page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False).tobytes('png'))
        for l in model['lines']:
            # Redaction with graphics=0: only text is removed. Page graphic rules and images are retained.
            with pymupdf.open(z.pdf) as tmp:
                pg=tmp[z.page-1]; x0,y0,x1,y1=l['bbox']
                rect=pymupdf.Rect(x0-0.2,y0+0.2,x1+0.2,y1-0.2)
                pg.add_redact_annot(rect,fill=False)
                pg.apply_redactions(images=0,graphics=0,text=0)
                pix=pg.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False)
                (z.output/'clean'/f'line-{l["id"]:03d}.png').write_bytes(pix.tobytes('png'))
    (z.output/'richtext-model.json').write_text(json.dumps(model,ensure_ascii=False,indent=2),encoding='utf-8')
    (z.output/'preview.html').write_text(HTML.replace('__MODEL__',json.dumps(model,ensure_ascii=False).replace('</','<\\/')).replace('__SCALE__',str(scale)),encoding='utf-8')
    print('mode=',mode,'group=',model['name'],'lines=',len(model['lines']),'preview=',z.output/'preview.html')
if __name__=='__main__':main()
