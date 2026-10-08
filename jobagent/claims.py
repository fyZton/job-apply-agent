"""The one honesty check every form answer goes through, whatever the field type.

Any answer other than No / 0 / None must be backed by the profile. The check reads the question and the
resolved answer and fails closed: unless the question is about a recognised non-claim topic (pay, dates,
location, contact details, consent...), everything it names must be a profile fact, and a free-text answer is
checked token by token. Whatever is not recognised is rejected and the field goes to manual review.
"""
import re
import unicodedata

from jobagent.facts import names_of
from jobagent.known_tech import AMBIGUOUS, CUES, KNOWN_TECH

NUM = r"(\d+(?:[.,]\d+)?)"
TOKEN = re.compile(r"[a-z0-9+#]+(?:[.\-][a-z0-9+#]+)*")
TOKEN_OR_COMMA = re.compile(TOKEN.pattern + "|,")
PLAIN_NUMBER = re.compile(NUM)

# Words that are not technologies: question words, auxiliaries, pronouns, generic nouns, role names, levels.
# Whatever is left in a question is a candidate technology (folded: lowercase, no accents).
STOP = set("""
how many much long do does did you your yours have has had having is are was were be been am will would can could
should may might what which who whom whose where when why this that these those it its i me my we our us they them
their he she his her not no yes yeah sure ok okay if than then so such any some all each every both either also
just only very more most less least over under about around approximately roughly total ever before yet
cuantos cuantas cuanto cuanta como cual cuales que quien donde cuando por porque tienes tiene tengo tienen has
haber ha he hemos eres es son soy fue estas esta estan estoy usted tu tus su sus mi mis nuestro el la los las lo
un una unos unas de del al en con sin para sobre y o e u ni mas menos minimo minima maximo desde hasta si
with in of on for and or the a an to at as by from into per via using use used usando
experience experiencia years year yrs yr months month meses mes anos ano time tiempo professional profesional
relevant relevante level nivel rate rating proficiency proficient skills skill knowledge conocimiento
conocimientos familiar familiarity hands-on handson production produccion industry field area role position
puesto company empresa software development desarrollo programming programacion language languages lenguaje
tool tools framework frameworks please indicate select enter number etc e.g eg ie describe tell list provide
explain briefly detail details yourself about work working worked works trabajo trabajado trabajar job laboral
current present previous past recent last commercial real world technology technologies tecnologia tecnologias
technical tecnico stack team teams remote environment similar related equivalent plus basic beginner
intermediate intermedio advanced avanzado expert experto fluent native none ninguno ninguna basico
developer engineer developers dev programmer analyst specialist consultant backend frontend fullstack full web
senior junior mid lead overall general main primary own personal project projects proyecto daily
speak speaking spoken written writing reading understand communicate converse
strong solid extensive deep good great proven practical significant broad prior following rank
certified certification certifications certificate certificacion certificado certificada degree degrees
bachelor bachelors masters master phd doctorate doctorado licenciatura maestria diploma mba msc bsc
undergraduate postgraduate universitario titulo grado
want wants wanted like interested willing able ability capable code coding coded program programmed
write wrote written deploy deployed deploying manage managed managing build built building develop developed
developing hold holds held handle handled hands background anything else additional comments comment other
others share mention add information info question questions give
sabes sabe saber manejas maneja manejar dominas domina dominar conoces conoce usas usa utilizas utiliza
programas programa programado desarrollado desarrollas puedes puede escribir escribes implementado
implementar gestionado construido cuenta cuentas hecho haces hacer
""".split())

LANGS = {
    "english": "en", "ingles": "en", "spanish": "es", "espanol": "es", "castellano": "es", "german": "de",
    "aleman": "de", "french": "fr", "frances": "fr", "portuguese": "pt", "portugues": "pt", "italian": "it",
    "italiano": "it", "chinese": "zh", "mandarin": "zh", "chino": "zh", "japanese": "ja", "japones": "ja",
    "korean": "ko", "coreano": "ko", "russian": "ru", "ruso": "ru", "dutch": "nl", "neerlandes": "nl",
    "holandes": "nl", "arabic": "ar", "arabe": "ar", "catalan": "ca", "turkish": "tr", "turco": "tr",
    "polish": "pl", "polaco": "pl", "hindi": "hi",
}
LANG_RX = re.compile(r"\b(?:" + "|".join(LANGS) + r")\b")
# Proficiency, 1 (exists) to 6 (native): CEFR levels and the words forms use for them.
RANK = {"a1": 1, "a2": 2, "b1": 3, "b2": 4, "c1": 5, "c2": 6}
for _rank, _words in ((2, "elementary basic beginner novice limited basico elemental principiante inicial"),
                      (3, "conversational conversacional intermediate intermedio independent"),
                      (4, "professional profesional"),
                      (5, "advanced avanzado fluent fluido proficient"),
                      (6, "native nativo bilingual bilingue expert experto")):
    RANK.update({w: _rank for w in _words.split()})
PHRASES = {"upper intermediate": 4, "professional working": 4, "full professional": 5, "limited working": 2,
           "intermedio alto": 4}
SCALE = {"1": 1, "2": 2, "3": 3, "4": 4, "5": 6}  # a 1-5 rating of a language: A1, A2, B1, B2, C2

CEFR = re.compile(r"[abc][12](?:-[abc][12])?")
YEARS_Q = re.compile(r"\byears?\b|\byrs?\b|\banos?\b|\bmonths?\b|\bmeses\b|\bmes\b|how long|cuanto tiempo|"
                     r"since when|desde cuando")
MONTHS = re.compile(r"\bmonths?\b|\bmeses\b|\bmes\b")
SKILL_Q = re.compile(r"\b(?:experienc\w*|proficien\w*|know|knowledge|conoc\w*|familiar\w*|used|use|using|worked|"
                     r"skills?|levels?|nivel|rate|rating|expert\w*|competen\w*|comfortable)\b")
EXP_WORDS = re.compile(r"experienc|proficien|skill|knowledge|conoc|familiar")
# Questions about pay, availability, legal status, location, contact details or consent: a number or a name there
# is not a claim of experience. EN + ES, folded.
NON_CLAIM = re.compile(
    r"salary|salario|sueldo|compensation|remuneraci|wage|\bpay\b|hourly|per hour|por hora|day rate|tarifa|"
    r"notice|preaviso|availab|disponib|start date|fecha de inicio|incorporaci|relocat|reubica|mudarse|visa\b|"
    r"sponsor|patrocinio|authori|autoriz|permit|permiso|citizen|nationality|nacionalidad|\bage\b|edad|\b18\b|"
    r"expectati|expectativa|pretension|country|\bpais|\bcity\b|ciudad|location|ubicacion|residen|time ?zone|"
    r"zona horaria|\bhours\b|\bhoras\b|horario|remote|remoto|\bname\b|nombre|apellido|surname|e-?mail|correo|"
    r"phone|telefono|celular|linkedin|github|portfolio|portafolio|website|sitio web|how did you hear|referr|"
    r"referid|como te enteraste|gender|genero|pronoun|consent|consiento|\bterms\b|terminos|privacy|privacidad|"
    r"policy|politica|\bagree|acepto|background check|drug|disabilit|discapacidad|veteran|\brace\b|ethnic|"
    r"etnia|raza|employer|empleador|address|direccion|\bzip\b|postal|\bwhy\b|por que|motivat|cover letter|"
    r"about yourself|sobre ti|tell us about|summary")
EDU_Q = re.compile(r"\b(?:degree|bachelor\w*|licenciatur\w*|masters?|maestri\w*|msc|bsc|mba|phd|doctorate|"
                   r"doctorado|diploma|titulo|grado|graduate|universit\w*|education|educacion|estudios|carrera)\b")
CERT_Q = re.compile(r"\bcertif\w*|\bcertificad\w*")
EDU_RANKS = ((3, r"\b(?:phd|doctor\w*)\b"), (2, r"\b(?:master\w*|maestri\w*|msc|mba|posgrado|postgrad\w*)\b"),
             (1, r"\b(?:bachelor\w*|licenciatur\w*|ingenier\w*|engineer\w*|bsc|undergrad\w*|grado)\b"))
MORE_THAN = re.compile(r"(?:more than|over|m[aá]s de)\s*" + NUM, re.I)
AT_LEAST = re.compile(r"(?:at least|minimum|m[ií]nimo)\s*" + NUM + r"|" + NUM + r"\s*\+?\s*(?:years?|yrs?|años?)\b",
                      re.I)
YEARS_RX = re.compile(NUM + r"\s*\+?\s*(?:years?|yrs?|anos?)\b")
UNIT_RX = re.compile(NUM + r"\s*\+?\s*(years?|yrs?|anos?|months?|meses|mes)\b")
# "experience with X", "worked with X", "conocimientos de X": X is what the answer claims.
CLAIM_RX = re.compile(r"\b(?:experience|expertise|worked|used|using|familiar|knowledge|skilled|proficient|expert)"
                      r"\s+(?:with|in|of|using|on|at)\s+|\b(?:experiencia|conocimientos?|trabajado|usado|"
                      r"manejo|dominio)\s+(?:con|en|de|del)\s+")
PREP = {"of", "with", "in", "de", "con", "en", "using", "usando", "on", "at", "del"}
CONJ = {"and", "y", "or", "o", "e", "u"}
YES = {"yes", "y", "si", "true", "checked", "sure"}
NO = {"no", "none", "ninguno", "ninguna", "false", "not", "never", "nunca", "0"}


def fold(text):
    """Lowercase, no accents, no apostrophes (NFKC first): the form every comparison here uses."""
    t = unicodedata.normalize("NFKC", str(text)).lower().replace("'", "").replace("’", "")
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def is_stop(tok):
    return (tok in STOP or tok in RANK or CEFR.fullmatch(tok) or not any(c.isalnum() for c in tok) or tok[0].isdigit()
            or tok.endswith("mente") or (len(tok) > 5 and tok.endswith("ly")))


def groups(text):
    """The runs of adjacent content tokens of `text` (folded): what is left after the stop words."""
    out, cur = [], []
    for tok in TOKEN.findall(text):
        if is_stop(tok):
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(tok)
    return out + [cur] if cur else out


def rank(text):
    words = max((RANK.get(t, 0) for t in re.findall(r"[a-z0-9]+", text)), default=0)
    return max([words] + [r for p, r in PHRASES.items() if p in text])


_NUMW = {}
for _words in ("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
               "seventeen eighteen nineteen twenty", "uno dos tres cuatro cinco seis siete ocho nueve diez once doce "
               "trece catorce quince dieciseis diecisiete dieciocho diecinueve veinte"):
    _NUMW.update({w: i for i, w in enumerate(_words.split(), 1)})
_NUMW["una"] = 1
_SPELLED = re.compile(r"\b(" + "|".join(_NUMW) + r")\b(?=\s*\+?\s*(?:years?|yrs?|anos?|months?|meses))")


def spell(v):
    """The folded answer with spelled numbers (one..twenty, uno..veinte) as digits: "ten years" is "10 years";
    a lone "three" is 3."""
    v = _SPELLED.sub(lambda m: str(_NUMW[m.group(1)]), v)
    return str(_NUMW[v.strip()]) if v.strip() in _NUMW else v


def answer_kind(v):
    """"yes", "no" or None for a folded answer, by its first word: "Yes, I do" is a yes, "No tengo" a no."""
    words = re.findall(r"[a-z0-9]+", v)
    first = words[0] if words else ""
    return "yes" if first in YES else "no" if first in NO else None


def threshold(text):
    """The most years a question asks for ("at least 5 years", "7+ years", "más de 5" is 6), or None."""
    nums = [float(m.replace(",", ".")) + 1 for m in MORE_THAN.findall(text)]
    nums += [float((a or b).replace(",", ".")) for a, b in AT_LEAST.findall(text)]
    return max(nums, default=None)


def years_in(v, months_q, low):
    """Years written in the folded answer `v`, or None. "3-5" is 3 when `low` (an option's lower bound) and 5
    otherwise; "less than 1" is 0. Months count /12 when the answer or (for a bare number) the question says
    months; "1 year 6 months" adds up."""
    units = UNIT_RX.findall(v)
    in_months = {u[0] == "m" for _, u in units}
    if len(in_months) == 2:
        return sum(float(n.replace(",", ".")) / (12 if u[0] == "m" else 1) for n, u in units)
    nums = list(PLAIN_NUMBER.finditer(v))
    if not nums:
        return None
    if low and re.search(r"less than|under|up to|menos de|hasta|<", v[:nums[0].start()]):
        return 0.0
    values = [float(m.group().replace(",", ".")) for m in nums]
    n = min(values) if low else max(values)
    return n / 12 if in_months == {True} or (months_q and not units) else n


def _chunk(rest):
    """The tokens of the clause that starts `rest` (folded)."""
    return TOKEN_OR_COMMA.findall(re.split(r"[;:!?\n(]|\.(?:\s|$)", rest, maxsplit=1)[0][:150])


def _after(rest):
    """What an answer says a claim is about, in the clause after "3 years of" / "experience with": None if it
    is not about experience, [] if it is generic ("3 years of experience"), else the technology groups."""
    toks = _chunk(rest)
    i = 0
    while i < len(toks) and toks[i] in PREP:
        i += 1
    if i == len(toks):
        return None
    if toks[i] in ("experience", "experiencia"):
        return []
    if is_stop(toks[i]):
        return None
    out, cur = [], []
    for tok in toks[i:]:
        if tok == "," or tok in CONJ:
            out += [cur] if cur else []
            cur = []
        elif is_stop(tok):
            break
        else:
            cur.append(tok)
    return out + [cur] if cur else out


def _before(pre):
    """The technology right before "(3 years)", ": 3 years", "- 3 years" or "for 3 years", as a group list."""
    m = re.search(r"(?:[(:\-]|\b(?:for|durante|por))\s*$", pre)
    if not m:
        return []
    cur = []
    for tok in reversed(TOKEN_OR_COMMA.findall(pre[:m.start()])):
        if tok == "," or is_stop(tok):
            break
        cur.insert(0, tok)
    return [cur] if cur else []


def mentions(v):
    """[(technology groups, years or None)] an answer claims: "7 years of Kubernetes", "Python (3 years)",
    "worked with Kubernetes". Groups are [] for a generic "3 years of experience"."""
    out = []
    for m in YEARS_RX.finditer(v):
        gs = _before(v[:m.start()]) or _after(v[m.end():])
        if gs is not None:
            out.append((gs, float(m.group(1).replace(",", "."))))
    for m in CLAIM_RX.finditer(v):
        gs = _after(v[m.end():])
        if gs:
            out.append((gs, None))
    return out


def edu_rank(text):
    t = re.sub(r"(?<=\w)\.(?=\w)", "", text)
    return next((r for r, rx in EDU_RANKS if re.search(rx, t)), 0)


# Certificates people name by acronym, and the degree words an answer may claim.
PURE_CERT = re.compile(r"\b(?:pmp|capm|cka|ckad|cks|cissp|cisa|cism|itil|ccna|ccnp|csm|psm|oscp|ceh|togaf|prince2|"
                       r"comptia|aws|azure|gcp|ielts|toefl)\b")
# A cert fact backs a name only where the text is about certificates (a vendor name alone is a skill claim).
CERT_CTX = re.compile(r"\bcertif\w*|\bholds?\b|\b(?:pmp|capm|cka|ckad|cks|cissp|cisa|cism|"
                      r"itil|ccna|ccnp|csm|psm|oscp|ceh|togaf|prince2|comptia|ielts|toefl)\b")
CERTIFIED = re.compile(r"\b(?:certified|certificad[oa])\b")
ANS_DEG = re.compile(r"\b(?:phd|doctorate|doctorado|masters?|maestria|mba|msc|bachelors?|licenciatura|bsc)\b")
SUBJECT = re.compile(r"\b(?:degrees?|bachelors?|masters?|phd|doctorate|doctorado|licenciatura|maestria|grado|titulo|"
                     r"diploma|mba|msc|bsc)\b[^.?!;,]*?\b(?:in|of|en|de|del)\s+([^.?!;,]*)")
# Words in an answer that look like names but are not technologies.
COMMON_CAPS = set("""
i im ok us usa uk eu cv hr it id pm am pdf faq usd eur gbp mxn cop ves utc gmt est pst cet monday tuesday wednesday
thursday friday saturday sunday january february march april may june july august september october november
december lunes martes miercoles jueves viernes sabado domingo enero febrero marzo abril mayo junio julio agosto
septiembre octubre noviembre diciembre hello hi hola thanks thank gracias regards sincerely dear mr mrs ms dr
e.g i.e etc
""".split())
WORD = re.compile(r"[\w+#]+(?:\.[\w+#]+)*")
ORDINAL = re.compile(r"\d+(?:st|nd|rd|th|k|m|h|d|x)")
SENTENCE_START = re.compile(r"\s*(?:[,;]|$|(?:is|are|was|and|for|es|y|para)\b)")


_NAMES = "|".join(re.escape(t) for t in sorted(KNOWN_TECH, key=len, reverse=True))
TECH_RX = re.compile(r"(?<![\w+#.-])(" + _NAMES + r")(?![\w+#]|-\w)")


def known_tech(raw):
    """KNOWN_TECH names in an answer, case ignored. Ambiguous ones ("go", "make", "rust") count only when
    capitalised in mid-sentence, next to a cue such as "language" or "code", or in a list with other names."""
    text = unicodedata.normalize("NFKC", raw)
    low = text.lower()
    hits = list(TECH_RX.finditer(low))
    firm = {m.start() for m in hits if m.group() not in AMBIGUOUS}
    out = []
    for m in hits:
        name, a, b = m.group(), m.start(), m.end()
        if name in AMBIGUOUS:
            near = re.findall(r"[a-z]+", low[max(0, a - 20):a])[-1:] + re.findall(r"[a-z]+", low[b:b + 20])[:1]
            before = text[:a].rstrip()
            cap = text[a].isupper() and bool(before) and before[-1] not in ".!?"
            listed = (re.search(r",\s*$", low[:a]) and any(x < a and low[x:a].count(" ") <= 2 for x in firm)
                      or re.match(r"\s*,\s*(?:and\s+|or\s+)?(\S+)", low[b:]) and any(
                          b < x < b + 20 for x in firm)
                      or re.match(r"\s*(?:and|or|y|o)\s+(\S+)", low[b:]) and any(b < x < b + 12 for x in firm)
                      or re.search(r"(?:and|or|y|o)\s+$", low[:a]) and any(a - 14 < x < a for x in firm))
            if not (cap or listed or CUES & set(near)):
                continue
        out.append(name)
    return out


def _tech_like(word, start, after):
    """The word of a free-text answer looks like a technology or proper name: letters with digits or + # .,
    CamelCase, ALL-CAPS, or a capitalised word that does not just start a sentence."""
    f = fold(word)
    if not any(c.isalpha() for c in word) or f in COMMON_CAPS or f in STOP and not word.isupper():
        return False
    if CEFR.fullmatch(f) or ORDINAL.fullmatch(f) or re.fullmatch(r"(?:utc|gmt)[+-]?\d*", f):
        return False
    if any(c.isdigit() for c in word) or any(c in word for c in "+#.") or re.search(r"[a-z][A-Z]", word):
        return True
    if len(word) >= 2 and word.isupper():
        return True
    if word[0].isupper() and f not in STOP and f not in LANGS:
        return not start or SENTENCE_START.match(after) is not None
    return False


def answer_runs(raw):
    """The runs of adjacent technology-like words in a free-text answer, as lists of folded tokens."""
    runs, cur, last = [], [], 0
    for m in WORD.finditer(raw):
        before = raw[:m.start()].rstrip(" \t\"'(*•-¿¡")
        start = not before or before[-1] in ".!?\n"
        if _tech_like(m.group(), start, raw[m.end():m.end() + 12]):
            if cur and raw[last:m.start()].strip():
                runs.append(cur)
                cur = []
            cur += TOKEN.findall(fold(m.group()))
        elif cur:
            runs.append(cur)
            cur = []
        last = m.end()
    return runs + [cur] if cur else runs


def _flatten(obj, skip=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in skip:
                yield from _flatten(v, skip)
    elif isinstance(obj, list | tuple):
        for v in obj:
            yield from _flatten(v, skip)
    elif isinstance(obj, str | int | float) and not isinstance(obj, bool):
        yield str(obj)


def _words(text):
    return set(re.findall(r"[a-z0-9]+", re.sub(r"(?<=\w)\.(?=\w)", "", text)))


class Claims:
    """Skills, languages, education and certificates of a profile, and the check against them."""

    def __init__(self, facts, v1_years=None, profile=None):
        self.facts = facts
        self.skills = {}  # folded name -> years (the most when a name is repeated)
        named = [(f.text, f.years) for f in facts.values() if f.kind == "skill" and f.text]
        if not facts:  # version 1 profile: years_of_experience
            named = [(str(k).replace("_", " "), v) for k, v in (v1_years or {}).items()
                     if isinstance(v, int | float) and not isinstance(v, bool)]
        for name, years in named:
            key = " ".join(TOKEN.findall(fold(name)))
            self.skills[key] = max(self.skills.get(key, 0.0), float(years or 0))
        self.enabled = bool(facts or self.skills)
        self.best = max(self.skills.values(), default=0.0)
        self.langs = {}
        for f in facts.values():
            if f.kind == "language":
                name, _, level = fold(f.text).partition(",")
                self.langs[LANGS.get((TOKEN.findall(name) or [""])[0])] = rank(level) or 1
        self.edu_facts = [(edu_rank(fold(f.text)), _words(fold(f.text)))
                          for f in facts.values() if f.kind == "education"]
        self.certs = [set(TOKEN.findall(fold(f.text))) for f in facts.values() if f.kind == "cert"]
        # Words the profile itself contains (employers, places, name...): an answer may repeat them. Certificates
        # are left out on purpose: they only back a certificate claim.
        text = [f.text for f in facts.values() if f.kind != "cert"]
        text += list(_flatten({k: v for k, v in (profile or {}).items() if k != "facts"},
                              skip=("fixed_answers", "screening_rules")))
        text += [r["value"] for r in (profile or {}).get("fixed_answers") or []
                 if isinstance(r, dict) and isinstance(r.get("value"), str)]
        self.known = set(TOKEN.findall(fold(" ".join(text))))

    @staticmethod
    def key(name):
        return " ".join(TOKEN.findall(fold(name)))

    def _skill(self, span):
        s = " ".join(span)
        for name, years in self.skills.items():
            if s == name or names_of(s) & names_of(name) or name.startswith(s + " "):
                return name, years
        return None

    def resolve(self, runs):
        """({skill name: years} matched, [tokens] not in the profile) for the groups of a text. A group is
        read greedily, longest skill name first, so "REST APIs" is the skill "REST APIs and integrations"."""
        matched, unmatched = {}, []
        for run in runs:
            i = 0
            while i < len(run):
                for j in range(len(run), i, -1):
                    if hit := self._skill(run[i:j]):
                        matched[hit[0]] = hit[1]
                        i = j
                        break
                else:
                    unmatched.append(run[i])
                    i += 1
        return matched, unmatched

    def years_q(self, text):
        t = fold(text)
        return bool(YEARS_Q.search(t)) and not (NON_CLAIM.search(t) and not EXP_WORDS.search(t))

    def named(self, text):
        """The profile skills a question names."""
        return self.resolve(groups(LANG_RX.sub(" ", fold(text))))[0]

    def stated_years(self, text, value):
        """The years a number or text answer states, or None."""
        return years_in(fold(value), bool(MONTHS.search(fold(text))), low=False)

    def check(self, field, text, value):
        """(ok, reason) for the resolved `value` of `field` under the question `text`."""
        if not self.enabled:
            return True, ""
        t, v = fold(text), spell(fold(value))
        kind = answer_kind(v)
        why = ""
        topic = bool(NON_CLAIM.search(t) and not EXP_WORDS.search(t))
        if not topic:
            if self.facts:
                why = self._language(t, v, kind) or self._credential(t, v, kind)
            why = why or self._skill_claim(field, text, t, v, kind)
        if not why and field["type"] in ("text", "textarea"):
            why = self._answer_claims(str(value), t, topic)
        return not why, why

    def _language(self, t, v, kind):
        if kind == "no":
            return ""
        langs = {LANGS[w] for w in LANG_RX.findall(t)} | {LANGS[w] for w in LANG_RX.findall(v)}
        if not langs:
            return ""
        level = max(rank(t), 1) if kind == "yes" else rank(v)
        if kind is None and not level and not YEARS_Q.search(t):
            level = SCALE.get(v.strip(), 0)
        left = [tok for tok in TOKEN.findall(v) if not is_stop(tok) and tok not in LANGS and tok not in RANK]
        unreadable = kind is None and not level and bool(left)
        for lang in langs:
            if lang not in self.langs:
                return f"claims {lang} proficiency, which is not in the profile"
            if unreadable:
                return f"the {lang} level cannot be read"
            if level > self.langs[lang]:
                return f"claims a {lang} level above the profile's"
        return ""

    def _subject_ok(self, text, toks):
        """The subject of "degree in X" is part of this education fact."""
        m = SUBJECT.search(text)
        return not m or {tok for run in groups(LANG_RX.sub(" ", m.group(1))) for tok in run} <= toks

    def _credential(self, t, v, kind):
        asked_degree, asked_cert = bool(EDU_Q.search(t)), bool(CERT_Q.search(t))
        need = edu_rank(t) if kind == "yes" else edu_rank(v) if kind is None and edu_rank(v) else None
        if need is None or not (asked_degree or asked_cert):
            return ""
        degree = asked_degree and any(r >= need and self._subject_ok(t, toks) for r, toks in self.edu_facts)
        words = {tok for run in groups(LANG_RX.sub(" ", t)) for tok in run}
        cert = asked_cert and any(words <= c for c in self.certs)
        if degree or cert:
            return ""
        return "claims a degree or certificate that is not in the profile"

    def _unbacked(self, tokens, context, echo=""):
        """The tokens that neither the profile text, the `echo` (the question an answer repeats) nor (in a
        certificate or degree question or answer, named by `context`) a cert or education fact backs."""
        pool = self.known | set(TOKEN.findall(echo))
        left = [tok for tok in tokens if tok not in pool]
        joined = context
        if left and CERT_CTX.search(joined) and any(set(left) <= c for c in self.certs):
            return []
        if left and EDU_Q.search(joined):
            left = [tok for tok in left if not any(tok in toks for _, toks in self.edu_facts)]
        return left

    def _skill_claim(self, field, text, t, v, kind):
        if kind == "no":
            return ""
        opts = field.get("options") or ()
        runs = groups(LANG_RX.sub(" ", t))
        years_q = bool(YEARS_Q.search(t)) or any(YEARS_Q.search(fold(o)) for o in opts)
        months_q, ftype = bool(MONTHS.search(t)), field["type"]
        years, exists = None, False
        if ftype == "number":
            if not PLAIN_NUMBER.fullmatch(v.strip()):
                return f"{str(v)[:30]!r} is not a plain number"
            n = float(v.replace(",", "."))
            exists, years = n > 0, (n / 12 if months_q else n) if years_q and n > 0 else None
        elif opts or ftype == "checkbox":
            own = years_in(v, months_q, low=True) if opts and (years_q or not LANG_RX.search(t)) else None
            if own is not None:
                exists, years = own > 0 or kind == "yes", own or None
            elif kind in ("yes", None):
                exists, years = True, threshold(text)
        else:
            n = years_in(v, months_q, low=False)
            if n is not None:
                exists, years = n > 0, n or None
            elif kind == "yes":
                exists, years = True, threshold(text)
            elif kind is None:
                if years_q:
                    return "the answer has no number of years to check"
                exists = bool(rank(v)) or len(v.split()) <= 3  # a long free answer is read by _answer_claims
        if not exists:
            return ""
        if opts and kind is None:
            runs += groups(LANG_RX.sub(" ", v))  # an option names its own technology: "5+ years with Node.js"
        matched, unmatched = self.resolve(runs)
        unmatched = self._unbacked(unmatched, f"{t} {v}")
        if unmatched:
            return f"claims experience with {' '.join(unmatched)!r}, which is not in the profile"
        return self._years_within(matched, years)

    def _years_within(self, matched, years):
        if not years:
            return ""
        for name, have in matched.items():
            if years > have:
                return f"claims {years:g} years of {name}, above the profile's {have:g}"
        if not matched and years > self.best:
            return f"claims {years:g} years, above the profile's best skill ({self.best:g})"
        return ""

    def _answer_claims(self, raw, t, topic):
        """A text answer may not name a technology, language, degree or certificate (or years of one) that the
        profile does not back. Each technology-like word must be a skill, be in the question, or be in the
        profile; anything else is rejected. ponytail: a lowercase unknown technology ("kubernetes") is not seen."""
        v = spell(fold(raw))
        for name in known_tech(raw):  # lowercase names count too, on every question
            matched, unmatched = self.resolve([TOKEN.findall(name)])
            if left := self._unbacked(unmatched, f"{t} {v}", t):
                return f"the answer names {' '.join(left)!r}, which is not in the profile"
        for run in [] if topic else answer_runs(raw):  # a place or a name answers a non-claim topic
            matched, unmatched = self.resolve([run])
            if left := self._unbacked(unmatched, f"{t} {v}", t):
                return f"the answer names {' '.join(left)!r}, which is not in the profile"
        for runs, years in mentions(v):
            matched, unmatched = self.resolve(runs)
            if left := self._unbacked(unmatched, f"{t} {v}", t):
                return f"the answer claims experience with {' '.join(left)!r}, which is not in the profile"
            if why := self._years_within(matched, years):
                return "the answer " + why
        return self._answer_credentials(v) if self.facts else ""

    def _answer_credentials(self, v):
        toks = TOKEN_OR_COMMA.findall(v)
        for i, tok in enumerate(toks):
            if tok not in LANGS:
                continue
            lang, level = LANGS[tok], 0
            for j in range(i - 1, max(i - 4, -1), -1):  # words before, up to a comma or another language
                if toks[j] == "," or toks[j] in LANGS:
                    break
                level = max(level, rank(" ".join(toks[j:i])))
            for j in range(i + 1, min(i + 4, len(toks))):
                if toks[j] in LANGS:
                    break
                level = max(level, rank(" ".join(toks[i + 1:j + 1])))
            if lang not in self.langs:
                return f"the answer claims {lang}, which is not in the profile"
            if level > self.langs[lang]:
                return f"the answer claims a {lang} level above the profile's"
        degrees = ANS_DEG.findall(v)
        if degrees:
            need = edu_rank(" ".join(degrees))
            if not any(r >= need and self._subject_ok(v, words) for r, words in self.edu_facts):
                return "the answer claims a degree that is not in the profile"
        for c in PURE_CERT.findall(v):
            if not (any(c in cert for cert in self.certs) or self._skill([c])):
                return f"the answer claims {c.upper()}, which is not in the profile"
        if CERTIFIED.search(v) and not self.certs:
            return "the answer claims a certification, which is not in the profile"
        return ""
