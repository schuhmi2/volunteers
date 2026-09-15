"""
Manifest of bundled Unicode fonts used by :mod:`volunteers.labels` to render
volunteer names and spoken languages in their native script on printed
labels.

None of these font files are committed to the repository (see
``.gitignore``): they are downloaded on demand -- either explicitly via
``python manage.py download_fonts`` or lazily the first time a label PDF is
generated -- and verified against a pinned SHA-256 checksum before use.

All fonts are open source (SIL Open Font License 1.1, or the Bitstream Vera
License for DejaVu Sans) and their license terms are documented in
THIRD_PARTY_LICENSES.md at the repository root. The download URLs are
pinned to a specific upstream commit/release so the exact bytes -- and
therefore the checksum -- never change from under us.
"""
import hashlib
import io
import os
import urllib.request
import zipfile

FONTS_DIR = os.path.join(os.path.dirname(__file__), 'static', 'fonts')

_GOOGLE_FONTS_COMMIT = '4c74c4f5b5a0e1a9d72ac772304dc2bc8f2d99a9'
_GOOGLE_FONTS_OFL_BASE = (
    f'https://raw.githubusercontent.com/google/fonts/{_GOOGLE_FONTS_COMMIT}/ofl'
)

# key -> {
#   filename: name of the extracted font file inside FONTS_DIR
#   url: where to download it from
#   sha256: expected checksum of the extracted font file
#   archive_member: for zip-packaged fonts (DejaVu), the path inside the zip
#   ofl_slug: google/fonts "ofl/<slug>" directory name, used to also fetch
#       that font's OFL.txt license/attribution file
#   scripts: human-readable description of glyph coverage, for docs/logging
# }
FONT_MANIFEST = {
    'dejavu_sans': {
        'filename': 'DejaVuSans.ttf',
        'url': 'https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip',
        'archive_member': 'dejavu-fonts-ttf-2.37/ttf/DejaVuSans.ttf',
        'license_archive_member': 'dejavu-fonts-ttf-2.37/LICENSE',
        'license_filename': 'DejaVuSans-LICENSE.txt',
        'sha256': '7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954',
        'license': 'Bitstream Vera License (fetched on demand as DejaVuSans-LICENSE.txt)',
        'scripts': 'Latin, Cyrillic, Greek, Armenian, Georgian, Hebrew, Arabic (isolated forms)',
    },
    'cjk_jp': {
        'filename': 'NotoSansJP.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notosansjp/NotoSansJP%5Bwght%5D.ttf',
        'sha256': 'c2f3b4d463500a2ddcd3849cded1fceeb9fd6d1c32e6cbecd568453ba50fc68f',
        'ofl_slug': 'notosansjp',
        'scripts': 'Japanese (Kanji, Hiragana, Katakana)',
    },
    'cjk_kr': {
        'filename': 'NotoSansKR.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notosanskr/NotoSansKR%5Bwght%5D.ttf',
        'sha256': '194018e6b2b293a7964f037b25c0249ce1418bc9ab3c971060a03aa57861e252',
        'ofl_slug': 'notosanskr',
        'scripts': 'Korean (Hangul, Hanja)',
    },
    'cjk_sc': {
        'filename': 'NotoSansSC.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notosanssc/NotoSansSC%5Bwght%5D.ttf',
        'sha256': 'a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da',
        'ofl_slug': 'notosanssc',
        'scripts': 'Chinese (Simplified)',
    },
    'cjk_tc': {
        'filename': 'NotoSansTC.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notosanstc/NotoSansTC%5Bwght%5D.ttf',
        'sha256': '864727d210d54f2537bbe23b3a839436c3992af72de9322af5270897246bd44f',
        'ofl_slug': 'notosanstc',
        'scripts': 'Chinese (Traditional)',
    },
    'devanagari': {
        'filename': 'NotoSansDevanagari.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notosansdevanagari/NotoSansDevanagari%5Bwdth%2Cwght%5D.ttf',
        'sha256': '14ec4af41f27482216d1c2229f417ff9b1425e1babb014e57d1d40d03229853e',
        'ofl_slug': 'notosansdevanagari',
        'scripts': 'Devanagari (Hindi, Marathi, Sanskrit, Nepali, ...)',
    },
    'bengali': {
        'filename': 'NotoSansBengali.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notosansbengali/NotoSansBengali%5Bwdth%2Cwght%5D.ttf',
        'sha256': 'dcd42978094e584a849c84a51450eeac40c8826057d566ea6d4b9627a403a05a',
        'ofl_slug': 'notosansbengali',
        'scripts': 'Bengali/Assamese',
    },
    'gujarati': {
        'filename': 'NotoSansGujarati.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notosansgujarati/NotoSansGujarati%5Bwdth%2Cwght%5D.ttf',
        'sha256': '9901d8552f1dd5d2c50dbd4caa6f6e174e74e8264f06594ab259ae6e7b1ac428',
        'ofl_slug': 'notosansgujarati',
        'scripts': 'Gujarati',
    },
    'gurmukhi': {
        'filename': 'NotoSansGurmukhi.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notosansgurmukhi/NotoSansGurmukhi%5Bwdth%2Cwght%5D.ttf',
        'sha256': '1e6f728fa620e566f842d81e220265813faa12771214765d289c98e035adc5f2',
        'ofl_slug': 'notosansgurmukhi',
        'scripts': 'Gurmukhi (Punjabi)',
    },
    'kannada': {
        'filename': 'NotoSansKannada.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notosanskannada/NotoSansKannada%5Bwdth%2Cwght%5D.ttf',
        'sha256': 'cca4f3b3a8cb12fb261f1b43baf5d2f7f59d90fe123d41f0065ed3a183997ec9',
        'ofl_slug': 'notosanskannada',
        'scripts': 'Kannada',
    },
    'malayalam': {
        'filename': 'NotoSansMalayalam.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notosansmalayalam/NotoSansMalayalam%5Bwdth%2Cwght%5D.ttf',
        'sha256': '312e0e7c3cc15fa09eb42a8f749eeb246b593ed420e3c81aafe8d910c3a6fb56',
        'ofl_slug': 'notosansmalayalam',
        'scripts': 'Malayalam',
    },
    'oriya': {
        'filename': 'NotoSansOriya.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notosansoriya/NotoSansOriya%5Bwdth%2Cwght%5D.ttf',
        'sha256': '910342275d619081b896b4ed25fd9ad6ff320c25591b810de1fcc4beb153ba82',
        'ofl_slug': 'notosansoriya',
        'scripts': 'Oriya',
    },
    'tamil': {
        'filename': 'NotoSansTamil.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notosanstamil/NotoSansTamil%5Bwdth%2Cwght%5D.ttf',
        'sha256': 'aa3a9b321f4b0bb2c40203ffbde9af89713227866e0e13f76e5b9eeea727cf88',
        'ofl_slug': 'notosanstamil',
        'scripts': 'Tamil',
    },
    'telugu': {
        'filename': 'NotoSansTelugu.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notosanstelugu/NotoSansTelugu%5Bwdth%2Cwght%5D.ttf',
        'sha256': 'e618af7bf999df192ed4f388eba2e563f2b5015034e9cbb317b5bd793bd7334d',
        'ofl_slug': 'notosanstelugu',
        'scripts': 'Telugu',
    },
    'sinhala': {
        'filename': 'NotoSansSinhala.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notosanssinhala/NotoSansSinhala%5Bwdth%2Cwght%5D.ttf',
        'sha256': '9bd93e407a278075be403324063bc94a7e306c44de4df81214e932330c22eecf',
        'ofl_slug': 'notosanssinhala',
        'scripts': 'Sinhala',
    },
    'thai': {
        'filename': 'NotoSansThai.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notosansthai/NotoSansThai%5Bwdth%2Cwght%5D.ttf',
        'sha256': '5a1c559bb539583c8a1fd99d1c5b9491e5e14478c9cd2bd0970d5c3096cc9ef8',
        'ofl_slug': 'notosansthai',
        'scripts': 'Thai',
    },
    'khmer': {
        'filename': 'NotoSansKhmer.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notosanskhmer/NotoSansKhmer%5Bwdth%2Cwght%5D.ttf',
        'sha256': 'f37a8431a0c5d5ed2f81a767417546aca576a81fb7eff9c924d46aecf828f2ca',
        'ofl_slug': 'notosanskhmer',
        'scripts': 'Khmer',
    },
    'tibetan': {
        'filename': 'NotoSerifTibetan.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notoseriftibetan/NotoSerifTibetan%5Bwght%5D.ttf',
        'sha256': '060ec022b04c306de3f58d051fb0e1cf81a5b610c5910fbfc43bba154c057cda',
        'ofl_slug': 'notoseriftibetan',
        'scripts': 'Tibetan (no Noto Sans variant exists upstream; Noto Serif used instead)',
    },
    'ethiopic': {
        'filename': 'NotoSansEthiopic.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notosansethiopic/NotoSansEthiopic%5Bwdth%2Cwght%5D.ttf',
        'sha256': '0dbccc00b22d180ebd6a4bd8a733918a29e709fa6798023adc3e6cd40da65077',
        'ofl_slug': 'notosansethiopic',
        'scripts': 'Ethiopic (Amharic, Tigrinya, ...)',
    },
    'yi': {
        'filename': 'NotoSansYi.ttf',
        'url': f'{_GOOGLE_FONTS_OFL_BASE}/notosansyi/NotoSansYi-Regular.ttf',
        'sha256': 'ee4de376a1e4f3c4bc7e116f4f46538348716b8408b86a0fc18c1c6128d2e56d',
        'ofl_slug': 'notosansyi',
        'scripts': 'Yi (Nuosu)',
    },
    'myanmar': {
        'filename': 'NotoSansMyanmar.ttf',
        'url': 'https://raw.githubusercontent.com/google/fonts/1ac2012c34919f5fa2675aacf723fa98edb30b5f/ofl/notosansmyanmar/NotoSansMyanmar%5Bwdth%2Cwght%5D.ttf',
        'sha256': '7abbbfbe2514105d7ce94937aee3feb2ba89b73a256c8b77b5866bd9b83e32ec',
        'ofl_slug': 'notosansmyanmar',
        'ofl_base': 'https://raw.githubusercontent.com/google/fonts/1ac2012c34919f5fa2675aacf723fa98edb30b5f/ofl',
        'scripts': 'Myanmar (Burmese)',
    },
    'thaana': {
        'filename': 'NotoSansThaana.ttf',
        'url': 'https://raw.githubusercontent.com/google/fonts/1ac2012c34919f5fa2675aacf723fa98edb30b5f/ofl/notosansthaana/NotoSansThaana%5Bwght%5D.ttf',
        'sha256': 'a296795c892a9ec2b0f4d3af315568506ef9fd55920386170992d3935d8866ca',
        'ofl_slug': 'notosansthaana',
        'ofl_base': 'https://raw.githubusercontent.com/google/fonts/1ac2012c34919f5fa2675aacf723fa98edb30b5f/ofl',
        'scripts': 'Thaana (Divehi/Dhivehi)',
    },
}

# Priority order in which fonts are tried when rendering a character: the
# first font in this list that contains a glyph for a given character wins.
# DejaVu Sans is tried first since it covers common Latin/European text; the
# rest fall back to whichever script-specific Noto font is needed.
FONT_PRIORITY = [
    'dejavu_sans',
    'cjk_jp', 'cjk_kr', 'cjk_sc', 'cjk_tc',
    'devanagari', 'bengali', 'gujarati', 'gurmukhi', 'kannada', 'malayalam',
    'oriya', 'tamil', 'telugu', 'sinhala', 'thai', 'khmer', 'tibetan',
    'ethiopic', 'yi', 'myanmar', 'thaana',
]


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def font_path(key):
    """Path where the font for `key` should live, whether or not it exists yet."""
    return os.path.join(FONTS_DIR, FONT_MANIFEST[key]['filename'])


def is_font_ready(key):
    path = font_path(key)
    entry = FONT_MANIFEST[key]
    return os.path.exists(path) and _sha256(path) == entry['sha256']


def ensure_font(key, stdout=None):
    """
    Ensure the font for `key` is downloaded and verified, downloading it (and
    its license file) on demand if necessary. Returns the local file path, or
    None if it could not be obtained (e.g. no network access) -- callers
    should treat that as "this script's native names fall back to English".
    """
    entry = FONT_MANIFEST[key]
    path = font_path(key)

    if is_font_ready(key):
        return path

    os.makedirs(FONTS_DIR, exist_ok=True)

    def log(msg):
        if stdout:
            stdout.write(msg)

    try:
        if 'archive_member' in entry:
            log(f'Downloading {entry["url"]} ...')
            with urllib.request.urlopen(entry['url'], timeout=30) as resp:
                archive_bytes = resp.read()
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
                data = zf.read(entry['archive_member'])
                if 'license_archive_member' in entry:
                    license_path = os.path.join(FONTS_DIR, entry['license_filename'])
                    if not os.path.exists(license_path):
                        with open(license_path, 'wb') as f:
                            f.write(zf.read(entry['license_archive_member']))
            with open(path, 'wb') as f:
                f.write(data)
        else:
            log(f'Downloading {entry["url"]} ...')
            urllib.request.urlretrieve(entry['url'], path)

            if 'ofl_slug' in entry:
                ofl_base = entry.get('ofl_base', _GOOGLE_FONTS_OFL_BASE)
                ofl_url = f'{ofl_base}/{entry["ofl_slug"]}/OFL.txt'
                ofl_path = os.path.join(FONTS_DIR, f'OFL-{entry["ofl_slug"]}.txt')
                if not os.path.exists(ofl_path):
                    urllib.request.urlretrieve(ofl_url, ofl_path)
    except Exception as exc:
        log(f'Failed to download font "{key}": {exc}')
        if os.path.exists(path):
            os.remove(path)
        return None

    if not is_font_ready(key):
        log(f'Downloaded font "{key}" failed checksum verification; discarding.')
        if os.path.exists(path):
            os.remove(path)
        return None

    log(f'OK: {key} -> {path}')
    return path
