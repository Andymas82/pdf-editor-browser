"""Local-only bridge between Pyodide and the final Stage 5.5.8 text engine."""
import base64, copy, json, math, tempfile
from vector_path_move import move_vectors
from object_transform_safe import move_clipped_images
from pathlib import Path
import pymupdf
from stage487 import make_model, block_edits, build_pdf
from detect_blocks import page_groups
from textless_preview import make_textless_png

SOURCE = Path('/tmp/editor_source.pdf')
MODEL = None

def image_objects(page):
    """Detect unique displayed, non-rotated PDF image occurrences."""
    result = []
    for i, info in enumerate(page.get_image_info(xrefs=True)):
        xref = int(info.get('xref') or 0)
        box = pymupdf.Rect(info['bbox'])
        transform = info.get('transform')
        # Rotated / mirrored images require a different PDF transform pipeline.
        if not xref or box.is_empty or box.width < 4 or box.height < 4:
            continue
        if transform and (abs(transform[1]) > .0001 or abs(transform[2]) > .0001 or transform[0] <= 0 or transform[3] <= 0):
            continue
        result.append({'id': 'img'+str(i), 'kind':'image', 'xref':xref, 'bbox': list(box)})
    return result

def load_document():
    global MODEL
    with pymupdf.open(SOURCE) as doc:
        if len(doc) != 1:
            raise ValueError('v0.1 supports one-page PDFs only; no edits were made')
        page=doc[0]
        MODEL=make_model(page,'auto')
        MODEL['objects']=image_objects(page)
        # Keep stage487's native vector detection for lines and small icons.
        MODEL['web_font_names']=[]
        MODEL['detected_mode']='auto'
        fonts={}
        for entry in page.get_fonts(full=True):
            try:
                family, ext, _, binary=doc.extract_font(entry[0])
                name=entry[3].split('+',1)[-1]
                if ext.lower() in ('ttf','otf') and binary and len(binary)<3_000_000:
                    fonts[name]='data:font/'+ext.lower()+';base64,'+base64.b64encode(binary).decode('ascii')
            except Exception:
                pass
        MODEL['web_font_names']=list(fonts)
        original=page.get_pixmap(matrix=pymupdf.Matrix(1.5,1.5),alpha=False).tobytes('png')
    textless=make_textless_png(SOURCE.read_bytes(),0)
    return json.dumps({'model':MODEL,'original':base64.b64encode(original).decode('ascii'), 'textless':base64.b64encode(textless).decode('ascii'),'fonts':fonts})

def render_document(payload):
    data=json.loads(payload)
    blocks=data.get('blocks') or {}; frames=data.get('frames') or {}
    if not isinstance(blocks,dict) or len(blocks)>100 or any(not isinstance(x,str) or len(x)>25_000 for x in blocks.values()):
        raise ValueError('Invalid edits')
    names={block['name'] for block in MODEL['blocks']}
    if set(blocks)-names or set(frames)-names: raise ValueError('Invalid block IDs')
    if any(not isinstance(w,(int,float)) or not math.isfinite(w) or not 40<=w<=MODEL['width'] for w in frames.values()):
        raise ValueError('Invalid text frame')
    graphics=data.get('graphics') or {}
    objects=data.get('objects') or {}
    graphic_ids={g['id'] for g in MODEL['graphics']}
    image_ids={o['id'] for o in MODEL['objects']}
    if not isinstance(graphics,dict) or len(graphics)>100 or set(graphics)-graphic_ids:
        raise ValueError('Invalid graphic IDs')
    if not isinstance(objects,dict) or len(objects)>100 or set(objects)-image_ids:
        raise ValueError('Invalid image IDs')
    for delta in graphics.values():
        if not isinstance(delta,dict) or any(not isinstance(delta.get(k), (int,float)) or not math.isfinite(delta[k]) or abs(delta[k])>2000 for k in ('dx','dy')):
            raise ValueError('Invalid graphic move')
    for delta in objects.values():
        if not isinstance(delta,dict) or any(not isinstance(delta.get(k), (int,float)) or not math.isfinite(delta[k]) for k in ('dx','dy','sx','sy')):
            raise ValueError('Invalid image move')
        if abs(delta['dx'])>2000 or abs(delta['dy'])>2000 or not .1<=delta['sx']<=8 or not .1<=delta['sy']<=8:
            raise ValueError('Image move exceeds limits')
    mod=copy.deepcopy(MODEL)
    for block in mod['blocks']:
        if block['name'] in frames:
            block['bbox'][2]=min(mod['width']-3,block['bbox'][0]+frames[block['name']])
    edits, shifts=block_edits(mod,blocks,data.get('line_sources'))
    # Stage 5.1 pipeline: mutate only original isolated PDF paint commands.
    # NEVER use stage487's area-based graphics / image redaction.
    working=SOURCE.read_bytes()
    warnings=[]
    if objects:
        adapted=[]
        for item in MODEL['objects']:
            adapted.append({**item,'id':'image-'+item['id'][3:]})
        edits2={'image-'+key[3:]:delta for key,delta in objects.items()}
        working,w=move_clipped_images(working,adapted,edits2,0)
        warnings+=w
    if graphics:
        working,w=move_vectors(working,MODEL['graphics'],graphics,0)
        warnings+=w
    # Staged PDF is already modified, so text edits only from here onward.
    # Text model coordinates remain anchored to the original page.
    with tempfile.TemporaryDirectory(prefix='pdf_web_safe_') as folder:
        staged=Path(folder)/'graphics_then_text.pdf'
        staged.write_bytes(working)
        pdf,png,w=build_pdf(staged,0,mod,edits,None,shifts,{}, {})
        warnings+=w
    # Preview always comes from the actual exported PDF, not from a stale layer.
    with pymupdf.open(stream=pdf,filetype='pdf') as result:
        png=result[0].get_pixmap(matrix=pymupdf.Matrix(1.5,1.5),alpha=False).tobytes('png')
    return json.dumps({'pdf':base64.b64encode(pdf).decode('ascii'),'png':base64.b64encode(png).decode('ascii'),'warnings':warnings})
