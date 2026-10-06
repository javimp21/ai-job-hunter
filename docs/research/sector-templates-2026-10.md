# Plantillas de sector: contenido de software y datos y de finanzas y administración

Investigación para el paso 6 de `docs/SECTOR_TEMPLATES_DESIGN.md` (segunda plantilla y prueba con ofertas reales).
Fecha de lectura de todas las páginas: **2026-10-06**. Sin código tocado. Rama `research/sector-templates-2026-10`.

## 0. Método, volumen y límites (leer primero)

### 0.1 Qué se leyó

| Qué | Cantidad | Detalle |
| --- | --- | --- |
| Fichas de oferta leídas completas (texto de la página de la oferta) | **143** | 72 de software y datos, 71 de finanzas y administración (75 de Michael Page, 68 de tableros de empresa) |
| Títulos vistos solo en listados (sin abrir la ficha) | **≈ 850** | ≈ 570 tarjetas de Michael Page (9 países, sin deduplicar: hay repetidas entre listados) y ≈ 280 de tableros de 9 empresas |
| Ofertas cuya página solo mostró el formulario de solicitud | 4 | GetYourGuide (Berlín): solo título, no se cuentan como leídas |
| Lecturas fallidas o de ofertas ya cerradas | ≈ 30 | 404, 403, 410, redirección al listado general. No se usan en ningún cuadro |

Reglas aplicadas en todo el informe:

- **Marca ✔** = título visto hoy (en un listado o en una ficha). Cada ✔ lleva la etiqueta de la fuente (tabla 0.2).
- **Marca ○** = no visto hoy. Es conocimiento general del dominio, **sin verificar**. Hay que validarlo antes de meterlo en la plantilla.
- **Años**: cita literal de la ficha. "sin años" significa que la ficha no declara años. No se ha deducido ninguna cifra.
- Los títulos van en el idioma en que aparecen. Cuando el título del listado difiere del de la ficha, se usa el de la ficha y se indica.
- "Anónima (Michael Page)" = la ficha no nombra al empleador. No se ha inventado ni inferido ninguna empresa.
- Una búsqueda web devolvió resúmenes que no coincidían con las fichas (por ejemplo, el titular "Financial Controller & Reporting Analyst" era en la ficha "Junior Financial Reporting & Controlling Analyst"). Por eso solo cuenta lo que se leyó en la propia ficha.
- Un error mío durante la sesión: se construyó una URL de Spotify con un sufijo inventado para probar; dio 404 y está excluida. Las URLs de este informe son las que devolvieron las páginas o los listados.

### 0.2 Fuentes y etiquetas

| Etiqueta | Fuente | Tipo | Países cubiertos |
| --- | --- | --- | --- |
| MPes, MPfr, MPde, MPnl, MPpt, MPit, MPie, MPch, MPbe | Michael Page, dominio de cada país (`michaelpage.es`, `.fr`, `.de`, `.nl`, `.pt`, `.it`, `.ie`, `.ch`, `.be`; Luxemburgo aparece en el listado de `.be`) | Consultora de selección. Clientes casi siempre anónimos | ES, FR, DE, NL, PT, IT, IE, CH, BE, LU |
| ITP | In The Pocket (tablero Greenhouse) | Empresa | BE, RO |
| GL | GitLab (Greenhouse) | Empresa | remoto (CA, US, UK, PL, IN) |
| SP | Spotify (Lever) | Empresa | SE, UK |
| TF | Typeform (Greenhouse) | Empresa | remoto DE, IE, NL, PT, ES, UK |
| PL | Palantir (Lever) | Empresa | ES, UK, NL, DE, FR, PL, SE, NO, LT |
| BP | Bitpanda (Greenhouse UE) | Empresa | AT, ES, DE, FR, RO |
| QO | Qonto (Lever) | Empresa | FR, ES, DE, IT, RS |
| AL | Alpaca (Greenhouse) | Empresa | remoto global |
| GYG | GetYourGuide (Greenhouse) | Empresa | DE, CH |
| AN | Anthropic (Greenhouse) | Empresa | UK, CH |
| QC, PN, SS, FL | QuantCo (Lever), Planet (Greenhouse), Sopra Steria (SmartRecruiters), Flink (SmartRecruiters) | Empresa | DE, AT, BE |

### 0.3 Límites y sesgos que condicionan las conclusiones

1. **Michael Page sesga hacia puestos medios y altos** y hacia España. Sus listados de Alemania son casi todo "Head of Accounting", "Head of Finance" y "Leiter ..." (más de una docena de "Head of Accounting" entre 30 tarjetas). Los niveles de entrada están infrarrepresentados en alemán y holandés.
2. **Software: solo unas 13 empresas de producto o scale-up** más Michael Page España. Sin fichas de Portugal, Italia ni Luxemburgo. Los títulos de software en español son escasos (las ofertas españolas de software salen casi siempre con título en inglés).
3. **Finanzas: Italia y Luxemburgo solo en títulos de listado, ninguna ficha leída.** Francia, Países Bajos, Alemania, Irlanda, Portugal, Suiza y Bélgica tienen entre 1 y 6 fichas cada uno.
4. **Fechas de publicación.** Michael Page expone la referencia `jn-MMYYYY` (mes de creación). Hay fichas vivas con referencias de 2025 (`jn-092025`, `jn-112025`, `jn-122025`). "Vivo el 2026-10-06" no equivale a "publicado en 2026".
5. **No se probó ningún feed ni scraping.** Todo se leyó como lectura manual de páginas públicas. Antes de automatizar la ingesta de un portal hay que releer sus condiciones. Del `robots.txt` de Michael Page España solo se obtuvo un resumen automático (permite `/job-detail/`, bloquea `/job-apply/`, `*/jobs/*/*/*/` y parámetros de salario). Debe releerse el original.
6. **Las listas de herramientas (núcleo, adyacente, ajeno) son mi criterio sobre muestras pequeñas** (3 a 8 fichas por familia). Son una propuesta, no un hecho medido.

## 1. Hallazgos que cambian el diseño de la plantilla

1. **Solo el 52 % de las fichas declara años de experiencia** (74 de 143): 45 de 75 en Michael Page (60 %) y 29 de 68 en tableros de empresa (43 %). Casi la mitad de las ofertas no lo dice. `UNKNOWN` tiene que ser el caso normal, no la excepción.
2. **El título y los años no casan.** Ejemplos leídos: "Data Scientist" sin nivel pide "5+ years" (SP); "Payroll Expert - SAP" pide "entre 7 y 10 años" (MPes); "Tax senior in house" pide "6-8 años" mientras "Senior Accounting" pide "Mínimo 5 años"; "Operational Treasury Executive" pide "2-3 years". Las palabras `Expert`, `Specialist`, `Executive`, `Coordinator` y `Officer` son escalones propios que ni `junior` ni `senior` cubren.
3. **El nivel puede estar solo en la URL.** MPnl lista "Controller" (Róterdam) con la ruta `junior-controller`; MPes lista "Back Office Financiero Junior" y la ficha lo confirma. Conviene conservar el slug.
4. **Sufijos de género y de jornada en el título** que el normalizador debe quitar. Variantes vistas: `(m/w/d)`, `(w/m/d)`, `(m/w)`, `(m/f/d)`, `(m/f)`, `(m/f/x/d)`, `(f/h)`, `(F/H)`, `(H/F)`, `(h/f)`, `(H/M)`, `(H/M/D)`, `(h/m)`, `(M/F/X)`, `(mfd)`. Jornada: `100%`, `80-100%`, `60% - 100%`.
5. **Calificadores de idioma y de contrato dentro del título**: `with English`, `fluent in English and Spanish`, `French Speaker`, `Italian Speaker`, `Dutch Speaker`, `German Speaker`, `ENG / FR`, `FR / ENG`, `ASAP:`, `Interim`, `a.i.` (ad interim, NL), `TEMP`, `Temporal`, `Freelance`, `Zzp er`, `12 month contract`, `(maternity cover)`. Y la ciudad pegada: `- Madrid`, `(Tenerife)`, `- Barcelona`.
6. **Títulos sin sustantivo de rol**: "Java - Spring boot - Microservicios" (MPes), "Treasury Corporate" (MPes, la ficha) y "SAP FI" (MPes). Hacen falta reglas por tecnología o por área, no solo por sustantivo.
7. **Los títulos de software en España y Alemania están en inglés** ("Senior Software Engineer - Frontend (m/f)" en Berlín). El vocabulario local sirve sobre todo para finanzas.
8. **Sinónimos de la misma familia con nombres distintos**: `Data Analytics (h/m)` con dbt, BigQuery y Looker es ingeniería de analítica; "Product Engineer" (QO) es móvil; "Quality Engineer" (ITP) es QA de software; "Auditor de Calidad" no es auditoría financiera.
9. **Las ofertas del mismo título pueden ser de otra familia**: ver sección 7.

## 2. Seniority tal como lo escriben las ofertas

Se da una tabla por sector (no por familia) y, en cada familia, solo los niveles observados en ella. Cada celda cita lo visto el 2026-10-06; "no visto" significa 0 apariciones en lo leído.

### 2.1 Software y datos

| Nivel | Inglés (visto) | Español (visto) | Otros idiomas (visto) | Años en fichas |
| --- | --- | --- | --- | --- |
| Becario / intern | `Intern, Frontend QA Engineering` (BP); `Software Engineer, Internship` (PL); `Data Engineering Intern` (QO); `Internship` (ITP); `Working Student, Security Engineer` (GYG, Zúrich) | no visto en software (`becario`, `prácticas` ○) | DE `Werkstudent` (QO, no software, pero es el token); FR `en alternance` (texto de QO) | sin años |
| Graduate / trainee | `New Grad` (PL: `Software Engineer, New Grad`, `Forward Deployed Infrastructure Engineer, New Grad`) | no visto (`recién titulado`, `trainee` ○) | no visto | sin años |
| Junior / Jr | `Junior` en MPes: `JUNIOR DATA ANALYST`, `Project Manager Junior Data` | `Junior` (mismos) | no visto en software | `Data Analyst` sin nivel: "Alrededor de 1 año"; FDSE España: "1+ years of relevant, post-college work experience" |
| Associate | no visto en software | no visto | no visto | n/a |
| I / II / III, nivel 1/2/3 | `Backend Engineer II - Data Platform` (SP); "solid experience as a Engingeer I" (texto de SP Android, con errata); `Data Center Technician III` (MPes, hardware: no es software) | no visto | no visto | sin años |
| Mid / semi-senior | `Intermediate Backend Engineer` (GL); `Intermediate-Senior Backend Engineer (Ruby)` (GL); "Mid-level position" (texto de TF); "Mid to Senior level" (texto de MPes iOS) | `semi-senior` no visto ○ | no visto | sin años en los que usan la palabra; sin la palabra: `Data Engineer` "3-4 años", `Data & AI Engineer` "2-4 años", `C# Back-End Engineer` "(3+ years)", `Node.js Back-End Engineer` "(2+ years of experience)" |
| Senior / Sr | `Senior ...` (todas las empresas); `Sr Consultant IT Wealth & Managment` (MPes) | `Senior` en títulos mixtos de MPes (`Senior QA Engineer`, `Senior Embedded Cybersecurity Engineer`, `Senior Full-Stack Developer`); la URL de "Java - Spring boot - Microservicios" dice `programador-senior-java` | DE `Senior ...` en inglés | **4+**: Palantir `Senior Front End`, TF `Senior AI Engineer`, BP `Senior Cyber Security`, MPes WAF; **5+**: ITP `Senior Node.js`, SP `Senior Fullstack`, MPes `Senior QA`, AL `Senior Software Engineer, Quality Engineering`; **6+**: PL `Senior Backend Infrastructure`; **8+**: ITP `Senior C# Back-End` |
| Lead / team lead / tech lead | `Data Engineering Lead`, `QA Lead`, `Technical Data Lead`, `Team Lead` (ITP), `Interim GRC Lead` | `QA Analyst Lead` (listado de MPes) | no visto | `Data Engineering Lead`: "A partir de 7 años" |
| Principal / staff / distinguished | `Staff Backend Engineer`, `Staff Fullstack Engineer`, `Staff Data Analyst`, `Staff Analytics Engineer`, `Staff Data Scientist`, `Principal Backend Engineer` (QO), `Principal Engineer`, `Distinguished Engineer` (GL) | no visto | no visto | `Staff Analytics Engineer`: "7+ years"; GL staff y principal: sin años |
| Manager / responsable / jefe de | `Engineering Manager`, `Data Manager`, `IT Security Manager` | `Responsable de IA`, `Responsable de Comunicaciones y Ciberseguridad`, `Jefe/a de Unidad de Comunicaciones y Ciberseguridad` (única vez que aparece `Jefe`) | no visto | sin años |
| Head of | no visto en software | no visto | no visto | n/a |
| Director | `Director of Engineering`, `Director, Engineering`, `Director of Data Platform`, `Engineering Director (AI & Technology)`; `CIO`, `CISO` | `CIO`, `CISO` (MPes) | no visto | sin años |

Lectura: en software, **senior = 4 a 8+ años, mediana de lo visto 5**. `Staff`, `Lead` y `Principal` rara vez traen años. La palabra `Intermediate` solo la usa GitLab.

### 2.2 Finanzas y administración

| Nivel | Inglés (visto) | Español (visto) | Otros idiomas (visto) | Años en fichas |
| --- | --- | --- | --- | --- |
| Becario / intern | `Accounting Intern` (MPpt) | no visto (`becario` ○) | FR "en alternance ou en poste" (texto de QO); DE `Werkstudent` (QO) | sin años |
| Graduate / trainee | `Young graduate - Finance and Accounting` (MPbe, ref de 2022) | no visto | no visto | sin años |
| Junior / Jr | `Junior Tax Analyst`, `Junior Accountant`, `Junior Finance Operations` (IT), `Junior Controller` (DE y NL), `Jr. Financial Controller`, `Jr. Business Controller` (NL), `Junior Financial Reporting & Controlling Analyst` | `Back Office Financiero Junior`, "Perfil JUNIOR" (texto de `Office Assistant`) | FR `Collaborateur Comptable - Junior`; FR `Aide comptable`, `Comptable auxiliaire`; NL `Assistent Controller`; IE `Assistant Accountant`; CH `Finance Assistant` | "1 año"; "At least 1 year"; "6 mois minimum"; "1-3 años" |
| Associate | `Associate, Financial Operations` (BP); `Finance Associate` (MPit); `Associate - M&A` (MPpt); `Associate Project Finance` (MPit) | no visto | no visto | `Associate, Financial Operations`: "(1+ years)" |
| I / II / III, nivel 1/2/3 | no visto | no visto | no visto | n/a |
| Mid / semi-senior | `Specialist` (BP: `Specialist, Consolidation`, `Specialist, Risk & Controls Assurance`), `Executive` (MPes: `Indirect Tax Executive`, `Operational Treasury Executive`), `Expert` (BP: `Expert, Treasury ALM`), `Coordinator` | `Técnico Contable`, `Analista Fiscal`, `Coordinador de Compras`; `semi-senior` no visto | FR `Comptable confirmé(e)`, `Auditeur Confirmé`, `Collaborateur Comptable - Expérimenté/Mémorialiste` | `Specialist`: "2+ years", "3–5 years"; `Executive`: "2-3 years"; `Expert, Treasury ALM`: "3+ Years"; `Analista Fiscal`: "mínima de 3 años"; `Coordinador de Compras`: "Entre 1 y 3 años" |
| Senior / Sr | `Senior Accounting`, `Senior Accountant`, `Senior Finance Manager`, `Senior Payroll Specialist`; `Sr Legal Counsel` | `Técnico Contable Senior`, `Auditor Interno Senior`, `Tax senior in house` | DE `Senior Buchhalter`, `Senior Controller`; CH `Senior Financial Accountant` | "Mínimo 5 años"; "aproximadamente 5 años"; `Tax senior in house`: "6-8 años"; `Senior Credit Officer`: "At least 5 years" |
| Lead / team lead | `Team Lead`, `R2R Team Lead / Senior Accountant`, `Record to Report Team Lead`, `Accounting Team Lead & Financial Controller`, `Teamlead Group Accounting`, `Interim GRC Lead` | no visto con `Líder`; `Responsable` cumple esa función | DE `Teamleiter Rechnungswesen`, `Prüfungsleiter` (jefe de equipo de auditoría); FR `Chef de mission` (cabinet) | `Chef de mission Comptable - Manager`: "2 ans minimum" de gestión en cabinet |
| Principal / staff / distinguished | no visto en finanzas | no visto | no visto | n/a. Equivalente bancario: `AVP` (`Regulatory Reporting AVP`) sin años |
| Manager / responsable / jefe de | `Finance Manager`, `Accounting Manager`, `Payroll Manager`, `Tax Manager`, `Procurement Manager`, `Manager FP&A` | `Responsable de Tesorería`, `Responsable de Back Office`, `Responsable de auditoría`, `Responsable de Contabilidad & Tax`; `Jefe` no visto en finanzas | FR `Responsable Comptable et Consolidation`, `Responsable de mission audit`, `Manager Audit - Assurance`; DE `Leiter Rechnungswesen`, `Leiter Finanzen`; PT `Responsável Administrativo e Financero` (con errata); IT `Finance Manager` | `Accounting Manager`: "Minimum 5 years"; `Tax Manager`: "mínima de 5 años"; `Manager FP&A`: "5+ years"; `Responsable de Tesorería`: "4-5 years"; `Responsable Comptable et Consolidation`: "7 ans minimum" |
| Head of | `Head of Accounting` (DE, más de una docena de listados), `Head of Finance`, `Head of Treasury`, `Head of FP&A`, `Head of Internal Controls`, `Head of Category Management` | no visto con `Jefe de` | no visto | `Head of Treasury`: "8-10 years"; `Head of Category Management`: "entre 7 y 10 años" |
| Director | `Finance Director`, `Accounting Director`, `Corporate Finance Director`, `Director of Accounting & Controlling`; `CFO`, `Deputy CFO`, `Chief Accountant`, `Chief Accounting Officer` | `Director Corporate Finance y Controlling`, `Director/a Financiero/a (H/M/D)`, `CFO` | FR `Directeur des Finances`, `Directeur de missions Audit`; PT `Diretor - Finance & IT`; CH `Directeur/ice Finance & Administration` | sin años |

Lectura: en finanzas, **el escalón intermedio se llama `Specialist`, `Executive`, `Analyst`, `Técnico` o `Coordinador` y pide 2 a 5 años; senior y manager piden 4 a 8; head y director, 7 a 10**. `Principal` y `Staff` no existen en finanzas: el equivalente son `Head of`, `AVP` y `Chief ...`.

## 3. Sector A: software y datos

### 3.1 Familias de puesto (13)

Convención de cada familia: descripción, títulos vistos (✔ con fuente) y no vistos (○), títulos parecidos que pertenecen a otra familia o no se quieren, niveles observados y cinco ofertas leídas con años. Las tablas de ofertas llevan la URL completa; "años" es cita literal.

Resumen de cobertura (ofertas leídas completas por familia): backend 5 (+3), frontend 4, full stack 5 (+1), DevOps/SRE/plataforma 5, ingeniería de datos 5, ingeniería de analítica 3, análisis de datos/BI 5, ciencia de datos 4, ML/IA 5, móvil 5 (+1), QA 5 (+1), seguridad 5 (+1), soluciones/forward deployed 5. **Frontend, ingeniería de analítica y ciencia de datos no llegan a cinco** porque en los tableros leídos no había más fichas vivas de esas familias.

#### F1. Backend

Diseña, construye y opera servicios y APIs del lado servidor.

- Títulos ✔ EN: `Backend Engineer` (SP, GL, PL, QO), `Backend Software Engineer` (PL), `Senior Backend Engineer` (GL, GYG), `Senior Software Engineer (Backend focused)` (GYG), `Intermediate Backend Engineer` (GL), `Staff Backend Engineer` (GL), `Principal Backend Engineer` (QO), `Senior/Staff - Go Backend Engineer - remote friendly` (QO), `Backend Engineer (Python)` y `(Ruby)` (GL), `C# Back-End Engineer`, `Java Back-End Engineer`, `Node.js Back-End Engineer` (ITP), `Backend Engineer II` (SP).
- Títulos ✔ ES: solo `Java - Spring boot - Microservicios` (MPes, sin sustantivo de rol; la URL dice `programador-senior-java`).
- ○ ES: `Desarrollador/a backend`, `Ingeniero/a de software backend`, `Programador/a Java`, `Desarrollador/a .NET`. ○ FR: `Développeur backend`, `Ingénieur logiciel`. ○ DE: `Backend-Entwickler`, `Softwareentwickler`. ○ NL: `Backend ontwikkelaar`. ○ PT: `Programador backend`. ○ IT: `Sviluppatore backend`.
- Parecidos: `Backend Engineer - Data Platform` y `Senior Backend Data Engineer` (SP) caen entre backend e ingeniería de datos; `Backend Engineer - Platform Security` (SP) entre backend y seguridad; `Software Engineer - Query Engines` y `Software Engineer - Apollo Platform` (PL) entre backend e infraestructura; `Migration Engineer - GitLab Dedicated` (GL) infraestructura.
- Niveles observados: `Intermediate`, `Senior`, `Staff`, `Principal`, `II`, y sin nivel ("C# Back-End Engineer").

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| C# Back-End Engineer | In The Pocket | Bélgica | https://job-boards.greenhouse.io/inthepocket/jobs/8108076 | "Strong knowledge of C# and .NET 10 (3+ years)." |
| Node.js Back-End Engineer | In The Pocket | Bucarest | https://job-boards.greenhouse.io/inthepocket/jobs/8258311 | "Solid knowledge of TypeScript and Node.js (2+ years of experience)." |
| Senior Node.js Back-End Engineer | In The Pocket | Bélgica | https://job-boards.greenhouse.io/inthepocket/jobs/8248626 | "Excellent knowledge of TypeScript (5+ years of experience)" |
| Senior C# Back-End Engineer | In The Pocket | Bélgica | https://job-boards.greenhouse.io/inthepocket/jobs/8113709 | "Strong knowledge of C# and .NET 10 (8+ years of experience)" |
| Backend Engineer II - Data Platform | Spotify | Estocolmo o Londres | https://jobs.lever.co/spotify/186b763a-2a61-4563-8813-ff6b40c9c8a7 | sin años |

Extras leídos: `Java Back-End Engineer` (ITP, Bucarest, https://job-boards.greenhouse.io/inthepocket/jobs/8210823, sin años); `Intermediate Backend Engineer, AMER` (GL, https://job-boards.greenhouse.io/gitlab/jobs/8773006002, sin años); `Staff Backend Engineer, India` (GL, https://job-boards.greenhouse.io/gitlab/jobs/8775136002, sin años). Obsérvese que ITP escribe `Back-End` y pide años por tecnología entre paréntesis, no por rol.

#### F2. Frontend

Interfaces web: componentes, estado, rendimiento y accesibilidad.

- Títulos ✔: `Senior Front End Software Engineer` (PL), `Senior Web Engineer` (SP), `Senior Angular Front-End Engineer` (ITP), `Senior Software Engineer - Frontend (m/f)` (Friendsurance, ficha sin nombre de empresa).
- ○: `Frontend Developer`, `Frontend Engineer (React)`, `UI Engineer`, `Desarrollador/a frontend`, `Ingeniero/a frontend`, `Développeur front-end`, `Frontend-Entwickler`, `Sviluppatore front-end`. Un título `Graduate Frontend Engineer - React/TypeScript` (BP) apareció solo en una búsqueda; la ficha ya no estaba viva y no cuenta.
- Parecidos: `Intern, Frontend QA Engineering` (BP, es QA); `Product Designer` y `Senior Brand Designer` (diseño, no); `Web Engineer` (SP) incluye API y base de datos, está entre frontend y full stack; `CRM & MarTech Associate Manager` (MPes) no es desarrollo.
- Niveles observados: `Senior` en las cuatro. Sin nivel junior ni intermedio en lo leído.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Senior Front End Software Engineer - Application Development | Palantir | Londres | https://jobs.lever.co/palantir/4e7d0732-f477-4c7a-aac9-abd62f8c9987 | "4+ years of frontend software engineering experience" |
| Senior Web Engineer - Subscriptions | Spotify | Londres (remoto EMEA) | https://jobs.lever.co/spotify/1e8c984e-fa8e-4dbb-8f74-6f608ae3bfa1 | sin años |
| Senior Angular Front-End Engineer | In The Pocket | Bucarest | https://job-boards.greenhouse.io/inthepocket/jobs/7842845 | sin años |
| Senior Software Engineer - Frontend (m/f) | no nombrada en la ficha (dominio friendsurance.de) | Berlín, presencial | https://www.friendsurance.de/jobs-Senior-Frontend-Developer | sin años |

Solo cuatro fichas leídas.

#### F3. Full stack

Mismo propietario para interfaz y servicio.

- Títulos ✔: `Full Stack Developer` (TF), `Full Stack Software Engineer` (PL), `Senior Fullstack Engineer` (SP), `Fullstack Engineer (TypeScript)` y `Staff Fullstack Engineer` (GL), `Senior Full-Stack Developer (Italian Speaker) - 100% Remoto` (MPes). Tres grafías: `Full Stack`, `Fullstack`, `Full-Stack`.
- ○: `Desarrollador/a full stack`, `Développeur full stack`, `Full-Stack-Entwickler`, `Sviluppatore full stack`.
- Parecidos: `Web Engineer` (SP); `Software Engineer` genérico (PL: `Software Engineer, New Grad`); `Product Engineer` (QO, móvil).
- Niveles observados: `Senior`, `Staff`, "Mid-level" (texto de TF), y sin nivel con 2+ años.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Full Stack Developer | Typeform | Remoto (DE, IE, NL, PT, ES, UK) | https://job-boards.greenhouse.io/typeform/jobs/7942504 | "Mid-level position", sin años |
| Full Stack Software Engineer - Application Development | Palantir | Londres | https://jobs.lever.co/palantir/c44510a1-9537-4c52-ae81-51546979fe47 | "2+ years of frontend software engineering experience" |
| Senior Fullstack Engineer - Internationalisation Platform | Spotify | Londres o Estocolmo | https://jobs.lever.co/spotify/d1df9e53-27a1-4399-aa8b-7144cf634360 | "You have 5+ years of experience building and shipping production-grade software as a fullstack engineer" |
| Fullstack Engineer (TypeScript), AI Engineering: Duo Client SDK | GitLab | Remoto (CA, US) | https://job-boards.greenhouse.io/gitlab/jobs/8698330002 | sin años |
| Senior Full-Stack Developer (Italian Speaker) - 100% Remoto | Page Consulting Tech Solutions (Michael Page) | remoto desde España | https://www.michaelpage.es/job-detail/senior-full-stack-developer-italian-speaker-100-remoto/ref/jn-102026-7119508 | sin años |

Extra: `Staff Fullstack Engineer, Data Products (Golang / Node)` (GL, https://job-boards.greenhouse.io/gitlab/jobs/8845277002, sin años; en la práctica es ingeniería de datos con Go).

#### F4. DevOps / SRE / plataforma

Infraestructura, despliegue, fiabilidad y herramientas internas.

- Títulos ✔: `DevOps Engineer`, `Senior DevOps Engineer` (ITP), `Senior Site Reliability Engineer`, `Staff Site Reliability Engineer` (GL), `Senior Platform Engineer` (GL), `Edge Infrastructure Engineer` (PL, Londres, París, Varsovia), `Backend Software Engineer - Infrastructure` y `Senior Backend Software Engineer - Infrastructure` (PL), `Forward Deployed Infrastructure Engineer` (PL).
- ○: `Ingeniero/a DevOps`, `Ingeniero/a de plataforma`, `Cloud Engineer`, `Ingénieur DevOps`, `DevOps-Ingenieur`, `Ingegnere DevOps`.
- Parecidos o no deseados: `Técnico de Sistemas` (MPes, sistemas, ○ familia sistemas), `Técnico de Red Core (3G, 4G, 5G)` (telecomunicaciones), `Data Center Technician III` (MPes, hardware), `Ingeniero Mecánico especialista en Data Centers`, `Senior Business IT Engineer, Atlassian Cloud` (BP, TI corporativa), `Senior Data Platform Engineer` (AL, datos), `Engineering Manager, Infrastructure Platform` (GYG, dirección).
- Niveles observados: `Senior`, `Staff`, y sin nivel.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| DevOps Engineer | In The Pocket | Bélgica | https://job-boards.greenhouse.io/inthepocket/jobs/8143399 | sin años |
| Senior DevOps Engineer | In The Pocket | Bélgica | https://job-boards.greenhouse.io/inthepocket/jobs/8050741 | sin años |
| Senior Site Reliability Engineer - Monitoring and Anomaly Detection (Monetization) | GitLab | Bangalore | https://job-boards.greenhouse.io/gitlab/jobs/8615319002 | sin años (abierto a Senior y Staff) |
| Senior Platform Engineer, GitLab Orbit | GitLab | Remoto (CA, US) | https://job-boards.greenhouse.io/gitlab/jobs/8771527002 | sin años |
| Edge Infrastructure Engineer | Palantir | Londres | https://jobs.lever.co/palantir/fe65ee3c-61e0-4eb6-99e5-c90e38e7043f | "5+ years experience managing medium to large scale systems"; el francés es obligatorio |

#### F5. Ingeniería de datos

Pipelines, almacenes y plataformas de datos.

- Títulos ✔: `Data Engineer` (MPes ×3), `Data Engineer (hands on)`, `Data Engineer (Tech Solutions)`, `Data Engineering Lead`, `Data & AI Engineer` (MPes), `Senior Data Engineer - Data Platform` (SP), `Senior Data Engineer, Growth Data Engineering` (GYG), `Senior Backend Data Engineer – Content Intelligence` (SP), `Senior Data Platform Engineer` (AL), `Data Engineering Intern` (QO).
- ○ ES: `Ingeniero/a de datos`, `Arquitecto/a de datos`. ○ FR: `Ingénieur data`, `Data engineer` (se usa en inglés). ○ DE: `Dateningenieur`. ○ NL: `Data engineer`. ○ PT: `Engenheiro de dados`. ○ IT: `Ingegnere dei dati`.
- Parecidos o no deseados: `Master Data Specialist - SSC located in Madrid` y `Accounts Payables - Master Data` (MPes, datos maestros de ERP, no ingeniería); `Data Governance - Collibra` (adyacente: gobierno del dato); `Data Manager`; `Data Center Technician III`; `Ingeniero Mecánico especialista en Data Centers`; `Investment Data Specialist` (MPes, operaciones de inversión).
- Niveles observados: `Senior`, `Lead`, `Intern`, sin nivel.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Senior Data Engineer - Data Platform | Spotify | Londres | https://jobs.lever.co/spotify/204f6cd7-98a3-4360-87e3-8876adf087da | sin años |
| Data Engineer | anónima, sector industrial (Michael Page) | Badalona | https://www.michaelpage.es/job-detail/data-engineer-badalona/ref/jn-082026-7092431 | "mínima de 3-4 años en cargos similares" |
| Data Engineering Lead | anónima, consultora de servicios financieros (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/data-engineering-lead/ref/jn-092026-7107115 | "A partir de 7 años de experiencia" |
| Data & AI Engineer | anónima, tecnología y telecomunicaciones (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/data-ai-engineer/ref/jn-092026-7107863 | "2-4 años de experiencia en posiciones similares" |
| Data Engineer (hands on) | anónima, almacenaje (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/data-engineer-hands/ref/jn-082026-7080035 | sin años (proyecto temporal) |

#### F6. Ingeniería de analítica (analytics engineering)

Modelado de datos para análisis (dbt, almacén, capa semántica).

- Títulos ✔: `Analytics Engineer` (QO, FL), `Staff Analytics Engineer` (AL), `Data Analytics (h/m)` (MPes; es un puesto de ingeniería de analítica por herramientas: dbt, BigQuery, Looker).
- ○ (solo en resultados de búsqueda, fichas no leídas): `Senior Analytics Engineer` (Sword Health, Protolabs), `Analytics Engineer / DBT Modelling Engineer` (CI&T). ○ ES: `Ingeniero/a de analítica`. ○ FR: `Analytics engineer` (se usa en inglés; Qonto lo escribe en inglés).
- Parecidos: `Data Analyst` y `BI Developer` (F7); `Data Engineer` (F5); `Staff Data Analyst - Ops & Compliance` (QO usa dbt y Omni).
- Niveles observados: `Staff`, sin nivel.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Analytics Engineer | Qonto | París o Barcelona (remoto) | https://jobs.lever.co/qonto/ebed5dab-630c-48ea-be8f-9e018797c193 | sin años |
| Analytics Engineer (m/f/d) | Flink | Berlín | https://jobs.smartrecruiters.com/Flink3/744000153445652-analytics-engineer-m-f-d- | sin años |
| Staff Analytics Engineer | Alpaca | Remoto EMEA | https://job-boards.greenhouse.io/alpaca/jobs/6146909004 | "7+ years in analytics engineering or data engineering focused on transformation and warehouse architecture" |

Y, ambiguo: `Data Analytics (h/m)`, anónima (IoT y gemelos digitales), Zaragoza, https://www.michaelpage.es/job-detail/data-analytics-hm/ref/jn-102026-7116713, "3-5 años de experiencia en roles similares". Solo tres fichas puras.

#### F7. Análisis de datos / BI

Consultas, cuadros de mando y análisis para el negocio.

- Títulos ✔: `Data Analyst` (MPes ×2), `Junior Data Analyst`, `JUNIOR DATA ANALYST`, `Data Analyst sector Telecomunicaciones`, `Senior Data Analyst (Sales & RevOps)` (GYG), `Staff Data Analyst` (GL), `Staff Data Analyst - Ops & Compliance`, `Senior Marketing Data Analyst` (QO), `Manager, Growth Analytics` (BP), `Power BI Reporting` (MPes), `Senior Decision Scientist, Customer Care Analytics` (GYG), `Senior Data Analyst/Responsable Data - Retail/Automotive` (MPes), `Finance Data & BI Specialist` (MPit), `Data Analytics IA` (MPes).
- ○ ES: `Analista de datos`, `Analista BI`, `Desarrollador/a Power BI`. ○ FR: `Analyste de données`, `Chargé d'études`. ○ DE: `Datenanalyst`. ○ NL: `Data-analist`. ○ PT: `Analista de dados`. ○ IT: `Analista dati`.
- Parecidos o no deseados: `Business Analyst` (MPnl; puede ser TI o negocio), `Logistic Planner - Data Analytics` (logística), `Product Quality Analyst - AI Voice` (SP, evaluación de calidad de voz), `Fraud Analyst` y `KYCB Analyst` (operaciones de riesgo), `Technical Pricing Actuary` (actuarial).
- Niveles observados: `Junior`, `Senior`, `Staff`, `Manager`, sin nivel con "1 año".

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Staff Data Analyst | GitLab | Bangalore | https://job-boards.greenhouse.io/gitlab/jobs/8827370002 | sin años |
| Staff Data Analyst - Ops & Compliance | Qonto | París, Barcelona, Belgrado, Berlín, Milán | https://jobs.lever.co/qonto/1591d10c-c025-42ef-ab54-f9e1a3a93fa2 | sin años |
| Junior Data Analyst | anónima, cliente final (Michael Page) | España | https://www.michaelpage.es/job-detail/junior-data-analyst/ref/jn-092026-7104085 | sin años |
| Data Analyst sector Telecomunicaciones | anónima, tecnología y telecomunicaciones (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/data-analyst-sector-telecomunicaciones/ref/jn-092026-7102830 | "Alrededor de 1 año de experiencia en posiciones similares" |
| Power BI Reporting (Hibrido Bilbao) | Page Consulting Tech Solutions (Michael Page) | Bilbao | https://www.michaelpage.es/job-detail/power-bi-reporting-hibrido-bilbao/ref/jn-102026-7119472 | sin años (el texto dice Senior Power BI Developer) |

Extra: `Manager, Growth Analytics` (BP, Viena, https://job-boards.eu.greenhouse.io/bitpanda/jobs/4983426101, sin años).

#### F8. Ciencia de datos

Modelos estadísticos y de aprendizaje, experimentación e inferencia causal.

- Títulos ✔: `Data Scientist` (SP, QC, PN, SS), `Senior Data Scientist` y `Staff Data Scientist` (GYG), `Senior Product Data Scientist` y `Staff Data Scientist, Growth` (AL), `Data Scientist - Music Mission` y `- Music Promotion` (SP, Nueva York), `Senior Data Science Manager` (GYG), `Research Scientist` y `Senior Applied Research Scientist` (SP), `Senior Decision Scientist` y `Staff Decision Scientist` (GYG).
- ○ ES: `Científico/a de datos`. ○ FR: `Data scientist` (en inglés), `Ingénieur data scientist`. ○ DE: `Data Scientist` (en inglés). ○ NL, PT (`Cientista de dados`), IT (`Data scientist`).
- Parecidos: `Staff Economist, Marketplace Economics` (GYG, economía aplicada); `Decision Scientist` (GYG: analítica de decisión); `Machine Learning Engineer` (F9); `Data Analyst` (F7).
- Niveles observados: `Senior`, `Staff`, `Manager`, sin nivel (con años altos).

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Data Scientist, Company Planning & Execution | Spotify | Estocolmo o Londres | https://jobs.lever.co/spotify/8a9cc53c-48c0-4d43-8287-d81ab09e74fa | "5+ years of experience with a quantitative background in science, economics, engineering, or a related field" |
| Data Scientist | QuantCo | Europa | https://jobs.lever.co/quantco-/3e18574e-ab5a-46a2-8714-a0221fb937e7 | sin años (exige título universitario) |
| Data Scientist | Planet | Graz (Austria) | https://job-boards.greenhouse.io/planetlabs/jobs/8231379 | "4+ years of relevant work experience" |
| Data Scientist | Sopra Steria | Bélgica | https://jobs.smartrecruiters.com/SopraSteria1/744000023797783-data-scientist | "At least 3+ years of experience in Data Science" |

Solo cuatro fichas. Título idéntico, años de 3+ a 5+ sin palabra de nivel.

#### F9. ML / IA (ingeniería)

Entrenamiento, despliegue y producto con modelos y LLM.

- Títulos ✔: `AI Engineer` (ITP), `Senior AI Engineer` (TF, GL), `Senior AI Engineer - EU` y `Staff AI Engineer - EU` (TF), `Senior Machine Learning Engineer - Messaging Platform` y `Senior Machine Learning Engineer - Policy & Safety` (SP), `Research Engineer, Machine Learning (Reinforcement Learning)` (AN), `Staff Applied AI Engineer - Backend` (QO), `Data & AI Engineer` (MPes), `Responsable de IA` (MPes, dirección), `AI Transformation Expert` (ITP, consultoría).
- ○ ES: `Ingeniero/a de machine learning`, `Ingeniero/a de IA`. ○ FR: `Ingénieur machine learning`. ○ DE: `ML-Ingenieur`.
- Parecidos: `Senior AI Engineer` (GL) automatiza sistemas de negocio (Salesforce, Marketo, Zendesk, Workato) y no es ML; `Responsable de IA` es estrategia; `Research Scientist` (F8).
- Niveles observados: `Senior`, `Staff`, `Research Engineer`, sin nivel.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| AI Engineer | In The Pocket | Bélgica | https://job-boards.greenhouse.io/inthepocket/jobs/8141417 | sin años |
| Senior AI Engineer - EU | Typeform | Remoto (DE, IE, NL, PT, ES, UK) | https://job-boards.greenhouse.io/typeform/jobs/8185412 | "At least four years of experience building and deploying machine learning or AI systems in production" |
| Senior Machine Learning Engineer - Messaging Platform | Spotify | Londres o Estocolmo | https://jobs.lever.co/spotify/c322d068-5b59-4658-b618-bb2a032eeb9b | sin años |
| Research Engineer, Machine Learning (Reinforcement Learning) | Anthropic | Londres | https://job-boards.greenhouse.io/anthropic/jobs/5115935008 | "Years of experience required will correlate with the internal job level requirements for the position" |
| Senior AI Engineer | GitLab | Remoto (US) | https://job-boards.greenhouse.io/gitlab/jobs/8565469002 | sin años (ver ambigüedades) |

#### F10. Móvil

Aplicaciones nativas o multiplataforma para Android e iOS.

- Títulos ✔: `Android Engineer - Experience` (SP), `Senior C++/iOS Engineer - User Platform` (SP), `Mobile Engineer (Flutter)` (ITP), `Android Developer (Remoto)` y `iOS Developer (Remoto)` (MPes), `Senior Android Engineer - AI Product`, `Senior Product Engineer - Android/Kotlin` y `Senior Product Engineer - iOS/Swift` (QO).
- ○ ES: `Desarrollador/a móvil`, `Desarrollador/a Android`, `Desarrollador/a iOS`. ○ FR: `Développeur mobile`. ○ DE: `Mobile-Entwickler`.
- Parecidos: `Intern, Frontend QA Engineering` (BP, QA); `Product Engineer` (QO) solo es móvil si el sufijo lo dice.
- Niveles observados: `Senior`, "Engineer I", sin nivel.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Mobile Engineer (Flutter) | In The Pocket | Bélgica | https://job-boards.greenhouse.io/inthepocket/jobs/8232526 | sin años |
| Android Engineer - Experience | Spotify | Londres o Estocolmo | https://jobs.lever.co/spotify/2193db3f-77c5-43b8-b030-8f92c9882bf1 | "You have solid experience as a Engingeer I" (errata del original; es un nivel, no años) |
| Senior C++/iOS Engineer - User Platform | Spotify | Estocolmo o Londres | https://jobs.lever.co/spotify/813b4b62-429c-42e9-a8f7-59e9412fb287 | sin años |
| Android Developer (Remoto) | Michael Page Tech Solutions | España (remoto, visitas a Madrid) | https://www.michaelpage.es/job-detail/android-developer-remoto/ref/jn-102026-7119943 | sin años |
| iOS Developer (Remoto) | Michael Page Tech Solutions | Madrid | https://www.michaelpage.es/job-detail/ios-developer-remoto/ref/jn-102026-7119450 | sin años (el texto dice "Mid to Senior") |

Extra: `Senior Product Engineer - Android/Kotlin` (QO, https://jobs.lever.co/qonto/0c9f8b02-398c-4128-bbd1-b1b0acf3956e, sin años).

#### F11. QA / testing

Pruebas manuales y automáticas, calidad del software.

- Títulos ✔: `Quality Engineer` (ITP), `Intern, Frontend QA Engineering` (BP), `QA Engineer` (MPes, listado `QA - AUTOMATION - TESTER`), `QA Lead` (MPes, listado `QA Analyst Lead`), `Senior QA Engineer - IA Videoanalytics company (Vallés)` (MPes), `Senior Software Engineer, Quality Engineering` (AL).
- ○ ES: `Tester`, `Analista QA`, `Ingeniero/a de calidad de software`, `Técnico/a de pruebas`. ○ FR: `Testeur`, `Ingénieur QA`. ○ DE: `Softwaretester`, `QA-Ingenieur`.
- Parecidos o no deseados: `QA Operacional (H/M) Turnos rotativos` (MPes, farmacéutico), `Técnico/a Garantía de Calidad - Planta Farmacéutica`, `Auditor de Calidad` (MPes), `Quality Analyst Consultant` (MPes, listado de riesgo; sin leer), `Senior Product Quality Analyst - AI Voice` (SP, evaluación de voz).
- Niveles observados: `Intern`, `Senior`, `Lead`, sin nivel.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Quality Engineer | In The Pocket | Bucarest | https://job-boards.greenhouse.io/inthepocket/jobs/8232517 | sin años |
| Intern, Frontend QA Engineering | Bitpanda | Barcelona | https://job-boards.eu.greenhouse.io/bitpanda/jobs/4940716101 | sin años |
| QA Engineer | anónima, comercio minorista (Michael Page) | León | https://www.michaelpage.es/job-detail/qa-engineer/ref/jn-092026-7107791 | sin años |
| QA Lead | Michael Page (consultoría tecnológica) | Madrid | https://www.michaelpage.es/job-detail/qa-lead/ref/jn-092026-7095200 | sin años |
| Senior QA Engineer - IA Videoanalytics company (Vallés) | anónima (Michael Page) | Barcelona (Vallès Occidental) | https://www.michaelpage.es/job-detail/senior-qa-engineer-ia-videoanalytics-company-vallés/ref/jn-022026-6949712 | "más de cinco años en automatización de pruebas" |

Extra: `Senior Software Engineer, Quality Engineering` (AL, https://job-boards.greenhouse.io/alpaca/jobs/6114845004, "5+ years of experience as a software engineer building and maintaining production systems").

#### F12. Seguridad (ciberseguridad)

Operaciones de seguridad, ingeniería de seguridad, DLP, WAF y gobierno de seguridad de la información.

- Títulos ✔: `Senior Cyber Security Engineer, Elastic (Security Operations)` y `Senior SOC Analyst, Security Operations` (BP), `Security Engineer - Detection and Response` (SP, Nueva York), `Backend Engineer - Platform Security` (SP), `Working Student, Security Engineer` (GYG), `Analista de ciberseguridad (CLIENTE FINAL)`, `Ingeniero de Ciberseguridad - Especialista WAF / WAAP`, `Senior Embedded Cybersecurity Engineer`, `IT Security Manager` (dos ofertas), `Security Architect (Hybrid role in Barcelona)`, `CISO (Hybrid in Barcelona)`, `Responsable de Comunicaciones y Ciberseguridad`, `Jefe/a de Unidad de Comunicaciones y Ciberseguridad`, `Técnico de Soporte de Ciberseguridad e IT` (MPes), `Cyber Security Advisor/Consultant a.i.` (MPnl), `Data Risk Engineer` (AL), `Sanctions Specialist` y `KYC Specialist` (MPch; son cumplimiento financiero).
- ○ ES: `Especialista en seguridad de la información`, `Analista SOC`, `Pentester`. ○ FR: `Ingénieur sécurité`, `Analyste SOC`, `RSSI`. ○ DE: `IT-Sicherheitsexperte`, `Informationssicherheitsbeauftragter`.
- Parecidos o no deseados: `Sales Specialist - venta de servicios de Ciberseguridad` (MPes, ventas), `BMS Security Engineer - Data Centers Company` (MPes, sistemas de gestión de edificios), `Responsable de seguridad` (MPes, Valencia, 30-35 mil euros; sin leer, puede ser seguridad física), `IT-Auditor` y `SAP GRC Manager` (auditoría y control: sección 7), `Técnico de Sistemas`.
- Niveles observados: `Senior`, `Manager`, `Jefe/a de Unidad`, `CISO`, `Working Student`, sin nivel.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Senior Cyber Security Engineer, Elastic (Security Operations) | Bitpanda | Viena | https://job-boards.eu.greenhouse.io/bitpanda/jobs/4699355101 | "4+ years of hands-on security engineering experience" |
| Senior SOC Analyst, Security Operations | Bitpanda | Viena | https://job-boards.eu.greenhouse.io/bitpanda/jobs/4966607101 | "4+ years of hands-on security engineering experience" (mismo texto que el anterior: la ficha de analista SOC pide años de ingeniería) |
| Analista de ciberseguridad (CLIENTE FINAL) | anónima (Michael Page) | Madrid sur | https://www.michaelpage.es/job-detail/analista-de-ciberseguridad-cliente-final/ref/jn-072026-7058136 | sin años |
| Ingeniero de Ciberseguridad - Especialista WAF / WAAP | Page Consulting Tech Solutions (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/ingeniero-de-ciberseguridad-especialista-waf-waap/ref/jn-072026-7073465 | "Experiencia mínima de 4 años en infraestructuras, ciberseguridad o administración de plataformas tecnológicas" |
| Senior Embedded Cybersecurity Engineer | anónima, IoT (Michael Page) | Madrid sur | https://www.michaelpage.es/job-detail/senior-embedded-cybersecurity-engineer/ref/jn-092026-7095289 | sin años |

Extra: `Data Risk Engineer` (AL, remoto, https://job-boards.greenhouse.io/alpaca/jobs/6137928004, "3+ years in DLP, data protection, or adjacent security work with real alert volume").

#### F13. Soluciones / forward deployed engineering

Ingeniería de cliente: despliegue en el cliente, preventa técnica, arquitectura de soluciones.

- Títulos ✔: `Forward Deployed Software Engineer` (PL, nueve sedes en el listado: Madrid, Ámsterdam, Múnich, Londres, Estocolmo, Vilna, Oslo y dos de cliente institucional; también variantes `- NATO`, `- UK Government`, `Internship`, `New Grad`), `Forward Deployed Infrastructure Engineer` (PL), `Deployment Strategist` (PL, Madrid, Londres, Oslo, Vilna), `Solution Architect` y `Solution Architect - Embedded expert` (ITP), `Solution Architect Pres-Sales Cloud híbrida (BCN)` (MPes), `Enterprise Architect` (ITP), `Staff Enterprise Architect` (GL), `Sr Consultant IT Wealth & Managment` (MPes), `Consultor Sector Público IT` (MPes).
- ○ ES: `Ingeniero/a de preventa`, `Consultor/a técnico/a`, `Arquitecto/a de soluciones`. ○ FR: `Ingénieur d'affaires technique`, `Architecte solutions`, `Ingénieur avant-vente`. ○ DE: `Lösungsarchitekt`, `Presales Engineer`. ○ IT: `Solution architect`.
- Parecidos o no deseados (los que pide el diseño): `Sales Engineer` ○ (no visto hoy), `Customer Support Engineer` ○ (no visto hoy), `Account Manager | Empresa tecnológica SaaS / FinTech` (MPes ✔, ventas), `Sales Specialist` (✔), `Client Partner` (SP ✔), `Customer Success Manager` (QO ✔), `Technical Senior CRM Dynamics CE` (MPes ✔, desarrollo CRM), `IT Corporate Business Partner`, `Digital Business Facilitator` (MPes ✔, TI corporativa).
- Niveles observados: `Internship`, `New Grad`, sin nivel (con "1+ years"), `Staff`.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Forward Deployed Software Engineer - Spain | Palantir | Madrid | https://jobs.lever.co/palantir/53fb4c05-f949-4146-a046-5c063c36a628 | "1+ years of relevant, post-college work experience"; fluidez en español |
| Forward Deployed Software Engineer | Palantir | Ámsterdam | https://jobs.lever.co/palantir/492a16bb-6b9f-457e-82c3-294e1a2c565d | sin años; neerlandés fluido y viajes del 25 al 50 % |
| Forward Deployed Infrastructure Engineer - UK Government | Palantir | Londres | https://jobs.lever.co/palantir/72e51928-07f0-4be0-aae5-0ae6956a4846 | sin años; habilitación de seguridad DV y nacionalidad británica |
| Deployment Strategist - Spain | Palantir | Madrid | https://jobs.lever.co/palantir/1f007e36-a620-4d15-bf0b-70dc3f3439d8 | sin años; fluidez en español, viajes del 25 al 75 %; Python, R, SQL "a plus" |
| Solution Architect Pres-Sales Cloud híbrida (BCN) | anónima, sector tecnológico (Michael Page) | Barcelona | https://www.michaelpage.es/job-detail/solution-architect-pres-sales-cloud-híbrida-bcn/ref/jn-102026-7116874 | "aproximadamente 5 años o más de experiencia en arquitectura de soluciones" |

### 3.2 Vocabulario del sector software y datos

#### Sustantivos que nombran al profesional

| Idioma | Vistos hoy ✔ | No vistos ○ |
| --- | --- | --- |
| Inglés | engineer, developer, architect, scientist, analyst, consultant, specialist, administrator, advisor, `Research Engineer`, `Product Engineer`, `Technician` (hardware: no) | programmer |
| Español | ingeniero/a (`Ingeniero de Ciberseguridad`), analista, técnico/a, responsable, jefe/a de unidad, consultor/a, programador/a (solo en una URL) | desarrollador/a, arquitecto/a, científico/a de datos, tester |
| Francés | consultant, technicien (`Technicien Support Applicatif - Finance`), chef de projet, administrateur, manager (en listados de finanzas TI de MPfr) | ingénieur, développeur |
| Alemán | Auditor (`IT-Auditor`), Consultant | Entwickler, Ingenieur, Softwareentwickler |
| Neerlandés | advisor/consultant (`Cyber Security Advisor/Consultant a.i.`), analyst | ontwikkelaar, ingenieur |
| Portugués | analyst (`Finance Systems Analyst`) | programador, engenheiro |
| Italiano | specialist (`SPECIALISTA ERP AX365`) | sviluppatore, ingegnere |

Nota: los listados de tecnología leídos fueron españoles (MPes) o de empresas con puestos en inglés. Los sustantivos de rol en francés, alemán, neerlandés, portugués e italiano no pudieron comprobarse en software.

#### Señales de rol no técnico o ajeno (vistas hoy ✔)

`Account Executive`, `Account Manager`, `Sales Development Representative`, `Sales Specialist`, `Client Partner`, `Business Developer`, `Customer Care Agent/Manager`, `Customer Success Manager`, `Customer Support`, `Product Manager`, `Product Designer`, `Brand Designer`, `Copywriter`, `Marketing Specialist`, `Social Media Manager`, `Technical Recruiter`, `Talent Manager`, `Legal Counsel`, `Executive Assistant`, `Workforce Manager`, `Fraud Analyst`, `KYC/KYCB Analyst`, `Agente Comercial`, `Comercial Interno`, `Administrativo/a`, `Técnico de Red Core`, `Data Center Technician`, `Ingeniero Mecánico`, `Perito de Siniestros`, `HSE Manager`, `Responsable de PRL`. Los títulos con `Product Manager` y `Project Manager` no son ingeniería aunque lleven `Data` (`Project Manager Junior Data`).

#### Grafías compuestas

| Concepto | Variantes vistas ✔ |
| --- | --- |
| backend | `Backend`, `Back-End` |
| frontend | `Frontend`, `Front End`, `Front-End` |
| full stack | `Full Stack`, `Fullstack`, `Full-Stack` |
| ciberseguridad | `Cyber Security` (BP, MPnl), `Cybersecurity` (MPes), `Ciberseguridad` |
| FDE | `Forward Deployed`, `Forward Deployed Software Engineer` |
| otras | `DevOps`, `Site Reliability Engineer`, `Data & AI Engineer`, `iOS`, `C++/iOS`, `Node.js`, `Microservicios` |
| ○ no vistas | `Back end`, `Front-end` en minúsculas con espacio, `Data-Engineer`, `QA/Test` |

#### Tecnologías por familia: núcleo, adyacente y ajeno

Criterio: núcleo = aparece en dos o más fichas de la familia o es el centro del puesto; adyacente = una sola ficha o tecnología de la familia vecina; ajeno = tecnología que, si domina, indica otro sector u otro puesto. Es mi criterio sobre las fichas leídas.

| Familia | Núcleo | Adyacente | Ajeno |
| --- | --- | --- | --- |
| Backend | Java, Kotlin, Spring (Boot, Cloud, Data), C# y .NET, Node.js y TypeScript, Go, Ruby on Rails, Python, PostgreSQL, MySQL, MongoDB, Redis, Kafka, RabbitMQ, SNS/SQS, Pub/Sub, REST, GraphQL, gRPC, Docker, Kubernetes, AWS, GCP, Azure | Terraform, OAuth, OpenID Connect, SAML, Rust, C++, Elasticsearch, Cassandra, Flink, Spark | SAP, Dynamics, Salesforce, Zuora, Excel |
| Frontend | TypeScript, JavaScript, React, Angular, Next.js, HTML, CSS, GraphQL, Webpack | Vue, Storybook, Tailwind, Material-UI, Blueprint, Playwright, Jest, Vitest | Power BI, Figma como única herramienta |
| Full stack | React y Node/TypeScript, Java y Kotlin, Next.js, Go, Vue 3 | Docker, AWS, Terraform, Playwright, GitHub Actions | Excel, ERP |
| DevOps / SRE / plataforma | Terraform, Kubernetes, Helm, GitLab CI, GitHub Actions, Prometheus, Grafana, OpenTelemetry, AWS, GCP | ClickHouse, NATS, Argo CD, Cassandra, administración de Linux, Oracle y PostgreSQL (edge) | Atlassian Cloud como administración, hardware Dell/HP, Zuora |
| Ingeniería de datos | SQL, Python, Scala, Java, Spark, Flink, Beam, Airflow, dbt, Snowflake, BigQuery, Databricks, Kafka, Iceberg | Terraform, Trino, ClickHouse, Airbyte, Debezium, Collibra | SAP datos maestros |
| Ingeniería de analítica | dbt, SQL (BigQuery), Looker, Lightdash, Omni, Python, Git, Kimball y esquema en estrella | Airflow, Terraform, GCP | Excel como única herramienta |
| Análisis de datos / BI | SQL, Tableau, Power BI, Looker, Python, R, Excel, DAX | dbt, BigQuery, SQL Server, Oracle, Zendesk Explore | SAP FI, GA4 como único foco (marketing) |
| Ciencia de datos | Python, R, SQL, TensorFlow, PyTorch, Spark, Scala, Azure ML, SageMaker, inferencia causal | dbt, BigQuery, Tableau, Looker | Excel, Salesforce |
| ML / IA | Python, PyTorch, TensorFlow, JAX, LangChain, LangGraph, FastAPI, RAG, bases vectoriales, MLflow, SageMaker, Bedrock, Ray | Kubernetes, Terraform, Kafka, Airflow, Spark, Rust, C++ | Salesforce, Marketo, Zendesk, Workato, n8n (automatización de negocio) |
| Móvil | Kotlin, Jetpack Compose, Swift, UIKit, Objective-C, Flutter, Dart, Firebase, Fastlane, Bitrise | C++ compartido, REST, GraphQL, CI | ninguna observada |
| QA | Playwright, k6, TDD, BDD, CI/CD, Jira, TypeScript, Python | chaos engineering (Chaos Mesh, LitmusChaos), Kubernetes, Appian, UiPath | APQP, PPAP, FMEA, ISO 9001, SAP QM, GMP (calidad industrial) |
| Seguridad | Elastic Security, SIEM (Splunk, ELK), SOAR, AWS, Datadog, WAF (F5, Imperva, Cloudflare, Akamai), DLP, ISO 27001, PCI DSS, DORA, NIST CSF, SOC 2 | C, C++, ARM, FreeRTOS, Zephyr (embebido), CISA, CISM, CISSP | BMS, seguridad física, PRL |
| Soluciones / FDE | Python, Java, TypeScript, SQL, AWS, Azure, GCP, Terraform, Kubernetes | VMware, Nutanix, OpenStack, Foundry y Apollo (Palantir) | Salesforce o CRM como herramienta de venta |

### 3.3 Portales del sector software y datos

Ver la sección 5 (tabla única con ambos sectores).

## 4. Sector B: finanzas y administración

### 4.1 Familias de puesto (11)

Misma convención que en la sección 3. Las URLs de Michael Page se dan completas (dominio de cada país). Las fichas de Michael Page casi nunca nombran a la empresa: va como "anónima" con el sector que la ficha declara.

Cobertura (fichas leídas completas por familia): contabilidad 5 (+2), FP&A y control de gestión 5 (+2), tesorería 5 (+2), auditoría 5 (+3 ambiguas), fiscalidad 5 (+1), nóminas 5, compras 5, administración y back office 5, crédito y riesgo 5, operaciones bancarias 5, reporting financiero y consolidación 5. **Italia y Luxemburgo: ninguna ficha, solo títulos de listado.**

#### G1. Contabilidad

Registro contable, cuentas por pagar y cobrar, cierre mensual y anual.

- Títulos ✔ EN: `Accountant`, `General Accountant`, `Staff Accountant`, `Senior Accounting`, `Senior Accountant`, `Accounting Manager`, `Accounting Director`, `Chief Accounting Officer`, `Chief Accountant`, `General Ledger Accountant`, `GL Accountant`, `Financial Accountant`, `Assistant Accountant`, `Accounts Payable Specialist`, `Accounts Receivable`, `OTC Accountant with French`, `Cash to Accounting`, `R2R Team Lead / Senior Accountant`, `Record to Report Team Lead`, `Accounting Specialist (German Speaker)`, `Accounting Controller - French Speaker`, `Accounting Intern`, `Group Accountant`, `Management Accountant`.
- Títulos ✔ ES: `Técnico Contable Senior`, `Contable (H/M/D)`, `Responsable de Contabilidad & Tax`, `Responsable de Auditoría/Contabilidad`.
- Local ✔. FR: `Comptable général`, `Comptable auxiliaire`, `Aide comptable`, `Comptable fournisseurs`, `Comptable clients`, `Comptable tiers`, `Comptable confirmé(e)`, `Comptable polyvalent`, `Comptable banque`, `Collaborateur Comptable - Junior` y `- Expérimenté/Mémorialiste`, `Chef de mission Comptable - Manager`. DE: `Buchhalter`, `Finanzbuchhalter`, `Senior Buchhalter`, `Bilanzbuchhalter`, `Kreditorenbuchhalter`, `Debitorenbuchhalter`, `Teamleiter Rechnungswesen`, `Leiter Buchhaltung`, `Leiter Rechnungswesen`, `Head of Accounting`. PT: `Técnico(a) de Contabilidade`. IT: `Accounting Specialist - Fondo di Investimento`, `Accounting & Finance Coordinator con inglese`, `Chief Accountant`. NL: `Accounting Assistant`, `Financial Accounting Coordinator`, `Finance Administrator (Accounts Payable)`. CH: `Buchhalter 80-100%`, `Accountant 80-100%`, `Senior Financial Accountant`, `Junior Accountant FR / ENG`. IE: `Assistant Accountant`, `Financial Accountant`. BE: `Accountant/Controller`, `Accounting Team Lead & Financial Controller`.
- ○: `Auxiliar contable`, `Jefe/a de contabilidad`, `Contador/a` (Latinoamérica), `Responsable administrativo`. ○ IT: `Contabile`, `Responsabile amministrativo`. ○ NL: `Boekhouder`, `Medewerker boekhouding`. ○ PT: `Contabilista`.
- Parecidos o no deseados: `Account Executive Accounting - France` (QO, ventas de software de contabilidad), `Staff Product Manager [Accounting expertise]` (QO, producto), `SAP FI` y `Administrateur SAP Finance` (consultoría y TI de ERP), `Técnico ERP (Módulo Contabilidad)` (MPes, TI), `Lagerbuchhaltung` (contabilidad de almacén), `Accounts Payables - Master Data` (MPes, datos maestros), `Accounts Payable Back Office - Call Center` (MPes, atención).
- Niveles observados: `Intern`, `Assistant`, `Aide`, `auxiliaire`, `Junior`, `Staff`, `Specialist`, `Senior`, `confirmé(e)`, `Team Lead`, `Manager`, `Responsable`, `Leiter`, `Head of`, `Director`, `Chief`.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Staff Accountant with English - Madrid / Remote | anónima, marcas de consumo (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/staff-accountant-english-madrid-remote/ref/jn-092026-7109009 | "1-3 years of accounting or bookkeeping experience" |
| General Accountant - FMCG industry | anónima, gran consumo (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/general-accountant-fmcg-industry/ref/jn-052026-7027251 | sin años |
| Técnico Contable Senior en Madrid | anónima, holding educativo (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/técnico-contable-senior-en-madrid/ref/jn-092026-7106067 | "aproximadamente 5 años de experiencia en posiciones contables" |
| Senior Accounting (ficha: Senior Accountant & Consolidation) | anónima, inmobiliaria (Michael Page) | Madrid norte | https://www.michaelpage.es/job-detail/senior-accounting/ref/jn-072026-7059231 | "Mínimo 5 años de experiencia en puesto similar" |
| Accounting Manager - Leading International Organization | anónima (Michael Page) | Barcelona | https://www.michaelpage.es/job-detail/accounting-manager-leading-international-organization/ref/jn-102026-7117431 | "Minimum 5 years of accounting or finance experience" |

Extras en francés (Qonto, París): `Collaborateur Comptable - Junior` (https://jobs.lever.co/qonto/8404b1e8-bc0f-4371-94db-2df0b7d73455, "6 mois minimum avec du front-client, en alternance ou en poste") y `Collaborateur Comptable - Expérimenté/Mémorialiste` (https://jobs.lever.co/qonto/bd21a384-9a0d-4005-8822-4b0377485891, "3 ans minimum"). Son puestos de despacho contable (cartera de clientes), no de contabilidad de empresa.

#### G2. FP&A, análisis financiero y control de gestión

Presupuesto, previsión, análisis de resultados, business partnering y controlling.

- Títulos ✔ EN: `Financial Planning & Analysis (FP&A)` (MPes), `Head of FP&A` (MPie), `Manager FP&A` y `Manager, Financial Planning & Analysis` (SP), `Finance Business Partner / Commercial Controller`, `Finance Business Partner Iberia - Retail`, `Finance and Business Controller`, `Controller Senior`, `Strategic Finance Partner - Marketing` (TF), `Commercial Finance Manager` (MPit), `Finance & Investment Analyst` (MPit), `Controlling & Finance Analytics Manager` (MPpt), `Financial Controller` (muy frecuente en MPnl, MPie, MPch, MPbe), `Business Controller`, `Jr. Business Controller`, `Group Controller`.
- Títulos ✔ ES: `Controller Financiero`, `Director Corporate Finance y Controlling`, `Administracion y finanzas Senior` (título de la ficha; el listado lo mostraba como `Finance Analytic Controller`; ver ambigüedades).
- Local ✔. DE: `Senior Business Controller`, `Senior Controller`, `Junior Controller`, `Vertriebscontroller / Sales Controller`, `Senior Finance Business Partner`, `Produktionscontroller`, `Senior Werkscontroller`, `Finanzcontroller/in`. NL: `Assistent Controller`, `Controller`, `Financial Controller`, `Business Controller`. FR: `Responsable gestion et finance`. CH: `Group Controller`, `Finanzcontroller/in (m/w/d) 100%`.
- ○: `Analista financiero`, `Controller de gestión`, `Controlling`, `Analista de planificación financiera`. ○ FR: `Contrôleur de gestion` (no apareció en los listados leídos), `Analyste financier`. ○ DE: `Finanzanalyst`. ○ PT: `Controller financeiro`. ○ IT: `Controller`, `Analista finanziario`.
- Parecidos o no deseados: `Production/Plant Controller` (`Produktionscontroller`, `Werkscontroller`, `Plant Finance Manager`: control de costes industrial; ver ambigüedades), `Credit Controller` (cobros; ver G9), `Finance Manager` y `Head of Finance` (generalistas), `Finance Systems Analyst/Specialist` (TI financiera), `Investment/Corporate Finance Analyst` (M&A).
- Niveles observados: `Jr.`, `Junior`, `Assistent`, `Senior`, `Manager`, `Head of`, `Director`, `Business Partner`.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Head Commercial and Supply Chain FP&A (listado: Commercial finance (FP&A)) | anónima, agroalimentaria (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/commercial-finance-fpa/ref/jn-042026-7003520 | "Mínimo 6 años de experiencia como Business Controller/ FP&A" |
| Finance Business Partner / Commercial Controller | anónima, distribución farmacéutica (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/finance-business-partner-commercial-controller/ref/jn-072026-7054766 | "4-8 años de experiencia" |
| Financial Planning & Analysis (FP&A) | anónima, distribución de automoción (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/financial-planning-analysis-fpa/ref/jn-102026-7116528 | "A minimum of 5 years' experience in Financial Planning / Controlling" |
| Finance and Business Controller | anónima, grupo industrial (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/finance-and-business-controller/ref/jn-072026-7071451 | "mínimo de 3-5 años como Controller en una multinacional del sector manufacturero" |
| Manager FP&A, Distribution Partnerships | Spotify | Estocolmo o Londres | https://jobs.lever.co/spotify/46c223d0-7b9c-4bff-9035-c0c6cc67bbdf | "5+ years of experience in FP&A, Strategy & Analytics, Investment Banking, Corporate Finance, or a similar analytical role" |

Extras: `Manager, Financial Planning & Analysis – Payments & Customer Service` (SP, https://jobs.lever.co/spotify/1d7db6ea-59dd-4ebb-86c5-f0f12ee2db92, "5+ years in FP&A, Corporate Development, Investment Banking, or strategic finance"); `Strategic Finance Partner - Marketing` (TF, https://job-boards.greenhouse.io/typeform/jobs/7681767, sin años).

#### G3. Tesorería

Caja, bancos, pagos, previsión de liquidez y riesgo financiero.

- Títulos ✔: `Treasury Specialist` (listado) o `Treasury Corporate` (ficha) (MPes), `Group Treasury Manager`, `Operational Treasury Executive with English C1`, `Responsable de Tesorería`, `Head of Treasury` (MPes y QO), `Expert, Treasury ALM` (BP), `Finance & Treasury Manager | Big4 Background` (MPpt), `Senior Capital Manager (m/f/d)` (MPes, sin leer).
- ○: `Tesorero/a`, `Técnico/a de tesorería`, `Analista de tesorería`. ○ FR: `Trésorier`, `Gestionnaire trésorerie`. ○ DE: `Treasury Manager`, `Treasurer`. ○ NL: `Treasury analyst`. ○ PT: `Tesoureiro`. ○ IT: `Tesoriere`.
- Parecidos: `Cash to Accounting` (contabilidad de cobros), `Head of Securities Operations - Private Banking` (MPch, operaciones de valores), `Finance Manager` (generalista).
- Niveles observados: `Specialist`, `Executive`, `Expert`, `Manager`, `Responsable`, `Head of`.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Treasury Corporate | anónima, energía (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/treasury-corporate/ref/jn-052026-7022126 | sin años |
| Operational Treasury Executive with English C1 | anónima, multinacional (Michael Page) | Barcelona | https://www.michaelpage.es/job-detail/operational-treasury-executive-english-c1/ref/jn-062026-7048597 | "Minimum of 2-3 years' experience in a Treasury function" |
| Responsable de Tesorería. Zona Noroeste de Madrid | anónima, servicios e infraestructuras (Michael Page) | Madrid noroeste | https://www.michaelpage.es/job-detail/responsable-de-tesorer%C3%ADa-zona-noroeste-de-madrid/ref/jn-092026-7114126 | "Minimum 4-5 years in corporate treasury, banking management or financial accounting" |
| Group Treasury Manager | anónima, grupo internacional (Michael Page) | A Coruña | https://www.michaelpage.es/job-detail/group-treasury-manager-coru%C3%B1a/ref/jn-072026-7058069 | "Más de 7 años de experiencia en tesorería y/o posiciones financieras con exposición directa a gestión de caja" |
| Head of Treasury (Tenerife) (m/f/d) | anónima, SaaS (Michael Page) | Tenerife | https://www.michaelpage.es/job-detail/head-treasury-tenerife-mfd/ref/jn-052026-7027550 | "Minimum of 8-10 years of experience in treasury leading roles" |

Extras: `Expert, Treasury ALM` (BP, Viena, https://job-boards.eu.greenhouse.io/bitpanda/jobs/4914511101, "3+ Years of Core Treasury Experience"); `Head of Treasury` (QO, París, https://jobs.lever.co/qonto/8c338d8b-59fb-465c-9d6b-e4ec7fa903dc, sin años; pide francés por la relación con el supervisor ACPR).

#### G4. Auditoría

Auditoría externa de cuentas, auditoría interna y control interno.

- Títulos ✔ EN: `Corporate Internal Auditor`, `Global Internal Auditor`, `Internal Audit Manager - Compliance` (QO), `Senior Internal Audit Manager` (GYG), `Head of Internal Controls` (GYG), `Internal Auditor`, `Internal Audit & Advisory`, `Senior Auditor Risk Management` (MPde), `Audit & Compliance Specialist`, `Internal Controller` (MPnl).
- Títulos ✔ ES: `Auditor/a Senior Interno`, `Auditor Interno Senior (A Coruña)`, `Auditor Interno Sector Industrial/Manufacturero`, `Auditor/a de Cuentas - Importante despacho`, `Responsable de auditoría`, `Responsable de Auditoría/Contabilidad`.
- Local ✔. FR: `Auditeur interne`, `Auditeur financier`, `Auditeur comptable international`, `Auditeur (H/F)`, `Chef de mission Audit`, `Responsable de mission audit`, `Directeur de missions Audit`, `Manager Audit - Assurance`. DE: `Internal Audit`, `Internal Auditor`, `Prüfungsleiter`, `Senior Consultant - WpHG Audit and Regulatory`. NL: `Auditor Controle & Support`.
- ○: `Auditor junior`, `Auditor de cuentas`, `Senior de auditoría`, `Gerente de auditoría`. ○ FR: `Commissaire aux comptes`, `Auditeur senior`. ○ DE: `Wirtschaftsprüfer`, `Revisor`. ○ PT: `Auditor interno`. ○ IT: `Revisore`.
- Parecidos o no deseados: `Auditor de Calidad` (MPes, calidad), `Consultant Senior Auditeur Energie & SMÉ` (MPfr, auditoría energética), `Medewerker Milieumetingen` (MPnl, medidas ambientales, apareció en el listado "audit"), `IT-Auditor`, `SAP GRC Manager` y `Interim GRC Lead` (TI y control; ver sección 7), `Audit & Finance Project Manager` (MPfr, sin leer), `Perito de Siniestros`.
- Niveles observados: `Senior`, `Manager`, `Responsable`, `Chef de mission`, `Directeur de missions`, `Prüfungsleiter`.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Corporate Internal Auditor | anónima, multinacional (Michael Page) | Barcelona | https://www.michaelpage.es/job-detail/corporate-internal-auditor/ref/jn-092026-7109419 | "Al menos 5 años de experiencia en auditoría o gestión de riesgos" |
| Global Internal Auditor | anónima, multinacional (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/global-internal-auditor/ref/jn-082026-7093151 | "experiencia mínima de 5 años en Auditoría Interna o Externa en entornos multinacionales" |
| Auditeur Interne (F/H) | anónima, grupo industrial (Michael Page) | Sèvres (Francia) | https://www.michaelpage.fr/job-detail/auditeur-interne-fh/ref/jn-032026-6974379 | "Au moins 5 années d'expérience en audit ou conseil" |
| Auditeur Financier F/H | anónima, cabinet d'audit et de conseil (Michael Page) | Villeneuve-d'Ascq (Francia) | https://www.michaelpage.fr/job-detail/auditeur-financier-fh/ref/jn-092026-7099149 | "d'une expérience d'au moins 4 ans sur un poste d'Auditeur Financier H/F" |
| Internal Audit Manager - Compliance | Qonto | París | https://jobs.lever.co/qonto/4207d7ea-7edb-48f2-8104-00d854d79316 | sin años ("Solid experience in internal audit within banking or payment institutions") |

Fichas leídas que caen en el límite de la familia (ver sección 7): `IT-Auditor (m/w/d)` (MPde, Fráncfort, https://www.michaelpage.de/job-detail/it-auditor-mwd/ref/jn-102026-7117545, sin años); `Auditor Controle & Support` (MPnl, La Haya, https://www.michaelpage.nl/job-detail/auditor-controle-support/ref/jn-092026-7100325, sin años); `Specialist, Risk & Controls Assurance` (BP, Viena, https://job-boards.eu.greenhouse.io/bitpanda/jobs/4867987101, "3–5 years of experience in risk, controls, assurance, or audit within financial services, fintech, payments, brokerage, or crypto environments").

#### G5. Fiscalidad

Impuestos de sociedades, IVA/VAT, fiscalidad internacional y cumplimiento fiscal.

- Títulos ✔ EN: `Tax Manager`, `Tax senior in house - Multinacional`, `Junior Tax Analyst`, `Tax & Statutory Compliance Executive`, `Tax Technology Specialist with English`, `Indirect Tax Executive with English`, `Tax Analyst` (SP), `Head of Tax` (AL), `Tax M&A 4-9 Años Experiencia`.
- Títulos ✔ ES: `Analista Fiscal - Tax Specialist con SAP`, `Responsable de Contabilidad & Tax`.
- Local ✔: DE `Steuerfachangestellter (m/w/d)` (asistente fiscal).
- ○: `Asesor/a fiscal`, `Técnico/a tributario`, `Fiscalista`. ○ FR: `Fiscaliste`, `Juriste fiscal`. ○ DE: `Steuerberater`, `Steuerreferent`. ○ NL: `Fiscalist`. ○ PT: `Técnico de fiscalidade`. ○ IT: `Consulente fiscale`.
- Parecidos: `Tax Technology Specialist` (software fiscal), `Tax M&A` en despacho (asesoría, no empresa), `Certified Accountant - Tax Residence in Spain` (contabilidad), `Legal Counsel ... Banking & Finance` (legal).
- Niveles observados: `Junior`, `Executive`, `Analyst`, `Specialist`, `senior`, `Manager`, `Head of`.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Junior Tax Analyst - Barcelona | anónima, entretenimiento en directo (Michael Page) | Barcelona | https://www.michaelpage.es/job-detail/junior-tax-analyst-barcelona/ref/jn-062026-7040184 | "1 año en un rol similar (despacho o empresa)" |
| Analista Fiscal - Tax Specialist con SAP | anónima, grupo agroalimentario (Michael Page) | provincia de Sevilla | https://www.michaelpage.es/job-detail/analista-fiscal-tax-specialist-con-sap/ref/jn-052026-7022528 | "Experiencia mínima de 3 años en fiscalidad nacional e internacional" |
| Tax Manager | anónima, energía (Michael Page) | Barcelona (Osona) | https://www.michaelpage.es/job-detail/tax-manager/ref/jn-092026-7099800 | "Experiencia mínima de 5 años en departamento fiscal, despacho de abogados o consultoría fiscal" |
| Tax senior in house - Multinacional | anónima (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/tax-senior-house-multinacional/ref/jn-072026-7072311 | "6-8 años de experiencia" |
| Tax M&A 4-9 Años Experiencia | "Despacho Grande" (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/tax-ma-4-9-a%C3%B1os-experiencia/ref/jn-092026-7099944 | "4-9 años" |

Extra: `Tax Analyst` (SP, Estocolmo, https://jobs.lever.co/spotify/d2489df3-87cb-48bb-81af-83aab5f03bdc, "Approximately 2 years of relevant tax related work experience").

#### G6. Nóminas

Cálculo y administración de nómina, Seguridad Social y retenciones.

- Títulos ✔ EN: `Payroll Specialist`, `Payroll Manager`, `Payroll Expert - SAP - Sector Energía Renovables`, `Senior Payroll Specialist - TEMP (maternity cover)` (el original escribe "Secialist"), `Payroll Admin - English C1`, `Payroll and HR Operations Manager`, `PAYROLL SPECIALIST / HR ANALYTICS`, `Head of Labor Relations & Payroll`, `Payroll Manager EMEA`.
- Títulos ✔ ES: `Payroll Expert/Técnico de nóminas - Empresa Multinacional en Barcelona (Temporal)`.
- ○: `Técnico/a de nóminas`, `Administrativo/a de nóminas`, `Responsable de nóminas`. ○ FR: `Gestionnaire de paie`. ○ DE: `Lohnbuchhalter`, `Entgeltabrechner`. ○ NL: `Salarisadministrateur`. ○ PT: `Técnico de processamento salarial`. ○ IT: `Addetto paghe`.
- Parecidos: `Senior C&B Manager` (QO) y `Senior Global Compensation and Benefits Manager` (GYG) son compensación y beneficios (RR. HH.); `Técnico/a de RRHH Senior` (MPes, RR. HH.); `Reisekostenabrechnung` (MPde, gastos de viaje, contabilidad).
- Niveles observados: `Specialist`, `Senior`, `Expert`, `Admin`, `Manager`, `Head of`.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Payroll Specialist | anónima, farmacéutica (Michael Page) | Barcelona | https://www.michaelpage.es/job-detail/payroll-specialist/ref/jn-092026-7110260 | sin años (cobertura de baja por maternidad, 3 meses) |
| Payroll Manager | anónima, externalización de servicios (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/payroll-manager/ref/jn-092026-7098298 | sin años (equipo de 6 a 11 personas) |
| Payroll Expert - SAP - Sector Energía Renovables | anónima, renovables (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/payroll-expert-sap-sector-energ%C3%ADa-renovables/ref/jn-082026-7077007 | "Experiencia previa de entre 7 y 10 años en puestos similares" |
| Senior Payroll Secialist - TEMP (maternity cover) | Michael Page SSC | Barcelona | https://www.michaelpage.es/job-detail/senior-payroll-secialist-temp-maternity-cover/ref/jn-092026-7105447 | sin años (≈ 700 empleados) |
| Payroll Expert/Tecnico de nominas-Multinacional Bcn (Temporal) | Michael Page (cliente anónimo) | Barcelona | https://www.michaelpage.es/job-detail/payroll-experttecnico-de-nominas-multinacional-bcn-temporal/ref/jn-092026-7114867 | sin años (contrato de 6 meses) |

#### G7. Compras (procurement)

Compras, abastecimiento, categorías y relación con proveedores.

- Títulos ✔ EN: `Purchasing Manager`, `Procurement Manager`, `Procurement Engineer (Automotive)`, `Project Procurement Engineer`, `Procurement & Operations Support Specialist`, `Head of Category Management`, `Supply Chain & Procurement Manager`.
- Títulos ✔ ES: `Coordinador de Compras - Sector Restauración / Food Service`, `Técnico/a de Compras`, `Responsable compras senior`, `Responsable de compras`.
- ○: `Comprador/a`, `Buyer`, `Analista de compras`, `Responsable de aprovisionamiento`. ○ FR: `Acheteur`. ○ DE: `Einkäufer`, `Strategischer Einkäufer`. ○ NL: `Inkoper`. ○ PT: `Comprador`. ○ IT: `Buyer`, `Addetto acquisti`.
- Parecidos o no deseados: `Procurement Engineer` (calidad de proveedores: APQP, PPAP, FMEA, IATF, VDA 6.3), `Demand Planner Iberia` (planificación), `Comptable fournisseurs - gestionnaires flux achats` (MPfr, cuentas a pagar).
- Niveles observados: `Técnico`, `Coordinador`, `Specialist`, `Manager`, `Responsable ... senior`, `Head of`.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Coordinador de Compras - Sector Restauración / Food Service | anónima, restauración internacional (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/coordinador-de-compras-sector-restauraci%C3%B3n-food-service/ref/jn-092026-7109418 | "Entre 1 y 3 años de experiencia en Procurement, Compras, Aprovisionamiento o Supply Chain" |
| Procurement & Operations Support Specialist | anónima, climatización (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/procurement-operations-support-specialist/ref/jn-062026-7051964 | "más de 5 años de experiencia en compras, logística u operaciones" (el perfil de candidato repite otra cifra; solo se cita la frase literal) |
| Procurement Manager | anónima, industrial multinacional (Michael Page) | Barcelona | https://www.michaelpage.es/job-detail/procurement-manager/ref/jn-102026-7119600 | sin años (experiencia en gestión y equipo de 3 personas) |
| Head of Category Management | anónima, gran consumo e industria (Michael Page) | Valencia | https://www.michaelpage.es/job-detail/head-category-management/ref/jn-082026-7077596 | "Experiencia mínima de entre 7 y 10 años en posiciones de compras, category management o strategic sourcing" |
| Procurement Engineer (Automotive) | anónima (Michael Page) | Barcelona | https://www.michaelpage.es/job-detail/procurement-engineer-automotive/ref/jn-092026-7112175 | "Minimum 3 years of experience in Supplier Quality Assurance, Supplier Development and/or Procurement Engineering, ideally 5+ years" (puesto de calidad de proveedores) |

#### G8. Administración y back office

Administración general, facturación, atención administrativa y soporte de oficina.

- Títulos ✔ ES: `Administrativo / Back Office con inglés B2`, `Administrativo/a Comercial`, `Responsable de Back Office y Digitalización`, `Back Office Técnico con SAGE`, `Back Office con EXCEL y análisis de datos`, `Administrativo comercial con Catalán`, `Back Office - Francés Fluido`.
- Títulos ✔ EN: `Administration Manager`, `Office Assistant con Inglés B2/C1`, `Finance & Administration Controller`, `Finance Administrator (M/F/X)` (MPbe), `Finance Assistant - 6-month contract` (MPch), `Junior Finance & Administration Support`.
- Local ✔: FR `Assistant(e) Back-Office`, `Gestionnaire Back-Office Juridique`, `Assistant d'Agence back office`; IT `Segreteria Amministrativa`; PT `Responsável Administrativo e Financero` (errata del original).
- ○: `Auxiliar administrativo`, `Asistente administrativo`, `Office Manager`, `Responsable administrativo`. ○ DE: `Sachbearbeiter`, `Verwaltungsangestellter`. ○ NL: `Administratief medewerker`.
- Parecidos o no deseados: `Back Office de siniestros` (seguros), `Back Office Comercial` (ventas), `Back Office Técnico` (preparación de material quirúrgico y almacén), `Customer service/back office` (atención al cliente), `Comercial Interno & Customer Support`, `Executive Assistant to CEO` (asistente de dirección).
- Niveles observados: `Assistant`, `Junior`, `Manager`, `Responsable`; el nivel casi no se escribe en esta familia.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Office Assistant con Inglés B2/C1 - Multinacional Barcelona | anónima, lujo (Michael Page) | Barcelona | https://www.michaelpage.es/job-detail/office-assistant-con-inglés-b2c1-multinacional-barcelona/ref/jn-072026-7054239 | "Perfil JUNIOR con 1-3 años de experiencia previa como Office Assistant/Recepción/Administración/Back Office" |
| Administrativo / Back Office con inglés B2 | anónima, robótica (Michael Page) | Barcelona | https://www.michaelpage.es/job-detail/administrativo-back-office-con-inglés-b2-barcelona/ref/jn-092026-7104047 | sin años |
| Back Office Técnico con SAGE | anónima, equipamiento médico (Michael Page) | Barcelona | https://www.michaelpage.es/job-detail/back-office-técnico-con-sage-barcelona/ref/jn-072026-7062048 | sin años (el trabajo incluye preparar equipos quirúrgicos y almacén) |
| Responsable de Back Office - Centro de Bilbao | anónima, transición energética (Michael Page) | Bilbao | https://www.michaelpage.es/job-detail/responsable-de-back-office-centro-de-bilbao/ref/jn-052026-7021718 | sin años |
| Administration Manager | anónima, colegio (Michael Page) | Barcelona | https://www.michaelpage.es/job-detail/administration-manager-barcelona/ref/jn-112025-6891061 | "3-5+ years of experience in management roles within finance/administration departments" |

#### G9. Crédito y riesgo

Dos significados distintos: riesgo de crédito de un banco o aseguradora y crédito a clientes de una empresa (límites, seguros de crédito, cobros). Los dos aparecen con el mismo título.

- Títulos ✔ EN: `Credit Risk Specialist fluent in English and Spanish` (crédito a clientes), `Credit Risk Officer - Trade Finance ENG / FR` (banco), `Senior Credit Officer FR / ENG` (banco privado), `European Risk Analyst (m/f)` (aseguradora), `Credit and Collections Analyst` (cobros), `Credit Controller` (MPnl y MPbe, cobros), `Financial Risk and Compliance Manager` (MPnl), `Responsable Compliance & Risk` (MPch), `ESG Risk & Sustainable Finance Analyst` (MPbe, Luxemburgo), `Credit Fraud Analyst` (QO).
- Títulos ✔ ES: ninguno en español puro. El único del listado de riesgo de MPes en español es `Responsable de Siniestros` (seguros; no es riesgo de crédito).
- Local ✔: FR `Directeur des Risques`.
- ○: `Analista de riesgos`, `Analista de crédito`, `Gestor de riesgos`, `Credit Analyst`. ○ FR: `Analyste crédit`, `Risk manager`. ○ DE: `Kreditsachbearbeiter`, `Risikocontroller`. ○ NL: `Risk analist`. ○ PT: `Analista de risco`. ○ IT: `Analista rischio di credito`.
- Parecidos o no deseados: `SAP GRC Manager`, `Interim GRC Lead`, `Manager IT Governance, Risk & Compliance` (TI), `Perito de Siniestros` (seguros), `Technical Pricing Actuary` (actuarial).
- Niveles observados: `Specialist`, `Officer`, `Senior`, `Analyst`, `Manager`, `Directeur`.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Credit Risk Specialist fluent in English and Spanish | anónima, belleza y moda (Michael Page) | Barcelona | https://www.michaelpage.es/job-detail/credit-risk-specialist-fluent-english-and-spanish/ref/jn-062026-7051776 | sin años (crédito a clientes: límites y seguro de crédito) |
| European Risk Analyst (m/f) - International Insurance Company | anónima, aseguradora (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/european-risk-analyst-mf-international-insurance-company/ref/jn-102026-7118870 | "3-5 years' experience in risk management, insurance, internal audit, compliance or a related control function" |
| Credit Risk Officer - Trade Finance ENG / FR 100% (m / f) | anónima, entidad financiera (Michael Page) | Ginebra | https://www.michaelpage.ch/job-detail/credit-risk-officer-trade-finance-eng-fr-100-m-f/ref/jn-082026-7088962 | "3 to 7 years of proven similar experience in credit analysis, credit risk management, corporate banking, or a similar environment in Switzerland" |
| Senior Credit Officer FR / ENG 100% (m / f) | anónima, banca privada (Michael Page) | Ginebra | https://www.michaelpage.ch/job-detail/senior-credit-officer-fr-eng-100-m-f/ref/jn-072026-7055614 | "At least 5 years of proven experience managing and monitoring complex Lombard lending transactions" |
| Credit and Collections Analyst en Sant Celoni | anónima, multinacional (Michael Page) | Sant Celoni (Barcelona) | https://www.michaelpage.es/job-detail/credit-and-collections-analyst-en-sant-celoni/ref/jn-122025-6902255 | sin años (cobros, SAP y HighRadius; ref de 2025) |

#### G10. Operaciones bancarias y de inversión

Middle y back office, liquidación de valores, administración de fondos, cumplimiento operativo.

- Títulos ✔ EN: `Associate, Financial Operations` (BP), `Fund Administrator - Financial Services` (MPch), `Head of Securities Operations - Private Banking`, `KYC Specialist - Private Banking`, `Sanctions Specialist - Banking`, `Investment Data Specialist - Madrid`, `Specialist, Trading Operations - Night Shift` (BP), `Finance & Operations Specialist` (MPch), `Regulatory Reporting Expert` (QO), `Team Lead Anti-Financial Crime`, `KYCB Analyst` y `KYCB Officer` (QO).
- Títulos ✔ ES: `Back Office Financiero Junior - Wealth Management`.
- Local ✔ FR: `Gestionnaire Middle Office - Opérations`, `Gestionnaire Middle Office Titres`, `Gestionnaire Middle Office Titrisation`, `Gestionnaire Middle Office - Société de gestion`, `Gestionnaire Back Office Moyens de paiement`, `Comptable banque`, `Comptable Banque Règlements`.
- ○: `Técnico/a de operaciones`, `Back office de valores`, `Analista de operaciones`. ○ DE: `Wertpapierabwicklung`. ○ IT: `Operations specialist`.
- Parecidos o no deseados: `Relationship Manager` y `Conseiller(ère) Clientèle en Gestion de Fortune` (banca privada comercial), `Directeur d'Agence` y `Responsable d'agence` (oficina bancaria), `Business Developer ... Private Banking`, `Chargé de service Clientèle`, `Conseiller Banque en Ligne` (atención), `Back Office de siniestros` (seguros).
- Niveles observados: `Associate`, `Specialist`, `Junior`, `Head of`, `Gestionnaire`.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Gestionnaire Middle Office - Opérations H/F | anónima, banco internacional (Michael Page) | París | https://www.michaelpage.fr/job-detail/gestionnaire-middle-office-opérations-hf/ref/jn-102026-7116686 | "Une expérience professionnelle d'environ 3 années sur un poste similaire" |
| Gestionnaire Middle Office Titres (H/F) | anónima, filial de grupo bancario (Michael Page) | Charenton-le-Pont | https://www.michaelpage.fr/job-detail/gestionnaire-middle-office-titres-hf/ref/jn-042026-6993888 | sin años (interim de 4 meses) |
| Fund Administrator - Financial Services | anónima, multi-family office (Michael Page) | Ginebra | https://www.michaelpage.ch/job-detail/fund-administrator-financial-services/ref/jn-092026-7115419 | "Around 3 years of experience in fund administration, fund operations, middle office, or a similar role" |
| Back Office Financiero Junior - Wealth Management | anónima, banca privada (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/back-office-financiero-junior-wealth-management/ref/jn-092026-7109546 | sin años |
| Associate, Financial Operations | Bitpanda | Viena | https://job-boards.eu.greenhouse.io/bitpanda/jobs/4996407101 | "Proven experience (1+ years) in an operations role, with a clear understanding of KYB documentation requirements" |

Extra: `Investment Data Specialist - Madrid` (MPes, aseguradora, https://www.michaelpage.es/job-detail/investment-data-specialist-madrid/ref/jn-092026-7112212, sin años).

#### G11. Reporting financiero y consolidación

Cierre de grupo, estados consolidados, normas contables y reporting regulatorio.

- Títulos ✔ EN: `Consolidation and Reporting Specialist`, `Consolidation Manager` y `Financial Reporting Manager` (GYG), `Specialist, Consolidation & Regional Finance` (BP), `Senior Finance Manager - Group Accounting & Reporting` (MPpt), `Group Finance Manager - Consolidations and FPA` (MPie), `Regulatory Reporting AVP` (MPie, el listado dice `Regulatory Reporting and Controls`), `Regulatory Reporting Expert` (QO), `Finance Director | IFRS | Consolidation` (MPpt), `Head of Accounting/Group`, `Teamlead Group Accounting`.
- Títulos ✔ ES: `Consolidation and Reporting Specialist` (mismo), `Senior Accounting` con "& Consolidation" en la ficha.
- Local ✔: FR `Responsable Comptable et Consolidation (F/H)`, `Directeur(ice) Comptabilité, Reporting & Consolidation`; DE `Leiter Konzernrechnungswesen`.
- ○: `Analista de consolidación`, `Responsable de consolidación y reporting`. ○ FR: `Consolideur`, `Contrôleur financier`. ○ DE: `Konzernbuchhalter`, `Konzernrechnungslegung`. ○ NL: `Consolidatie`.
- Parecidos: `Group Accountant` (contabilidad), `Controlling & Finance Analytics Manager`, `Finance Primary Data Senior Manager` (MPpt, datos).
- Niveles observados: `Specialist`, `Senior`, `Manager`, `AVP`, `Expert`, `Responsable`, `Director`.

| Título | Empresa | Lugar | URL | Años |
| --- | --- | --- | --- | --- |
| Consolidation and Reporting Specialist | anónima, multinacional (Michael Page) | Madrid | https://www.michaelpage.es/job-detail/consolidation-and-reporting-specialist/ref/jn-032026-6975880 | "Mínimo 5 años de experiencia (cliente final / Big4)" |
| Senior Finance Manager - Group Accounting & Reporting | anónima, tecnología de medios digitales (Michael Page) | Portugal, remoto | https://www.michaelpage.pt/job-detail/senior-finance-manager-group-accounting-reporting/ref/jn-102026-7116904 | sin años (pide ACCA, ACA, CIMA o CPA) |
| Regulatory Reporting AVP | anónima, banco de mercados de capitales (Michael Page) | Dublín | https://www.michaelpage.ie/job-detail/regulatory-reporting-avp/ref/jn-062026-7044538 | sin años ("mid to large Bank" y controles) |
| Responsable Comptable et Consolidation (F/H) | LE GOUESSANT (grupo cooperativo, Michael Page) | Lamballe (Francia) | https://www.michaelpage.fr/job-detail/responsable-comptable-et-consolidation-fh/ref/jn-032026-6960622 | "7 ans minimum en comptabilité" |
| Specialist, Consolidation & Regional Finance | Bitpanda | Viena | https://job-boards.eu.greenhouse.io/bitpanda/jobs/4988644101 | "2+ years of hands-on experience in group accounting, consolidation, or audit support." |

### 4.2 Vocabulario del sector finanzas y administración

#### Sustantivos que nombran al profesional

| Idioma | Vistos hoy ✔ | No vistos ○ |
| --- | --- | --- |
| Inglés | accountant, controller, analyst, specialist, auditor, manager, officer, executive, administrator, assistant, coordinator, associate, expert, business partner, `Head of`, `Chief ... Officer` | treasurer, buyer, payroll clerk |
| Español | contable, técnico/a contable, analista fiscal, responsable de, auditor/a, técnico/a de compras, técnico de nóminas, coordinador/a, administrativo/a, controller financiero, director/a financiero/a, consultor/a | contador, tesorero, comprador, asesor fiscal, auxiliar administrativo, jefe de contabilidad |
| Francés | comptable, aide comptable, collaborateur comptable, auditeur, chef de mission, gestionnaire (middle office), responsable, directeur des finances, assistant(e) | contrôleur de gestion, trésorier, acheteur, fiscaliste, gestionnaire de paie |
| Alemán | Buchhalter, Finanzbuchhalter, Bilanzbuchhalter, Kreditorenbuchhalter, Debitorenbuchhalter, Controller, Finanzcontroller/in, Vertriebscontroller, Produktionscontroller, Werkscontroller, Leiter/in, Teamleiter, Prüfungsleiter, Steuerfachangestellter | Steuerberater, Wirtschaftsprüfer, Einkäufer, Lohnbuchhalter |
| Neerlandés | Controller, Assistent Controller, Financial Controller, Credit Controller, Finance Administrator | boekhouder, inkoper, salarisadministrateur |
| Portugués | técnico(a) de contabilidade, responsável administrativo e financeiro, diretor, consultor financeiro | contabilista, comprador, tesoureiro |
| Italiano | segreteria amministrativa, specialista ERP (casi todo lo demás sale en inglés: `Finance Manager`, `Head of Finance`, `Chief Accountant`) | contabile, responsabile amministrativo, buyer |

#### Señales de rol no técnico o ajeno al sector (vistas hoy ✔)

`Agente Comercial`, `Account Manager`, `Account Executive`, `Sales Development Representative`, `Business Developer`, `Avvocato`, `Legal Counsel`, `Responsable Juridique`, `Attaché de Presse`, `Personalberater` (reclutador), `Customer Service`, `Conseiller Clientèle`, `Directeur d'Agence`, `Relationship Manager`, `Perito de Siniestros`, `Technical Pricing Actuary`, `Project Manager ERP`, `Consultor/Consultant ERP`, `SAP FI` (consultoría), `PMO`, `CRM`, `Demand Planner`, `Plant Manager`, `HSE Manager`, `Responsable de PRL`.

#### Grafías compuestas

| Concepto | Variantes vistas ✔ |
| --- | --- |
| FP&A | `FP&A`, `FPA`, `Financial Planning & Analysis`, `Financial Planning and Analysis` |
| back office | `Back Office`, `Backoffice`, `Back-Office` |
| registro a informe | `Record to Report`, `R2R` |
| cobros y pagos | `Accounts Payable`, `Accounts Payables`, `AP`, `OTC`, `Cash to Accounting`, `Kreditorenbuchhalter`, `Kreditorebuchhaltung` (errata en el original) |
| controlling | `Controller`, `Controlling`, `Finanzcontroller/in`, `Business Controller`, `Finance Business Partner`, `Commercial Controller` |
| otros | `Group Finance`, `Corporate Finance`, `P&L`, `IFRS`, `ACCA`, `Middle Office` |

#### Herramientas y normas: lo que se pidió frente a lo que se vio

| Término pedido | ¿Visto hoy? | Dónde |
| --- | --- | --- |
| SAP | ✔ | contabilidad, FP&A, tesorería, fiscalidad, nóminas, compras, crédito (casi todas las familias) |
| Oracle | ✔ | `Head of Category Management` (ERP: SAP, Oracle, RMS); valorado en `Power BI Reporting` |
| Excel | ✔ | todas las familias (casi siempre "avanzado") |
| Power BI | ✔ | FP&A, consolidación, crédito (preferido) |
| Hyperion | ✗ | no apareció en ninguna ficha |
| Anaplan | ✗ | no apareció |
| IFRS | ✔ | contabilidad, consolidación, auditoría, fiscal (Typeform), IFRS 15 y 16 |
| PGC (Plan General Contable) | ✗ | no aparece escrito; sí "Spanish GAAP", "Spanish accounting regulations", "Normativa contable y fiscal" |
| US GAAP | ✔ (solo título) | `Senior Accounting Specialist (US GAAP)` (MPes, listado sin abrir) |
| SII (Solvency II) | ✔ | una ficha de aseguradora: `European Risk Analyst` (Solvency II, ORSA, EIOPA) |
| Basel | ✗ | no apareció; sí COREP y FINREP (`Regulatory Reporting AVP`), IRRBB, MiFID II, MiCAR (`Expert, Treasury ALM`) |

Otras herramientas y normas vistas ✔: NetSuite (Senior Accounting, Typeform, Spotify), Microsoft Dynamics 365 y Business Central, Navision, Sage 200 y SAGE, Cegid XRP, LucaNet, SAP BPC, Workday Financials, Adaptive, Kyriba, Murex, SWIFT, SEPA, Bloomberg, Meta4, PeopleNet, SAP SuccessFactors, YOOZ, HighRadius, Infor LN, SCIIF e ICFR, COSO, ERM, Belgian GAAP y German GAAP (solo en títulos de MPbe), DORA, MaRisk, BAIT, KYC y KYB, MiCAR. Titulaciones y certificaciones: CIA, CPA, ACCA, ACA, CIMA, DSCG, Master CCA, DEC, ACAMS, CISA.

#### Herramientas por familia: núcleo, adyacente y ajeno

Mismo criterio y misma cautela que en 3.2.

| Familia | Núcleo | Adyacente | Ajeno |
| --- | --- | --- | --- |
| Contabilidad | SAP, NetSuite, Excel, IFRS, Spanish GAAP, IVA/VAT, Business Central, Dynamics, Navision, Sage, Cegid XRP | US GAAP, Belgian GAAP, German GAAP, YOOZ, HighRadius, Infor LN | Salesforce, desarrollo de ERP |
| FP&A y control de gestión | Excel avanzado, Power BI, SAP, SAP BPC, Dynamics 365, NetSuite, Adaptive, Workday Financials, SQL | Tableau | CRM, Salesforce |
| Tesorería | SAP, SWIFT, SEPA, Kyriba, Murex, TMS, Excel, banking APIs, cash pooling, covenants | MiCAR, MiFID II, IRRBB, Navision, Sage 200 | Bloomberg de operaciones de inversión |
| Auditoría | IFRS, SCIIF, ICFR, COSO, ERM, IIA, CIA, CPA, DEC | DORA, MaRisk, BAIT, ISO 27001, CISA, ACAMS | ISO 9001 de calidad, auditoría energética |
| Fiscalidad | SAP, Excel, Impuesto sobre Sociedades, IVA/VAT, retenciones | NetSuite, FATCA y CRS | asesoría legal de M&A |
| Nóminas | SAP SuccessFactors, SAP, PeopleNet, Meta4, Excel, Estatuto de los Trabajadores, convenios colectivos, Seguridad Social, IRPF | HR systems, beneficios | reclutamiento |
| Compras | SAP, Oracle, RMS, ERP, Excel, spend analysis, TCO, RFQ | Salesforce, APQP, PPAP, FMEA, IATF, VDA 6.3 | calidad de proveedores como foco único |
| Administración y back office | Excel, Word, ERP (Infor LN), Sage | SAP, Salesforce | preparación de almacén, atención telefónica |
| Crédito y riesgo | SAP, HighRadius, Power BI, Excel, seguro de crédito; banco: Lombard lending, LTV, análisis de estados financieros; aseguradora: Solvency II, ORSA, EIOPA, RCSA | Excel con macros | SAP GRC y GRC de TI |
| Operaciones bancarias | KYC, KYB, SWIFT, Bloomberg, Excel, NAV, AMF, OPC | Murex | venta y relación con clientes |
| Reporting y consolidación | IFRS, LucaNet, SAP BPC, Excel, Power BI, Cegid XRP, COREP, FINREP, IFRS 15 y 16, ACCA, ACA, CIMA, CPA, DSCG, Master CCA | ERP genérico | contabilidad de despacho |

### 4.3 Portales del sector finanzas y administración

Ver la sección 5.

## 5. Portales y directorios (con feed o API pública o sin ella)

LinkedIn, Indeed e InfoJobs: **solo se constata que existen** (InfoJobs no se abrió; `es.indeed.com` apareció en una búsqueda). No se usan ni se propone scraping.

Estado de verificación: **✔** = documentación o página leída hoy. **○** = existe por conocimiento general, no abierto hoy, feed o API **no verificados**.

### 5.1 Con feed o API verificados hoy

| Portal o proveedor | Sector | Países | ¿Feed o API pública? | Verificación |
| --- | --- | --- | --- | --- |
| Greenhouse (tablero por empresa) | ambos | todos (por empresa) | **Sí**, sin autenticación para GET: `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs` ("authentication is not required for any GET endpoints") | ✔ documentación. No hay listado global de empresas; hay que conocer el token. Datadog, MongoDB, Databricks y N26 redirigen a su propia web de empleo |
| Lever (tablero por empresa) | ambos | todos (por empresa) | **Sí**, sin autenticación: `https://api.lever.co/v0/postings/{site}`; host UE `https://api.eu.lever.co/v0/postings/{site}` | ✔ documentación |
| Ashby (tablero por empresa) | ambos | todos (por empresa) | **Sí**, sin autenticación: `GET https://api.ashbyhq.com/posting-api/job-board/{JOB_BOARD_NAME}` | ✔ documentación. El tablero HTML (`jobs.ashbyhq.com/ramp`) no devolvió contenido a mi lector; la API es la vía |
| SmartRecruiters | ambos | todos (por empresa) | **No pública**: la Posting API pide API key u OAuth 2.0 | ✔ documentación. Las páginas públicas de oferta sí se leen (Flink, Sopra Steria) |
| Arbeitnow | software y generalista | Europa y Reino Unido, mucha Alemania | **Sí**, sin clave: `https://www.arbeitnow.com/api/job-board-api`. Agrega ofertas de ATS (Greenhouse, SmartRecruiters, Join.com, Team Tailor, Recruitee, Comeet) | ✔ documentación. Sin límites declarados en la página; endpoint privado de pago bajo petición |
| Remotive | software, remoto | global, filtrar por ubicación | **Sí**, sin clave: `GET https://remotive.com/api/remote-jobs`. Máximo 2 peticiones por minuto, uso recomendado 4 veces al día, retraso de 24 h, atribución obligatoria, prohíbe reenviar sus ofertas a terceros (Jooble, Google Jobs, LinkedIn) | ✔ documentación |
| TheirStack | ambos | filtro por país (ISO) | **Sí, de pago**: `Authorization: Bearer`, 1 crédito por oferta devuelta, filtros por título, país, seniority, tecnologías y antigüedad | ✔ documentación. Ya existe `connectors/theirstack.py` en el repositorio |
| Adzuna | ambos | no verificado qué países cubre | **Sí, con registro**: obliga a pasar `app_id` y `app_key` | ✔ documentación (cobertura de países y condiciones: no verificadas) |
| Bundesagentur für Arbeit (Jobsuche) | ambos | Alemania | **No oficial**: endpoint `https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/` documentado por la comunidad con cabecera `X-API-Key`; el propio README dice que la Bundesagentur no ofrece API oficial | ✔ README de la comunidad. Riesgo de cambio sin aviso |
| EURES (portal europeo) | ambos | UE | La página de inicio no menciona API ni feed | ✔ solo la ausencia en la home; no prueba que no exista |
| Michael Page (9 dominios) | finanzas sobre todo; también tecnología | ES, FR, DE, NL, PT, IT, IE, CH, BE y LU | **No vi feed**. Páginas `/jobs/<palabra>` y `/job-detail/...` legibles; salario y referencia visibles | ✔ lectura de páginas. `robots.txt` de `.es` resumido automáticamente (permite `/job-detail/`, bloquea `/job-apply/` y `*/jobs/*/*/*/`): releerlo antes de cualquier automatización. `pagepersonnel.es` redirige (301) a `michaelpage.es` |

### 5.2 Existen, feed o API no verificados

| Portal | Sector | Países | Nota |
| --- | --- | --- | --- |
| France Travail (API "Offres d'emploi") | ambos | FR | ○ Su página de documentación no devolvió contenido a mi lector; no verificado si es pública ni qué requiere |
| WeAreDevelopers | software | Europa | Apareció en búsquedas; devolvió 403 a mi lector |
| Built In (`builtin.com`, secciones UE) | software | PT, ES, otros | Apareció en búsquedas; no abierto |
| StepStone (`stepstone.de`) | ambos | DE y otros | Apareció en búsquedas; no abierto |
| Iberempleos (`iberempleos.es`) | finanzas, generalista | ES | Apareció en búsquedas (fichas de FP&A); no abierto |
| Expresso Emprego (`expressoemprego.pt`) | generalista | PT | Apareció en búsquedas; no abierto |
| JobFluent (`jobfluent.com`) | software | ES (Barcelona) | Apareció en búsquedas; no abierto |
| Justjoin.it, Jointaro, Instaffo, European Job Days | software | PL, DE, UE | Aparecieron en búsquedas; no abiertos |
| Jobgether (tablero en Lever) | ambos | remoto | Agregador. Varias de sus fichas daban 404 |
| Glassdoor, Tecnoempleo, Infoempleo, Computrabajo | ambos | ES | ○ Solo existencia, por conocimiento general |
| Welcome to the Jungle, APEC, Hellowork | ambos | FR | ○ Solo existencia |
| Xing | ambos | DE | ○ Solo existencia |
| Nationale Vacaturebank | ambos | NL | ○ Solo existencia |
| VDAB | ambos | BE | ○ Solo existencia |
| IrishJobs | ambos | IE | ○ Solo existencia |
| Moovijob | ambos | LU | ○ Solo existencia |
| jobs.ch | ambos | CH | ○ Solo existencia |
| Net-Empregos | ambos | PT | ○ Solo existencia |
| Hays y Robert Walters | finanzas | varios | ○ Consultoras de selección; no consultadas |

Directorios de empresas útiles para el catálogo por sector (ver diseño, punto 4): los tableros de Greenhouse, Lever y Ashby por empresa sirven como directorio y se leen con la API pública. De las empresas probadas hoy, diez tenían tablero legible con su token público: In The Pocket, GitLab, Typeform, GetYourGuide, Bitpanda, Alpaca y Anthropic en Greenhouse; Spotify, Palantir y Qonto en Lever. Las que fallaron (404 o redirección a su web) no se cuentan como directorio.

## 6. Qué no se pudo verificar y siguientes pasos

1. **Cobertura por país en finanzas:** falta una ficha leída de Italia y de Luxemburgo. Los listados de Michael Page los cubren solo con títulos.
2. **Frontend, ingeniería de analítica y ciencia de datos** quedaron con 3 a 4 fichas, no 5. Habría que leer otros tableros de empresa (Ashby y Workable no se pudieron leer con este método).
3. **Títulos de software en español, francés, alemán, neerlandés, portugués e italiano**: casi no hay evidencia (las ofertas de software salen con título en inglés). Para la plantilla, mantener los sustantivos locales como ○ hasta tener muestras.
4. **Sin ofertas de nivel de entrada en alemán y holandés** en Michael Page (sus listados favorecen puestos altos). Conviene una segunda pasada con filtros de nivel.
5. **Caducidad:** las fichas cambian cada semana y algunas llevan referencias de 2025. Repetir la lectura antes de convertir esta evidencia en un corpus de prueba.
6. **Corpus de prueba posible:** los títulos de las secciones 3, 4 y 7 pueden etiquetarse a mano y servir como fixtures de la segunda plantilla (positivos, negativos y ambiguos). No hay ninguna clasificación hecha por el sistema aquí: las asignaciones a familia son mías.
7. **Pendiente de decidir con quien mantenga la plantilla:** si `Specialist`, `Executive`, `Expert`, `Coordinator` y `Officer` pasan a ser niveles propios en la plantilla de finanzas (hallazgo 2 de la sección 1).

## 7. Ambigüedades: títulos que no se pueden clasificar sin leer la descripción

Todos los ejemplos se leyeron hoy (listado o ficha). "Qué lo decide" es lo que la ficha dijo o lo que habría que mirar.

### 7.1 Software y datos

| Título (fuente) | Familias posibles | Qué lo decide |
| --- | --- | --- |
| `Senior AI Engineer` (GL) | ML/IA, automatización de negocio | La ficha habla de Salesforce, Marketo, Zendesk, Workato, n8n y agentes para sistemas de empresa: no es ingeniería de ML |
| `Responsable de IA` (MPes) | ML/IA, dirección, estrategia | "Estrategia de implantación de la IA": gestión, no desarrollo |
| `Data & AI Engineer` (MPes) | ingeniería de datos, ML/IA | Python, R y LLM frente a pipelines |
| `Data Analytics (h/m)` (MPes) | análisis de datos, ingeniería de analítica | dbt, BigQuery, Looker y Kimball: ingeniería de analítica |
| `Data Scientist, Company Planning & Execution` (SP) | ciencia de datos, análisis de datos | SQL, dbt, Tableau, Looker y planificación: perfil de analista senior |
| `Data Analyst` (varios) | análisis de datos, BI, ingeniería de analítica | Si exige dbt y modelado, es analítica |
| `Power BI Reporting` (MPes) | BI, desarrollo | El texto dice "Senior Power BI Developer" |
| `Forward Deployed Software Engineer` y `Forward Deployed Infrastructure Engineer` (PL) | soluciones/FDE, ingeniería, infraestructura | Habilitación de seguridad, nacionalidad, idioma obligatorio y viajes del 25 al 75 % |
| `Deployment Strategist` (PL) | soluciones, consultoría, ventas técnicas | Python, R y SQL son "a plus"; no es desarrollo |
| `Solution Architect Pres-Sales Cloud` (MPes) | soluciones, preventa (sales engineer) | "Pre-sales" indica venta técnica |
| `Senior Product Engineer - Android/Kotlin` (QO) | móvil, full stack | El sufijo dice la plataforma |
| `Web Engineer` (SP) | frontend, full stack | TypeScript y React más GraphQL, PostgreSQL y jOOQ: full stack |
| `Platform Engineer` (GL) | DevOps/plataforma, backend | Rust, Kubernetes, Helm, Terraform y ClickHouse: infraestructura de plataforma |
| `Backend Engineer - Data Platform` y `Senior Backend Data Engineer` (SP) | backend, ingeniería de datos | Java, BigQuery, Flink y catálogo de datos |
| `Backend Engineer - Platform Security` (SP) | backend, seguridad | Autenticación y autorización |
| `Senior Embedded Cybersecurity Engineer` (MPes) | seguridad, desarrollo embebido | C/C++, ARM y FreeRTOS |
| `Senior SOC Analyst` (BP) | seguridad | La ficha pide "4+ years of hands-on security engineering experience", texto idéntico al de ingeniero |
| `Data Risk Engineer` (AL) | seguridad, riesgo | DLP, SIEM, NIST CSF y SOC 2: seguridad de la información |
| `Quality Engineer` (ITP) | QA de software, calidad industrial | Tests automáticos de UI y de sistema: software |
| `Senior Product Quality Analyst - AI Voice` (SP) | QA, evaluación de calidad de voz | Evaluación de productos de IA, no pruebas de software |
| `Senior Software Engineer, Quality Engineering` (AL) | QA, backend | Go, Kubernetes, k6 y chaos engineering: ingeniería de calidad |
| `Responsable de seguridad` (MPes, Valencia) | seguridad informática, seguridad física, PRL | No leído: el título no lo dice |
| `Migration Engineer - GitLab Dedicated` (GL) | DevOps, consultoría | No leído |
| `Staff Fullstack Engineer, Data Products (Golang / Node)` (GL) | full stack, ingeniería de datos | CDC, Snowflake y Databricks: datos |
| `Software Engineer` genérico (PL) | cualquier familia de software | Solo la descripción |
| `Technical Senior CRM Dynamics CE` (MPes) | desarrollo, soluciones, CRM de negocio | No leído |
| `AI Transformation Expert` (ITP) | ML/IA, consultoría | No leído |

### 7.2 Finanzas y administración

| Título (fuente) | Familias posibles | Qué lo decide |
| --- | --- | --- |
| `Controller` / `Financial Controller` (NL, DE, CH, BE, IE) | FP&A, contabilidad, control industrial, dirección financiera | Si hay cierre y estatutarios (contabilidad), presupuesto y previsión (FP&A) o costes de planta. Un listado de MPnl muestra `Financial Controller` con una tarifa por hora (posible interino; no verificado) |
| `Produktionscontroller`, `Werkscontroller`, `Plant Finance Manager` | control industrial (costes), FP&A | Costes de producción |
| `Finance Manager` y `Head of Finance` (ES, NL, IT, PT) | contabilidad, FP&A, tesorería, administración | En empresas pequeñas es generalista: la descripción lista qué áreas dirige |
| `Administracion y finanzas Senior` (MPes, listado: `Finance Analytic Controller`) | contabilidad, FP&A, administración | La ficha cubre ERP, IFRS y gestión; el titular del listado decía otra cosa |
| `Credit Controller` (NL, BE) | crédito y riesgo, cobros (cuentas a cobrar) | Cobros a clientes, no riesgo bancario |
| `Credit Risk Specialist` (MPes) | crédito a clientes, riesgo bancario | La ficha habla de límites de crédito y seguros de crédito de clientes de una empresa de belleza |
| `Credit and Collections Analyst` (MPes) | cobros, riesgo | SAP y HighRadius: cuentas a cobrar |
| `Internal Controller` (MPnl), `Senior Analyst, Global IT - SAP Internal Controls` (MPnl), `SAP GRC Manager`, `Manager IT Governance, Risk & Compliance`, `Interim GRC Lead` (MPes) | auditoría, control interno, riesgo, seguridad de TI | Control financiero frente a control de accesos y SAP |
| `IT-Auditor` (MPde) | auditoría, seguridad | DORA, MaRisk, BAIT, ISO 27001, CISA/CISM |
| `Auditor Controle & Support` (MPnl) | auditoría, inspección de declaraciones | "controleren, analyseren en beoordelen van aangiften" (revisar declaraciones de terceros) |
| `Specialist, Risk & Controls Assurance` (BP) | auditoría, riesgo, control | "risk, controls, assurance, or audit" |
| `Auditeur` y `Auditeur (H/F)` (MPfr) | auditoría financiera, calidad, energía | Hay `Auditeur Energie & SMÉ`; `Auditeur financier` pide IFRS y DEC |
| `Auditor de Calidad` (MPes) | calidad industrial, auditoría | No es financiera |
| `Collaborateur Comptable` (QO) | contabilidad de despacho, contabilidad de empresa | Cartera de clientes, DSCG y "mémorialiste": despacho |
| `Account Executive Accounting - France` y `Staff Product Manager [Accounting expertise]` (QO) | ventas, producto | Parece contabilidad, es venta o producto |
| `SAP FI`, `Administrateur SAP Finance`, `Técnico ERP (Módulo Contabilidad)`, `Finance Systems Analyst`, `Consultant ERP Finance - NetSuite` | contabilidad, TI de ERP, consultoría | Si configura el sistema (TI) o usa el sistema (contabilidad) |
| `Procurement Engineer` (MPes) | compras, calidad de proveedores | La ficha pide APQP, PPAP, FMEA, IATF, VDA 6.3: ingeniería de calidad |
| `Procurement & Operations Support Specialist` (MPes) | compras, operaciones, soporte comercial | Salesforce y logística |
| `Supply Chain & Procurement Manager` (MPes) | compras, logística | No leído |
| `Back Office` (MPes, más de una docena de tarjetas con esa palabra) | administración financiera, seguros (siniestros), soporte comercial, atención al cliente, almacén | La ficha de `Back Office Técnico con SAGE` incluye preparación de material quirúrgico; la de `Back Office Financiero Junior` es de banca privada |
| `Administrativo/a Comercial` y `Back Office Comercial` | administración, ventas internas | Facturación y reclamación de cobros frente a apoyo comercial |
| `Master Data Specialist` y `Accounts Payables - Master Data` (MPes) | contabilidad, datos | Datos maestros de ERP |
| `Payroll Specialist / HR Analytics` (MPes) | nóminas, RR. HH., analítica | No leído |
| `Senior C&B Manager`, `Senior Global Compensation and Benefits Manager` (QO, GYG) | RR. HH., nóminas | Compensación y beneficios |
| `KYC Specialist`, `KYCB Analyst`, `Sanctions Specialist`, `Team Lead Anti-Financial Crime` | cumplimiento, operaciones bancarias | Cumplimiento normativo frente a operación diaria |
| `Regulatory Reporting AVP` y `Regulatory Reporting Expert` | reporting regulatorio, consolidación, contabilidad | COREP y FINREP (banca) frente a IFRS de grupo |
| `Fund Administrator`, `Investment Data Specialist` | operaciones de inversión, contabilidad, datos | NAV y suscripciones frente a datos de mercado |
| `Corporate Finance`, `Senior Associate M&A`, `Transaction Advisory`, `Investment & Corporate Finance Manager` | finanzas corporativas, banca de inversión, FP&A | Asesoría de transacciones frente a finanzas internas de una empresa |
| `Consultor Senior de Estrategia y Operaciones (Big 4)`, `Consultant Senior Capital markets & accounting advisory` | consultoría, finanzas | No leído |
| `Finance Operations` (IT, BP, CH) | operaciones bancarias, contabilidad | Tareas diarias de la ficha |
| `Perito de Siniestros`, `Technical Pricing Actuary` | seguros, actuarial | Fuera del sector aunque salgan en listados de finanzas y riesgo |

### 7.3 Familias más y menos ambiguas

- **Más ambiguas en software y datos:** ingeniería de analítica frente a análisis de datos y ciencia de datos (tres nombres para tareas contiguas), ML/IA frente a automatización de negocio, soluciones/forward deployed frente a preventa y consultoría, seguridad frente a auditoría y calidad, y frontend frente a full stack cuando el título dice `Web` o `Product Engineer`.
- **Menos ambiguas en software y datos:** backend, móvil y DevOps/SRE casi siempre se clasifican solo por el título (con la salvedad de plataforma de datos y de seguridad).
- **Más ambiguas en finanzas y administración:** crédito y riesgo (tres significados), auditoría (financiera, interna, de TI, de calidad), FP&A y controlling (los títulos `Controller` y `Finance Manager` cubren varias familias), administración y back office (el mismo título, cuatro trabajos distintos) y operaciones bancarias frente a cumplimiento.
- **Menos ambiguas en finanzas y administración:** fiscalidad, nóminas, tesorería y compras (con la excepción de `Procurement Engineer`), porque el sustantivo ya fija el área.
