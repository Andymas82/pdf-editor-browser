#!/usr/bin/env python3
"""Stage 4.8.7: persistent multi-object PDF editor preserving untouched source spans."""
import argparse
import re, base64, io, json, re, threading, difflib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import pymupdf
from detect_blocks import page_groups
from stage40 import embedded_font, MixedFont, font_path, wrap_text

APP = r'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PDF Block Editor 4.8.6</title><style>
*{box-sizing:border-box}body{margin:0;background:#edf1f4;color:#18323b;font:14px system-ui,Arial}header{background:white;padding:15px 22px;border-bottom:1px solid #ccd5da}h3,h4{margin:0 0 8px}header p{margin:0;color:#57717a;font-size:12px}main{display:grid;grid-template-columns:320px 1fr 1fr;gap:12px;padding:12px}.panel{background:white;padding:14px;border-radius:8px;min-width:0}.scroller{max-height:83vh;overflow:auto}.page{position:relative;display:block;width:100%}img{display:block;width:100%}.hit{position:absolute;border:1px solid #d98b25;background:rgba(242,146,14,.12);cursor:pointer}.graphic{position:absolute;z-index:2;cursor:grab;border:1px solid transparent;touch-action:none;min-height:9px;transform:translateY(-50%)}.graphic.icon-object{min-height:0;transform:none;border:1px solid rgba(16,126,152,.22);background:rgba(16,126,152,.08)}.graphic.icon-object:hover{border-color:#0d8193}.graphic.selected{border:1px dashed #e34a4a;background:rgba(227,74,74,.17)}.graphic:hover{border:1px solid #e34a4a}.hit.selected{border:2px solid #eb8100;background:rgba(248,158,32,.13)}select,textarea,button{font:inherit;border:1px solid #adbfc9;border-radius:5px}select{width:100%;padding:8px;margin:8px 0}textarea{width:100%;height:280px;padding:9px;resize:vertical;font:13px/1.4 Consolas,monospace}button{padding:9px;cursor:pointer;background:white}button.primary{background:#127b71;color:white;border-color:#127b71}button:disabled{opacity:.45}.actions{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}.status{font-size:12px;white-space:pre-wrap;color:#a35413}.edited{font-size:12px;color:#127b71;margin:8px 0}#inline{position:absolute;z-index:3;display:none;box-sizing:border-box;background:rgba(255,255,255,.95);border:2px solid #ef830e;min-height:65px;font:12px/1.35 serif;resize:both}small{color:#59737e}.help{font-size:12px;line-height:1.5;color:#5d7480}@media(max-width:1100px){main{grid-template-columns:320px 1fr}main>.panel:last-child{grid-column:2}}@media(max-width:720px){main{display:block}.panel{margin:8px}}
</style></head><body><header><h3>PDF Rich Text — Stage 4.8.7</h3><p>Целые блоки · несколько правок в одном PDF · сохранение неизменённых стилей</p></header><main><section class="panel"><h4>Редактирование блока</h4><p class="help">Выберите целый блок на Original. Двойной щелчок открывает ввод прямо поверх PDF. Каждая исходная визуальная строка отделена переводом строки для сохранения привязки стилей.</p><div class="actions"><button id="textMode" class="primary">Текст</button><button id="lineMode">Линии</button><button id="iconMode">Значки</button></div><div id="graphicInfo" class="help">Линии перемещаются независимо; изменения текста остаются.</div><select id="picker"></select><div id="info" class="help"></div><textarea id="edit" spellcheck="false"></textarea><div class="actions"><button id="reset">Сбросить блок</button><button id="resetAll">Reset All</button></div><div id="edits" class="edited"></div><div class="actions"><button class="primary" id="render">Пересчитать PDF</button><button id="download" disabled>Download edited PDF</button></div><div id="status" class="status"></div><p class="help">Наложения допускаются. Соседние объекты не перемещаются. В изменённых фрагментах применяются стили исходных span; неизменённые строки не перерисовываются.</p></section><section class="panel"><h4>Original</h4><div class="scroller"><div class="page" id="page"><img id="original" src="/original.png"><textarea id="inline" spellcheck="false"></textarea></div></div></section><section class="panel"><h4>Preview</h4><small>Изображение генерируется из PDF, который скачивается</small><div class="scroller"><img id="preview" src="/original.png"></div></section></main><script>
const model=__MODEL__, $=id=>document.getElementById(id),picker=$('picker'),txt=$('edit'),page=$('page'),inline=$('inline');
const groups=model.blocks, lookup=Object.fromEntries(groups.map(g=>[g.name,g]));
const graphicChanges={};let graphicMode=false,graphicType=null,selectedGraphic=null;const changes={};let selected=groups[0].name, seq=0, pdf=null,valid=-1,inlineOpen=false;
for(const g of groups){let o=document.createElement('option');o.value=g.name;o.textContent=g.name+' — один блок ('+g.line_ids.length+' строк)';picker.append(o)}
function originalText(g){return g.lines.join('\n')}
function currentText(name){return Object.hasOwn(changes,name)?changes[name]:originalText(lookup[name])}
function update(){const keys=Object.keys(changes);$('edits').textContent='Изменено блоков: '+keys.length+(keys.length?' · '+keys.join(', '):'');page.querySelectorAll('.hit').forEach(h=>h.classList.toggle('selected',h.dataset.block===selected))}
function dirty(){seq++;pdf=null;valid=-1;$('download').disabled=true;$('preview').style.opacity='.45';$('status').textContent='Изменения накоплены. Для предпросмотра нажмите «Пересчитать PDF».';update()}
function commit(name,value){if(value===originalText(lookup[name]))delete changes[name];else changes[name]=value;dirty()}
function finish(save){if(!inlineOpen)return;if(save){txt.value=inline.value;commit(selected,txt.value)}inline.style.display='none';inlineOpen=false}
function choose(name){if(graphicMode)return;finish(true);selected=name;picker.value=name;txt.value=currentText(name);$('info').textContent='Блок '+name+' · '+lookup[name].line_ids.length+' исходных строк · внутренние шрифты сохраняются';update()}
for(const g of groups){const h=document.createElement('div');h.className='hit';h.dataset.block=g.name;h.title='Выбрать блок '+g.name;const b=g.bbox;h.style.left=(b[0]/model.width*100)+'%';h.style.top=(b[1]/model.height*100)+'%';h.style.width=((b[2]-b[0])/model.width*100)+'%';h.style.height=((b[3]-b[1])/model.height*100)+'%';h.onclick=()=>choose(g.name);h.ondblclick=()=>{choose(g.name);inlineOpen=true;inline.value=txt.value;inline.style.left=h.style.left;inline.style.top=h.style.top;inline.style.width=h.style.width;inline.style.height=h.style.height;inline.style.display='block';inline.focus()};page.append(h)}
function setMode(mode){finish(true);graphicMode=mode!=='text';graphicType=mode;selectedGraphic=null;for(const [id,key] of [['textMode','text'],['lineMode','line'],['iconMode','icon']])$(id).classList.toggle('primary',key===mode);page.querySelectorAll('.graphic').forEach(el=>el.style.display=(mode===el.dataset.kind)?'block':'none');page.querySelectorAll('.hit').forEach(el=>el.style.pointerEvents=graphicMode?'none':'auto');}
$('textMode').onclick=()=>setMode('text');$('lineMode').onclick=()=>setMode('line');$('iconMode').onclick=()=>setMode('icon');
for(const g of model.graphics){const el=document.createElement('div');el.className='graphic'+(g.kind==='icon'?' icon-object':'');el.dataset.graphic=g.id;el.dataset.kind=g.kind;el.title='Перетащить '+(g.kind==='icon'?'значок ':'линию ')+g.id;el.style.display='none';const b=g.bbox;el.style.left=(b[0]/model.width*100)+'%';el.style.top=((g.kind==='icon'?b[1]:(b[1]+b[3])/2)/model.height*100)+'%';el.style.width=(Math.max(4,b[2]-b[0])/model.width*100)+'%';if(g.kind==='icon'){el.style.height=(Math.max(4,b[3]-b[1])/model.height*100)+'%';}let start=null;function updatePosition(){const rect=page.getBoundingClientRect();const dx=(graphicChanges[g.id]?.dx||0)/model.width*rect.width,dy=(graphicChanges[g.id]?.dy||0)/model.height*rect.height;el.style.transform=(g.kind==='icon'?'':'translateY(-50%) ')+`translate(${dx}px,${dy}px)`;}
el.onpointerdown=e=>{e.preventDefault();e.stopPropagation();selectedGraphic=g.id;page.querySelectorAll('.graphic').forEach(x=>x.classList.toggle('selected',x===el));el.setPointerCapture(e.pointerId);start={clientX:e.clientX,clientY:e.clientY,dx:(graphicChanges[g.id]?.dx||0),dy:(graphicChanges[g.id]?.dy||0)};$('graphicInfo').textContent=(g.kind==='icon'?'Значок ':'Линия ')+g.id+': перетащите мышью; двойной щелчок сбрасывает';};el.onpointermove=e=>{if(!start)return;const rect=page.getBoundingClientRect();const dx=start.dx+(e.clientX-start.clientX)*model.width/rect.width,dy=start.dy+(e.clientY-start.clientY)*model.height/rect.height;graphicChanges[g.id]={dx:Math.round(dx*10)/10,dy:Math.round(dy*10)/10};updatePosition()};el.onpointerup=e=>{if(!start)return;start=null;dirty();$('graphicInfo').textContent=(g.kind==='icon'?'Значок ':'Линия ')+g.id+' перемещён; нажмите «Пересчитать PDF»';};el.ondblclick=e=>{e.preventDefault();e.stopPropagation();delete graphicChanges[g.id];updatePosition();dirty()};page.append(el)}
picker.onchange=()=>choose(picker.value);txt.oninput=()=>commit(selected,txt.value);inline.oninput=()=>{txt.value=inline.value;commit(selected,inline.value)};
inline.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();finish(false)}if(e.key==='Enter'&&e.ctrlKey){e.preventDefault();finish(true);$('render').click()}};
$('reset').onclick=()=>{txt.value=originalText(lookup[selected]);commit(selected,txt.value)};
$('resetAll').onclick=()=>{if(!confirm('Сбросить все изменения?'))return;finish(false);for(const k of Object.keys(changes))delete changes[k];for(const k of Object.keys(graphicChanges))delete graphicChanges[k];page.querySelectorAll('.graphic').forEach(e=>e.style.transform=e.dataset.kind==='icon'?'translate(0px,0px)':'translateY(-50%)');txt.value=originalText(lookup[selected]);dirty()};
$('render').onclick=async()=>{finish(true);const rev=seq;$('render').disabled=true;$('status').textContent='Формируем PDF с '+Object.keys(changes).length+' блоками...';try{const r=await fetch('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({blocks:changes,graphics:graphicChanges})});const v=await r.json();if(!r.ok)throw Error(v.error);if(rev!==seq)return;pdf=new Blob([Uint8Array.from(atob(v.pdf),c=>c.charCodeAt(0))],{type:'application/pdf'});$('preview').src='data:image/png;base64,'+v.png;$('preview').style.opacity='1';valid=rev;$('download').disabled=false;$('status').textContent='Сохранено правок блоков: '+v.changed+'. '+(v.warnings.length?'Предупреждения: '+v.warnings.join('; '):'Предпросмотр готов.') }catch(e){$('status').textContent='Ошибка: '+e.message}finally{$('render').disabled=false}};
$('download').onclick=()=>{if(!pdf||valid!==seq)return;const url=URL.createObjectURL(pdf),a=document.createElement('a');a.href=url;a.download='edited-stage486.pdf';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),3000)};
choose(selected);
</script></body></html>''' 

def graphic_objects(page):
    """Independent stroked horizontal or vertical paths, plus small fill icons."""
    out=[]
    for path_index,d in enumerate(page.get_drawings()):
        if d['type'] != 's' or d.get('color') is None or d.get('closePath'):continue
        items=d['items']; r=d['rect']
        if not items or any(i[0]!='l' for i in items):continue
        horizontal=r.width>=25 and r.height<=1.1
        vertical=r.height>=25 and r.width<=1.1
        if not (horizontal or vertical):continue
        # The complete 4-sided rectangle is represented by four independent
        # PDF stroke operations in the sample CV. All four are selectable.
        out.append({'id':str(path_index),'kind':'line','orientation':'v' if vertical else 'h',
                    'bbox':[r.x0,r.y0,r.x1,r.y1],
                    'color':list(d['color']),'width':float(d['width']) if d.get('width') is not None else 1.0,'lineCap':d.get('lineCap'),'lineJoin':d.get('lineJoin'),'dashes':d.get('dashes'),'stroke_opacity':d.get('stroke_opacity',1)})
    for path_index,d in enumerate(page.get_drawings()):
        r=d['rect']
        if d['type'] not in ('f','fs') or d.get('fill') is None:continue
        if not (2<=r.width<=24 and 2<=r.height<=24):continue
        if r.y0<8 or r.x0<5:continue
        if not d['items'] or any(it[0] not in ('l','c','re','qu') for it in d['items']):continue
        out.append({'id':str(path_index),'kind':'icon','bbox':[r.x0,r.y0,r.x1,r.y1]})
    return out

def make_model(page, mode):
    _,groups,_,_=page_groups(page,mode)
    raw=page.get_text('dict',sort=False)
    candidates=[]
    for block in raw['blocks']:
        if 'lines' not in block:continue
        for line in block['lines']:
            spans=[s for s in line['spans'] if s.get('text','')]
            if not spans:continue
            bbox=list(line['bbox']);text=''.join(s['text'] for s in spans)
            if not text.strip():continue
            center=((bbox[0]+bbox[2])/2,(bbox[1]+bbox[3])/2)
            matches=[g for g in groups if g['bbox'][0]-4<=center[0]<=g['bbox'][2]+4 and g['bbox'][1]-4<=center[1]<=g['bbox'][3]+4]
            if not matches:continue
            group=min(matches,key=lambda g:(g['bbox'][2]-g['bbox'][0])*(g['bbox'][3]-g['bbox'][1]))
            candidates.append({'id':str(len(candidates)),'group':group['name'],'bbox':bbox,'text':text,'font':spans[0]['font'].split('+')[-1],'size':spans[0]['size'],'spans':[{'text':s['text'],'font':s['font'].split('+')[-1],'size':s['size'],'color':s['color'],'origin':list(s['origin']),'bbox':list(s['bbox'])} for s in spans]})
    blocks=[]
    for g in groups:
        member=[x for x in candidates if x['group']==g['name']]
        member.sort(key=lambda x:(round(x['bbox'][1]/3),x['bbox'][0]))
        if not member:continue
        blocks.append({'name':g['name'],'bbox':list(g['bbox']),'line_ids':[x['id'] for x in member], 'lines':[x['text'] for x in member]})
    return {'width':page.rect.width,'height':page.rect.height,'groups':[{'name':g['name'],'count':sum(x['group']==g['name'] for x in candidates)} for g in groups], 'items':candidates, 'blocks':blocks,'graphics':graphic_objects(page)}


def build_pdf(source, page_index, model, edits, replacement_font, shifts=None, graphics=None, objects=None):
    shifts = shifts or {}
    graphics = graphics or {}
    objects = objects or {}
    items={x['id']:x for x in model['items']}
    warnings=[]
    with pymupdf.open(source) as doc:
        pg=doc[page_index]
        fpath=font_path(replacement_font);fallback=pymupdf.Font(fontfile=str(fpath))
        # PDF Base-14 fonts (Type 1, not embedded) must be retained for
        # ordinary Latin text; otherwise every edited run becomes Droid Fallback.
        base14 = {
            'Helvetica':'helv', 'Helvetica-Bold':'hebo',
            'Helvetica-Oblique':'heit', 'Helvetica-BoldOblique':'hebi',
            'Times-Roman':'tiro', 'Times-Bold':'tibo',
            'Times-Italic':'tiit', 'Times-BoldItalic':'tibi',
            'Courier':'cour', 'Courier-Bold':'cobo',
            'Courier-Oblique':'coit', 'Courier-BoldOblique':'cobi',
            'Symbol':'symb', 'ZapfDingbats':'zadb',
        }
        standard_font_cache = {}
        def standard_font(name):
            short=base14.get(name.split('+')[-1])
            if not short:return None
            if name not in standard_font_cache:
                font=pymupdf.Font(fontname=short)
                # Type-1 standard Latin fonts use PDF WinAnsi; allow ASCII.
                # Unsupported glyphs are rendered in the Unicode fallback.
                coverage=set(range(32,127)) if short not in ('symb','zadb') else set()
                standard_font_cache[name]=(font,coverage,short)
            return standard_font_cache[name]
        # Text glyph bboxes in PDF routinely overlap adjacent baseline rows.
        # Full-height redactions erase unrelated text. Do not force repaint of
        # neighboring lines: leave them as native PDF text objects.
        edits = dict(edits)
        forced = set()
        def safe_redaction_rect(span):
            b = pymupdf.Rect(span['bbox'])
            # A narrow strip through the middle of glyphs intersects their
            # bounding boxes without reaching neighboring baseline rows.
            # PyMuPDF removes characters whose glyph bbox intersects strip.
            y = (b.y0 + b.y1) / 2.0
            half = min(0.35, max(0.08, b.height * 0.025))
            return pymupdf.Rect(b.x0 + .05, y-half, b.x1-.05, y+half)
        def assert_redactions_are_isolated():
            edited_ids = {k for k in edits if edits[k] != items[k]['text'] or shifts.get(k)}
            strip_rects = [safe_redaction_rect(sp)
                           for key in edited_ids for sp in items[key]['spans']]
            for key, item in items.items():
                if key in edited_ids: continue
                for sp in item['spans']:
                    if any(pymupdf.Rect(sp['bbox']).intersects(r) for r in strip_rects):
                        raise ValueError('Text edit blocked: neighboring source glyphs overlap the deletion strip')
        # Actual PDF text deletion uses a centerline strip below.
        # Reflow ONLY subsequent baseline rows in the same logical block.
        # Determine extra visual height caused by a changed source line BEFORE
        # redaction, and redraw later rows at their shifted positions.
        auto_shift = {}
        group_map = {b['name']: b for b in model['blocks']}
        measure_fonts = {}
        def measured_font(sp):
            name = sp['font']
            if name not in measure_fonts:
                payload, charset = embedded_font(doc, pg, name)
                try:
                    measure_fonts[name] = (pymupdf.Font(fontbuffer=payload), charset) if payload else ((standard_font(name) or (fallback, set(), None))[:2])
                except Exception:
                    measure_fonts[name] = (fallback, set())
            return measure_fonts[name]
        def measured_char_styles(item, new):
            old=item['text']; spans=item['spans']; orig=[]
            for i,sp in enumerate(spans):
                if not sp['text'].strip():
                    chosen=next((j for j in range(i-1,-1,-1) if spans[j]['text'].strip()),None)
                    if chosen is None:
                        chosen=next((j for j in range(i+1,len(spans)) if spans[j]['text'].strip()),i)
                else:chosen=i
                orig.extend([chosen]*len(sp['text']))
            output=[0]*len(new)
            for tag,i0,i1,j0,j1 in difflib.SequenceMatcher(a=old,b=new,autojunk=False).get_opcodes():
                if tag=='equal':output[j0:j1]=orig[i0:i1]
                elif tag=='insert':output[j0:j1]=[orig[max(0,i0-1)] if orig else 0]*(j1-j0)
                elif tag=='replace':output[j0:j1]=[orig[i0] if i0<len(orig) else orig[-1] if orig else 0]*(j1-j0)
            return output
        def wrap_geometry(item, value):
            """Use the actual per-character style and painter's wrap decisions.

            Return number of rendered visual rows and maximum visual leading.  The
            legacy estimator used only the first font, causing missed line moves
            in mixed-font or Cyrillic-fallback text.
            """
            spans=item['spans']; styles=measured_char_styles(item,value)
            first=spans[0];size=float(first['size'])
            group=group_map.get(item['group'])
            if not group:return 1,size*1.32
            limit=min(float(model['width'])-8.,float(group['bbox'][2]))
            if float(item['bbox'][2])>limit-1. and size>=20:
                limit=min(float(model['width'])-8.,max(limit,float(item['bbox'][2])+max(45.,size*1.25)))
            x=float(first['origin'][0]);cont_x=min(x,max(0.,float(group['bbox'][0])));line_x=x
            n=1;pos=0
            def cw(i,ch):
                sp=spans[styles[i]]
                font,cov=measured_font(sp)
                return (font if ord(ch) in cov else fallback).text_length(ch,fontsize=float(sp['size']))
            def next_line():
                nonlocal x,line_x,n
                n+=1;line_x=cont_x;x=line_x
            segments=value.split('\n')
            for si,segment in enumerate(segments):
                for token in re.finditer(r'\S+|[ \t]+',segment):
                    txt=token.group(0)
                    pairs=[(pos+token.start()+j,ch) for j,ch in enumerate(txt)]
                    if txt.isspace():
                        if x<=line_x+.01:continue
                        width=sum(cw(i,ch) for i,ch in pairs)
                        if x+width>limit+.01:next_line()
                        else:
                            for i,ch in pairs:
                                w=cw(i,ch)
                                if x+w>limit+.01 and x>line_x+.01:next_line()
                                x+=w
                        continue
                    width=sum(cw(i,ch) for i,ch in pairs)
                    if x>line_x+.01 and x+width>limit+.01:next_line()
                    for i,ch in pairs:
                        w=cw(i,ch)
                        if x>line_x+.01 and x+w>limit+.01:next_line()
                        x+=w
                pos+=len(segment)+1
                if si<len(segments)-1:next_line()
            return n,size*1.32
        def extra_wrap_height(item, text):
            if text==item['text'] or not text:return 0.
            n,leading=wrap_geometry(item,text)
            return min(800.,max(0,n-1)*leading)
        changed_positions=[]
        for key, value in list(edits.items()):
            item=items[key]
            extra=extra_wrap_height(item,value)
            if extra>.1:
                changed_positions.append((item['group'],float(item['spans'][0]['origin'][1]),extra))
        for key,item in items.items():
            y=float(item['spans'][0]['origin'][1]); group=item['group']
            shift=sum(height for g,anchor,height in changed_positions if group==g and y>anchor+0.75)
            if shift>.1:
                shifts[key]=shifts.get(key,0.)+shift
                edits.setdefault(key,item['text'])
        # Safety: avoid displacing anything outside the affected text group.
        # Capture original subset mappings BEFORE redactions remove font glyph references.
        font_cache={}
        for key,value in edits.items():
            if value==items[key]['text'] and not shifts.get(key) and key not in forced:continue
            for sp in items[key]['spans']:
                name=sp['font']
                if name not in font_cache:font_cache[name]=embedded_font(doc,pg,name)
        for key,value in edits.items():
            src=items[key]
            if value==src['text'] and not shifts.get(key) and key not in forced:continue
            for sp in src['spans']:
                r=safe_redaction_rect(sp)
                if not r.is_empty:pg.add_redact_annot(r,fill=False)
        assert_redactions_are_isolated()
        # Apply text edits separately: line/icon removal MUST NOT delete text.
        if any(value!=items[key]['text'] for key,value in edits.items()) or any(shifts.values()) or forced:
            pg.apply_redactions(images=0, graphics=0, text=0)
        graphical={g['id']:g for g in model['graphics']}
        icon_drawings=pg.get_drawings()
        moved=[]
        for gid, delta in graphics.items():
            if not delta or (abs(delta.get('dx',0))<.01 and abs(delta.get('dy',0))<.01):continue
            obj=graphical[gid]
            b=obj['bbox']
            margin=.12 if obj['kind']=='icon' else .25
            pg.add_redact_annot(pymupdf.Rect(b[0]-margin,b[1]-(.7 if obj['kind']=='line' else margin),b[2]+margin,b[3]+(.7 if obj['kind']=='line' else margin)),fill=False)
            moved.append((obj,delta))
        if moved:
            # Never redact graphics if another drawing is in the target area.
            # This prevents deleting the vertical sides of surrounding rectangles.
            draw_items=pg.get_drawings()
            for obj,delta in moved:
                target=pymupdf.Rect(obj['bbox'])
                for d in draw_items:
                    r=d['rect']
                    if not target.intersects(r):continue
                    # Ignore a page-wide solid background only: it encloses the
                    # target and cannot be wholly covered by its redaction.
                    if d.get('fill') is not None and r.contains(target) and r.get_area()>target.get_area()*20:continue
                    # Other unrelated strokes or borders may be grouped paths.
                    if d.get('type') in ('s','fs') and r.width>target.width*2 and r.height>target.height*2:continue
                    # Avoid rejecting the selected line/icon's own path.
                    if abs(r.x0-target.x0)<1 and abs(r.y0-target.y0)<1 and abs(r.x1-target.x1)<1 and abs(r.y1-target.y1)<1:continue
                    raise ValueError('Graphic move blocked: a neighboring path shares its area')
            # text=1 preserves every intersecting text glyph. graphics=2 limits
            # vector removal to covered paths, avoiding nearby shapes.
            # Detect destructive side-effects: PyMuPDF redaction is area-based,
            # and can remove filled paths (including the page's colored background).
            # NEVER silently damage the original artwork.
            def filled_signature(drawings):
                return sorted((round(d['rect'].x0,2),round(d['rect'].y0,2),round(d['rect'].x1,2),round(d['rect'].y1,2),str(d.get('fill')),str(d.get('items'))) for d in drawings if d.get('fill') is not None)
            fills_before=filled_signature(draw_items)
            pg.apply_redactions(images=0, graphics=2, text=1)
            if filled_signature(pg.get_drawings()) != fills_before:
                raise ValueError('Unsafe line/icon move: removing the original would alter a background or nearby filled graphic. The PDF was NOT exported. Please provide this source PDF for a lossless vector edit.')
        pg.insert_font(fontname='stage48fallback',fontfile=str(fpath))
        cached={}
        def font_for(name):
            if name not in cached:
                data,cov=font_cache.get(name,(None,set()))
                builtin=standard_font(name) if not data else None
                if builtin:
                    cached[name]=builtin
                elif data:
                    try:
                        tag='stage481font'+str(len(cached))
                        pg.insert_font(fontname=tag,fontbuffer=data)
                        cached[name]=(pymupdf.Font(fontbuffer=data),cov,tag)
                    except Exception:cached[name]=(fallback,set(),'stage48fallback')
                else:cached[name]=(fallback,set(),'stage48fallback')
            return cached[name]
        def source_styles(src):
            # Some PDF generators store trailing layout spaces as separate BLACK
            # spans even after white text. These invisible spans must not become
            # the caret/insertion style or recolor fallback glyphs.
            seq=[]
            spans=src['spans']
            for i,sp in enumerate(spans):
                # Whitespace-only spans inherit the preceding visible run.
                # If no preceding visible run, use the next one.
                if not sp['text'].strip():
                    chosen=next((j for j in range(i-1,-1,-1)
                                 if spans[j]['text'].strip()),None)
                    if chosen is None:
                        chosen=next((j for j in range(i+1,len(spans))
                                     if spans[j]['text'].strip()),i)
                else:
                    chosen=i
                seq.extend([chosen]*len(sp['text']))
            return seq
        def char_styles(src, new):
            """Keep styles on unchanged text, inherit insertion style from its caret.

            At a boundary prefer the preceding character for inserted text; the
            original implementation used styles[i0] (the following character),
            causing inserted body text to unexpectedly become a heading.
            For replacements use the replaced range's first style, because that
            is the style of the text the user selected to replace.
            """
            old = src['text']
            styles = source_styles(src)
            out = [0] * len(new)
            matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
            for kind, i0, i1, j0, j1 in matcher.get_opcodes():
                if kind == 'equal':
                    out[j0:j1] = styles[i0:i1]
                elif kind == 'insert':
                    anchor = i0 - 1 if i0 > 0 else 0
                    inherited = styles[anchor] if styles else 0
                    out[j0:j1] = [inherited] * (j1 - j0)
                elif kind == 'replace':
                    inherited = styles[i0] if i0 < len(styles) else (styles[-1] if styles else 0)
                    out[j0:j1] = [inherited] * (j1 - j0)
            return out
        def glyph_width(ch, sp):
            primary, cov, _ = font_for(sp['font'])
            f = primary if ord(ch) in cov else fallback
            return f.text_length(ch, fontsize=float(sp['size']))
        def draw_runs(runs, x, y):
            """Emit coherent same-style font runs, not one PDF text object per glyph."""
            for text_run, sp, tag, measured in runs:
                c = sp['color']
                color = tuple(((c >> j) & 255) / 255 for j in (16, 8, 0))
                pg.insert_text((x, y), text_run, fontsize=float(sp['size']), fontname=tag, color=color)
                x += measured
        for key,value in edits.items():
            src=items[key]
            if value==src['text'] and not shifts.get(key) and key not in forced:continue
            spans=src['spans'];first=spans[0]
            if not value:continue
            # Moving an UNCHANGED PDF line must never re-wrap it. Rebuild its
            # original positioned spans at the shifted baseline, preserving
            # spacing within rows such as hotel/date or job-title/period.
            if value == src['text'] and abs(shifts.get(key,0.0)) > .01 and key not in forced:
                dy=float(shifts[key])
                for sp in spans:
                    if not sp['text']:continue
                    _,cov,tag=font_for(sp['font'])
                    # Original lines can have multiple independently positioned
                    # spans. Preserve x for each, not a synthetic shared cursor.
                    x,y=sp['origin']; c=sp['color']
                    color=tuple(((c >> j) & 255) / 255 for j in (16,8,0))
                    if all(ord(ch) in cov for ch in sp['text']):
                        pg.insert_text((x,y+dy),sp['text'],fontsize=float(sp['size']),fontname=tag,color=color)
                    else:
                        cx=float(x)
                        for ch in sp['text']:
                            use=tag if ord(ch) in cov else 'stage48fallback'
                            pg.insert_text((cx,y+dy),ch,fontsize=float(sp['size']),fontname=use,color=color)
                            cx+=glyph_width(ch,sp)
                continue
            styles=char_styles(src,value)
            size=float(first['size']);bbox=src['bbox']
            # The edited line belongs to a logical block, not to the full page.
            # Only its own content reflows; unrelated source lines stay in place.
            group = next((g for g in model['blocks'] if g['name']==src['group']), None)
            group_right = float(group['bbox'][2]) if group else float(model['width'])-8
            baseline=float(first['origin'][1])+shifts.get(key,0.0);start_x=float(first['origin'][0])
            right_edge=max(start_x+10.0, min(float(model['width'])-8,group_right))
            # Some PDFs position large display text beyond the detected column
            # bbox. Do not force new glyphs of that SAME display line to wrap
            # at a boundary that was already narrower than the original text.
            if float(bbox[2]) > group_right-1.0 and size>=20.0:
                right_edge=min(float(model['width'])-8,
                               max(right_edge,float(bbox[2])+max(45.0,size*1.25)))
            # Right-aligned source lines (dates, prices) have little room to
            # their right. Keep the original starting position for the first
            # line, but wrap continuations from the logical block left edge.
            group_left=float(group['bbox'][0]) if group else start_x
            continuation_x=min(start_x, max(0.0, group_left))
            line_x=start_x
            cursor=line_x
            runs=[];run_tag=None;run_style=None;run_text='';run_width=0.0
            def flush():
                nonlocal run_text,run_width,run_tag,run_style,runs
                if run_text:
                    runs.append((run_text,run_style,run_tag,run_width))
                    run_text='';run_width=0.0;run_tag=None;run_style=None
            def end_line():
                nonlocal cursor,baseline,runs,line_x
                flush();draw_runs(runs,line_x,baseline)
                runs=[];line_x=continuation_x;cursor=line_x;baseline+=size*1.32
            def place_character(i,ch):
                nonlocal cursor,run_tag,run_style,run_text,run_width
                sp=spans[styles[i]]
                _,cov,tag=font_for(sp['font'])
                chosen=tag if ord(ch) in cov else 'stage48fallback'
                w=glyph_width(ch,sp)
                if cursor+w>right_edge+0.01 and cursor>line_x+0.01:
                    end_line()
                if run_tag!=chosen or run_style is not sp:
                    flush();run_tag,run_style=chosen,sp
                run_text+=ch;run_width+=w;cursor+=w
            # Respect explicit line breaks. Prefer word boundaries; for words
            # longer than the block, fall back to glyph-by-glyph wrapping.
            position=0
            for segment in value.split('\n'):
                for token in re.finditer(r'\S+|[ \t]+',segment):
                    token_text=token.group(0)
                    pairs=[(position+token.start()+j,ch) for j,ch in enumerate(token_text)]
                    if token_text.isspace():
                        # Avoid an artificial leading space immediately after wrap.
                        if cursor<=line_x+0.01:continue
                        word_width=sum(glyph_width(ch,spans[styles[i]]) for i,ch in pairs)
                        if cursor+word_width>right_edge+0.01:
                            end_line()
                        else:
                            for i,ch in pairs:place_character(i,ch)
                        continue
                    token_width=sum(glyph_width(ch,spans[styles[i]]) for i,ch in pairs)
                    if cursor>line_x+0.01 and cursor+token_width>right_edge+0.01:
                        end_line()
                    for i,ch in pairs:place_character(i,ch)
                position+=len(segment)+1
                if position<=len(value):end_line()
            flush();draw_runs(runs,line_x,baseline)
        # Recreate the original isolated vector path at its translated coordinates.
        # Use the real PDF drawing primitives (not a rasterized icon overlay).
        drawings=pg.get_drawings()  # Caution: post-redaction drawings lack erased paths.
        del drawings
        for obj, delta in moved:
            dx=float(delta['dx']);dy=float(delta['dy']);b=obj['bbox']
            if obj['kind']=='line':
                # Use source geometry, rather than bounding-box midpoint, and
                # never coerce a genuine 0 pt hairline into a 1 pt stroke.
                orig=icon_drawings[int(obj['id'])]
                shape=pg.new_shape()
                for segment in orig['items']:
                    if segment[0]=='l':
                        shape.draw_line((segment[1].x+dx,segment[1].y+dy),(segment[2].x+dx,segment[2].y+dy))
                shape.finish(color=orig.get('color'),width=float(orig['width']) if orig.get('width') is not None else 1.0,
                             dashes=orig.get('dashes') or None,stroke_opacity=orig.get('stroke_opacity',1) or 1,
                             lineCap=orig.get('lineCap',0)[0] if isinstance(orig.get('lineCap'),(tuple,list)) else (orig.get('lineCap') or 0),
                             lineJoin=orig.get('lineJoin') or 0)
                shape.commit(overlay=True)
            else:
                original=icon_drawings[int(obj['id'])]
                shape=pg.new_shape()
                def pt(v):return pymupdf.Point(v.x+dx,v.y+dy)
                for segment in original['items']:
                    op=segment[0]
                    if op=='l':shape.draw_line(pt(segment[1]),pt(segment[2]))
                    elif op=='c':shape.draw_bezier(pt(segment[1]),pt(segment[2]),pt(segment[3]),pt(segment[4]))
                    elif op=='re':shape.draw_rect(segment[1]+(dx,dy,dx,dy))
                    elif op=='qu':
                        q=segment[1];shape.draw_quad(pymupdf.Quad(pt(q.ul),pt(q.ur),pt(q.ll),pt(q.lr)))
                shape.finish(color=original.get('color'),fill=original.get('fill'),width=original.get('width',1),closePath=original.get('closePath',False),even_odd=original.get('even_odd',False),fill_opacity=original.get('fill_opacity',1) or 1,stroke_opacity=original.get('stroke_opacity',1) or 1)
                shape.commit(overlay=True)
        # Images are moved independently of the source text engine. Redaction
        # blanks the original image pixels, not intersecting glyphs or paths.
        changed_images=[]
        for oid,delta in objects.items():
            if all(abs(delta[k]-(1 if k in ('sx','sy') else 0))<.001 for k in ('dx','dy','sx','sy')):
                continue
            obj=next(x for x in model.get('objects',[]) if x['id']==oid)
            rect=pymupdf.Rect(obj['bbox'])
            newrect=pymupdf.Rect(rect.x0+delta['dx'],rect.y0+delta['dy'],rect.x0+delta['dx']+rect.width*delta['sx'],rect.y0+delta['dy']+rect.height*delta['sy'])
            if not pg.rect.contains(newrect):
                raise ValueError('Image destination must remain inside the PDF page')
            if any(rect.intersects(pymupdf.Rect(x['bbox'])) for x in model['items']):
                raise ValueError('Image overlaps text: automatic source removal is unsafe')
            changed_images.append((obj,rect,newrect))
        if changed_images:
            for obj,rect,target in changed_images:
                pg.add_redact_annot(rect, fill=False)
            pg.apply_redactions(images=2, graphics=0, text=1)
            for obj,rect,target in changed_images:
                extracted=doc.extract_image(int(obj['xref']))
                pg.insert_image(target, stream=extracted['image'], keep_proportion=False, overlay=True)
            warnings.append(f'Moved {len(changed_images)} raster image(s).')
        if moved:warnings.append(f'Moved {len(moved)} separate vector objects.')
        if len(edits)>0: warnings.append('Edited text keeps source span styles where possible; unmodified PDF objects remain untouched. Geometry may overlap.')
        pdf=doc.tobytes(garbage=4,deflate=True)
    with pymupdf.open(stream=pdf,filetype='pdf') as chk:
        png=chk[page_index].get_pixmap(matrix=pymupdf.Matrix(1.25,1.25),alpha=False).tobytes('png')
    return pdf,png,warnings

def block_edits(model, changed_blocks, line_sources=None):
    """Align block text to source lines; unchanged lines retain native PDF runs.

    Edits that expand a line are assigned to the affected source line; no
    unrelated lines are redrawn. This is a text-preserving first iteration,
    not a full word-processor-style whole-block reflow engine.
    """
    out={}
    shifts={}
    by_id={item['id']:item for item in model['items']}
    blocks={b['name']:b for b in model['blocks']}
    for name,value in changed_blocks.items():
        b=blocks[name]
        before=b['lines']; after=value.replace('\r\n','\n').split('\n')
        source_ids=(line_sources or {}).get(name) if isinstance(line_sources,dict) else None
        if (isinstance(source_ids,list) and len(source_ids)==len(after)
                and all(isinstance(x,str) and x in b['line_ids'] for x in source_ids)
                and all(b['line_ids'].index(source_ids[i])<=b['line_ids'].index(source_ids[i+1])
                        for i in range(len(source_ids)-1))):
            grouped={}
            for ident,ln in zip(source_ids,after):grouped.setdefault(ident,[]).append(ln)
            for ident,parts in grouped.items():
                new_value='\n'.join(parts)
                if new_value!=by_id[ident]['text']:out[ident]=new_value
            # The painter's automatic-wrap reflow handles additional rows.
            continue
        op=difflib.SequenceMatcher(a=before,b=after,autojunk=False)
        for kind,i0,i1,j0,j1 in op.get_opcodes():
            if kind=='equal':continue
            old_ids=b['line_ids'][i0:i1]
            new_lines=after[j0:j1]
            # A blank line inserted in the rich-text block occupies vertical
            # space: move following source text objects from this SAME block.
            # Unrelated blocks and page graphics are deliberately stationary.
            extra=len(new_lines)-len(old_ids)
            if extra > 0 and all(s == '' for s in new_lines[len(old_ids):]):
                anchor_index=max(0, i1-1)
                source_id=b['line_ids'][anchor_index]
                anchor=by_id[source_id]
                leading=float(anchor['size'])*1.32
                for following_id in b['line_ids'][i1:]:
                    shifts[following_id]=shifts.get(following_id,0.0)+extra*leading
            if not old_ids:
                anchor=b['line_ids'][max(0,i0-1)]
                out[anchor]=out.get(anchor,before[max(0,i0-1)])+'\n'+'\n'.join(new_lines)
            else:
                for offset,id in enumerate(old_ids):
                    out[id]=new_lines[offset] if offset<len(new_lines) else ''
                if len(new_lines)>len(old_ids):
                    last=old_ids[-1]
                    out[last]+='\n'+'\n'.join(new_lines[len(old_ids):])
    # Unchanged lines that move still need to be redrawn at their new locations.
    for ident in shifts:
        out.setdefault(ident,by_id[ident]['text'])
    return out, shifts

def main():
    p=argparse.ArgumentParser();p.add_argument('pdf',type=Path);p.add_argument('--mode',choices=['auto','columns','table'],default='auto');p.add_argument('--page',type=int,default=1);p.add_argument('--port',type=int,default=8765);p.add_argument('--font',type=Path)
    args=p.parse_args();source=args.pdf.resolve()
    with pymupdf.open(source) as doc:
        pg=doc[args.page-1];model=make_model(pg,args.mode)
        original=pg.get_pixmap(matrix=pymupdf.Matrix(1.25,1.25),alpha=False).tobytes('png')
    if not model['blocks']:p.error('No editable text lines found')
    html=APP.replace('__MODEL__',json.dumps(model,ensure_ascii=True)).encode('utf-8')
    class Handler(BaseHTTPRequestHandler):
        def send(self,data,ctype,status=200):
            self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if urlsplit(self.path).path in ('/','/index.html'):self.send(html,'text/html; charset=utf-8')
            elif urlsplit(self.path).path=='/original.png':self.send(original,'image/png')
            else:self.send_error(404)
        def do_POST(self):
            if urlsplit(self.path).path!='/api/render':self.send_error(404);return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<500000:raise ValueError('Invalid payload')
                data=json.loads(self.rfile.read(length));block_changes=data.get('blocks',{});graphics=data.get('graphics',{});edits,shifts=block_edits(model,block_changes)
                if not isinstance(block_changes,dict) or len(block_changes)>50:raise ValueError('Invalid changes')
                known={block['name'] for block in model['blocks']}
                if any(k not in known or not isinstance(v,str) or len(v)>20000 for k,v in block_changes.items()):raise ValueError('Invalid block edit')
                if not isinstance(graphics,dict) or len(graphics)>100:raise ValueError('Invalid graphic changes')
                ids={g['id'] for g in model['graphics']}
                if any(k not in ids or not isinstance(v,dict) or not all(isinstance(v.get(a), (int,float)) and abs(v[a])<1000 for a in ('dx','dy')) for k,v in graphics.items()):raise ValueError('Invalid graphic move')
                pdf,png,warnings=build_pdf(source,args.page-1,model,edits,args.font,shifts,graphics)
                out=json.dumps({'pdf':base64.b64encode(pdf).decode('ascii'),'png':base64.b64encode(png).decode('ascii'),'changed':len(block_changes),'warnings':warnings}).encode('ascii')
                self.send(out,'application/json')
            except Exception as exc:self.send(json.dumps({'error':str(exc)}).encode('utf-8'),'application/json',400)
    srv=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Stage 4.8.7: http://127.0.0.1:{args.port}/',flush=True)
    try:srv.serve_forever()
    except KeyboardInterrupt:pass
    finally:srv.server_close()
if __name__=='__main__':main()
