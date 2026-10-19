"""Conservative line move: delete only exact paint operation; repaint above fills.

No redaction. Preserves all other PDF objects. Rejects ambiguously indexed drawings.
"""
import io
import pymupdf
from pypdf import PdfReader
from pypdf.generic import ContentStream

PAINTS={b'S',b's',b'f',b'F',b'f*',b'B',b'B*',b'b',b'b*'}

def move_vectors(pdf_bytes, original_graphics, edits, page_index):
    selected={int(k):v for k,v in edits.items() if abs(v['dx'])+abs(v['dy'])>0.001}
    if not selected:return pdf_bytes,[]
    with pymupdf.open(stream=pdf_bytes,filetype='pdf') as doc:
        page=doc[page_index]
        xrefs=page.get_contents()
        if len(xrefs)!=1:raise ValueError('Unsupported page content: multiple streams')
        drawings=page.get_drawings()
        reader=PdfReader(io.BytesIO(pdf_bytes))
        cs=ContentStream(reader.pages[page_index].get_contents(),reader)
        paints=[i for i,(_,op) in enumerate(cs.operations) if op in PAINTS]
        if len(paints)!=len(drawings):raise ValueError('Cannot match PDF vector commands safely')
        candidates={int(g['id']):g for g in original_graphics}
        # Detect strokes painted on the boundary of their own clip path.
        # In this CV the PDF uses `W n` around a 2 pt stroke, hiding its
        # outer half. Repainting it without the clip at 2 pt doubles the
        # *visible* width. Only compensate for this bounded border case.
        clipped_border=set()
        for idx in selected:
            operation_index=paints[idx]
            k=operation_index
            while k>0 and cs.operations[k][1]!=b'q':
                k-=1
            local_ops=[op for _,op in cs.operations[k:operation_index]]
            d=drawings[idx]
            if (b'W' in local_ops or b'W*' in local_ops) and d['type']=='s' and len(d['items'])>=2 and all(it[0]=='l' for it in d['items']):
                clipped_border.add(idx)
        for index in selected:
            if index not in candidates or index>=len(drawings):raise ValueError('Unknown graphic object')
            d=drawings[index]; g=candidates[index]
            if any(abs(a-b)>0.75 for a,b in zip(d['rect'],g['bbox'])):raise ValueError('Object has moved since initial detection')
            if d.get('layer'):raise ValueError('Optional-content object not supported')
            if g['kind']=='line':
                if d['type']!='s' or d.get('color') is None or not d['items'] or any(item[0]!='l' for item in d['items']):raise ValueError('Only independent single-segment lines supported')
            elif g['kind']=='icon':
                if d['type'] not in ('f','fs'):raise ValueError('Icon drawing type not supported')
            else:raise ValueError('Unsupported graphic kind')
        # Disable the exact paint operation, without removing its path or other paints.
        for idx in selected:cs.operations[paints[idx]]=([],b'n')
        doc.update_stream(xrefs[0],cs.get_data())
        # Repaint only selected objects as an overlay. This prevents background fills
        # later in the original stream from hiding relocated vectors.
        shape=page.new_shape()
        for idx,delta in selected.items():
            d=drawings[idx]; dx=float(delta['dx']);dy=float(delta['dy'])
            def pt(v):return pymupdf.Point(v.x+dx,v.y+dy)
            items=d['items']
            # Rebuild consecutive straight segments as ONE stroked polyline.
            # PDF original corners have a single join; drawing each segment
            # separately adds line caps and makes borders appear heavier.
            if items and all(item[0]=='l' for item in items):
                chain=[items[0][1],items[0][2]]
                for item in items[1:]:
                    if abs(item[1].x-chain[-1].x)>.005 or abs(item[1].y-chain[-1].y)>.005:
                        raise ValueError('Disconnected path cannot be safely moved')
                    chain.append(item[2])
                shape.draw_polyline([pt(q) for q in chain])
            else:
                for item in items:
                    t=item[0]
                    if t=='c':shape.draw_bezier(pt(item[1]),pt(item[2]),pt(item[3]),pt(item[4]))
                    elif t=='re':shape.draw_rect(pymupdf.Rect(item[1])+(dx,dy,dx,dy))
                    elif t=='qu':
                        q=item[1];shape.draw_quad(pymupdf.Quad(pt(q.ul),pt(q.ur),pt(q.ll),pt(q.lr)))
                    elif t=='l':shape.draw_line(pt(item[1]),pt(item[2]))
                    else:raise ValueError('Unsupported path instruction')
            cap=d.get('lineCap',0)
            if isinstance(cap,(tuple,list)):cap=cap[0]
            shape.finish(color=d.get('color'),fill=d.get('fill'),width=float(d.get('width') or 1) * (0.5 if idx in clipped_border else 1.0),
                         closePath=bool(d.get('closePath')),lineCap=int(cap or 0),
                         lineJoin=int(d.get('lineJoin') or 0),dashes=d.get('dashes'),
                         stroke_opacity=float(d.get('stroke_opacity') if d.get('stroke_opacity') is not None else 1),
                         fill_opacity=float(d.get('fill_opacity') if d.get('fill_opacity') is not None else 1),
                         even_odd=bool(d.get('even_odd',False)))
        shape.commit(overlay=True)
        out=doc.tobytes(garbage=4,deflate=True)
    with pymupdf.open(stream=out,filetype='pdf') as verified:
        pg=verified[page_index]
        new=pg.get_drawings()
        old=drawings
        if len(new)!=len(old):raise ValueError('Vector count changed during edit')
        # Removing paint operations shifts drawing indices; replacements are appended.
        old_indices=sorted(selected)
        for offset,idx in enumerate(old_indices):
            delta=selected[idx];a=old[idx]['rect'];b=new[len(old)-len(selected)+offset]['rect']
            if abs(b.x0-a.x0-float(delta['dx']))>.5 or abs(b.y0-a.y0-float(delta['dy']))>.5:raise ValueError('Moved object location failed verification')
            if old[idx]['type']=='s':
                expected_width=float(old[idx]['width'])*(0.5 if idx in clipped_border else 1.0)
                if abs(new[len(old)-len(selected)+offset]['width']-expected_width)>.02:raise ValueError('Visible stroke width failed verification')
    return out, []
