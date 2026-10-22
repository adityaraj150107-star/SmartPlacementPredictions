"""AI agents + the tools they use (LLM, web search, deep research, visualize).

Heavy third-party libraries (langchain, ddgs, google-genai) are imported lazily
inside the functions that need them, so a missing/unconfigured provider only
breaks the feature that needs it -- never the whole app.
"""
import os, re, json, socket, ipaddress
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin
import requests

# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
BASE_RULES = (
    'Be accurate, practical and concise. Use Markdown (short headings, bullet lists, code blocks) when it helps. '
    'If you are not sure about something, say so instead of inventing facts. '
    'Reply in the same language the user writes in (Hinglish in, Hinglish out).'
)

PROJECT_KNOWLEDGE = """
SMART PLACEMENT PREDICTIONS — PROJECT KNOWLEDGE

Purpose:
Smart Placement Predictions is an AI-assisted placement platform for students and administrators. It combines student profiles, machine-learning placement prediction, resume analysis and a single AI Agent workspace.

Main user flow:
1. Student registers with name, email and password.
2. Email OTP verification is completed.
3. Student logs in; the account and session are stored in the SQLite database.
4. Student can maintain an academic profile.
5. Student can run a placement prediction.
6. Student can upload a PDF resume and request AI-assisted review.
7. Student can ask the single Smart Placement AI Agent about the project, placement preparation, coding, studies, courses, reports or viva.

AI Agent tools exposed in the + menu:
- Add photos & files
- Add from library
- Create image
- Sketch
- Web search
- Deep research
- Visualize
- OpenAI Platform link
- GitHub link

ML:
- Current placement model: Random Forest.
- Current model is based on a campus placement dataset.
- Model inputs include 10th percentage, 12th percentage, degree performance/CGPA, aptitude/e-test percentage, work experience/internship, HSC stream, degree type and specialisation.
- Output includes placement probability, placement status and improvement tips.
- Course selection can include BCA, MCA, MBA, B.Tech/BE, BBA, B.Com, B.Sc, M.Sc and Other. The course field is profile/context information; the current Random Forest model uses the documented placement features above.

Resume:
- PDF resumes are parsed for readable text using pypdf.
- AI review can return a score, strengths, missing keywords/sections, improvements and interview preparation suggestions.

Technology stack:
- Python
- FastAPI backend
- Flask frontend/proxy
- HTML, CSS and JavaScript frontend
- SQLite database
- REST APIs
- Persistent sessions
- Email OTP verification and password reset
- Per-user private file library
- Ollama local LLM support and Gemini cloud support/fallback depending on configuration
- Web search and deep research tools
- Self-contained interactive visualization generation

Roles:
- Student: profile, prediction, resume, AI tools, files and placement preparation.
- Admin: user/platform management, statistics and project oversight.

Course coverage:
The platform is intended to be useful across BCA, MCA, MBA, B.Tech/BE, BBA, B.Com, B.Sc, M.Sc and other courses. Guidance should be adapted to the course the student mentions rather than assuming every student is from BCA.

Response behavior:
- If the user asks about this project, use this knowledge first.
- Explain in simple student-friendly English or Hinglish according to the user's language.
- Do not invent project features that are not listed here.
- Clearly distinguish current implemented features from ideas or future enhancements.
- For technical viva questions, explain what is actually implemented in this project.
"""

BASE_SYSTEM = 'You are the single Smart Placement AI Agent for the Smart Placement Predictions project. You are not one of several separate agents. You help students and administrators with this project, placement preparation, academics, coding, resumes, reports, viva and course-specific career guidance. '

AGENTS = {
    'smart_placement': {
        'name': 'Smart Placement AI', 'icon': '🤖', 'tagline': 'Project + placement + study assistant',
        'system': BASE_SYSTEM,
        'starters': [
            'Explain the Smart Placement Predictions project in simple Hinglish',
            'How does the Random Forest placement prediction work?',
            'Prepare important viva questions for this project',
            'I am an MCA/MBA student. Make a placement roadmap for me.'
        ],
    },
}



def public_agents():
    return [{'id': k, 'name': v['name'], 'icon': v['icon'], 'tagline': v['tagline'], 'starters': v['starters']} for k, v in AGENTS.items()]


def agent_system(agent_id):
    a = AGENTS.get(agent_id) or AGENTS['smart_placement']
    return a['system'] + '\n\n' + PROJECT_KNOWLEDGE + '\n\n' + BASE_RULES


# ---------------------------------------------------------------------------
# LLM provider abstraction (Ollama local  <->  Gemini cloud)
# ---------------------------------------------------------------------------
class LLMUnavailable(Exception):
    pass


HELP_TEXT = ('No AI model is available. Either start Ollama (run `ollama serve` and `ollama pull llama3.2`) '
             'or set GEMINI_API_KEY in your .env file.')


def _gemini_key():
    key = os.getenv('GEMINI_API_KEY', '').strip()
    return '' if key.lower().startswith('your_') else key


def _provider_order(has_images):
    choice = os.getenv('LLM_PROVIDER', 'auto').strip().lower()
    if choice == 'gemini':
        return ['gemini']
    if choice == 'ollama':
        return ['ollama']
    if has_images:
        return ['gemini']  # local text models can't see images
    return ['ollama', 'gemini'] if _gemini_key() else ['ollama']


def _ollama_chat(system, history, user_text):
    """Call Ollama's stable local HTTP API directly, avoiding LangChain version conflicts."""
    import json
    import urllib.request
    import urllib.error
    base = os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')
    messages = [{'role': 'system', 'content': system}]
    for item in history[-20:]:
        role = 'assistant' if item.get('role') == 'assistant' else 'user'
        content = item.get('content', '')
        if content:
            messages.append({'role': role, 'content': str(content)})
    messages.append({'role': 'user', 'content': user_text})
    payload = json.dumps({'model': os.getenv('OLLAMA_MODEL', 'llama3.2'), 'messages': messages, 'stream': False}).encode('utf-8')
    req = urllib.request.Request(base + '/api/chat', data=payload, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=float(os.getenv('OLLAMA_TIMEOUT', '120'))) as response:
            data = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')[:500]
        raise RuntimeError(f'Ollama HTTP {exc.code}: {detail}') from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f'Ollama is not reachable at {base}. Start Ollama and pull {os.getenv("OLLAMA_MODEL", "llama3.2")}. Details: {exc}') from exc
    return (data.get('message') or {}).get('content', '')


def _gemini_chat(system, history, user_text, images):
    key = _gemini_key()
    if not key:
        raise LLMUnavailable('GEMINI_API_KEY is not set in .env' + (' (needed to understand images).' if images else '.'))
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=key)
    contents = []
    for h in history:
        role = 'model' if h['role'] == 'assistant' else 'user'
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=h['content'])]))
    parts = [types.Part.from_text(text=user_text)]
    for mime, data in images:
        parts.append(types.Part.from_bytes(data=data, mime_type=mime))
    contents.append(types.Content(role='user', parts=parts))
    resp = client.models.generate_content(
        model=os.getenv('GEMINI_TEXT_MODEL', 'gemini-2.5-flash'),
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=system),
    )
    return resp.text or ''


def call_llm(system, history, user_text, images=None):
    images = images or []
    errors = []
    for provider in _provider_order(bool(images)):
        try:
            out = _ollama_chat(system, history, user_text) if provider == 'ollama' else _gemini_chat(system, history, user_text, images)
            if out and out.strip():
                return out.strip()
            errors.append(f'{provider}: empty response')
        except LLMUnavailable as e:
            errors.append(str(e))
        except Exception as e:
            errors.append(f'{provider}: {e}')
    raise LLMUnavailable(HELP_TEXT + ' Details: ' + ' | '.join(errors))


# ---------------------------------------------------------------------------
# Web search + safe page fetching
# ---------------------------------------------------------------------------
def web_search(query, n=6):
    from ddgs import DDGS
    out = []
    for r in DDGS().text(query, max_results=n):
        url = r.get('href') or r.get('url') or ''
        if url:
            out.append({'title': r.get('title', '') or url, 'url': url, 'snippet': r.get('body') or r.get('snippet') or ''})
    return out


def is_public_host(host):
    """SSRF guard: only fetch hosts whose every resolved IP is a public address."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            if not ipaddress.ip_address(info[4][0].split('%')[0]).is_global:
                return False
        except ValueError:
            return False
    return True


class _TextExtractor(HTMLParser):
    SKIP = {'script', 'style', 'noscript', 'svg', 'head', 'nav', 'footer', 'form'}

    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def html_to_text(html):
    p = _TextExtractor()
    try:
        p.feed(html)
    except Exception:
        pass
    return re.sub(r'\s+', ' ', ' '.join(p.parts)).strip()


def fetch_page_text(url, max_bytes=400_000, timeout=8):
    """Fetch a public web page and return its readable text ('' on any problem).
    Redirects are followed manually so every hop is re-checked against the SSRF guard."""
    for _ in range(4):
        p = urlparse(url)
        if p.scheme not in ('http', 'https') or not p.hostname or p.port not in (None, 80, 443) or not is_public_host(p.hostname):
            return ''
        try:
            r = requests.get(url, timeout=timeout, stream=True, allow_redirects=False,
                             headers={'User-Agent': 'SmartPlacementBot/1.0 (+student project)'})
        except requests.RequestException:
            return ''
        try:
            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get('Location')
                if not loc:
                    return ''
                url = urljoin(url, loc)
                continue
            ctype = r.headers.get('Content-Type', '')
            if r.status_code != 200 or not ('text/html' in ctype or 'text/plain' in ctype):
                return ''
            raw = r.raw.read(max_bytes, decode_content=True)
            text = raw.decode(r.encoding or 'utf-8', errors='ignore')
            return html_to_text(text) if 'html' in ctype else re.sub(r'\s+', ' ', text).strip()
        finally:
            r.close()
    return ''


# ---------------------------------------------------------------------------
# Search answer, deep research, visualize
# ---------------------------------------------------------------------------
def _sources_block(docs):
    return '\n\n'.join(f'[{i}] {d["title"]} ({d["url"]})\n{d["text"]}' for i, d in enumerate(docs, 1))


def search_answer(system, history, question, images=None):
    results = web_search(question, 6)
    if not results:
        raise LLMUnavailable('No web results found. Try rephrasing your search.')
    docs = [{'title': r['title'], 'url': r['url'], 'text': r['snippet']} for r in results]
    prompt = (f'Question: {question}\n\nWeb results:\n{_sources_block(docs)}\n\n'
              'Answer using ONLY these results. Cite sources inline like [1], [2]. '
              'If the results do not answer the question, say so plainly.')
    answer = call_llm(system, history, prompt, images)
    return {'answer': answer, 'sources': [{'title': r['title'], 'url': r['url']} for r in results]}


def plan_queries(question, system):
    try:
        raw = call_llm(system, [], 'Break this research question into 3 or 4 short, different web search queries. '
                       'Return ONLY a JSON array of strings, nothing else.\n\nQuestion: ' + question)
        m = re.search(r'\[.*?\]', raw, re.S)
        qs = [str(q).strip() for q in json.loads(m.group(0))] if m else []
        qs = [q for q in qs if q][:4]
        if qs:
            return qs
    except Exception:
        pass
    return [question]


def deep_research(system, question, images=None):
    queries = plan_queries(question, system)
    seen, hits = set(), []
    for q in queries:
        try:
            for r in web_search(q, 5):
                if r['url'] not in seen:
                    seen.add(r['url']); hits.append(r)
        except Exception:
            continue
    hits = hits[:8]
    if not hits:
        raise LLMUnavailable('Web search returned nothing. Check your internet connection and try again.')

    def grab(r):
        return fetch_page_text(r['url']) or r['snippet']

    with ThreadPoolExecutor(max_workers=4) as pool:
        texts = list(pool.map(grab, hits[:6]))
    docs = [{'title': r['title'], 'url': r['url'], 'text': t[:3500]} for r, t in zip(hits[:6], texts)]
    prompt = (f'Research question: {question}\n\nSources:\n{_sources_block(docs)}\n\n'
              'Write a well-structured research report in Markdown: a short summary first, then sections with key findings, '
              'and a brief conclusion. Cite sources inline like [1], [2]. Use only facts found in the sources; '
              'mention disagreements or gaps honestly.')
    answer = call_llm(system, [], prompt, images)
    return {'answer': answer, 'queries': queries, 'sources': [{'title': d['title'], 'url': d['url']} for d in docs]}


VIZ_SYSTEM = (
    'You create visualizations as ONE complete, self-contained HTML document. Rules: inline CSS and JavaScript only; '
    'NO external files, libraries, fonts, images or network requests; draw charts with inline SVG or <canvas>; '
    'dark background (#0b1422) with light text; responsive (works on a 360px phone and a wide desktop); '
    'make it interactive when useful (hover tooltips, sliders, buttons). '
    'Return ONLY the HTML document, no explanation, no markdown fences.'
)
MAX_VIZ_BYTES = 250_000
VIZ_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
           "img-src data:; font-src data:; connect-src 'none'; form-action 'none'")


def extract_html(raw):
    m = re.search(r'```(?:html)?\s*(<!doctype.*?|<html.*?)```', raw, re.S | re.I)
    text = m.group(1) if m else raw
    start = re.search(r'<!doctype html|<html', text, re.I)
    if not start:
        raise ValueError('The model did not return a valid HTML visual.')
    return text[start.start():].strip()


def harden_html(html):
    """Inject a strict Content-Security-Policy so a generated page can run its own
    scripts but can never load anything external or call out to the network."""
    if len(html.encode('utf-8')) > MAX_VIZ_BYTES:
        raise ValueError('The generated visual is too large. Try a simpler request.')
    meta = f'<meta http-equiv="Content-Security-Policy" content="{VIZ_CSP}"><meta name="viewport" content="width=device-width,initial-scale=1">'
    if re.search(r'<head[^>]*>', html, re.I):
        return re.sub(r'(<head[^>]*>)', r'\1' + meta, html, count=1, flags=re.I)
    return re.sub(r'(<html[^>]*>)', r'\1<head>' + meta + '</head>', html, count=1, flags=re.I) if re.search(r'<html[^>]*>', html, re.I) else '<head>' + meta + '</head>' + html


def visualize(question, images=None):
    raw = call_llm(VIZ_SYSTEM, [], 'Create this visualization:\n' + question, images)
    return harden_html(extract_html(raw))
