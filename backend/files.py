"""Upload validation + text extraction. File type is decided by sniffing the
actual bytes, never by trusting the browser-supplied filename/mime."""
import io, re, zipfile
from pathlib import PurePath

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_EXCERPT_CHARS = 20000

TEXT_EXTENSIONS = {
    '.txt', '.md', '.csv', '.json', '.py', '.js', '.ts', '.java', '.c', '.cpp', '.h', '.cs',
    '.html', '.css', '.sql', '.xml', '.yml', '.yaml', '.log', '.php', '.go', '.rb', '.kt',
}


def safe_filename(name):
    base = PurePath(str(name or 'file')).name
    base = re.sub(r'[^A-Za-z0-9._ -]', '_', base).strip(' .') or 'file'
    return base[:120]


def sniff(data, filename):
    """Return (kind, mime, ext) or raise ValueError for unsupported files."""
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image', 'image/png', '.png'
    if data[:3] == b'\xff\xd8\xff':
        return 'image', 'image/jpeg', '.jpg'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'image', 'image/gif', '.gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image', 'image/webp', '.webp'
    if data[:5] == b'%PDF-':
        return 'pdf', 'application/pdf', '.pdf'
    ext = PurePath(str(filename or '')).suffix.lower()
    if data[:4] == b'PK\x03\x04' and ext == '.docx':
        return 'docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.docx'
    if ext in TEXT_EXTENSIONS and b'\x00' not in data[:4096]:
        return 'text', 'text/plain', ext
    raise ValueError('Unsupported file type. Allowed: images (PNG/JPG/WEBP/GIF), PDF, DOCX, and plain-text/code files.')


def extract_text(kind, data):
    try:
        if kind == 'text':
            return data.decode('utf-8', errors='replace')[:MAX_EXCERPT_CHARS]
        if kind == 'pdf':
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            return '\n'.join((p.extract_text() or '') for p in reader.pages)[:MAX_EXCERPT_CHARS]
        if kind == 'docx':
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if z.getinfo('word/document.xml').file_size > 20 * 1024 * 1024:
                    return ''
                xml = z.read('word/document.xml').decode('utf-8', errors='replace')
            xml = re.sub(r'</w:p>', '\n', xml)
            text = re.sub(r'<[^>]+>', '', xml)
            return re.sub(r'&amp;', '&', re.sub(r'&lt;', '<', re.sub(r'&gt;', '>', text)))[:MAX_EXCERPT_CHARS]
    except Exception:
        return ''
    return ''
