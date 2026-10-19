"""Move a clipped PDF image placement without redacting surrounding artwork.

Limited to PDFs where each image is wrapped in a self-contained q/Q graphics
state. Fail closed if ownership of an image placement is ambiguous.
"""
import io
import pymupdf
from pypdf import PdfReader
from pypdf.generic import ContentStream, FloatObject


def _move_clipped_images_raw(pdf_bytes, original_objects, edits, page_number):
    images = [(obj, val) for obj in original_objects for key, val in edits.items()
              if obj['id'] == key and obj['kind'] == 'image'
              and (abs(val['dx']) + abs(val['dy']) > 0.001 or
                   abs(val['sx']-1) + abs(val['sy']-1) > 0.001)]
    if not images:
        return pdf_bytes, []
    with pymupdf.open(stream=pdf_bytes, filetype='pdf') as doc:
        page=doc[page_number]
        # Only support one content stream: original page placements remain intact.
        xrefs=page.get_contents()
        if len(xrefs)!=1:
            raise ValueError('Image edit safely blocked: multiple content streams')
        xref=xrefs[0]
        raw=doc.xref_stream(xref)
        reader=PdfReader(io.BytesIO(pdf_bytes))
        ops=ContentStream(reader.pages[page_number].get_contents(),reader).operations
        positions=[]; stack=[]; matches={}
        for i,(args,op) in enumerate(ops):
            if op==b'q':stack.append(i)
            elif op==b'Do':
                positions.append((i,list(stack),str(args[0])))
            elif op==b'Q':
                if not stack:raise ValueError('Unbalanced PDF graphics stack')
                start=stack.pop();matches[start]=i
        if stack:raise ValueError('Unbalanced PDF graphics stack')
        page_info=page.get_image_info(xrefs=True)
        # Actual image placements are indexed by their paint order. Restrict to
        # a single image invocation per document to avoid ambiguous XObjects.
        # Image names may be /Im0, /Image11, or arbitrary resource names.
        # Resolve against the page /XObject resource dictionary, not a prefix.
        resources=reader.pages[page_number].get('/Resources',{}).get_object()
        xobjects=resources.get('/XObject',{}).get_object()
        image_names={str(name) for name,ref in xobjects.items()
                     if ref.get_object().get('/Subtype')=='/Image'}
        image_do=[(i,starts,name) for i,starts,name in positions if name in image_names]
        if len(image_do)!=len(page_info):
            raise ValueError('Image edit safely blocked: image placements are ambiguous')
        edits_by_op={}
        for obj,v in images:
            original_index=int(obj['id'].split('-')[-1]);
            if original_index>=len(image_do):raise ValueError('Image not found')
            i,parents,name=image_do[original_index]
            if not parents:raise ValueError('Image edit safely blocked: isolated graphics group unavailable')
            # Choose the smallest self-contained q/Q group that OWNS the clip.
            # A clipped image may have q [path W n] q cm /Im Do Q Q:
            # moving only the innermost q moves pixels, but leaves the circular
            # clipping path stationary (visible photo gets sliced).
            # A plain q cm /Image Do Q has no clip and keeps its inner group.
            safe=[]
            for candidate in reversed(parents):
                ending=matches[candidate]
                section=ops[candidate:ending+1]
                if any(code in (b'BT',b'Tj',b'TJ',b"'",b'"') for _,code in section):
                    continue
                if sum(1 for _,code in section if code==b'Do')!=1:
                    continue
                safe.append(candidate)
            if not safe:
                raise ValueError('Image edit safely blocked: no isolated image group')
            # Outermost local W/W* is the clip owner. Picking the outermost
            # clip-owning group prevents splitting nested clipping paths.
            clipped=[p for p in safe if any(code in (b'W',b'W*')
                      for _,code in ops[p:matches[p]+1])]
            if clipped:
                start=clipped[-1]
            else:
                start=safe[0]
            end=matches[start]
            if any(op in (b'BT',b'Tj',b'TJ') for _,op in ops[start:end+1]):
                raise ValueError('Image edit safely blocked: text shares image group')
            if sum(1 for _,op in ops[start:end+1] if op==b'Do')!=1:
                raise ValueError('Image edit safely blocked: compound image group')
            b=obj['bbox'];w=b[2]-b[0];h=b[3]-b[1]
            # Coordinate transformation in PDF y-up space. Scale from top-left.
            sx=float(v['sx']);sy=float(v['sy']);dx=float(v['dx']);dy=float(v['dy'])
            tx=(1-sx)*b[0]+dx
            ty=(1-sy)*(page.rect.height-b[1])+(-dy)
            edits_by_op[start]=(sx,0,0,sy,tx,ty)
        for start,m in sorted(edits_by_op.items(),reverse=True):
            end=matches[start]
            # Insert a new graphics-state wrapper around the entire clipped image
            # group, leaving the old content and original vector shapes untouched.
            ops.insert(end+1,([],b'Q'))
            ops.insert(start,([],b'q'))
            ops.insert(start+1,([FloatObject(x) for x in m],b'cm'))
        cs=ContentStream(None,reader)
        cs.operations=ops
        doc.update_stream(xref,cs.get_data())
        result=doc.tobytes(garbage=4,deflate=True)
    return result, []


def move_clipped_images(pdf_bytes, original_objects, edits, page_number):
    """Correct PDF-local image translations using measured rendered-page coordinates.

    An outer content-stream CTM may reverse Y or scale translation commands.
    Calibrate each requested pure translation on an isolated copy, then verify
    the final visual bounding box. Original PDF bytes remain untouched.
    """
    import math

    targets = [obj for obj in original_objects if obj.get('kind') == 'image'
               and obj['id'] in edits and
               (abs(edits[obj['id']]['dx']) + abs(edits[obj['id']]['dy'])) > 0.001]
    if not targets:
        return _move_clipped_images_raw(pdf_bytes, original_objects, edits, page_number)

    # Preserve the existing resize code. Calibration below is limited to
    # translations, where a bounding-box displacement has a clear meaning.
    if any(abs(edits[o['id']]['sx'] - 1) > 0.001 or
           abs(edits[o['id']]['sy'] - 1) > 0.001 for o in targets):
        return _move_clipped_images_raw(pdf_bytes, original_objects, edits, page_number)

    corrected = {key: dict(val) for key, val in edits.items()}
    with pymupdf.open(stream=pdf_bytes, filetype='pdf') as doc:
        before = doc[page_number].get_image_info(xrefs=True)

    def placement(blob, index):
        with pymupdf.open(stream=blob, filetype='pdf') as d:
            placements = d[page_number].get_image_info(xrefs=True)
            if index >= len(placements):
                raise ValueError('Image transformation changed image placements')
            return placements[index]['bbox']

    for obj in targets:
        oid = obj['id']
        index = int(oid.split('-')[-1])
        if index >= len(before):
            raise ValueError('Image index out of range')
        old = before[index]['bbox']
        columns = []
        for dx,dy in ((20.0,0.0),(0.0,20.0)):
            probe = {oid: {'dx':dx,'dy':dy,'sx':1.0,'sy':1.0}}
            result, _ = _move_clipped_images_raw(pdf_bytes, original_objects, probe, page_number)
            bb = placement(result,index)
            columns.append(((bb[0]-old[0])/20.0,(bb[1]-old[1])/20.0))
        a,c = columns[0]
        b,d = columns[1]
        determinant = a*d-b*c
        if not math.isfinite(determinant) or abs(determinant) < 1e-4:
            raise ValueError('Image movement not safely invertible in this PDF')
        requested = edits[oid]
        x,y = float(requested['dx']), float(requested['dy'])
        corrected[oid]['dx'] = (d*x-b*y)/determinant
        corrected[oid]['dy'] = (-c*x+a*y)/determinant

    result,warnings = _move_clipped_images_raw(pdf_bytes, original_objects, corrected, page_number)
    for obj in targets:
        oid=obj['id']; index=int(oid.split('-')[-1]); old=before[index]['bbox']
        bb=placement(result,index)
        want_x=old[0]+float(edits[oid]['dx'])
        want_y=old[1]+float(edits[oid]['dy'])
        if abs(bb[0]-want_x) > 0.5 or abs(bb[1]-want_y) > 0.5:
            raise ValueError('Image movement verification failed; PDF was not exported')
    return result,warnings
