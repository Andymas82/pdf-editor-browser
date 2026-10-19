"""Multi-page adapter. The verified v0.5.2 single-page engine is unchanged."""
import base64, json
from pathlib import Path
import pymupdf
import engine_single as single
ORIGINAL=Path('/tmp/multipage_original.pdf')
PAGE_DATA={}
CURRENT=0

def open_pages():
    global PAGE_DATA, CURRENT
    PAGE_DATA={}
    CURRENT=0
    with pymupdf.open(ORIGINAL) as doc:
        if doc.is_encrypted: raise ValueError('Encrypted PDFs are not supported')
        if len(doc)>100: raise ValueError('Maximum 100 pages')
        return len(doc)

def open_page(index):
    global CURRENT
    index=int(index)
    with pymupdf.open(ORIGINAL) as doc:
        if not 0<=index<len(doc): raise ValueError('Page out of range')
        temp=pymupdf.open();temp.insert_pdf(doc,from_page=index,to_page=index)
        # Collapsing fragmented streams is a preparation step required by the
        # verified single-stream vector/image mover; the painter is unchanged.
        pg=temp[0]
        if len(pg.get_contents())>1:pg.clean_contents()
        single.SOURCE.write_bytes(temp.tobytes(garbage=3,deflate=True))
    CURRENT=index
    return single.load_document()

def render_page(payload):
    result=json.loads(single.render_document(payload))
    PAGE_DATA[CURRENT]=base64.b64decode(result['pdf'])
    return json.dumps({'png':result['png'],'pdf':result['pdf'],'warnings':result.get('warnings',[])})

def combine():
    with pymupdf.open(ORIGINAL) as source:
        result=pymupdf.open()
        for i in range(len(source)):
            if i in PAGE_DATA:
                with pymupdf.open(stream=PAGE_DATA[i],filetype='pdf') as edited:
                    if len(edited)!=1:raise ValueError('Invalid modified page')
                    result.insert_pdf(edited)
            else:
                result.insert_pdf(source,from_page=i,to_page=i)
        out=result.tobytes(garbage=3,deflate=True)
        result.close()
        return base64.b64encode(out).decode('ascii')
