import pytest

from ai_job_hunter.sectors.engine import classify_role_family

# Titles read from real postings (docs/research/sector-templates-2026-10.md, section 4), grouped by the family a person
# in finance would put them in. The classifier decides by title alone, so each title needs only its family.
FAMILIES = {
    "accounting": [
        "Accountant", "General Accountant", "Staff Accountant with English - Madrid / Remote", "Senior Accounting",
        "Accounting Manager - Leading International Organization", "General Ledger Accountant", "GL Accountant",
        "Financial Accountant", "Assistant Accountant", "Accounts Payable Specialist", "Accounts Receivable",
        "Group Accountant", "Management Accountant", "Accounting Intern", "OTC Accountant with French",
        "R2R Team Lead / Senior Accountant", "Accounting Controller - French Speaker",
        "Técnico Contable Senior en Madrid", "Contable (H/M/D)", "Comptable général", "Aide comptable",
        "Comptable fournisseurs", "Comptable confirmé(e)", "Collaborateur Comptable - Junior", "Buchhalter",
        "Finanzbuchhalter", "Senior Buchhalter", "Bilanzbuchhalter", "Kreditorenbuchhalter", "Debitorenbuchhalter",
        "Teamleiter Rechnungswesen", "Leiter Buchhaltung", "Técnico(a) de Contabilidade", "Buchhalter 80-100%",
        "Accounting Specialist - Fondo di Investimento", "Finance Administrator (Accounts Payable)", "Boekhouder", "Contabile", "Contabilista",
    ],
    "FP&A and controlling": [
        "Financial Planning & Analysis (FP&A)", "Head of FP&A", "Manager FP&A", "Finance Business Partner / Commercial Controller",
        "Finance Business Partner Iberia - Retail", "Finance and Business Controller", "Controller Senior",
        "Financial Controller", "Business Controller", "Jr. Business Controller", "Group Controller",
        "Controller Financiero", "Senior Business Controller", "Junior Controller", "Vertriebscontroller / Sales Controller",
        "Produktionscontroller", "Finanzcontroller/in (m/w/d) 100%", "Assistent Controller", "Contrôleur de gestion",
        "Controller de gestión", "Analista financiero", "Finance & Investment Analyst", "Controlling",
    ],
    "treasury": [
        "Treasury Specialist", "Treasury Corporate", "Group Treasury Manager", "Operational Treasury Executive with English C1",
        "Responsable de Tesorería. Zona Noroeste de Madrid", "Head of Treasury (Tenerife) (m/f/d)", "Expert, Treasury ALM",
        "Analista de tesorería", "Trésorier", "Tesoureiro", "Treasury analyst", "Tesoriere",
    ],
    "audit": [
        "Corporate Internal Auditor", "Global Internal Auditor", "Internal Audit Manager - Compliance", "Internal Auditor",
        "Auditor/a Senior Interno", "Auditor/a de Cuentas - Importante despacho", "Responsable de auditoría",
        "Auditeur interne", "Auditeur financier", "Chef de mission Audit", "Wirtschaftsprüfer", "Prüfungsleiter",
        "Commissaire aux comptes", "Revisore",
    ],
    "tax": [
        "Tax Manager", "Tax senior in house - Multinacional", "Junior Tax Analyst - Barcelona", "Indirect Tax Executive with English",
        "Head of Tax", "Analista Fiscal - Tax Specialist con SAP", "Steuerfachangestellter (m/w/d)", "Asesor/a fiscal",
        "Fiscaliste", "Steuerberater", "Fiscalist", "Técnico/a tributario",
    ],
    "payroll": [
        "Payroll Specialist", "Payroll Manager", "Payroll Expert - SAP - Sector Energía Renovables",
        "Senior Payroll Specialist - TEMP (maternity cover)", "Payroll Admin - English C1", "Payroll and HR Operations Manager",
        "Técnico/a de nóminas", "Gestionnaire de paie", "Lohnbuchhalter", "Salarisadministrateur", "Addetto paghe",
    ],
    "procurement": [
        "Purchasing Manager", "Procurement Manager", "Coordinador de Compras - Sector Restauración / Food Service",
        "Técnico/a de Compras", "Responsable compras senior", "Head of Category Management", "Supply Chain & Procurement Manager",
        "Procurement & Operations Support Specialist", "Comprador/a", "Acheteur", "Einkäufer", "Strategischer Einkäufer", "Inkoper",
    ],
    "administration and back office": [
        "Administrativo / Back Office con inglés B2", "Administrativo/a Comercial", "Responsable de Back Office y Digitalización",
        "Back Office con EXCEL y análisis de datos", "Back Office - Francés Fluido", "Administration Manager",
        "Office Assistant con Inglés B2/C1", "Assistant(e) Back-Office", "Segreteria Amministrativa", "Auxiliar administrativo",
        "Asistente administrativo", "Office Manager", "Sachbearbeiter", "Administratief medewerker", "Finance Administrator (M/F/X)"
    ],
    "credit and risk": [
        "Credit Risk Specialist fluent in English and Spanish", "Credit Risk Officer - Trade Finance ENG / FR 100% (m / f)",
        "Senior Credit Officer FR / ENG", "European Risk Analyst (m/f) - International Insurance Company",
        "Credit and Collections Analyst en Sant Celoni", "Credit Controller", "Financial Risk and Compliance Manager",
        "Directeur des Risques", "Analista de riesgos", "Analista de crédito", "Analyste crédit", "Risk analist",
        "Analista de risco", "Kreditsachbearbeiter",
    ],
    "banking and investment operations": [
        "Fund Administrator - Financial Services", "KYC Specialist - Private Banking", "Sanctions Specialist - Banking",
        "Investment Data Specialist - Madrid", "Team Lead Anti-Financial Crime", "KYCB Analyst", "Associate, Financial Operations",
        "Back Office Financiero Junior - Wealth Management", "Gestionnaire Middle Office - Opérations", "Gestionnaire Middle Office Titres (H/F)",
        "Gestionnaire Back Office Moyens de paiement",
    ],
    "financial reporting and consolidation": [
        "Consolidation and Reporting Specialist", "Consolidation Manager", "Financial Reporting Manager",
        "Specialist, Consolidation & Regional Finance", "Senior Finance Manager - Group Accounting & Reporting",
        "Regulatory Reporting AVP", "Regulatory Reporting Expert", "Responsable Comptable et Consolidation (F/H)", "Leiter Konzernrechnungswesen",
        "Analista de consolidación", "Konzernbuchhalter",
    ],
}

# General finance roles: in the sector but not one family; the person decides.
GENERAL_FINANCE = ["Finance Manager", "Head of Finance", "Finance Director", "Director Financiero", "CFO"]

# Titles the research lists as looking like finance but belonging elsewhere.
OTHER_FIELDS = [
    "Account Executive Accounting - France", "Staff Product Manager [Accounting expertise]", "SAP FI", "Administrateur SAP Finance",
    "Técnico ERP (Módulo Contabilidad)", "Finance Systems Analyst", "Auditor de Calidad", "IT-Auditor (m/w/d)",
    "Consultant Senior Auditeur Energie & SMÉ", "SAP GRC Manager", "Interim GRC Lead", "Perito de Siniestros",
    "Technical Pricing Actuary", "Responsable de Siniestros", "Procurement Engineer (Automotive)", "Demand Planner Iberia",
    "Relationship Manager", "Conseiller Banque en Ligne", "Directeur d'Agence", "Executive Assistant to CEO",
    "Senior C&B Manager", "Técnico/a de RRHH Senior", "Account Manager", "Sales Development Representative",
    "Legal Counsel Banking & Finance", "Business Developer Private Banking", "Backend Engineer", "Data Scientist",
    "Senior Software Engineer - Payments & Treasury", "Salesforce Administrator", "IT-Administrator (m/w/d)",
    "Senior Security Risk Officer", "Técnico/a Superior en Prevención de Riesgos Laborales", "Enterprise Sales Director, Financial Services",
    "Business Systems Architect (Tax)", "Plant Manager", "HSE Manager", "Marketing Manager", "Customer Service Agent", "Tax Technology Specialist with English",
]


@pytest.mark.parametrize("family,title", [(family, title) for family, titles in FAMILIES.items() for title in titles])
def test_real_finance_titles_land_in_their_family(family, title):
    result = classify_role_family(title, "finance")
    assert (result.fit, result.family) == ("TARGET", family), title


@pytest.mark.parametrize("title", GENERAL_FINANCE)
def test_general_finance_roles_are_potentially_relevant(title):
    assert classify_role_family(title, "finance").fit == "POTENTIALLY_RELEVANT", title


@pytest.mark.parametrize("title", OTHER_FIELDS)
def test_titles_that_only_look_like_finance_are_not_targets(title):
    assert classify_role_family(title, "finance").fit == "NON_TARGET", title
