"""The one honesty check every form answer goes through, whatever the field type.

An answer that claims something (years with a technology, a skill, a language level, a degree or a
certificate) must be backed by a fact of the profile. The check reads the question and the resolved answer
and fails closed: a technology the question or the answer names that is not a profile skill, or a claim it
cannot read, is rejected and the field goes to manual review.
"""
import re
import unicodedata

from jobagent.facts import names_of

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
certified certification certifications certificate certificacion certificado certificada degree
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
                      (5, "professional profesional advanced avanzado fluent fluido proficient"),
                      (6, "native nativo bilingual bilingue expert experto")):
    RANK.update({w: _rank for w in _words.split()})

CEFR = re.compile(r"[abc][12](?:-[abc][12])?")
YEARS_Q = re.compile(r"\byears?\b|\byrs?\b|\banos?\b|\bmonths?\b|\bmeses\b|\bmes\b|how long|cuanto tiempo|"
                     r"since when|desde cuando")
MONTHS = re.compile(r"\bmonths?\b|\bmeses\b|\bmes\b")
SKILL_Q = re.compile(r"\b(?:experienc\w*|proficien\w*|know|knowledge|conoc\w*|familiar\w*|used|use|using|worked|"
                     r"skills?|levels?|nivel|rate|rating|expert\w*|competen\w*|comfortable)\b")
EXP_WORDS = re.compile(r"experienc|proficien|skill|knowledge|conoc|familiar")
# Questions about pay, availability or legal status: a number there is not a claim of experience.
NON_CLAIM = re.compile(r"salary|salario|sueldo|compensation|remuneraci|wage|\bpay\b|hourly|per hour|por hora|"
                       r"notice|preaviso|availab|disponib|start date|fecha de inicio|incorporaci|relocat|visa|"
                       r"sponsor|authori|permit|permiso|citizen|nationality|nacionalidad|\bage\b|edad|expectati|"
                       r"expectativa|pretension")
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
    return (tok in STOP or CEFR.fullmatch(tok) or not any(c.isalnum() for c in tok) or tok[0].isdigit()
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
    return max((RANK.get(t, 0) for t in re.findall(r"[a-z0-9]+", text)), default=0)


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
    """The technology right before "(3 years)", ": 3 years" or "- 3 years", as a group list."""
    if not re.search(r"[(:\-]\s*$", pre):
        return []
    cur = []
    for tok in reversed(TOKEN_OR_COMMA.findall(pre)):
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


class Claims:
    """Skills, languages, education and certificates of a profile, and the check against them."""

    def __init__(self, facts, v1_years=None):
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
        self.edu = [edu_rank(fold(f.text)) for f in facts.values() if f.kind == "education"]
        self.certs = [set(TOKEN.findall(fold(f.text))) for f in facts.values() if f.kind == "cert"]

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
        t, v = fold(text), fold(value)
        if NON_CLAIM.search(t) and not EXP_WORDS.search(t):
            return True, ""
        kind = answer_kind(v)
        why = ""
        if self.facts:
            why = self._language(t, v, kind) or self._credential(t, v, kind)
        why = why or self._skill_claim(field, text, t, v, kind)
        if not why and field["type"] in ("text", "textarea"):
            why = self._answer_claims(v)
        return not why, why

    def _language(self, t, v, kind):
        langs = {LANGS[w] for w in LANG_RX.findall(t)}
        claimed = max(rank(t), 1) if kind == "yes" else rank(v) if kind is None else 0
        for lang in (langs if claimed else ()):
            if lang not in self.langs:
                return f"claims {lang} proficiency, which is not in the profile"
            if claimed > self.langs[lang]:
                return f"claims a {lang} level above the profile's"
        return ""

    def _credential(self, t, v, kind):
        asked_degree, asked_cert = bool(EDU_Q.search(t)), bool(CERT_Q.search(t))
        need = edu_rank(t) if kind == "yes" else edu_rank(v) if kind is None and edu_rank(v) else None
        if need is None or not (asked_degree or asked_cert):
            return ""
        degree = asked_degree and any(r >= need for r in self.edu)
        words = {tok for run in groups(LANG_RX.sub(" ", t)) for tok in run}
        cert = asked_cert and any(words <= c for c in self.certs)
        if degree or cert:
            return ""
        return "claims a degree or certificate that is not in the profile"

    def _skill_claim(self, field, text, t, v, kind):
        opts = field.get("options") or ()
        runs = groups(LANG_RX.sub(" ", t))
        years_q = bool(YEARS_Q.search(t)) or any(YEARS_Q.search(fold(o)) for o in opts)
        skill_q = bool(SKILL_Q.search(t)) and bool(runs)
        if not (years_q or skill_q or any(rank(fold(o)) for o in opts)):
            return ""
        months_q, ftype = bool(MONTHS.search(t)), field["type"]
        years, exists = None, False
        if ftype == "number":
            if not PLAIN_NUMBER.fullmatch(v.strip()):
                return f"{str(v)[:30]!r} is not a plain number"
            n = float(v.replace(",", "."))
            exists, years = n > 0, (n / 12 if months_q else n) if years_q and n > 0 else None
        elif opts or ftype == "checkbox":
            own = years_in(v, months_q, low=True) if opts else None
            if own is not None:
                exists, years = own > 0 or kind == "yes", own or None
            elif kind == "yes":
                exists, years = True, threshold(text)
            elif kind is None:
                years = threshold(text)
                exists = bool(rank(v) or years)
        else:
            n = years_in(v, months_q, low=False)
            if n is not None:
                exists, years = n > 0, n or None
            elif kind == "yes":
                exists, years = True, threshold(text)
            elif kind is None:
                if years_q:
                    return "the answer has no number of years to check"
                exists = True
        if not exists:
            return ""
        if opts and any(c.isdigit() for c in v):
            runs += groups(v)  # an option such as "5+ years with Node.js" names its own technology
        matched, unmatched = self.resolve(runs)
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

    def _answer_claims(self, v):
        """A text answer may not claim a technology (or years of one) that the profile does not back."""
        for runs, years in mentions(v):
            matched, unmatched = self.resolve(runs)
            if unmatched:
                return f"the answer claims experience with {' '.join(unmatched)!r}, which is not in the profile"
            if why := self._years_within(matched, years):
                return "the answer " + why
        return ""
