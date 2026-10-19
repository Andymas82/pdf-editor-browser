"""Make a temporary preview raster with PDF text-show operations suppressed.
Original document and saved PDF are never modified by this helper.
"""
from io import BytesIO
import pymupdf
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, DecodedStreamObject

TEXT_SHOW = {b'Tj', b'TJ', b"'", b'"'}

def make_textless_png(pdf_bytes: bytes, page_index: int, scale: float=1.5) -> bytes:
    reader = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    page = writer.pages[page_index]
    stream = ContentStream(page.get_contents(), writer)
    # Replace glyph-display operators only; leave all vector, clipping,
    # images, and graphics-state operators in the content stream.
    stream.operations = [(args, op) for args, op in stream.operations if op not in TEXT_SHOW]
    ds = DecodedStreamObject()
    ds.set_data(stream.get_data())
    page.replace_contents(ds)
    buf = BytesIO()
    writer.write(buf)
    with pymupdf.open(stream=buf.getvalue(), filetype='pdf') as doc:
        return doc[page_index].get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False).tobytes('png')
