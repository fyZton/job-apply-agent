"""Everyday screening questions, English and Spanish, with the truthful answer for profile.example.yaml.

Every row must be accepted by the honesty check: a check that rejects ordinary questions is as broken as one that
lets claims through. The last table holds the honest No / 0 / None variants.
"""
from pathlib import Path

import pytest
import yaml

from jobagent.claims import Claims
from jobagent.facts import load_facts

PROFILE = yaml.safe_load((Path(__file__).parent.parent / "profile.example.yaml").read_text(encoding="utf-8"))
CLAIMS = Claims(load_facts(PROFILE), None, PROFILE)
YN = ["Yes", "No"]
SN = ["Sí", "No"]
EMP = ["Employed", "Unemployed", "Student", "Self-employed"]
EDU = ["High school", "Bachelor's", "Master's", "PhD"]
LEVELS = ["Basic", "Intermediate", "Upper intermediate", "Advanced", "Native"]
TEN = [str(i) for i in range(1, 11)]

ROWS = [
    # age
    ("radio", "Are you at least 18 years old?", YN, "Yes"),
    ("radio", "Are you 18 years of age or older?", YN, "Yes"),
    ("radio", "Are you over 18?", YN, "Yes"),
    ("radio", "¿Eres mayor de edad?", SN, "Sí"),
    ("radio", "¿Tienes más de 18 años?", SN, "Sí"),
    # availability and start date
    ("text", "When can you start?", None, "In 2 weeks"),
    ("text", "Earliest start date", None, "Immediately"),
    ("text", "Disponibilidad para empezar", None, "Inmediata"),
    ("radio", "¿Tienes disponibilidad inmediata?", SN, "Sí"),
    ("radio", "Are you available to start immediately?", YN, "Yes"),
    ("number", "How long is your notice period? (weeks)", None, "2"),
    ("text", "What's your notice period?", None, "2 weeks"),
    ("text", "¿Cuál es tu periodo de preaviso?", None, "2 semanas"),
    # schedule and contract
    ("radio", "Are you available to work full-time?", YN, "Yes"),
    ("radio", "Are you open to part-time work?", YN, "Yes"),
    ("radio", "Are you open to contract work?", YN, "Yes"),
    ("radio", "Are you willing to work on a contract basis?", YN, "Yes"),
    ("radio", "Are you open to freelance projects?", YN, "Yes"),
    ("radio", "Can you work from our office 3 days a week?", YN, "Yes"),
    ("radio", "Can you work in a hybrid model?", YN, "Yes"),
    ("radio", "Are you comfortable working remotely?", YN, "Yes"),
    ("radio", "Are you comfortable with a 3-month contract?", YN, "Yes"),
    ("radio", "Do you have a reliable internet connection?", YN, "Yes"),
    ("radio", "Do you have the equipment you need to work from home?", YN, "Yes"),
    ("radio", "¿Aceptas trabajar de forma remota?", SN, "Sí"),
    ("text", "Modalidad de trabajo preferida", None, "Remoto"),
    ("select", "Preferred work mode", ["On-site", "Hybrid", "Remote"], "Remote"),
    # work authorization
    ("radio", "Are you legally authorized to work in Spain?", YN, "Yes"),
    ("radio", "Will you now or in the future require visa sponsorship?", YN, "No"),
    ("radio", "Do you require sponsorship to work in the United States?", YN, "No"),
    ("radio", "¿Tienes autorización para trabajar en España?", SN, "Sí"),
    ("radio", "¿Necesitas patrocinio de visa?", SN, "No"),
    # location
    ("text", "Where are you located?", None, "Caracas, Venezuela"),
    ("text", "Where are you based?", None, "Caracas"),
    ("text", "Where do you live?", None, "Caracas"),
    ("text", "Current city", None, "Caracas"),
    ("text", "Country of residence", None, "Venezuela"),
    ("text", "País", None, "Venezuela"),
    ("text", "Ciudad", None, "Caracas"),
    ("radio", "Are you based in Venezuela?", YN, "Yes"),
    ("radio", "Are you located in LATAM?", YN, "Yes"),
    ("text", "What's your time zone?", None, "UTC-4"),
    ("radio", "Can you work in the EST time zone?", YN, "Yes"),
    ("radio", "Can you overlap 4 hours with US Eastern time?", YN, "Yes"),
    ("text", "¿Cuál es tu zona horaria?", None, "UTC-4"),
    # salary
    ("number", "What's your expected salary?", None, "1800"),
    ("number", "Expected monthly salary in USD", None, "1800"),
    ("number", "Pretensión salarial", None, "1800"),
    ("number", "Pretensión salarial (USD)", None, "1800"),
    ("number", "Aspiración salarial", None, "1800"),
    ("number", "Expectativa salarial", None, "1800"),
    ("number", "Salario deseado", None, "1800"),
    ("number", "Sueldo pretendido", None, "1800"),
    ("text", "Salary expectations", None, "1800 USD per month"),
    ("number", "Expected hourly rate in USD", None, "12"),
    # how did you hear
    ("text", "How did you hear about us?", None, "LinkedIn"),
    ("text", "How did you hear about this vacancy?", None, "LinkedIn"),
    ("text", "How did you hear about this opportunity?", None, "Indeed"),
    ("text", "¿Cómo te enteraste de esta vacante?", None, "Computrabajo"),
    ("text", "¿Cómo te enteraste de la oferta?", None, "LinkedIn"),
    ("text", "¿Cómo te enteraste de nosotros?", None, "LinkedIn"),
    # employment status and title
    ("radio", "Are you currently employed?", YN, "Yes"),
    ("radio", "¿Actualmente empleado?", SN, "Sí"),
    ("select", "What is your employment status?", EMP, "Employed"),
    ("select", "Current employment status", EMP, "Employed"),
    ("select", "Employment status", EMP, "Employed"),
    ("select", "Situación laboral actual", ["Empleado", "Desempleado", "Estudiante"], "Empleado"),
    ("select", "¿Cuál es tu situación laboral?", ["Empleado", "Desempleado"], "Empleado"),
    ("text", "What is your current job title?", None, "Backend Developer"),
    ("text", "Current employer", None, "Acme"),
    # generic and profile-skill years
    ("number", "How many years of experience do you have?", None, "3"),
    ("number", "What's your total years of experience?", None, "3"),
    ("number", "Years of experience in software engineering", None, "3"),
    ("number", "How many years of experience do you have with Python?", None, "3"),
    ("number", "Years of experience with SQL", None, "2"),
    ("number", "¿Cuántos años de experiencia tienes con Python?", None, "3"),
    ("number", "How much Python experience do you have?", None, "3"),
    ("number", "Years working with Docker", None, "1"),
    ("radio", "Do you have Python experience?", YN, "Yes"),
    ("radio", "Can you work with Python?", YN, "Yes"),
    ("radio", "Do you have a minimum of 3 years of Python?", YN, "Yes"),
    ("radio", "Do you have advanced knowledge of Python?", YN, "Yes"),
    ("radio", "¿Tienes experiencia con SQL?", SN, "Sí"),
    ("radio", "Have you used Docker?", YN, "Yes"),
    ("radio", "Do you have experience building REST APIs?", YN, "Yes"),
    ("textarea", "Tell us about yourself", None, "I have 3 years of Python experience building REST APIs."),
    ("textarea", "Why do you want to work here?", None,
     "I like your remote-first culture and I have 3 years of Python."),
    # English level
    ("select", "English level", ["A2", "B1", "B2", "C1"], "B2"),
    ("select", "What's your English proficiency?", LEVELS, "Upper intermediate"),
    ("select", "What is your proficiency in English?", ["Limited working proficiency",
                                                       "Professional working proficiency"],
     "Professional working proficiency"),
    ("select", "¿Nivel de inglés?", ["Básico", "Intermedio", "Intermedio alto", "Avanzado"],
     "Intermedio alto"),
    ("select", "Rate your English from 1 to 10", TEN, "6"),
    ("radio", "Do you speak English?", YN, "Yes"),
    ("radio", "Do you speak Spanish?", YN, "Yes"),
    ("radio", "Is Spanish your first language?", YN, "Yes"),
    ("radio", "Are you a native Spanish speaker?", YN, "Yes"),
    # education
    ("select", "Highest education", EDU, "Bachelor's"),
    ("select", "Highest degree obtained", EDU, "Bachelor's"),
    ("select", "Education level", ["High school", "Bachelor's degree", "Master's degree"], "Bachelor's degree"),
    ("text", "What is your highest level of education?", None, "B.Sc. Computer Science"),
    ("select", "Grado de instrucción", ["Secundaria", "Universitario", "Posgrado"], "Universitario"),
    ("select", "¿Nivel de estudios?", ["Secundaria", "Universitario", "Posgrado"], "Universitario"),
    ("radio", "Do you have a university degree?", YN, "Yes"),
    ("radio", "Do you have a Bachelor's degree?", YN, "Yes"),
    # teamwork
    ("radio", "Are you a team player?", YN, "Yes"),
    ("radio", "Can you work well in a team?", YN, "Yes"),
    ("radio", "Do you work well with others?", YN, "Yes"),
    ("radio", "Do you enjoy working in a team?", YN, "Yes"),
    ("radio", "¿Te gusta trabajar en equipo?", SN, "Sí"),
    # motivation
    ("textarea", "Why do you want to join our team?", None,
     "I like building backend services in Python and the role is fully remote."),
    ("textarea", "What interests you about this role?", None, "I like building backend services in Python."),
    ("textarea", "¿Por qué quieres trabajar con nosotros?", None,
     "Me gusta construir servicios backend en Python y el puesto es remoto."),
    ("textarea", "¿Por qué te interesa este puesto?", None, "Me gusta construir servicios backend en Python."),
    ("textarea", "¿Qué te motiva de esta oferta?", None, "Me gusta construir servicios backend en Python."),
    # consent, privacy, checks
    ("checkbox", "I agree to the privacy policy", None, True),
    ("checkbox", "I accept the terms and conditions", None, True),
    ("checkbox", "I confirm", None, True),
    ("radio", "Do you consent to the processing of your data?", YN, "Yes"),
    ("radio", "Are you willing to undergo a background check?", YN, "Yes"),
    ("radio", "Are you willing to take a drug test?", YN, "Yes"),
    ("radio", "Do you agree to receive phone calls?", YN, "Yes"),
    ("radio", "Can we contact your references?", YN, "Yes"),
    # contact and links
    ("text", "Phone number", None, "+58 400 000 0000"),
    ("text", "Email", None, "alex@example.com"),
    ("text", "First name", None, "Alex"),
    ("text", "Last name", None, "Example"),
    ("text", "LinkedIn profile", None, "https://www.linkedin.com/in/alex-example"),
    ("text", "GitHub", None, "https://github.com/alex-example"),
    ("text", "Portfolio URL", None, "https://github.com/alex-example"),
    ("text", "Website", None, "https://github.com/alex-example"),
]


@pytest.mark.parametrize("type_, question, options, answer", ROWS, ids=[f"{r[1][:48]}|{r[3]}" for r in ROWS])
def test_everyday_questions_are_accepted(type_, question, options, answer):
    field = {"type": type_, "question": question, "context": "", "options": options}
    ok, why = CLAIMS.check(field, question, answer)
    assert ok, why


def test_the_corpus_is_big_enough():
    assert len(ROWS) >= 80


HONEST_NO = [
    ("radio", "Do you have experience with Kubernetes?", YN, "No"),
    ("radio", "¿Tienes experiencia con Kubernetes?", SN, "No"),
    ("number", "How many years of experience do you have with Kubernetes?", None, "0"),
    ("number", "Years of Rust experience", None, "0"),
    ("select", "Kubernetes", ["None", "Some", "Expert"], "None"),
    ("radio", "Do you have a Master's degree?", YN, "No"),
    ("radio", "Do you have a PhD?", YN, "No"),
    ("radio", "Do you speak German?", YN, "No"),
    ("radio", "Do you hold a PMP certification?", YN, "No"),
    ("radio", "Have you managed a team?", YN, "No"),
    ("radio", "Are you an expert in Docker?", YN, "No"),
    ("checkbox", "I hold a PhD", None, False),
    ("checkbox", "I hold a PhD", None, 0),
    ("text", "Do you have Kubernetes experience?", None, "No, I have not used Kubernetes."),
    ("text", "Do you have Kubernetes experience?", None, "No tengo experiencia con Kubernetes."),
    ("textarea", "Anything else?", None, "I have never used Kubernetes."),
    ("radio", "Do you require sponsorship?", YN, "No"),
    ("select", "¿Cuántos años de experiencia tienes con Kubernetes?", ["Sin experiencia", "1-3 años"],
     "Sin experiencia"),
    ("radio", "Do you have Kubernetes experience?", ["No, but willing to learn", "Yes"], "No, but willing to learn"),
    ("select", "Experiencia con Java", ["Sin experiencia", "Avanzada"], "Sin experiencia"),
    ("radio", "¿Experiencia con Kubernetes?", ["No, pero dispuesto a aprender", "Sí"],
     "No, pero dispuesto a aprender"),
    ("text", "Nivel de alemán", None, "No hablo alemán"),
    ("text", "How many people have you managed?", None, "Not applicable"),
    ("text", "¿Personas a cargo?", None, "No aplica"),
    ("select", "Highest level of education", EDU, "High school"),
    ("textarea", "Describe your Kubernetes experience", None, "I have zero Kubernetes experience."),
    ("text", "Do you speak German?", None, "I don't speak German"),
]


@pytest.mark.parametrize("type_, question, options, answer", HONEST_NO, ids=[f"{r[1][:48]}|{r[3]}" for r in HONEST_NO])
def test_honest_no_answers_are_accepted(type_, question, options, answer):
    field = {"type": type_, "question": question, "context": "", "options": options}
    ok, why = CLAIMS.check(field, question, answer)
    assert ok, why
