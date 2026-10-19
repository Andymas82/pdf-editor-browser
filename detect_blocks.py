#!/usr/bin/env python3
"""Experimental text-block detector. Reads PDFs without changing them.
Outputs per-page PNG overlays and a JSON report. Requires PyMuPDF.
"""
import argparse, json, statistics
from pathlib import Path
import pymupdf as fitz


def overlap(a,b):
    return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))

def union(boxes):
    return [min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]

def lines_for(page):
    ret=[]
    for b in page.get_text('dict')['blocks']:
        if b.get('type')!=0: continue
        for line in b['lines']:
            spans=[s for s in line['spans'] if s.get('text','').strip()]
            if not spans:continue
            ret.append({'bbox':union([s['bbox'] for s in spans]),'text':''.join(s['text'] for s in spans),
                        'spans':[{'text':s['text'],'font':s['font'],'size':round(s['size'],2),'color':s['color']} for s in spans]})
    return sorted(ret,key=lambda x:(x['bbox'][1],x['bbox'][0]))

def separators(page):
    h=[];v=[]
    for d in page.get_drawings():
        for item in d['items']:
            if item[0]=='l':
                a,b=item[1],item[2]
                if abs(a.y-b.y)<1.5 and abs(a.x-b.x)>16:h.append((min(a.x,b.x),(a.y+b.y)/2,max(a.x,b.x)))
                elif abs(a.x-b.x)<1.5 and abs(a.y-b.y)>16:v.append(((a.x+b.x)/2,min(a.y,b.y),max(a.y,b.y)))
            elif item[0]=='re':
                r=item[1]
                if r.height<=2 and r.width>16:h.append((r.x0,(r.y0+r.y1)/2,r.x1))
                elif r.width<=2 and r.height>16:v.append(((r.x0+r.x1)/2,r.y0,r.y1))
    return h,v

def table_grid(h,v,width):
    # Require several shared vertical and horizontal table rules, preventing CV decoration
    long_v=[x for x in v if x[2]-x[1]>40]
    long_h=[x for x in h if x[2]-x[0]>width*.3]
    crossings=sum(1 for x,y1,y2 in long_v for a,y,b in long_h if a<=x<=b and y1<=y<=y2)
    return crossings>=6 and len(long_v)>=3 and len(long_h)>=3

def page_groups(page,mode):
    lines=lines_for(page); h,v=separators(page)
    if mode=='auto': mode='table' if table_grid(h,v,page.rect.width) else 'columns'
    groups=[]
    if mode=='columns':
        # Find dominant vertical whitespace separating columns. Covers CV-style page layout.
        w=page.rect.width; best=None
        for frac in [x/100 for x in range(25,66)]:
            x=w*frac
            crossing=sum(1 for l in lines if l['bbox'][0]+3<x<l['bbox'][2]-3)
            left=sum(1 for l in lines if l['bbox'][2]<=x)
            right=sum(1 for l in lines if l['bbox'][0]>=x)
            if not left or not right:continue
            score=crossing*100 + abs(frac-.34)*10
            if best is None or score<best[0]:best=(score,x,crossing)
        x=best[1] if best and best[2]<len(lines)*.1 else None
        if x:
            buckets={'left':[],'right':[],'crossing':[]}
            for l in lines:
                if l['bbox'][2]<=x:buckets['left'].append(l)
                elif l['bbox'][0]>=x:buckets['right'].append(l)
                else:buckets['crossing'].append(l)
        else:buckets={'page':lines}
        for name, ls in buckets.items():
            if ls:groups.append({'kind':'column','name':name,'bbox':union([l['bbox'] for l in ls]),'lines':ls})
    elif mode=='table':
        # Locate the cell occupied by each line using horizontal and vertical
        # rules that actually cross that position (not global row/column IDs).
        # Thin filled rectangles, common in spreadsheet-exported PDFs, are rules.
        buckets={}
        for l in lines:
            x0,y0,x1,y1=l['bbox'];cx=(x0+x1)/2;cy=(y0+y1)/2
            hs=sorted(set(round(y,2) for a,y,b in h if a-1<=cx<=b+1))
            vs=sorted(set(round(x,2) for x,a,b in v if a-1<=cy<=b+1))
            top=max((y for y in hs if y<=cy),default=0)
            bottom=min((y for y in hs if y>cy),default=page.rect.height)
            left=max((x for x in vs if x<=cx),default=0)
            right=min((x for x in vs if x>cx),default=page.rect.width)
            key=(top,bottom,left,right)
            buckets.setdefault(key,[]).append(l)
        for i,(key,ls) in enumerate(sorted(buckets.items(),key=lambda x:(x[0][0],x[0][2]))):
            top,bottom,left,right=key
            groups.append({'kind':'cell-candidate','name':f'cell-{i+1}',
             'cell_bbox':[left,top,right,bottom],
             'bbox':union([l['bbox'] for l in ls]),'lines':ls})
    else:raise ValueError(mode)
    return mode, groups, len(h),len(v)

def analyze(src,out,mode,dpi):
    pdf=fitz.open(src);out.mkdir(parents=True,exist_ok=True)
    results={'source':str(src),'note':'Heuristic grouping; not equivalent to PDF-XChange internal structure','pages':[]}
    for pno,page in enumerate(pdf):
        actual,groups,nh,nv=page_groups(page,mode)
        results['pages'].append({'page':pno+1,'mode':actual,'horizontal_rules':nh,'vertical_rules':nv,'groups':groups})
        pix=page.get_pixmap(matrix=fitz.Matrix(dpi/72,dpi/72),alpha=False)
        from PIL import Image,ImageDraw,ImageFont
        import io
        im=Image.open(io.BytesIO(pix.tobytes('png'))).convert('RGB');draw=ImageDraw.Draw(im,'RGBA')
        k=dpi/72
        colors=[(231,83,55,225),(22,121,223,225),(128,70,189,225),(0,130,116,225)]
        for i,g in enumerate(groups):
            x0,y0,x1,y1=[int(c*k) for c in g['bbox']]
            rgb=colors[i%len(colors)];draw.rectangle((x0-3,y0-3,x1+3,y1+3),outline=rgb,width=3)
            label=f'{i+1}: {g["name"]} ({len(g["lines"])} lines)'
            ty=max(0,y0-24);tw=6*len(label)+12
            draw.rectangle((x0,ty,x0+tw,ty+20),fill=rgb)
            draw.text((x0+5,ty+3),label,fill=(255,255,255,255))
        im.save(out/f'page-{pno+1:02d}-overlay.png')
    (out/'blocks.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Analyzed {len(pdf)} pages; wrote {out}');print('Groups:',[len(p['groups']) for p in results['pages']]);print('Modes:',[p['mode'] for p in results['pages']])

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('pdf',type=Path);a.add_argument('--output',type=Path,default=Path('block-output'));a.add_argument('--mode',choices=['auto','columns','table'],default='auto');a.add_argument('--dpi',type=int,default=130)
    z=a.parse_args();analyze(z.pdf,z.output,z.mode,z.dpi)
