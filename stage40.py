#!/usr/bin/env python3
"""Stage 4.0 experimental real PDF export: selective paragraph redaction + Unicode text.

This is deliberately separate from the browser preview. The source PDF is never modified.
"""
import argparse
import json
import os
import re
import unicodedata
import io
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
from pathlib import Path
import pymupdf
from detect_blocks import page_groups
from stage32_core import model_for


def font_path(cli_path):
    if cli_path:
        p=Path(cli_path)
        if not p.is_file(): raise ValueError(f'Font not found: {p}')
        return p
    paths=[r'C:\Windows\Fonts\times.ttf',r'C:\Windows\Fonts\arial.ttf',
           '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf',
           '/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf']
    for name in paths:
        if Path(name).is_file(): return Path(name)
    # Browser / Pyodide has no Windows or Linux system fonts. PyMuPDF ships
    # a built-in Unicode fallback; materialize it only in the runtime's
    # temporary filesystem. No font file is distributed with this application.
    import tempfile
    built_in = Path(tempfile.gettempdir()) / 'pdf_editor_unicode_runtime.ttf'
    if not built_in.is_file():
        built_in.write_bytes(pymupdf.Font(fontname='cjk').buffer)
    return built_in


def embedded_font(doc, page, requested_name):
    """Rebuild Unicode cmap for glyphs proven by source PDF texttrace."""
    mapping = {}
    for span in page.get_texttrace():
        name = span['font'].split('+')[-1]
        if name != requested_name:
            continue
        for char in span['chars']:
            cp, gid = char[:2]
            if isinstance(cp, int) and cp >= 32 and isinstance(gid, int) and gid > 0:
                mapping[cp] = gid
    for xref, ext, typ, base, *_ in page.get_fonts(full=True):
        if base.split('+')[-1] != requested_name or ext.lower() not in ('ttf', 'otf'):
            continue
        try:
            raw = doc.extract_font(xref)[3]
            ft = TTFont(io.BytesIO(raw), lazy=False)
            glyphs = ft.getGlyphOrder()
            cmap = {}
            if 'cmap' in ft:
                for table in ft['cmap'].tables:
                    if table.isUnicode():
                        cmap.update(table.cmap)
            for cp, gid in mapping.items():
                if gid < len(glyphs):
                    cmap[cp] = glyphs[gid]
            if not cmap:
                continue
            sub = CmapSubtable.newSubtable(12)
            sub.platformID, sub.platEncID, sub.language = 3, 10, 0
            sub.cmap = cmap
            table = newTable('cmap')
            table.tableVersion, table.tables = 0, [sub]
            ft['cmap'] = table
            output = io.BytesIO()
            ft.save(output)
            ft.close()
            return output.getvalue(), set(cmap)
        except Exception as exc:
            print('Embedded font reconstruction skipped: ' + str(exc).encode('ascii', 'backslashreplace').decode(), flush=True)
    return None, set()


class MixedFont:
    def __init__(self, primary, fallback, coverage):
        self.primary, self.fallback, self.coverage = primary, fallback, coverage

    def is_primary(self, ch):
        return ch != ' ' and ord(ch) in self.coverage

    def font_for(self, ch):
        return self.primary if self.is_primary(ch) else self.fallback

    def text_length(self, s, fontsize):
        return sum(self.font_for(ch).text_length(ch, fontsize=fontsize) for ch in s)

    def runs(self, s):
        output=[]
        for ch in s:
            primary=self.is_primary(ch)
            if output and output[-1][0]==primary:
                output[-1]=(primary,output[-1][1]+ch)
            else:
                output.append((primary,ch))
        return output


def paragraph_lines(lines, paragraph):
    if paragraph=='all': return lines
    start=next((i+1 for i,l in enumerate(lines) if l['text'].strip().lower()=='resumen'),None)
    if start is None: raise ValueError('Resumen heading not found')
    stop=next((i for i in range(start,len(lines)) if lines[i]['text'].strip()=='4.' or lines[i]['text'].strip().lower().startswith('formación académica')),len(lines))
    return lines[start:stop]


def wrap_text(text,font,size,max_width):
    """Width-based wrap, including oversized no-space words; preserve explicit newlines."""
    lines=[]
    for paragraph in text.split('\n'):
        if not paragraph:
            lines.append('');continue
        tokens=re.findall(r'\S+|\s+',paragraph)
        current=''
        for token in tokens:
            if token.isspace():
                if current and font.text_length(current+' ',fontsize=size)<=max_width: current+=' '
                continue
            if current and font.text_length(current+token,fontsize=size)<=max_width:
                current+=token;continue
            if current.strip(): lines.append(current.rstrip());current=''
            for ch in token:
                if current and font.text_length(current+ch,fontsize=size)>max_width:
                    lines.append(current);current=''
                if font.text_length(ch,fontsize=size)>max_width:
                    raise ValueError(f'Character wider than block: U+{ord(ch):04X}')
                current+=ch
        lines.append(current.rstrip())
    return lines


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('pdf',type=Path)
    ap.add_argument('--mode',choices=['auto','columns','table'],default='auto')
    ap.add_argument('--group',required=True)
    ap.add_argument('--paragraph',choices=['all','resumen'],default='all')
    ap.add_argument('--page',type=int,default=1)
    ap.add_argument('--text-file',type=Path,required=True,help='UTF-8 replacement text')
    ap.add_argument('--font',type=Path,help='Full Unicode TTF font (recommended on Windows: C:\\Windows\\Fonts\\times.ttf)')
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--box',nargs=4,type=float,metavar=('X0','Y0','X1','Y1'),help='Editable text frame in PDF points')
    ap.add_argument('--allow-overlap',action='store_true',help='Allow text to overlap lower content (as PDF-XChange sometimes does)')
    args=ap.parse_args()
    if args.pdf.resolve()==args.output.resolve(): raise SystemExit('Refusing to overwrite input PDF')
    text=args.text_file.read_text(encoding='utf-8-sig').replace('\r\n','\n').strip()
    if not text:raise SystemExit('Replacement text is empty')
    fpath=font_path(args.font)
    fallback=pymupdf.Font(fontfile=str(fpath))
    with pymupdf.open(args.pdf) as doc:
        page=doc[args.page-1]
        mode,groups,_,_=page_groups(page,args.mode)
        group=next((g for g in groups if g['name']==args.group),None)
        if group is None:raise SystemExit('Group not found. Choices: '+', '.join(g['name'] for g in groups))
        lines=model_for(page,group)['lines'];selected=paragraph_lines(lines,args.paragraph)
        if not selected:raise SystemExit('No selected lines')
        area=group.get('cell_bbox',group['bbox'])
        x0=float(area[0])+ (2 if group['kind']=='cell-candidate' else 0)
        x1=float(area[2])- (2 if group['kind']=='cell-candidate' else 0)
        y0=float(min(l['bbox'][1] for l in selected));
        if args.box:
            bx0,by0,bx1,by1=args.box
            if not (0<=bx0<bx1<=page.rect.width and 0<=by0<by1<=page.rect.height):
                raise SystemExit('Invalid edit box')
            x0,x1,y0=bx0,bx1,by0
        sample=selected[0]['spans'][0];size=float(sample['size'])
        requested=sample['font'].split('+')[-1]
        fontbytes,coverage=embedded_font(doc,page,requested)
        use_embedded=bool(fontbytes)
        if use_embedded:
            primary=pymupdf.Font(fontbuffer=fontbytes)
        else:
            primary=fallback
        font=MixedFont(primary,fallback,coverage if use_embedded else set())
        spacing=[selected[i+1]['bbox'][1]-selected[i]['bbox'][1] for i in range(len(selected)-1)]
        # PDF boxes often have leading 1.3x; cap unreasonable gaps for a single paragraph.
        leading=max(size*1.24,min(size*1.65,sorted(spacing)[len(spacing)//2] if spacing else size*1.3))
        rows=wrap_text(text,font,size,x1-x0)
        # Check each rendered row against actual nearby text, not the entire column.
        # The old test incorrectly flagged words far to the right of a short row.
        # Use conservative glyph boxes; never ignore a real collision.
        selected_ids={l['id'] for l in selected}
        other_lines=[l for l in lines if l['id'] not in selected_ids]
        rows_geometry=[]
        overlaps=[]
        pad=0.35
        baseline=y0+size
        for i,row in enumerate(rows):
            width=font.text_length(row,fontsize=size)
            left=x0+max(0,(x1-x0-width)/2) if group['kind']=='cell-candidate' else x0
            # A rendered line starts at baseline minus ascender height; glyph descent is smaller.
            # PDF Font ascender / descender values are expressed relative to font size.
            rise=max(primary.ascender, fallback.ascender)*size
            descent=max(-primary.descender, -fallback.descender)*size
            rect=pymupdf.Rect(left-pad, baseline-rise-pad, left+width+pad, baseline+descent+pad)
            hit=[]
            for l in other_lines:
                if rect.intersects(pymupdf.Rect(l['bbox'])):
                    hit.append(l['id'])
            rows_geometry.append({'row':i+1,'text':row,'bbox':[round(v,2) for v in rect], 'overlap_ids':hit})
            overlaps.extend(hit)
            baseline+=leading
        overlaps=sorted(set(overlaps))
        bottom=max(r['bbox'][3] for r in rows_geometry)
        # The column's bounding box is NOT a paragraph boundary. Use the next
        # text line's top coordinate as a conservative hard stop.
        max_bottom=float(args.box[3]) if args.box else float(area[3])-(2 if group['kind']=='cell-candidate' else 0)
        if not args.box and args.paragraph!='all' and group['kind']!='cell-candidate':
            following=[l for l in other_lines if l['bbox'][1]>=y0 and l['bbox'][2]>x0 and l['bbox'][0]<x1]
            if following:
                max_bottom=min(max_bottom,min(l['bbox'][1] for l in following)-1.0)
        overflow=bottom>max_bottom
        if (overflow or overlaps) and not args.allow_overlap:
            print(json.dumps({'status':'blocked','reason':'overflow_or_overlap','vertical_overflow':overflow,
                              'overlap_line_ids':overlaps,'rendered_lines':len(rows),
                              'limit_y':round(max_bottom,2),'text_bottom_y':round(bottom,2),
                              'line_geometry':rows_geometry},ensure_ascii=True,indent=2))
            raise SystemExit('Unsafe layout: actual text overlap or next-section boundary exceeded. Shorten text.')
        # Redact ONLY text. Graphics and images stay. Selection rectangles are inset vertically.
        for l in selected:
            a=l['bbox'];page.add_redact_annot(pymupdf.Rect(a[0]-.15,a[1]+.4,a[2]+.15,a[3]-.4),fill=False)
        page.apply_redactions(images=0,graphics=0,text=0)
        page.insert_font(fontname='stage40unicode',fontfile=str(fpath))
        if use_embedded:
            page.insert_font(fontname='stage43original',fontbuffer=fontbytes)
        baseline=y0+size*1.0
        for row in rows:
            if group['kind']=='cell-candidate':
                w=font.text_length(row,fontsize=size)
                x=x0+max(0,(x1-x0-w)/2)
            else:x=x0
            for is_original, segment in font.runs(row):
                if segment:
                    page.insert_text((x,baseline),segment,fontsize=size,
                                     fontname='stage43original' if is_original else 'stage40unicode',
                                     color=((sample.get('color',0)>>16&255)/255,
                                            (sample.get('color',0)>>8&255)/255,
                                            (sample.get('color',0)&255)/255),overlay=True)
                    x+=font.text_length(segment,fontsize=size)
            baseline+=leading
        args.output.parent.mkdir(parents=True,exist_ok=True)
        doc.save(str(args.output),garbage=4,deflate=True)
    with pymupdf.open(args.output) as check:
        extracted=check[args.page-1].get_text(sort=True)
    def normalize(s):
        return ' '.join(unicodedata.normalize('NFKC',s).split())
    expected=normalize(' '.join(rows))
    actual=normalize(extracted)
    missing=[] if expected in actual else ['Exported text does not match expected text']
    report={'status':'saved' if not missing else 'saved_with_verification_warnings', 'output':str(args.output),
            'font':str(fpath),'source_font':requested,'embedded_original':use_embedded,'embedded_coverage':len(coverage),'font_size':size,'new_lines':len(rows),'overflows_container':overflow,
            'overlap_line_ids':overlaps,'editable_box':args.box,'missing_extracted_lines':missing,
            'source_file_unchanged':True,'warnings_acknowledged':bool(args.allow_overlap and (overflow or overlaps)),'note':'Uses reconstructed original subset glyphs when available, Unicode fallback otherwise; no document-wide reflow.'}
    print(json.dumps(report,ensure_ascii=True,indent=2))
    (args.output.with_suffix('.report.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if missing and not (args.allow_overlap and (overflow or overlaps)):
        raise SystemExit('Exported but text verification found discrepancies; see report')
    if missing and args.allow_overlap and (overflow or overlaps):
        print('WARNING: Overlapping objects prevent reliable extracted-text verification; inspect the rendered page.', flush=True)

if __name__=='__main__':main()
