"""Write src/ai_job_hunter/sectors/templates/finance.json: the finance and administration sector template.

The vocabulary comes from docs/research/sector-templates-2026-10.md (section 4): 11 role families, titles in English,
Spanish, French, German, Dutch, Portuguese and Italian. Word sets are folded the way the title normalizer folds words
(lower case, accents removed). German and Dutch compounds ("Finanzbuchhalter") are caught by regexes on the raw title.
The tests in tests/test_finance_template.py are the golden titles taken from the same research.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUBRIC_SOURCE = ROOT / "docs" / "research" / "finance-rubric-2026-10.json"

SETS = {
    "finance_words": [
        "finance", "financial", "financiero", "financiera", "financieros", "finanzas", "finanzen", "financier",
        "financiers", "finanziario", "finanziaria", "financeiro", "financeira", "financas",
    ],
    "accounting": [
        "accountant", "accountants", "accounting", "accountancy", "bookkeeper", "bookkeeping", "ledger", "r2r",
        "contable", "contables", "contabilidad", "contabilidade", "contabilista", "contabile", "contabili",
        "comptable", "comptables", "comptabilite", "buchhalter", "buchhalterin", "buchhaltung", "boekhouder",
        "boekhouding", "payable", "payables", "receivable", "receivables", "accountspayable", "accountsreceivable",
    ],
    "controlling": [
        "controller", "controllers", "controlling", "controleur", "controleuse", "contralor", "controllo",
    ],
    "fpa": [
        "fpa", "budgeting", "forecasting", "budget",
    ],
    "tax": [
        "tax", "taxes", "fiscal", "fiscalista", "fiscaliste", "fiscalite", "fiscalidad", "fiscalidade", "tributario",
        "tributaria", "tributacao", "vat", "iva", "fiscalist", "steuerberater", "steuerreferent",
    ],
    "payroll": [
        "payroll", "nomina", "nominas", "paie", "paghe", "paye", "salarisadministrateur", "salarisadministratie",
        "entgeltabrechner", "lohnbuchhalter", "lohnbuchhaltung",
    ],
    "treasury": [
        "treasury", "treasurer", "tesoreria", "tesorero", "tesorera", "tesouraria", "tesoureiro", "tesoriere",
        "tresorerie", "tresorier", "tresoriere", "liquidity",
    ],
    "audit": [
        "audit", "auditor", "auditors", "auditoria", "auditeur", "auditrice", "revisor", "revisore", "revisione",
        "commissaire", "wirtschaftsprufer", "prufungsleiter", "prufer", "auditing",
    ],
    "procurement": [
        "procurement", "purchasing", "compras", "comprador", "compradora", "aprovisionamiento", "aprovisionamento",
        "acheteur", "acheteuse", "achats", "einkauf", "einkaufer", "einkauferin", "inkoop", "inkoper", "acquisti",
        "sourcing", "buyer", "abastecimiento",
    ],
    "credit_risk": [
        "credit", "credito", "creditos", "risk", "riesgo", "riesgos", "risque", "risques", "risico", "risiko",
        "rischio", "risco", "collections", "cobros", "recouvrement", "cobranzas", "kreditsachbearbeiter",
    ],
    "bank_ops": [
        "kyc", "kyb", "kycb", "aml", "sanctions", "sanciones", "securities", "settlement", "custody", "custodia",
        "titres", "valores", "wertpapierabwicklung", "middleoffice", "wealth", "fraud",
    ],
    "consolidation": [
        "consolidation", "consolidations", "consolidacion", "consolidatie", "consolideur", "consolidamento", "corep",
        "finrep", "konzernbuchhalter",
    ],
    "admin": [
        "administrativo", "administrativa", "administratif", "administrative", "administration", "administracion",
        "administratief", "administratieve", "amministrativo", "amministrativa", "amministrazione", "backoffice", "sachbearbeiter", "segreteria",
        "verwaltungsangestellter", "secretaria", "secretary",
    ],
    "admin_roles": [
        "assistant", "assistente", "asistente", "auxiliar", "gestionnaire", "specialist", "officer", "clerk",
        "coordinator", "coordinador", "responsable", "manager", "tecnico", "tecnica", "analyst", "executive",
    ],
    "finance_core": [
        "controller", "controllers", "controlling", "accountant", "accounting", "contable", "contabilidad", "comptable",
        "buchhalter", "finance", "financial", "financiero", "financiera", "tax", "payroll", "treasury", "audit", "auditor",
    ],
    "sales": [
        "sales", "ventas", "vendedor", "vendedora", "vertrieb", "vente", "ventes", "verkauf", "comercial",
        "commercial", "sdr", "bdr", "salesperson",
    ],
    "sales_roles": [
        "executive", "manager", "director", "representative", "specialist", "associate", "agent", "agente", "advisor",
        "consultant", "consultor", "development", "developer", "representante",
    ],
    "client_facing": [
        "customer", "cliente", "clientes", "clientele", "clientele", "client", "atencion", "kundenservice",
        "kundenberater", "relationship",
    ],
    "tech": [
        "engineer", "engineering", "developer", "programmer", "devops", "software", "frontend", "backend", "fullstack",
        "architect", "scientist", "sre", "qa", "it", "sistemas", "systems", "infrastructure", "network", "cloud",
        "salesforce", "ai", "ml", "llm", "swe", "cybersecurity",
    ],
    "legal": [
        "legal", "lawyer", "attorney", "counsel", "abogado", "abogada", "avvocato", "juridique", "jurista", "juriste",
        "jurist", "rechtsanwalt", "paralegal",
    ],
    "hr": [
        "hr", "hrbp", "rrhh", "recruiter", "recruiting", "recruitment", "reclutador", "reclutadora", "talent",
        "personalberater", "compensation", "benefits", "humanos", "rh",
    ],
    "insurance_claims": [
        "siniestros", "siniestro", "perito", "claims", "sinistres", "actuary", "actuarial", "actuario", "actuaire",
    ],
    "operations_other": [
        "plant", "hse", "prl", "logistics", "logistica", "warehouse", "almacen", "production", "produccion", "planner",
        "marketing", "marketer", "designer", "writer", "copywriter", "press", "attache", "pmo", "crm", "ehs",
    ],
    "audit_other": [
        "quality", "calidad", "energy", "energia", "energie", "milieu", "environmental", "ambiental", "security",
        "seguridad", "cyber", "cybersecurity", "safety", "iso", "sap", "grc", "energetique",
    ],
    "role_nouns": [
        "manager", "director", "head", "analyst", "assistant", "officer", "specialist", "partner", "associate",
        "executive", "coordinator", "responsable", "gerente", "directeur", "directrice", "leiter", "teamleiter",
        "controller", "expert", "lead", "tecnico", "tecnica", "analista", "analyste", "coordinador", "cfo", "chief",
    ],
}

REGEXES = {
    # German / Dutch compounds the word sets cannot list one by one.
    "accounting_compound": r"buchh[aä]lt|buchf[uü]hr|rechnungswesen|kreditoren|debitoren|boekhoud|contabil|comptab|comptabilit",
    "tax_compound": r"steuer|belasting|fiscali|impuesto|imposta",
    "payroll_compound": r"lohn(?:buch|abrech)|entgelt|salarisadmin|gestionnaire\s+de\s+paie|n[oó]minas?\b",
    "treasury_compound": r"tr[eé]sor|tesorer|tesour|liquidit[aä]t",
    "audit_compound": r"\baudit|pr[uü]fung|revisi[oó]n|commissaire\s+aux\s+comptes|wirtschaftspr",
    "procurement_compound": r"einkauf|inkoop|\bachats?\b|\bcompras\b|aprovision|abastecimiento|procurement|purchasing",
    "credit_compound": r"\bkredit(?!oren)|credit(?:o|\b)|\brisk|riesg|risque|risico|risiko|rischio|\brisco",
    "controlling_compound": r"controll|contr[oô]le(?:ur)?\s+(?:de\s+)?gestion|control\s+de\s+gesti[oó]n",
    "consolidation_compound": r"consolid|konsolid|konzernrechnung|konzernabschluss",
    "bank_ops": r"\bkyc\b|\bkyb\b|\baml\b|sanction|wertpapier|middle\s*office|back\s*office\s+(?:financ|titres|valeurs|bancari|valores)"
                r"|fund\s+(?:admin|operations)|securities|settlement|transfer\s+agen|trading\s+operations|financial\s+operations"
                r"|banking\s+operations|investment\s+data|financial\s+crime|moyens\s+de\s+paiement",
    "reporting": r"accounting\s*(?:and|&)\s*reporting|(?:financial|regulatory|group|statutory|management|esg)\s+reporting|reporting\s+(?:and|&)\s+controls|\breporting\b.*\b(?:ifrs|finance|financial)\b",
    "generic_finance_head": r"\b(?:cfo|chief\s+financial|head\s+of\s+finance|finance\s+(?:manager|director|lead)|director(?:a)?\s+financier|directeur\s+financier|finanzleiter|leiter\s+finanzen)",
    "admin_compound": r"administrativ|administratie|administraci[oó]n|amministrativ|verwaltung|office\s+(?:assistant|manager)|segreter|back[\s-]?office|backoffice",
    "erp_it": r"\berp\b|sap\s+(?:fi|co|fico|mm|sd|s/4)\b|consult\w*\s+sap|sap\s+consult|finance\s+systems|administrateur\s+sap|sap\s+finance|systems?\s+(?:analyst|specialist|administrator)",
    "it_audit": r"\bit[-\s]?audit|audit\s+(?:it|informatique)|auditor\s+it\b|\bgrc\b",
    "media_buyer": r"media\s+buyer|buyer\s+(?:media|fashion)|fashion\s+buyer|visual\s+merch",
    "executive_assistant": r"executive\s+assistant|personal\s+assistant|asistente\s+de\s+direcci|assistant(?:e)?\s+de\s+direction|secretar\w+\s+de\s+direcci|\bea\s+to\b",
    "key_account": r"key\s+account|account\s+(?:executive|manager|director|representative)|business\s+develop|agente\s+comercial",
    "customer_service": r"customer\s+(?:service|support|success|care)|atenci[oó]n\s+al\s+cliente|servicio\s+al\s+cliente|call\s+cent|conseiller(?:e|\(\w+\))?\s+(?:client|banque|en\s+gestion)|relationship\s+manager|chargé\s+de\s+service",
    "branch": r"directeur\s+d['’]agence|responsable\s+d['’]agence|bank\s+branch|oficina\s+bancaria|director\s+de\s+oficina",
    "quality_or_energy_audit": r"auditor(?:\s+de|\s+of)?\s+calidad|quality\s+audit|energy\s+audit|audit\s+(?:energ|qualit)|milieumeting|auditeur\s+energie|iso\s*\d{4,5}",
    "supplier_quality": r"procurement\s+engineer|supplier\s+quality|compras\s+ingenier|\bapqp\b|\bppap\b",
    "occupational_risk": r"riesgos\s+laborales|prevenci[oó]n\s+de\s+riesgos|health\s+and\s+safety",
    "tax_technology": r"tax\s+(?:technology|tech|software|systems)",
    "hr_not_payroll": r"\bhr\b|rr\.?hh|recursos\s+humanos|human\s+resources|ressources\s+humaines|personal(?:wesen|berater)|recruit|c&b\b|compensation",
}


def words(*parts: str) -> dict:
    return {"tokens_any": list(parts)}


def rx(name: str) -> dict:
    return {"regex": name}


def either(*conditions: dict) -> dict:
    return {"any": list(conditions)}


def both(*conditions: dict) -> dict:
    return {"all": list(conditions)}


def negate(condition: dict) -> dict:
    return {"not": condition}


NON_TARGET_REASON = "Title belongs to the non-target {family} role family."
TARGET_REASON = "Title names a {family} role."
POTENTIAL_REASON = "Role family '{family}' is only potentially relevant; review whether the work is {focus}."


def rule(rule_id: str, when: dict, fit: str, family: str, reason: str, focus: str = "") -> dict:
    return {"id": rule_id, "when": when, "fit": fit, "family": family, "reason": reason, "focus": focus}


def non_target(rule_id: str, when: dict, family: str) -> dict:
    return rule(rule_id, when, "NON_TARGET", family, NON_TARGET_REASON)


def target(rule_id: str, when: dict, family: str) -> dict:
    return rule(rule_id, when, "TARGET", family, TARGET_REASON)


def load_rubric() -> dict:
    """The Jev wording for finance, drafted from 12 real postings (docs/research/finance-rubric-2026-10.md)."""

    data = json.loads(RUBRIC_SOURCE.read_text(encoding="utf-8"))["rubric"]
    return {key: data[key] for key in ("version", "question_types", "questions", "score_criteria")}


def build() -> dict:
    finance_core = words("@finance_core")
    rules: list[dict] = [
        # --- clearly other fields (a finance noun in the title keeps the role in the sector) --------------------------
        non_target("legal", words("@legal"), "legal"),
        non_target("executive_assistant", rx("executive_assistant"), "executive assistant"),
        non_target("insurance_claims", words("@insurance_claims"), "insurance claims / actuarial"),
        non_target("media_buyer", rx("media_buyer"), "marketing / merchandising"),
        non_target("it_audit", rx("it_audit"), "IT audit / governance"),
        non_target("quality_or_energy_audit", rx("quality_or_energy_audit"), "quality / energy / environmental audit"),
        non_target("supplier_quality", rx("supplier_quality"), "supplier quality engineering"),
        non_target("erp_it", rx("erp_it"), "ERP / finance systems"),
        non_target("tax_technology", rx("tax_technology"), "tax technology"),
        non_target("product", {"any": [{"tokens_all": ["product", "manager"]}, {"tokens_all": ["product", "owner"]}]}, "product management"),
        non_target("key_account", rx("key_account"), "sales"),
        non_target("customer_service", rx("customer_service"), "customer service / relationship management"),
        non_target("branch", rx("branch"), "bank branch / commercial banking"),
        non_target(
            "sales",
            both(words("@sales"), negate(words("controller", "controllers", "controlling", "accountant", "accounting")),
                 negate(words("administrativo", "administrativa", "backoffice"))),
            "sales",
        ),
        non_target("tech", words("@tech"), "software / engineering"),
        non_target("security_risk", both(words("@audit_other"), words("risk", "riesgo", "riesgos", "risque", "compliance")), "security / safety risk"),
        non_target("occupational_risk", rx("occupational_risk"), "occupational health and safety"),
        non_target("operations_other", both(words("@operations_other"), negate(finance_core)), "operations / marketing / other"),
        # --- families, most specific first ---------------------------------------------------------------------
        target("g11_consolidation", either(words("@consolidation"), rx("consolidation_compound"), rx("reporting")), "financial reporting and consolidation"),
        target("g6_payroll", either(words("@payroll"), rx("payroll_compound")), "payroll"),
        non_target("hr", rx("hr_not_payroll"), "human resources"),
        target("g4_audit", either(words("@audit"), rx("audit_compound")), "audit"),
        target("g5_tax", either(words("@tax"), rx("tax_compound")), "tax"),
        target("g3_treasury", either(words("@treasury"), rx("treasury_compound")), "treasury"),
        target("g7_procurement", either(words("@procurement"), rx("procurement_compound"), {"tokens_all": ["category", "management"]}), "procurement"),
        target("g10_banking_operations", either(words("@bank_ops"), rx("bank_ops")), "banking and investment operations"),
        target("g9_credit_and_risk", either(words("@credit_risk"), rx("credit_compound")), "credit and risk"),
        target("g1_accounting", either(words("@accounting"), rx("accounting_compound")), "accounting"),
        target(
            "g2_fpa_and_controlling",
            either(
                words("@controlling", "@fpa"),
                rx("controlling_compound"),
                {"tokens_all": ["finance", "partner"]},
                {"tokens_all": ["financial", "analyst"]},
                {"tokens_all": ["finance", "analyst"]},
                {"tokens_all": ["analista", "financiero"]},
                {"tokens_all": ["analyste", "financier"]},
                {"tokens_all": ["financial", "planning"]},
            ),
            "FP&A and controlling",
        ),
        target("g8_finance_administrator", {"tokens_all": ["finance", "administrator"]}, "administration and back office"),
        rule(
            "general_finance", either(words("@finance_words"), rx("generic_finance_head")), "POTENTIALLY_RELEVANT",
            "general finance", POTENTIAL_REASON, "in the finance function (accounting, planning, treasury...) rather than finance sales or systems",
        ),
        target("g8_administration", either(words("@admin"), rx("admin_compound")), "administration and back office"),
        non_target("no_sector_term", {"true": True}, "outside finance and administration (no sector term in title)"),
    ]
    return {
        "id": "finance",
        "label": "Finanzas y administración",
        "sets": SETS,
        "regexes": REGEXES,
        "compounds": [
            {"parts": ["back", "office"], "word": "backoffice", "expand_back": True},
            {"parts": ["mid", "office"], "word": "middleoffice", "expand_back": False},
            {"parts": ["fp", "a"], "word": "fpa", "expand_back": False},
            {"parts": ["accounts", "payable"], "word": "accountspayable", "expand_back": False},
            {"parts": ["accounts", "receivable"], "word": "accountsreceivable", "expand_back": False},
        ],
        "rules": rules,
        # No stack: tools in finance postings are "desirable" or in "such as" lists, so no bonus or penalty per tool.
        "rubric": load_rubric(),
    }


if __name__ == "__main__":
    target_path = ROOT / "src" / "ai_job_hunter" / "sectors" / "templates" / "finance.json"
    target_path.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {target_path}")
