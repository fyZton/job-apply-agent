"""The one honesty check every form answer goes through, whatever the field type.

Any answer other than No / 0 / None must be backed by the profile. The check reads the question and the
resolved answer and fails closed: unless the question is about a recognised non-claim topic (pay, dates,
location, contact details, consent...), everything it names must be a profile fact, and a free-text answer is
checked token by token. Whatever is not recognised is rejected and the field goes to manual review.
"""
import datetime
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
full junior mid overall general main primary own personal project projects proyecto daily
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
here upper alto working limited zone hear heard hire hiring letter cover date start inicio fecha check sitio web hora
horaria zona enteraste usd eur gbp mxn cop ves ars clp pen brl cad monthly annual yearly net gross mensual anual
engineering ingenieria processing process data application applications
highest education educacion university universidad universitario universitaria completed educativo academic
academico estudios titulo level
period periods days day weeks week dias semanas semana expected desired
preferred earliest immediately eligible valid currently legally receive calls call require requires now future
first last middle given family maiden
profile url link
links handle username contact nombre apellidos
""".split())
# Countries and regions: a question that names where you may work names no technology.
PLACES = set("""
united states america usa canada mexico spain espana colombia argentina chile peru venezuela brazil brasil uruguay
ecuador bolivia paraguay panama guatemala honduras salvador nicaragua cuba dominican republic puerto rico costa rica
germany alemania france francia italy italia portugal netherlands holland belgium switzerland suiza austria poland
ireland kingdom britain england scotland europe europa latam latin latina emea apac asia india china japan korea
australia zealand africa israel turkey russia ukraine eu uk
""".split())

LANGS = {
    "francais": "fr", "deutsch": "de", "nederlands": "nl", "polski": "pl", "svenska": "sv", "russkiy": "ru",
    "русский": "ru",
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
WORKING = re.compile(r"\b(?:work\w*|trabaj\w*|employ\w*|empleado)\b|experienc")
YEARS_EXEMPT = re.compile(r"\b(?:old|age|edad|notice|preaviso|live\w*|reside\w*|residen\w*|located|based|ubicad\w*|"
                          r"viv\w+|duration|length)\b")
EXP_WORDS = re.compile(r"experienc|proficien|skill|knowledge|conoc|familiar")
# Questions about pay, availability, legal status, location, contact details or consent: a number or a name there
# is not a claim of experience. EN + ES, folded.
NON_CLAIM_WORDS = set("""
salary salaries salario salarios sueldo sueldos compensation remuneracion wage wages pay hourly tarifa tarifas
notice preaviso available availability disponible disponibilidad incorporacion
relocate relocating relocation reubicacion reubicarte reubicarse mudarte mudarse mudanza
visa visas sponsor sponsorship sponsoring patrocinio patrocinar
authorize authorized authorised authorization authorisation autorizado autorizada autorizacion permit permits permiso
permisos citizen citizens citizenship ciudadano ciudadania nationality nacionalidad age edad 18
expectation expectations expectativa expectativas pretension pretensiones
country countries pais paises city cities ciudad ciudades location locations ubicacion ubicaciones residence
residency resident residente reside residencia timezone hours horas horario horarios
remote remotely remoto remota remotos remotamente
name names nombre nombres apellido apellidos surname email emails e-mail correo correos phone phones telefono
telefonos celular movil linkedin portfolio portafolio website referral referrals referred referido
gender genero pronoun pronouns consent consento consiento terms terminos privacy privacidad policy politica
policies agree agreed agreement acepto aceptas acuerdo gdpr newsletter
disability disabilities discapacidad veteran veterans race ethnic ethnicity etnia raza drug drugs
employer employers empleador address direccion zip postal
why motivation motivations motivated motivacion summary resumen
confirm confirmed confirmation confirmo acknowledge acknowledged declare declared declaro attest reconozco
old older adult adults mayor mayores edad accept accepts
whats whos wheres hows whens whys youre youd youve youll im ive dont doesnt isnt arent wont cant theres thats lets
hasnt havent hadnt wasnt werent wouldnt couldnt shouldnt didnt there know
player well enjoy enjoying collaborate collaborative collaboration together others communicate communication adapt
adaptable learn learner fast motivated problem solving equipo gusta disfrutas colaborar obtained undergo
completo parcial te
located based live living lives reside resides ubicado ubicada vives vive vivo est edt cst pst mst eastern central
pacific mountain gmt utc cet overlap comfortable model duration
full-time part-time fulltime parttime contract contractor contractors freelance employee employees office oficina
onsite on-site hybrid commute internet connection reliable equipment laptop computer inmediata inmediato
immediately forma modalidad shift shifts weekend weekends travel viajar references reference referencias open
presencial
""".split())
NON_CLAIM_PHRASES = ("per hour", "por hora", "day rate", "start date", "fecha de inicio", "time zone",
                     "zona horaria", "sitio web", "how did you hear", "como te enteraste", "background check",
                     "cover letter", "about yourself", "sobre ti", "tell us about", "por que", "drug test")
# Whole words and phrases only: "PhoneGap" and "Confirmit" are not about phones or confirming.
NON_CLAIM = re.compile(r"(?<![\w.-])(?:" + "|".join(sorted(NON_CLAIM_WORDS | set(NON_CLAIM_PHRASES), key=len,
                                                        reverse=True)) + r")(?![\w-]|\.\w)")
# Role and domain words: not generic, so a question or answer that names one needs profile text behind it.
ROLE_TERMS = set("""
developer developers dev programmer engineer engineers analyst specialist consultant backend frontend fullstack web
senior lead teamlead mobile devops qa architect manager scrummaster dataengineer dataanalyst datascientist
productmanager projectmanager director principal
""".split())
# In an answer every role word needs profile text behind it, backend and developer included.
ROLE_ANS = ROLE_TERMS - {"web"}
ADVERBS = set("""
fluently natively currently previously recently mainly mostly directly remotely fully really only early daily weekly
monthly yearly approximately roughly professionally personally commercially successfully independently actively
extensively heavily regularly occasionally primarily specifically ideally highly actually totally mostly
nearly usually normally typically generally
actualmente anteriormente recientemente principalmente directamente completamente fluidamente nativamente
aproximadamente totalmente normalmente generalmente
""".split())
NUMTOK = re.compile(r"\d+(?:[.,]\d+)?(?:[-+]\d+(?:[.,]\d+)?)?\+?(?:k|m|st|nd|rd|th|x|%)?|"
                    r"\d+-(?:months?|years?|weeks?|days?|hours?|mes|meses)")
WORD_YEARS = {2: 0, 3: 1, 4: 2, 5: 3, 6: 5}  # beginner, intermediate, professional, advanced, expert: years behind
MONEY = set("""
usd eur gbp mxn cop ves ars clp pen brl cad k m mil month months mes meses year years yearly annual monthly mensual
anual ano anos hour hr hora per por a al negotiable negociable gross net bruto neto approx approximately aprox
before after tax taxes impuestos and y or o around circa to
""".split())
SALARY_Q = re.compile(r"\b(?:salary|salaries|salario|salarios|sueldo|compensation|wage|pay|hourly|remuneracion)\b")
# Questions whose answer is a place, a name or a link: proper names in the answer are fine there.
PLACE_Q = re.compile(r"located|based|\blive\b|living|\blives\b|reside|ubicad|\bvives?\b|vivo|"
                     r"country|pais|city|ciudad|location|ubicacion|residen|address|direccion|"
                     r"\bzip\b|postal|\bname\b|nombre|apellido|surname|employer|empleador|linkedin|github|portfolio|"
                     r"portafolio|website|sitio web|hear|referr|referid|enteraste|citizen|nationality|nacionalidad|"
                     r"gender|genero|pronoun|time ?zone|zona horaria|school|university|universidad|company|empresa")
EDU_Q = re.compile(r"\b(?:degree|doctoral|bachelor\w*|licenciatur\w*|masters?|maestri\w*|msc|bsc|mba|phd|doctorate|"
                   r"doctorado|diploma|titulo|grado|graduate|universit\w*|education|educacion|estudios|carrera)\b")
CERT_Q = re.compile(r"\bcertif\w*|\bcertificad\w*")
EDU_RANKS = ((3, r"\b(?:phd|doctor\w*)\b"),
             (2, r"\b(?:master\w*|maestri\w*|msc|ms|mba|posgrado|postgrad\w*|advanced degree|"
                 r"graduate degree)\b"),
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


ROLE_PHRASES = tuple((re.compile(rx), w) for rx, w in (
    (r"\bfront[- ]?end\b", "frontend"), (r"\bback[- ]?end\b", "backend"), (r"\bfull[- ]?stack\b", "fullstack"),
    (r"\b(?:team|tech|technical) lead(?:er)?\b", "teamlead"), (r"\bdata engineer\w*", "dataengineer"),
    (r"\bdata analy\w+", "dataanalyst"), (r"\bdata scien\w+", "datascientist"),
    (r"\bscrum master\b", "scrummaster"), (r"\bproduct manager\b", "productmanager"),
    (r"\bproject manager\b", "projectmanager"), (r"\bmobile (?:phone|number|no\.?|telephone)\b", "phone number"),
))
DOTNET = re.compile(r"(?<![\w.])\.net\b|\bdot ?net\b")


def fold(text):
    """Lowercase, no accents, no apostrophes (NFKC first): the form every comparison here uses."""
    t = unicodedata.normalize("NFKC", str(text)).lower().replace("'", "").replace("’", "")
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    t = DOTNET.sub("dotnet", t)  # ".NET" and "dot net" are one word, not the stop word "net"
    for rx, word in ROLE_PHRASES:  # "front-end", "data analyst"... are one role word each
        t = rx.sub(word, t)
    return t


KNOWN_TOK = {t for t in KNOWN_TECH if t not in AMBIGUOUS and TOKEN.fullmatch(t)}


def is_stop(tok):
    if tok in KNOWN_TOK:  # a technology name is always a claim term, whatever the stop rules say
        return False
    return (tok in STOP or tok in RANK or tok in PLACES or tok in NON_CLAIM_WORDS or tok in ADVERBS
            or CEFR.fullmatch(tok) is not None or not any(c.isalnum() for c in tok)
            or NUMTOK.fullmatch(tok) is not None)


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
    words = max((RANK.get(t) or RANK.get(t[:-2], 0) if t.endswith("ly") else RANK.get(t, 0)
                  for t in re.findall(r"[a-z0-9]+", text)), default=0)
    return max([words] + [r for p, r in PHRASES.items() if p in text])


_NUMW = {}
for _words in ("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
               "seventeen eighteen nineteen twenty", "uno dos tres cuatro cinco seis siete ocho nueve diez once doce "
               "trece catorce quince dieciseis diecisiete dieciocho diecinueve veinte"):
    _NUMW.update({w: i for i, w in enumerate(_words.split(), 1)})
_NUMW["una"] = 1
_SPELLED = re.compile(r"\b(" + "|".join(_NUMW) + r")\b(?=\s*\+?\s*(?:years?|yrs?|anos?|months?|meses))")


DECADES = re.compile(r"\b(\d+|" + "|".join(_NUMW) + r")\s+(?:decades|decadas)\b")
COUPLE_DECADES = re.compile(r"\b(?:a )?couple of decades\b|\bun par de decadas\b")
HALF_DECADE = re.compile(r"\bhalf an? decade\b|\bmedia decada\b")
DECADE = re.compile(r"\b(?:(?:a|one|un|una)\s+)?(?:decade|decada)\b")


def spell(v):
    """The folded answer with spelled numbers (one..twenty, uno..veinte) as digits: "ten years" is "10 years";
    a lone "three" is 3."""
    v = HALF_DECADE.sub("5 years", v)
    v = DECADES.sub(lambda m: f"{int(m.group(1)) * 10 if m.group(1).isdigit() else _NUMW[m.group(1)] * 10} years", v)
    v = COUPLE_DECADES.sub("20 years", v)
    v = DECADE.sub("10 years", v)
    v = _SPELLED.sub(lambda m: str(_NUMW[m.group(1)]), v)
    return str(_NUMW[v.strip()]) if v.strip() in _NUMW else v


SCALE_RX = re.compile(NUM + r"\s*(?:-|to|a)\s*" + NUM)
OUT_OF = re.compile(r"(?:out of|sobre)\s*(\d+)")
SLASH = re.compile(r"/\s*(\d+)")
RATING_Q = re.compile(r"\brat(?:e|ing)\b|skill level|level of|proficiency|\bscore\b|\bnivel|calific|puntu|self-?assess")
RATING_A = re.compile(NUM + r"(?:\s*/\s*(\d+))?\s*%?")


ARITH = re.compile(r"\d\s*[*x/+]\s*\d")
NO_RANGE = re.compile(r"\d+\s*(?:-|to|a)\s*\d+")


def rating_of(v):
    """(number, scale top or None) if the folded answer is a bare rating such as "8", "8/10" or "80%"."""
    m = RATING_A.fullmatch(v.strip())
    if not m:
        return None
    return float(m.group(1).replace(",", ".")), float(m.group(2)) if m.group(2) else 100.0 if "%" in v else None


def scale_of(t, opts):
    """(low, high) of the numeric scale a folded question or its options show, or None."""
    if "%" in t or "porcentaje" in t:
        return 0.0, 100.0
    if m := SCALE_RX.search(t):
        lo, hi = float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
        if hi > lo:
            return lo, hi
    if m := OUT_OF.search(t) or SLASH.search(t):
        return 0.0, float(m.group(1))
    nums = [float(o) for o in map(str, opts) if re.fullmatch(r"\d+", o.strip())]
    return (min(nums), max(nums)) if len(nums) >= 2 else None


INTERJ = re.compile(r"^\W*(?:no (?:doubt|question|complaints?|problem|worries|way)|not a problem|sin duda|por supuesto|"
                    r"of course|absolutely|certainly)\W*")


def answer_kind(v):
    """"yes", "no" or None for a folded answer. It is a no only when its first clause is a governed negation
    ("No", "No tengo", "I have never used it"); "No complaints, C2" and "No less than 8" are not. Interjections
    such as "No doubt," are skipped: "No doubt, yes" is a yes."""
    v = INTERJ.sub("", v)
    clauses = [c for c in CLAUSES.split(v) if c and c.strip()]
    if clauses and negated(clauses[0]):
        return "no"
    words = re.findall(r"[a-z0-9]+", clauses[0] if clauses else v)
    return "yes" if words and words[0] in YES else None


AGE = re.compile(r"(?:(?:at least|minimum|more than|over|m[aá]s de)\s*)?\d+\s*\+?\s*(?:years?|yrs?|a[nñ]os?)\s*"
                 r"(?:old|of age|de edad)|mayor(?:es)? de\s*\d+", re.I)


def threshold(text):
    """The most years a question asks for ("at least 5 years", "7+ years", "más de 5" is 6), or None. An age
    ("18 years old") is not an experience threshold."""
    text = AGE.sub(" ", text)
    nums = [float(m.replace(",", ".")) + 1 for m in MORE_THAN.findall(text)]
    nums += [float((a or b).replace(",", ".")) for a, b in AT_LEAST.findall(text)]
    return max(nums, default=None)


# "(since 2015)", "desde 2015", "(2015-2020)": a date, not a duration.
SINCE = re.compile(r"\([^)]*\b(?:19|20)\d\d\b[^)]*\)|\b(?:since|desde|from)\s+(?:19|20)\d\d\b")


def years_in(v, months_q, low):
    """Years written in the folded answer `v`, or None. "3-5" is 3 when `low` (an option's lower bound) and 5
    otherwise; "less than 1" is 0. Months count /12 when the answer or (for a bare number) the question says
    months; "1 year 6 months" adds up."""
    v = SINCE.sub(" ", v)
    units = UNIT_RX.findall(v)
    in_months = {u[0] == "m" for _, u in units}
    if len(in_months) == 2:
        return sum(float(n.replace(",", ".")) / (12 if u[0] == "m" else 1) for n, u in units)
    nums = list(PLAIN_NUMBER.finditer(v))
    if not nums:
        return None
    head = v[:nums[0].start()]
    values = [float(m.group().replace(",", ".")) for m in nums]
    if re.search(r"(?<!no )(?<!not )(?<!never )less than|under|up to|(?<!no )menos de|hasta|<", head) and (
            low or values[0] <= 1):
        return 0.0
    n = min(values) if low else max(values)
    if re.search(r"more than|over|mas de|greater than|above|mayor a|superior a|>", head):
        n += 1  # "more than 3" claims more than 3
    return n / 12 if in_months == {True} or (months_q and not units) else n


def _chunk(rest):
    """The tokens of the clause that starts `rest` (folded)."""
    return TOKEN_OR_COMMA.findall(re.split(r"[;:!?\n(]|\.(?:\s|$)", rest, maxsplit=1)[0][:150])


GENERIC_ADJ = set("""
professional relevant hands-on handson industry overall total solid proven practical real-world commercial strong
extensive deep good great software work working full-time related
""".split())


def _after(rest):
    """What an answer says a claim is about, in the clause after "3 years of" / "experience with": None if it
    is not about experience, [] if it is generic ("3 years of experience"), else the technology groups."""
    toks = _chunk(rest)
    i, generic = 0, False
    while i < len(toks) and (toks[i] in PREP or toks[i] in GENERIC_ADJ):
        generic = generic or toks[i] in GENERIC_ADJ
        i += 1
    if i == len(toks):
        return [] if generic else None
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
SCRUM = re.compile(r"\bscrum masters?\b")
CERTIFIED = re.compile(r"\b(?:certified|certificad[oa])\b")
ANS_DEG = re.compile(r"\b(?:phd|doctorate|doctorado|doctoral|doctor of philosophy|masters?|maestria|mba|msc|"
                     r"m\.sc|ms|m\.s|bachelors?|licenciatura|"
                     r"bsc|posgrado|postgrad\w*|advanced degree|graduate degree|degree|undergraduate|"
                     r"college degree|graduated|graduate of|titulo|carrera|ingenieria en|ingeniero en)\b")
BILINGUAL = re.compile(r"\bbilingu\w*|\bnative[- ]level|\bnativ[eo][- ]?(?:speaker|proficiency)|\bnivel nativo|"
                       r"\bnative proficiency|\bfull proficiency")
# A clause that starts with a negation says nothing about the profile ("No", "I have not used X yet"); "not just X",
# "no one" and "no other" do not negate. Clauses end at . ; ! ? : , " - " and "but".
# A clause is skipped only when the negation governs the claim: "no", "not yet", "I have never used X", "no tengo
# experiencia con X". "No doubt I am a X expert", "I never stopped using X" or "not just X" are claims.
BARE_NO = re.compile(r"(?:no|nope|none|ninguno|ninguna|nada|false|0|n/a|not yet|not really|never|nunca|not|"
                     r"no thanks|no gracias|no tengo|no he|(?:i |yo )?(?:do not|dont|did not|didnt|have not|havent|"
                     r"am not|have none)(?: (?:have|any|yet))*)\W*")
NEG_GOV = re.compile(r"^\W*(?:(?:i|yo)\s+)?(?:(?:have|has|had|do|did|am|was|he|hemos|ha)\s+)?"
                     r"(?:not|never|nunca|no|havent|dont|didnt)\s+(?:(?:yet|todavia|aun|ever|really|actually|any|have|ha|he)\s+)*"
                     r"(?:used|use|worked|work|working|experience|knowledge|tengo|usado|trabajado|touched|done|programmed|"
                     r"coded|written|had|conocimientos?|experiencia|usar|trabaje)\b")
NEG_BLOCK = re.compile(r"\b(?:doubt|problem|stopped|stop|without|sin|only|just|solo|solamente|except|excepto|even|also|"
                       r"tambien|more than|day)\b")
CLAUSES = re.compile(r"[.;!?:\n]+|,\s|\s[-\u2013\u2014]\s|"
                     r"\b(?:but|pero|however|although|aunque|while|whereas|though)\b|"
                     r"\b(?:and|y)\s+(?=(?:i|yo|we|my|mi|have|am|soy|tengo)\b)", re.I)
FILLER = re.compile(r"(?:thanks|thank you|gracias|sorry|please|yet|todavia|aun|really|at all|for now|por ahora)\W*")


def negated(clause):
    f = fold(clause).strip()
    return bool(BARE_NO.fullmatch(f) or FILLER.fullmatch(f) or (NEG_GOV.match(f) and not NEG_BLOCK.search(f)))


def positive(raw):
    """The answer without its negated clauses: "" if all of it is negated, `raw` itself if none is."""
    clauses = [c for c in CLAUSES.split(raw) if c and c.strip()]
    keep = [c for c in clauses if not negated(c)]
    if len(keep) == len(clauses):
        return raw
    return ". ".join(c.strip() for c in keep)


TEAM = re.compile(r"\b(managed|managing|manage|handled|handling|led|leading|lead|supervised|supervising|mentored|"
                  r"mentoring|coordinat\w*|directed|lider\w*|dirig\w*|gestion\w*)\b[^.;!?]{0,30}?\b(?:\d+|"
                  + "|".join(_NUMW)
                  + r"|teams?|people|others|employees?|members|direct reports|engineers|developers|equipos?|personas|"
                  r"empleados|colaboradores|staff|interns|juniors|reports)\b")
MANAGING = re.compile(r"manag\w*|led|lead\w*|supervis\w*|mentor\w*|coordin\w*|direct\w*|lider\w*|dirig\w*|gestion\w*")
MGMT_VERB = (r"(?:manag\w*|handl\w*|led|lead(?:ing)?|supervis\w*|mentor\w*|coordinat\w*|direct(?:ed|ing)|lider\w*|"
             r"gestion\w*|dirig\w*)")
MGMT_OBJ = (r"(?:teams?|people|others|employees?|members|direct reports|engineers|developers|equipos?|personas|"
            r"empleados|colaboradores|staff|reports|juniors|interns)")
MGMT_Q = re.compile(r"\b" + MGMT_VERB + r"\b[^.?!;]{0,30}?\b" + MGMT_OBJ + r"\b|"
                    r"\bexperience (?:in )?(?:managing|leading|supervising)\b|\bpeople management\b|"
                    r"\bteam management\b")
SINCE_YEAR = re.compile(r"\b(?:since|desde)\s+((?:19|20)\d\d)\b")
DOING = re.compile(r"cod(?:e|ing)|program\w*|develop\w*|software|engineer\w*|work(?:ed|ing)|using|used|experience|"
                   r"experiencia|trabaj\w*|desarroll\w*|usando|building|built")
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


def _tech_like(word, start, after, names=True):
    """The word of a free-text answer looks like a technology or proper name: letters with digits or + # .,
    CamelCase, ALL-CAPS, or a capitalised word that does not just start a sentence."""
    f = fold(word)
    if not any(c.isalpha() for c in word) or f in COMMON_CAPS or f in STOP and not word.isupper():
        return False
    if CEFR.fullmatch(f) or ORDINAL.fullmatch(f) or re.fullmatch(r"(?:utc|gmt)[+-]?\d*", f):
        return False
    if any(c.isdigit() for c in word) or any(c in word for c in "+#."):
        return True
    if names and (re.search(r"[a-z][A-Z]", word) or len(word) >= 2 and word.isupper()):
        return True  # CamelCase and ALL-CAPS: a place or a job board ("LinkedIn", "LATAM") answers a place question
    if names and word[0].isupper() and f not in STOP and f not in LANGS:
        return not start or SENTENCE_START.match(after) is not None
    return False


def answer_runs(raw, names=True):
    """The runs of adjacent technology-like words in a free-text answer, as lists of folded tokens."""
    runs, cur, last = [], [], 0
    for m in WORD.finditer(raw):
        before = raw[:m.start()].rstrip(" \t\"'(*•-¿¡")
        start = not before or before[-1] in ".!?\n"
        if _tech_like(m.group(), start, raw[m.end():m.end() + 12], names):
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
        self.known = set(TOKEN.findall(fold(" ".join(text))))
        # Links and addresses the profile or a rule of the user holds: a contact-link answer equal to one is backed.
        # A rule's other values do not back claims: a rule cannot make "Kubernetes expert" true.
        rules = [r["value"] for r in (profile or {}).get("fixed_answers") or []
                 if isinstance(r, dict) and isinstance(r.get("value"), str)]
        self.links = {fold(x).strip() for x in text + rules if re.search(r"://|@|^www\.", x)}

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

    def _topic(self, q, named=True):
        """The folded question is only about a non-claim topic (pay, dates, place, consent...): once its topic
        words are removed it names no skill, language, degree, certificate or technology. A `named` topic must
        also say which one; a legend (`named` False) may be neutral but must claim no experience."""
        if not named and (YEARS_Q.search(q) or threshold(q)):
            return False
        if YEARS_Q.search(q) and WORKING.search(q) and not YEARS_EXEMPT.search(q):
            return False  # years of working are years of experience, whatever follows
        return ((not named or bool(NON_CLAIM.search(q))) and not EXP_WORDS.search(q)
                and not groups(LANG_RX.sub(" ", q))
                and not (LANG_RX.search(q) or EDU_Q.search(q) or CERT_Q.search(q) or PURE_CERT.search(q)
                         or known_tech(q)))

    def years_q(self, text):
        t = fold(text)
        return bool(YEARS_Q.search(t)) and not self._topic(t)

    def named(self, text):
        """The profile skills a question names."""
        return self.resolve(groups(LANG_RX.sub(" ", fold(text))))[0]

    def stated_years(self, text, value):
        """The years a number or text answer states, or None."""
        return years_in(fold(value), bool(MONTHS.search(fold(text))), low=False)

    def check(self, field, text, value, fixed=False):
        """(ok, reason) for the resolved `value` of `field` under the question `text`. A `fixed` value is the
        user's own rule: the question is not checked, but the value cannot claim a technology, role, degree,
        certificate or language the profile lacks."""
        if not self.enabled:
            return True, ""
        if fold(value).strip() in self.links:
            return True, ""
        value = positive(str(value))  # what is left once the negated clauses are out
        if not value.strip():
            return True, ""  # a bare "No" claims nothing
        t, v = fold(text), spell(fold(value))
        if "decad" in v:
            return False, "the answer counts in decades in a way that cannot be read"
        kind = answer_kind(v)
        why = ""
        free = field["type"] in ("text", "textarea")
        if fixed:  # the rule answers its label; a legend that claims experience is still checked
            legend = field.get("context") or ""
            why = ""
            if legend and not self._topic(fold(legend), named=False):
                why = self.check({**field, "question": legend, "context": ""}, legend, value)[1]
            why = why or self._answer_claims(str(value), "", True)
            if not why and re.search(r"\d", v):  # a number a rule gives for a question is checked like any other
                why = self.check(field, text, value)[1]
            return not why, why
        if field["type"] in ("text", "textarea") and SALARY_Q.search(fold(field.get("question") or text)) and [
                tok for tok in TOKEN.findall(v) if not NUMTOK.fullmatch(tok) and tok not in MONEY]:
            return False, "a pay answer is a number and a currency, nothing else"
        if MGMT_Q.search(t) and not self._manages():
            return False, "claims to have managed or led people, which the profile does not back"
        q, ctx = fold(field.get("question") or text), fold(field.get("context") or "")
        topic = self._topic(q) and (not ctx or self._topic(ctx, named=False))  # label and legend both
        if self.facts:
            why = self._language(t, v, kind, field.get("options") or ()) or self._credential(t, v, kind)
        why = why or self._skill_claim(field, text, t, v, kind, topic)
        if not why and free:
            why = self._answer_claims(str(value), t, topic and bool(PLACE_Q.search(q)))
        elif not why and field.get("options") and kind is None:  # the text of an option claims things too
            why = self._answer_claims(str(value), t, True)
        return not why, why

    def _manages(self):
        return any(MANAGING.fullmatch(tok) for tok in self.known)

    def _language(self, t, v, kind, opts=()):
        if kind == "no":
            return ""
        langs = {LANGS[w] for w in LANG_RX.findall(t)} | {LANGS[w] for w in LANG_RX.findall(v)}
        if not langs:
            if (BILINGUAL.search(t) or BILINGUAL.search(v)) and sum(r >= 6 for r in self.langs.values()) < 2:
                return "claims to be bilingual, which the profile's languages do not back"
            return ""
        level = max(rank(t), 1) if kind == "yes" else rank(v)
        if kind is None and not level and not YEARS_Q.search(t) and (num := rating_of(v)):
            n, top = num
            scale = (0.0, top) if top else scale_of(t, opts)
            if scale is None:
                level = 1 if n <= 1 else None  # a rating on an unknown scale cannot be mapped
            elif scale == (1.0, 5.0):
                level = SCALE.get(str(int(n)), 0)
            else:
                level = 1 + round(min(max((n - scale[0]) / (scale[1] - scale[0]), 0), 1) * 5)
            if level is None:
                return "the language rating is on a scale that cannot be read"
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

    def _unbacked(self, tokens, context, echo="", strict=False):
        """The tokens that neither the profile text, the `echo` (the question an answer repeats) nor (in a
        certificate or degree question or answer, named by `context`) a cert or education fact backs."""
        pool = self.known | set(TOKEN.findall(echo))
        left = [tok for tok in tokens if tok not in pool or (strict and tok in KNOWN_TOK)]
        joined = context
        if left and CERT_CTX.search(joined) and any(set(left) <= c for c in self.certs):
            return []
        if left and EDU_Q.search(joined):
            left = [tok for tok in left if not any(tok in toks for _, toks in self.edu_facts)]
        return left

    def _skill_claim(self, field, text, t, v, kind, topic=False):
        if kind == "no" or topic:  # a pure topic question names nothing the profile could back
            return ""
        opts = field.get("options") or ()
        runs = groups(LANG_RX.sub(" ", t))
        years_q = (bool(YEARS_Q.search(t)) or any(YEARS_Q.search(fold(o)) for o in opts))
        months_q, ftype = bool(MONTHS.search(t)), field["type"]
        rating = None if years_q or LANG_RX.search(t) or not RATING_Q.search(t) else rating_of(v)
        years, exists = None, False
        if ftype == "number":
            if not PLAIN_NUMBER.fullmatch(v.strip()):
                return f"{str(v)[:30]!r} is not a plain number"
            n = float(v.replace(",", "."))
            exists, years = n > 0, (n / 12 if months_q else n) if years_q and n > 0 else None
        elif opts or ftype == "checkbox":
            reads_years = opts and not rating and (years_q or not LANG_RX.search(t))
            own = years_in(v, months_q, low=True) if reads_years else None
            if own is not None:
                exists, years = own > 0 or kind == "yes", own or None
            elif kind in ("yes", None):
                exists, years = True, threshold(text)
        else:
            if years_q and (ARITH.search(v) or not UNIT_RX.search(v) and len(PLAIN_NUMBER.findall(NO_RANGE.sub(
                    " ", SINCE.sub(" ", v)))) > 1):
                return "the answer has more than one number of years"
            counts = years_q or UNIT_RX.search(v) or re.fullmatch(
                r"\W*(?:(?:more than|over|at least|up to|less than|m[a\u00e1]s de)\s*)?[\d.,]+\+?"
                r"(?:\s*[-\u2013]\s*[\d.,]+)?\W*", v)
            n = None if rating or not counts else years_in(v, months_q, low=False)
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
        for name in known_tech(t):  # "Office 365": a phrase the stop words would otherwise swallow
            words = TOKEN.findall(name)
            if len(words) > 1 and not self._skill(words):
                return f"claims experience with {name!r}, which is not in the profile"
        if opts and kind is None:
            runs += groups(LANG_RX.sub(" ", v))  # an option names its own technology: "5+ years with Node.js"
        matched, unmatched = self.resolve(runs)
        unmatched = self._unbacked(unmatched, f"{t} {v}", strict=True)
        if unmatched:
            return f"claims experience with {' '.join(unmatched)!r}, which is not in the profile"
        word = 0 if kind or years_q or rating or LANG_RX.search(t) else rank(v)
        if word and matched:  # "Expert" in Python needs the years of an expert, and not the top of the scale
            for name, have in matched.items():
                if have < WORD_YEARS.get(word, 0):
                    return f"rates {name} above the {have:g} years the profile has"
            ranks = sorted({r for o in opts if (r := rank(fold(o)))})
            if len(ranks) >= 3 and word in ranks and ranks.index(word) > (len(ranks) - 1) / 2:
                return "rates a skill above the middle of the levels offered"
        if rating and matched:  # a self-rating of a profile skill: no higher than the middle of the scale
            n, top = rating
            scale = (0.0, top) if top else scale_of(t, opts)
            if scale is None and n > 1 or scale and n > (scale[0] + scale[1]) / 2:
                return "rates a skill higher than the middle of the scale"
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

    def _answer_claims(self, raw, t, places):
        """A text answer may not name a technology, language, degree or certificate (or years of one) that the
        profile does not back. Each technology-like word must be a skill, be in the question, or be in the
        profile; anything else is rejected. ponytail: a lowercase unknown technology ("kubernetes") is not seen."""
        v = spell(fold(raw))
        for name in known_tech(raw):  # lowercase names count too, on every question
            matched, unmatched = self.resolve([TOKEN.findall(name)])
            if left := self._unbacked(unmatched, f"{t} {v}"):
                return f"the answer names {' '.join(left)!r}, which is not in the profile"
        for tok in TOKEN.findall(v):
            if tok in ROLE_ANS and tok not in self.known:
                return f"the answer names the role {tok!r}, which is not in the profile"
        if re.search(r"\bhead of\b", v) and "head" not in self.known:
            return "the answer names the role 'head', which is not in the profile"
        if TEAM.search(v) and not self._manages():
            return "the answer claims to have managed or led people, which the profile does not back"
        for run in answer_runs(raw, names=not places):  # a place or a name answers a place question
            matched, unmatched = self.resolve([run])
            if left := self._unbacked(unmatched, f"{t} {v}"):
                return f"the answer names {' '.join(left)!r}, which is not in the profile"
        for runs, years in mentions(v):
            matched, unmatched = self.resolve(runs)
            if left := self._unbacked(unmatched, f"{t} {v}"):
                return f"the answer claims experience with {' '.join(left)!r}, which is not in the profile"
            if why := self._years_within(matched, years):
                return "the answer " + why
        return self._answer_levels(v) or self._answer_since(v) or (self._answer_credentials(v) if self.facts else "")

    def _answer_levels(self, v):
        """"Expert in Python": a level word next to a profile skill needs the years of that level."""
        for clause in re.split(r"[.;!?\n]", v):
            toks = TOKEN_OR_COMMA.findall(clause)
            for i, tok in enumerate(toks):
                word = RANK.get(tok) or RANK.get(tok[:-2], 0) if tok.endswith("ly") else RANK.get(tok, 0)
                word = 6 if tok in ("mastered", "guru", "senior-level") else word
                if word < 3 or tok in LANGS:
                    continue
                for j in [*range(i - 1, max(i - 5, -1), -1), *range(i + 1, min(i + 5, len(toks)))]:
                    if toks[j] == "," or toks[j] in LANGS:
                        continue
                    if (hit := self._skill([toks[j]])) and hit[1] < WORD_YEARS.get(word, 0):
                        return f"the answer rates {hit[0]} above the {hit[1]:g} years the profile has"
        return ""

    def _answer_since(self, v):
        """"I have been coding since 1999" is 27 years, unless the answer also says how long."""
        if YEARS_RX.search(v):
            return ""
        for clause in re.split(r"[.;!?\n]", v):
            m = SINCE_YEAR.search(clause)
            if not m or not DOING.search(clause):
                continue
            years = datetime.date.today().year - int(m.group(1))
            matched, _ = self.resolve(groups(clause))
            if why := self._years_within(matched, years):
                return "the answer " + why
        return ""

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
        if SCRUM.search(v) and not any("scrum" in c for c in self.certs):
            return "the answer claims a certification, which is not in the profile"
        degrees = ANS_DEG.findall(SCRUM.sub(" ", v))
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
