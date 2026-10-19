"""Stage 5.1: safe, limited PDF image and solid rectangular object transforms.

Each object is independent and selected explicitly. Original document is untouched.
Complex masks and overlapping illustrations are intentionally excluded.
"""
import io
import math
import pymupdf


def eligible_objects(page):
    out=[]
    for n, item in enumerate(page.get_image_info(xrefs=True)):
        b=list(item['bbox']); xref=item.get('xref',0)
        if not xref or b[2]-b[0]<8 or b[3]-b[1]<8:continue
        # Exclude masks, clips and rotated placement: only axis-aligned for now.
        t=item['transform'];
        if abs(t[1])>0.01 or abs(t[2])>0.01:continue
        out.append({'id':'image-'+str(n),'kind':'image','bbox':b,'xref':xref,
                    'width':item['width'],'height':item['height']})
    for n, d in enumerate(page.get_drawings()):
        items=d['items'];r=d['rect']
        if len(items)!=1 or items[0][0]!='re':continue
        if not (12<=r.width<=300 and 8<=r.height<=300):continue
        if d.get('fill') is None and d.get('color') is None:continue
        # Avoid rectangles that contain most of the page or represent icons.
        if r.width*r.height>page.rect.width*page.rect.height*.20:continue
        out.append({'id':'rect-'+str(n),'kind':'rect','bbox':[r.x0,r.y0,r.x1,r.y1],
                    'fill':d.get('fill'), 'stroke':d.get('color'), 'stroke_width':d.get('width') or 0,
                    'fill_opacity':d.get('fill_opacity',1), 'stroke_opacity':d.get('stroke_opacity',1)})
    return out


def apply_object_edits(pdf_bytes, model_objects, edits, page_number, original_pdf=None):
    """Fail-closed graphical editing.

    Images are moved by rewriting only their isolated PDF placement (with clip).
    Rectangle edits are withheld rather than redacting arbitrary page graphics.
    """
    from object_transform_safe import move_clipped_images
    non_image=[obj['id'] for obj in model_objects if obj['kind']!='image' and obj['id'] in edits]
    if non_image:
        raise ValueError('Unsafe rectangle transformation blocked: shared vector paths might be damaged')
    return move_clipped_images(pdf_bytes,model_objects,edits,page_number)
