# Catálogo de empleadores: Finanzas y administración (investigación 2026-10-06)

Sector: finanzas y administración (contabilidad, análisis financiero y control de gestión / FP&A, tesorería, auditoría, administración y back office, nóminas, fiscal, compras, operaciones bancarias). Todos los niveles. Países: España primero, luego Portugal, Francia, Alemania, Países Bajos, Bélgica, Irlanda, Luxemburgo, Suiza e Italia. Candidatos hispanohablantes y anglohablantes.

Fichero de leads asociado: `config/leads/catalog-finance-2026-10.json` (256 leads, `source_label` `catalog_finance_2026_10`).

## Leer primero

- **Fecha de lectura de todas las URL de este documento: 2026-10-06** (cada tabla indica la URL del tablero leído). Nada procede de resúmenes de buscador: los datos salen de lecturas directas de las APIs públicas sin clave, de los sitemaps y de las fichas de oferta de cada empresa.
- **256 empleadores con tablero público verificado y al menos una vacante de finanzas/administración en los diez países** (2080 vacantes relevantes encontradas en total). Salieron de 1001 nombres candidatos que sondeé (la lista de candidatos es mía: un nombre candidato no es un hecho hasta que su tablero responde y su identidad se comprueba).
- Tipo de tablero de los 256 incluidos: careers site (sitemap + JobPosting) 115, Workday 79, Greenhouse 19, SmartRecruiters 16, Ashby 11, Recruitee 7, Lever 6, Personio 2, RSS público 1.
- Empleadores por país (una empresa cuenta en cada país donde tiene vacantes relevantes): España 75, Portugal 28, Francia 69, Alemania 96, Países Bajos 55, Bélgica 31, Irlanda 33, Luxemburgo 23, Suiza 32, Italia 38.
- Los **recuentos son cotas inferiores** en los sitios propios (se leen hasta 40 fichas por empresa, 80 si el título no está en la URL) y dependen de una clasificación por título (ver «Método»). No son «vacantes abiertas de la empresa».
- **Fechas**: Greenhouse, Lever, Ashby, SmartRecruiters, Personio, Teamtailor, Recruitee y los sitios con JobPosting publican fecha; Workday solo dice «hace N días» hasta 29 y «30+» después (leí `startDate` en tres fichas de muestra por tablero). Los tableros sin fecha (Société Générale, Engie, Pirelli, Bank of America, bpost, CNH Industrial, Deloitte Luxemburgo, ITA Airways, Banque Cantonale Vaudoise) se mantienen y lo indican como «sin fechas». Excluí los tableros cuyas ofertas relevantes llevan fecha pero todas son anteriores a 2026-07-08.
- **Niveles**: se deducen solo de marcadores en el título («intern», «junior», «senior», «manager», «director», «head of»…). «Sin marcador» agrupa lo que no dice nivel y probablemente es nivel medio; **no es un hecho** que sea mid. Reparto global de las vacantes relevantes: prácticas/graduate 472, junior 85, sin marcador (mid probable) 715, senior 285, responsable/manager 428, director/head 95.
- **Idioma**: lo detecto sobre el texto de la oferta (palabras funcionales) o, en SmartRecruiters, con el código de idioma que da la API. Cuando solo tengo el título (Workday) lo marco «n/d» y doy la muestra de tres fichas.
- **Banco de España** se incluye como excepción documentada: su «tablero» es un RSS público más páginas HTML de convocatorias, sin ATS ni JobPosting; hace falta un conector RSS para vigilarlo. Cuenta 1 vacante administrativa estricta (Auxiliar administrativo de caja) y 4 llamadas de economista/técnico general que no cuento.
- No consiguieron lectura: KPMG (ver sección 3), CNMV (portal 403 desde el entorno), CESCE, ICO (Workday con 4 ofertas, ninguna de finanzas), Sabadell, Bankinter, Unicaja, Ibercaja y otros (motivos en la sección 3).

## 1. Método y criterios

1. **Candidatos**: 1001 nombres escritos por mí (bancos y aseguradoras, Big Four y consultoras, grandes corporaciones de energía, telecomunicaciones, retail, industria y farma, fintech, gestoras, administradores de fondos, centros de servicios compartidos y organismos financieros públicos de los diez países). Ningún nombre se da por bueno sin lectura.
2. **Descubrimiento de tableros** (todo sin clave): (a) sondeo de slugs en Greenhouse (`boards-api.greenhouse.io/v1/boards/{slug}/jobs`), Lever (`api.lever.co/v0/postings/{slug}?mode=json`, y host `api.eu.lever.co`), Ashby (`api.ashbyhq.com/posting-api/job-board/{slug}`), Workable (`apply.workable.com/api/v1/widget/accounts/{slug}`), SmartRecruiters (`api.smartrecruiters.com/v1/companies/{slug}/postings`), Personio (`{slug}.jobs.personio.de/xml`), Teamtailor (`{slug}.teamtailor.com/jobs.rss`) y Recruitee (`{slug}.recruitee.com/api/offers/`); (b) Workday: el `robots.txt` del tenant (`{tenant}.wdN.myworkdayjobs.com/robots.txt`) declara el sitio permitido y leo `/wday/cxs/{tenant}/{sitio}/jobs`, filtrando por la faceta de país cuando existe; (c) sitios de empleo propios (SuccessFactors, Phenom y similares) con sitemap y fichas con JobPosting (JSON-LD o microdatos), respetando `robots.txt`; (d) segundo salto: página de inicio de la empresa, enlaces de empleo y, desde ahí, el ATS o el host de empleo.
3. **Cortesía**: una petición por segundo por host, `User-Agent` identificado (`AI-Job-Hunter/0.1`), sin autenticación, sin saltarse ningún muro de login. Peticiones de lectura únicamente; no se envió nada a ninguna empresa.
4. **Identidad del tablero**: un slug acertado puede ser de otra empresa. Acepté un tablero solo si (i) el nombre que devuelve la API coincide con la empresa, (ii) el nombre de la empresa aparece en el texto de varias ofertas, (iii) el tenant de Workday o el host de empleo cuelga del dominio de la propia empresa. Descarté por colisión, por ejemplo, un tablero Recruitee de otra persona con el slug `wuestenrot`, y el tablero Recruitee de Fineco Banca Privada Kutxabank para el candidato Fineco (Italia).
5. **Qué cuenta como vacante relevante**: título con términos de contabilidad, FP&A/control de gestión, tesorería, auditoría (financiera e interna), fiscal, nóminas, compras, administración/back office y operaciones bancarias o de fondos, en cualquier nivel, en inglés, español, francés, alemán, neerlandés, portugués o italiano. Excluyo títulos de tecnología, ventas, atención al cliente, riesgos/compliance/AML, auditorías de calidad o certificación (ISO, TISAX), consultoría de implantación de ERP/SAP, productos de banca de inversión (leveraged/structured/trade finance) y contratos duales/becas de tesis. La clasificación es heurística y por título: habrá falsos positivos y negativos.
6. **País**: salen del texto de localización de la oferta (país, ciudad conocida o código `ES-Madrid`). Una ciudad sin país junto a un país fuera de la lista («Venice, FL, US») no cuenta. En Workday, cuando el tablero filtra por país y la oferta dice «2 Locations», la cuento como «sin país atribuible» y lo indico.
7. **Staffing excluido**: Adecco, Randstad, Hays, Michael Page y similares publican vacantes de terceros y no entran en el catálogo.
8. **Duplicados**: varios candidatos apuntaban al mismo tablero (por ejemplo Allianz, Allianz Technology y Allianz Suisse) y se cuentan una sola vez; otros tableros de la misma empresa que aportan ofertas distintas van en las notas del lead.

## 2. Tablas por país

Una empresa aparece en cada país donde tiene vacantes relevantes. «Vacantes relevantes» es el número de ofertas del tablero con título relevante y localización en ese país el 2026-10-06. «Fechas» muestra cuántas de las ofertas con fecha tienen menos de 90 días (≥ 2026-07-08), o «sin fechas» si el tablero no las publica (en Workday el máximo observable son 29 días).

### 2.1 España (75 empresas, 315 vacantes relevantes)

| Empresa | Ciudad | Tablero (URL leída 2026-10-06) | Vacantes relevantes | Niveles presentes (por título) | Idioma del texto | Fechas |
|---|---|---|---:|---|---|---|
| Deloitte (España) | n/d | careers site (sitemap + JobPosting): [empleo.es.deloitte.com](https://empleo.es.deloitte.com/) | 40 | prácticas/graduate 2, junior 29, sin marcador (mid probable) 4, senior 4, responsable/manager 1 | es 26, en 14 | 40/40 ≤90 d |
| PwC | Madrid, Alicante, Barcelona | Workday: [pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers](https://pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers) | 19 | sin marcador (mid probable) 6, senior 8, responsable/manager 5 | n/d (muestra: en 2, it 1) | 9/9 ≤29 d |
| Fever | Madrid | Greenhouse: [boards.greenhouse.io/feverup](https://boards.greenhouse.io/feverup) | 16 | prácticas/graduate 1, junior 3, sin marcador (mid probable) 6, senior 3, responsable/manager 3 | en 16 | 14/16 ≤90 d |
| Acciona | Madrid, Barcelona, Alicante | Workday: [acciona.wd3.myworkdayjobs.com/ACCIONA_Employment_Channel](https://acciona.wd3.myworkdayjobs.com/ACCIONA_Employment_Channel) | 14 | prácticas/graduate 6, sin marcador (mid probable) 7, responsable/manager 1 | n/d (muestra: es 3) | 13/13 ≤29 d |
| Delivery Hero | Barcelona, Madrid | SmartRecruiters: [jobs.smartrecruiters.com/deliveryhero](https://jobs.smartrecruiters.com/deliveryhero) | 11 | prácticas/graduate 1, junior 1, sin marcador (mid probable) 2, senior 1, responsable/manager 5, director/head 1 | en 11 | 10/11 ≤90 d |
| El Corte Inglés | Madrid, Valencia | Workday: [elcorteingles.wd3.myworkdayjobs.com/Ext](https://elcorteingles.wd3.myworkdayjobs.com/Ext) | 11 | prácticas/graduate 5, sin marcador (mid probable) 4, senior 1, responsable/manager 1 | n/d (muestra: es 3) | 4/4 ≤29 d |
| Glovo | n/d | careers site (sitemap + JobPosting): [careers.glovoapp.com](https://careers.glovoapp.com/) | 11 | prácticas/graduate 1, junior 1, sin marcador (mid probable) 2, senior 1, responsable/manager 5, director/head 1 | en 11 | 10/11 ≤90 d |
| Barceló | Las Palmas, Barcelona, Bilbao | Workday: [barcelo.wd3.myworkdayjobs.com/Barcelo_Careers](https://barcelo.wd3.myworkdayjobs.com/Barcelo_Careers) | 9 | prácticas/graduate 1, sin marcador (mid probable) 7, responsable/manager 1 | n/d (muestra: es 3) | 2/2 ≤29 d |
| CaixaBank | Barcelona, Madrid | careers site (sitemap + JobPosting): [caixabankcareers.com](https://caixabankcareers.com/) | 9 | sin marcador (mid probable) 3, responsable/manager 6 | es 9 | 9/9 ≤90 d |
| Ferrovial | Madrid | Workday: [ferrovial.wd3.myworkdayjobs.com/Ferrovial_Career_Site](https://ferrovial.wd3.myworkdayjobs.com/Ferrovial_Career_Site) | 8 | prácticas/graduate 4, sin marcador (mid probable) 1, senior 2, responsable/manager 1 | n/d (muestra: en 2, es 1) | 6/6 ≤29 d |
| Accor | Barcelona | careers site (sitemap + JobPosting): [careers.accor.com](https://careers.accor.com/) | 7 | prácticas/graduate 5, sin marcador (mid probable) 2 | en 6, es 1 | 7/7 ≤90 d |
| Eurofins | Barcelona | SmartRecruiters: [jobs.smartrecruiters.com/eurofins](https://jobs.smartrecruiters.com/eurofins) | 6 | sin marcador (mid probable) 6 | es 6 | 1/6 ≤90 d |
| Roche | Madrid, Sant Cugat | careers site (sitemap + JobPosting): [careers.roche.com](https://careers.roche.com/) | 6 | sin marcador (mid probable) 1, responsable/manager 5 | en 1 | 6/6 ≤90 d |
| SGS | Madrid, Barcelona | SmartRecruiters: [jobs.smartrecruiters.com/sgs](https://jobs.smartrecruiters.com/sgs) | 6 | sin marcador (mid probable) 4, responsable/manager 1, director/head 1 | es 5, en 1 | 6/6 ≤90 d |
| Banco Santander | Boadilla, Madrid | Workday: [santander.wd3.myworkdayjobs.com/SantanderCareers](https://santander.wd3.myworkdayjobs.com/SantanderCareers) | 5 | sin marcador (mid probable) 3, senior 1, responsable/manager 1 | n/d (muestra: es 2, en 1) | 4/4 ≤29 d |
| Bureau Veritas | Zaragoza, Pamplona, A Coruña | careers site (sitemap + JobPosting): [jobs.bureauveritas.com](https://jobs.bureauveritas.com/) | 5 | sin marcador (mid probable) 4, responsable/manager 1 | es 3 | 5/5 ≤90 d |
| Cabify | Madrid | Greenhouse: [boards.greenhouse.io/cabify](https://boards.greenhouse.io/cabify) | 5 | prácticas/graduate 3, sin marcador (mid probable) 2 | es 4 | 3/5 ≤90 d |
| Engie | n/d | careers site (sitemap + JobPosting): [jobs.engie.com](https://jobs.engie.com/) | 5 | prácticas/graduate 1, junior 1, sin marcador (mid probable) 1, senior 2 | es 5 | sin fechas |
| ING | Madrid | careers site (sitemap + JobPosting): [careers.ing.com](https://careers.ing.com/) | 5 | prácticas/graduate 1, sin marcador (mid probable) 4 | en 5 | 5/5 ≤90 d |
| Mapfre | Majadahonda | careers site (sitemap + JobPosting): [jobs.mapfre.com](https://jobs.mapfre.com/) | 5 | prácticas/graduate 1, sin marcador (mid probable) 4 | es 5 | 5/5 ≤90 d |
| Sanitas | Madrid, Barcelona, Girona | careers site (sitemap + JobPosting): [empleo.sanitas.es](https://empleo.sanitas.es/) | 5 | sin marcador (mid probable) 4, responsable/manager 1 | es 4 | 4/5 ≤90 d |
| Straumann | Madrid | careers site (sitemap + JobPosting): [careers.straumann.com](https://careers.straumann.com/) | 5 | sin marcador (mid probable) 3, responsable/manager 2 | es 3, en 2 | 5/5 ≤90 d |
| Telefónica | n/d | careers site (sitemap + JobPosting): [jobs.telefonica.com](https://jobs.telefonica.com/) | 5 | prácticas/graduate 2, sin marcador (mid probable) 1, responsable/manager 2 | es 2 | 5/5 ≤90 d |
| Trafigura | Madrid | Workday: [trafigura.wd3.myworkdayjobs.com/ImpalaCareerSite](https://trafigura.wd3.myworkdayjobs.com/ImpalaCareerSite) | 5 | sin marcador (mid probable) 4, director/head 1 | n/d (muestra: en 3) | 3/3 ≤29 d |
| Técnicas Reunidas | Madrid | careers site (sitemap + JobPosting): [careers.tecnicasreunidas.es](https://careers.tecnicasreunidas.es/) | 5 | sin marcador (mid probable) 3, senior 1, responsable/manager 1 | es 3, en 2 | 5/5 ≤90 d |
| DSM-Firmenich | Barcelona | careers site (sitemap + JobPosting): [jobs.dsm-firmenich.com](https://jobs.dsm-firmenich.com/) | 4 | prácticas/graduate 2, senior 2 | en 4 | 4/4 ≤90 d |
| Ebury | Madrid, Málaga | Greenhouse: [boards.greenhouse.io/ebury](https://boards.greenhouse.io/ebury) | 4 | prácticas/graduate 2, junior 1, sin marcador (mid probable) 1 | en 1 | 4/4 ≤90 d |
| Indra | Madrid | careers site (sitemap + JobPosting): [careers.indragroup.com](https://careers.indragroup.com/) | 4 | sin marcador (mid probable) 3, senior 1 | es 4 | 4/4 ≤90 d |
| Ageras (Shine) | Madrid | careers site (sitemap + JobPosting): [careers.shine.co](https://careers.shine.co/) | 3 | sin marcador (mid probable) 3 | en 3 | 0/3 ≤90 d |
| Allianz | Barcelona, Madrid | careers site (sitemap + JobPosting): [careers.allianz.com](https://careers.allianz.com/) | 3 | prácticas/graduate 1, sin marcador (mid probable) 1, senior 1 | es 1 | 3/3 ≤90 d |
| Deutsche Bank | Barcelona, Madrid | Workday: [db.wd3.myworkdayjobs.com/DBWebsite](https://db.wd3.myworkdayjobs.com/DBWebsite) | 3 | prácticas/graduate 1, sin marcador (mid probable) 1, director/head 1 | n/d (muestra: en 2, de 1) | 2/2 ≤29 d |
| EY | Madrid | careers site (sitemap + JobPosting): [careers.ey.com](https://careers.ey.com/) | 3 | prácticas/graduate 2, senior 1 | es 3 | 3/3 ≤90 d |
| Novartis | Barcelona | Workday: [novartis.wd3.myworkdayjobs.com/Novartis_Careers](https://novartis.wd3.myworkdayjobs.com/Novartis_Careers) | 3 | prácticas/graduate 2, responsable/manager 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| Oyster HR | n/d | Ashby: [jobs.ashbyhq.com/oyster](https://jobs.ashbyhq.com/oyster) | 3 | sin marcador (mid probable) 1, senior 1, director/head 1 | en 3 | 3/3 ≤90 d |
| Alcon | n/d | Workday: [alcon.wd5.myworkdayjobs.com/careers_alcon](https://alcon.wd5.myworkdayjobs.com/careers_alcon) | 2 | prácticas/graduate 1, senior 1 | n/d (muestra: en 2, es 1) | 1/1 ≤29 d |
| BBVA | Madrid | Workday: [bbva.wd3.myworkdayjobs.com/BBVA](https://bbva.wd3.myworkdayjobs.com/BBVA) | 2 | sin marcador (mid probable) 2 | n/d (muestra: es 2, en 1) | 1/1 ≤29 d |
| Bosch | Madrid | SmartRecruiters: [jobs.smartrecruiters.com/boschgroup](https://jobs.smartrecruiters.com/boschgroup) | 2 | prácticas/graduate 2 | es 2 | 2/2 ≤90 d |
| Capgemini | n/d | careers site (sitemap + JobPosting): [careers.capgemini.com](https://careers.capgemini.com/) | 2 | junior 1, sin marcador (mid probable) 1 | es 2 | 2/2 ≤90 d |
| Idealista | Madrid | careers site (sitemap + JobPosting): [careers.idealista.com](https://careers.idealista.com/) | 2 | prácticas/graduate 1, senior 1 | es 1, fr 1 | 2/2 ≤90 d |
| Marsh McLennan | Madrid | careers site (sitemap + JobPosting): [careers.marshmclennan.com](https://careers.marshmclennan.com/) | 2 | senior 2 | en 2 | 2/2 ≤90 d |
| Munich Re | Madrid | careers site (sitemap + JobPosting): [careers.munichre.com](https://careers.munichre.com/) | 2 | sin marcador (mid probable) 1, responsable/manager 1 | en 2 | 2/2 ≤90 d |
| N26 | Madrid, Barcelona | Greenhouse: [boards.greenhouse.io/n26](https://boards.greenhouse.io/n26) | 2 | senior 1, responsable/manager 1 | en 1 | 2/2 ≤90 d |
| Nationale-Nederlanden | Madrid | Workday: [nngroup.wd3.myworkdayjobs.com/WDExternal](https://nngroup.wd3.myworkdayjobs.com/WDExternal) | 2 | sin marcador (mid probable) 1, responsable/manager 1 | n/d (muestra: en 2, nl 1) | 2/2 ≤29 d |
| OPmobility (Plastic Omnium) | n/d | careers site (sitemap + JobPosting): [careers.opmobility.com](https://careers.opmobility.com/) | 2 | sin marcador (mid probable) 1, responsable/manager 1 | en 2 | 2/2 ≤90 d |
| Pleo | Madrid | Ashby: [jobs.ashbyhq.com/pleo](https://jobs.ashbyhq.com/pleo) | 2 | senior 1, director/head 1 | en 2 | 2/2 ≤90 d |
| Redeia | n/d | careers site (sitemap + JobPosting): [talento.carrerasenred.com](https://talento.carrerasenred.com/) | 2 | prácticas/graduate 1, sin marcador (mid probable) 1 | es 2 | 2/2 ≤90 d |
| Repsol | Madrid | Workday: [repsol.wd3.myworkdayjobs.com/Repsol](https://repsol.wd3.myworkdayjobs.com/Repsol) | 2 | sin marcador (mid probable) 2 | n/d (muestra: es 1, en 1) | 2/2 ≤29 d |
| Sanofi | Barcelona | Workday: [sanofi.wd3.myworkdayjobs.com/SanofiCareers](https://sanofi.wd3.myworkdayjobs.com/SanofiCareers) | 2 | sin marcador (mid probable) 1, responsable/manager 1 | n/d (muestra: en 3) | 2/2 ≤29 d |
| Satispay | Barcelona | Ashby: [jobs.ashbyhq.com/satispay](https://jobs.ashbyhq.com/satispay) | 2 | director/head 2 | en 2 | 2/2 ≤90 d |
| Sonova | n/d | careers site (sitemap + JobPosting): [jobs.sonova.com](https://jobs.sonova.com/) | 2 | prácticas/graduate 1, senior 1 | en 2 | 2/2 ≤90 d |
| AXA | Madrid | careers site (sitemap + JobPosting): [careers.axa.com](https://careers.axa.com/) | 1 | prácticas/graduate 1 | en 1 | 1/1 ≤90 d |
| Air Liquide | Valencia | Workday: [airliquidehr.wd3.myworkdayjobs.com/AirLiquideExternalCareer](https://airliquidehr.wd3.myworkdayjobs.com/AirLiquideExternalCareer) | 1 | sin marcador (mid probable) 1 | n/d (muestra: fr 2, es 1) | 1/1 ≤29 d |
| Almirall | Barcelona | Workday: [almirall.wd3.myworkdayjobs.com/External](https://almirall.wd3.myworkdayjobs.com/External) | 1 | prácticas/graduate 1 | n/d (muestra: en 1) | 1/1 ≤29 d |
| Alter Domus | n/d | careers site (sitemap + JobPosting): [jobs.alterdomus.com](https://jobs.alterdomus.com/) | 1 | senior 1 | en 1 | 1/1 ≤90 d |
| Apex Group | Valencia | Workday: [theapexgroup.wd3.myworkdayjobs.com/apexgroupcareers](https://theapexgroup.wd3.myworkdayjobs.com/apexgroupcareers) | 1 | sin marcador (mid probable) 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| Back Market | Barcelona | Ashby: [jobs.ashbyhq.com/backmarket](https://jobs.ashbyhq.com/backmarket) | 1 | senior 1 | en 1 | 1/1 ≤90 d |
| Banco de España | n/d | RSS público: [www.bde.es/wbe/en/inicio/rss/rss-trabajar-banco](https://www.bde.es/wbe/en/inicio/rss/rss-trabajar-banco/) | 1 | sin marcador (mid probable) 1 | es 1 | 1/1 ≤90 d |
| Celonis | Madrid | Greenhouse: [boards.greenhouse.io/celonis](https://boards.greenhouse.io/celonis) | 1 | responsable/manager 1 | en 1 | 1/1 ≤90 d |
| Clariant | Tarragona | careers site (sitemap + JobPosting): [careers.clariant.com](https://careers.clariant.com/) | 1 | responsable/manager 1 | en 1 | 1/1 ≤90 d |
| Continental | n/d | SmartRecruiters: [jobs.smartrecruiters.com/continental](https://jobs.smartrecruiters.com/continental) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Enagás | Madrid | Workday: [enagas.wd3.myworkdayjobs.com/Portal_Externo](https://enagas.wd3.myworkdayjobs.com/Portal_Externo) | 1 | prácticas/graduate 1 | n/d (muestra: es 1) | 1/1 ≤29 d |
| Estée Lauder | Madrid | careers site (sitemap + JobPosting): [careers.elcompanies.com](https://careers.elcompanies.com/) | 1 | responsable/manager 1 | en 1 | 1/1 ≤90 d |
| HP Inc | Barcelona | Workday: [hp.wd5.myworkdayjobs.com/ExternalCareerSite](https://hp.wd5.myworkdayjobs.com/ExternalCareerSite) | 1 | sin marcador (mid probable) 1 | n/d (muestra: en 3) | sin fechas |
| Holded | Barcelona | Recruitee: [holded.recruitee.com](https://holded.recruitee.com) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Jobandtalent | Madrid | Lever: [jobs.lever.co/jobandtalent](https://jobs.lever.co/jobandtalent) | 1 | senior 1 | en 1 | 1/1 ≤90 d |
| Merck KGaA | Madrid | careers site (sitemap + JobPosting): [careers.merckgroup.com](https://careers.merckgroup.com/) | 1 | senior 1 | en 1 | 1/1 ≤90 d |
| PayFit | Barcelona | careers site (sitemap + JobPosting): [careers.payfit.com](https://careers.payfit.com/) | 1 | senior 1 | es 1 | 1/1 ≤90 d |
| Pennylane | Barcelona | Ashby: [jobs.ashbyhq.com/pennylane](https://jobs.ashbyhq.com/pennylane) | 1 | sin marcador (mid probable) 1 | es 1 | 1/1 ≤90 d |
| Pernod Ricard | Málaga | Workday: [pernodricard.wd3.myworkdayjobs.com/pernod-ricard](https://pernodricard.wd3.myworkdayjobs.com/pernod-ricard) | 1 | junior 1 | n/d (muestra: fr 2, en 1) | 1/1 ≤29 d |
| Philips | Madrid | Workday: [philips.wd3.myworkdayjobs.com/jobs-and-careers](https://philips.wd3.myworkdayjobs.com/jobs-and-careers) | 1 | prácticas/graduate 1 | n/d (muestra: de 1, en 1) | sin fechas |
| Pierre Fabre | Barcelona | Workday: [pierrefabre.wd3.myworkdayjobs.com/External_Career_Site](https://pierrefabre.wd3.myworkdayjobs.com/External_Career_Site) | 1 | sin marcador (mid probable) 1 | n/d (muestra: fr 2) | 1/1 ≤29 d |
| Procter & Gamble | Madrid | Workday: [pg.wd5.myworkdayjobs.com/1000](https://pg.wd5.myworkdayjobs.com/1000) | 1 | responsable/manager 1 | n/d (muestra: en 2, fr 1) | 1/1 ≤29 d |
| Valeo | Getafe | Workday: [valeo.wd3.myworkdayjobs.com/valeo_jobs](https://valeo.wd3.myworkdayjobs.com/valeo_jobs) | 1 | sin marcador (mid probable) 1 | n/d (muestra: en 2, fr 1) | sin fechas |
| Vistra | Barcelona | careers site (sitemap + JobPosting): [jobs.vistra.com](https://jobs.vistra.com/) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Vueling | n/d | careers site (sitemap + JobPosting): [careers.vueling.com](https://careers.vueling.com/) | 1 | sin marcador (mid probable) 1 | n/d | 1/1 ≤90 d |

### 2.2 Portugal (28 empresas, 79 vacantes relevantes)

| Empresa | Ciudad | Tablero (URL leída 2026-10-06) | Vacantes relevantes | Niveles presentes (por título) | Idioma del texto | Fechas |
|---|---|---|---:|---|---|---|
| Bosch | Braga, Aveiro | SmartRecruiters: [jobs.smartrecruiters.com/boschgroup](https://jobs.smartrecruiters.com/boschgroup) | 9 | prácticas/graduate 5, junior 3, sin marcador (mid probable) 1 | en 8, pt 1 | 9/9 ≤90 d |
| Infineon | Porto | careers site (sitemap + JobPosting): [jobs.infineon.com](https://jobs.infineon.com/) | 7 | prácticas/graduate 1, sin marcador (mid probable) 4, senior 1, director/head 1 | en 5, de 1 | 7/7 ≤90 d |
| Air Liquide | Leiria | Workday: [airliquidehr.wd3.myworkdayjobs.com/AirLiquideExternalCareer](https://airliquidehr.wd3.myworkdayjobs.com/AirLiquideExternalCareer) | 6 | sin marcador (mid probable) 6 | n/d (muestra: fr 2, es 1) | 3/3 ≤29 d |
| Solvay | n/d | careers site (sitemap + JobPosting): [careers.solvay.com](https://careers.solvay.com/) | 6 | prácticas/graduate 2, sin marcador (mid probable) 2, senior 1, responsable/manager 1 | en 6 | 6/6 ≤90 d |
| Eurofins | Braga | SmartRecruiters: [jobs.smartrecruiters.com/eurofins](https://jobs.smartrecruiters.com/eurofins) | 5 | junior 2, sin marcador (mid probable) 1, senior 1, responsable/manager 1 | en 5 | 4/5 ≤90 d |
| Hewlett Packard Enterprise | Porto | careers site (sitemap + JobPosting): [careers.hpe.com](https://careers.hpe.com/) | 5 | prácticas/graduate 1, junior 1, sin marcador (mid probable) 1, responsable/manager 2 | n/d | 5/5 ≤90 d |
| Amgen | Lisbon | Workday: [amgen.wd1.myworkdayjobs.com/Careers](https://amgen.wd1.myworkdayjobs.com/Careers) | 4 | prácticas/graduate 1, responsable/manager 3 | n/d (muestra: en 3) | 1/1 ≤29 d |
| Farfetch | Porto | Lever: [jobs.lever.co/farfetch](https://jobs.lever.co/farfetch) | 3 | sin marcador (mid probable) 1, senior 1, responsable/manager 1 | en 3 | 3/3 ≤90 d |
| Hiscox | Lisbon | Workday: [hiscox.wd3.myworkdayjobs.com/Hiscox_External_Site](https://hiscox.wd3.myworkdayjobs.com/Hiscox_External_Site) | 3 | prácticas/graduate 1, sin marcador (mid probable) 2 | n/d (muestra: en 3) | 3/3 ≤29 d |
| Oyster HR | n/d | Ashby: [jobs.ashbyhq.com/oyster](https://jobs.ashbyhq.com/oyster) | 3 | sin marcador (mid probable) 1, senior 1, director/head 1 | en 3 | 3/3 ≤90 d |
| Pleo | Lisbon | Ashby: [jobs.ashbyhq.com/pleo](https://jobs.ashbyhq.com/pleo) | 3 | senior 2, director/head 1 | en 3 | 3/3 ≤90 d |
| Acciona | Lisboa | Workday: [acciona.wd3.myworkdayjobs.com/ACCIONA_Employment_Channel](https://acciona.wd3.myworkdayjobs.com/ACCIONA_Employment_Channel) | 2 | junior 1, senior 1 | n/d (muestra: es 3) | sin fechas |
| Apex Group | Lisbon | Workday: [theapexgroup.wd3.myworkdayjobs.com/apexgroupcareers](https://theapexgroup.wd3.myworkdayjobs.com/apexgroupcareers) | 2 | senior 2 | n/d (muestra: en 3) | 2/2 ≤29 d |
| Capgemini | n/d | careers site (sitemap + JobPosting): [careers.capgemini.com](https://careers.capgemini.com/) | 2 | sin marcador (mid probable) 2 | en 2 | 2/2 ≤90 d |
| Continental | n/d | SmartRecruiters: [jobs.smartrecruiters.com/continental](https://jobs.smartrecruiters.com/continental) | 2 | sin marcador (mid probable) 2 | en 2 | 1/2 ≤90 d |
| EnBW | Lisbon | careers site (sitemap + JobPosting): [careers.enbw.com](https://careers.enbw.com/) | 2 | senior 2 | en 2 | 2/2 ≤90 d |
| Kantar | Porto | Workday: [kantar.wd3.myworkdayjobs.com/KANTAR](https://kantar.wd3.myworkdayjobs.com/KANTAR) | 2 | sin marcador (mid probable) 1, senior 1 | n/d (muestra: en 2) | 2/2 ≤29 d |
| Mota-Engil | Porto | careers site (sitemap + JobPosting): [careers.mota-engil.com](https://careers.mota-engil.com/) | 2 | sin marcador (mid probable) 1, director/head 1 | en 2 | 2/2 ≤90 d |
| Willis Towers Watson | Lisbon | careers site (sitemap + JobPosting): [careers.wtwco.com](https://careers.wtwco.com/) | 2 | sin marcador (mid probable) 2 | en 2 | 2/2 ≤90 d |
| AbbVie | Amadora | SmartRecruiters: [jobs.smartrecruiters.com/abbvie](https://jobs.smartrecruiters.com/abbvie) | 1 | prácticas/graduate 1 | en 1 | 1/1 ≤90 d |
| Abbott | Porto | Workday: [abbott.wd5.myworkdayjobs.com/abbottcareers](https://abbott.wd5.myworkdayjobs.com/abbottcareers) | 1 | sin marcador (mid probable) 1 | n/d (muestra: en 2, de 1) | 1/1 ≤29 d |
| Ageras (Shine) | Porto | careers site (sitemap + JobPosting): [careers.shine.co](https://careers.shine.co/) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Allianz | Lisboa | careers site (sitemap + JobPosting): [careers.allianz.com](https://careers.allianz.com/) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Ayvens | Lisbon | Workday: [ayvens.wd3.myworkdayjobs.com/AyvensCareers](https://ayvens.wd3.myworkdayjobs.com/AyvensCareers) | 1 | sin marcador (mid probable) 1 | n/d (muestra: fr 1, en 1, pt 1) | 1/1 ≤29 d |
| Euronext | Porto | Workday: [hrhub.wd3.myworkdayjobs.com/Euronext_Career_Page](https://hrhub.wd3.myworkdayjobs.com/Euronext_Career_Page) | 1 | prácticas/graduate 1 | n/d (muestra: en 3) | sin fechas |
| Procter & Gamble | Lisbon | Workday: [pg.wd5.myworkdayjobs.com/1000](https://pg.wd5.myworkdayjobs.com/1000) | 1 | responsable/manager 1 | n/d (muestra: en 2, fr 1) | 1/1 ≤29 d |
| Syensqo | n/d | careers site (sitemap + JobPosting): [careers.syensqo.com](https://careers.syensqo.com/) | 1 | prácticas/graduate 1 | en 1 | 1/1 ≤90 d |
| Thales | n/d | careers site (sitemap + JobPosting): [careers.thalesgroup.com](https://careers.thalesgroup.com/) | 1 | junior 1 | n/d | 1/1 ≤90 d |

### 2.3 Francia (69 empresas, 455 vacantes relevantes)

| Empresa | Ciudad | Tablero (URL leída 2026-10-06) | Vacantes relevantes | Niveles presentes (por título) | Idioma del texto | Fechas |
|---|---|---|---:|---|---|---|
| Forvis Mazars | Levallois, Strasbourg, Rennes | SmartRecruiters: [jobs.smartrecruiters.com/mazars](https://jobs.smartrecruiters.com/mazars) | 136 | prácticas/graduate 27, junior 17, sin marcador (mid probable) 34, senior 34, responsable/manager 24 | fr 131, en 5 | 86/136 ≤90 d |
| Vinci | La Defense, Velizy, Toulouse | careers site (sitemap + JobPosting): [jobs.vinci.com](https://jobs.vinci.com/) | 26 | prácticas/graduate 10, sin marcador (mid probable) 6, senior 2, responsable/manager 4, director/head 4 | fr 26 | 26/26 ≤90 d |
| Grant Thornton | Neuilly, Lyon, Rouen | Recruitee: [grantthornton.recruitee.com](https://grantthornton.recruitee.com) | 25 | prácticas/graduate 3, sin marcador (mid probable) 12, senior 3, responsable/manager 6, director/head 1 | fr 25 | 11/25 ≤90 d |
| Pennylane | Lyon, Marseille, Nantes | Ashby: [jobs.ashbyhq.com/pennylane](https://jobs.ashbyhq.com/pennylane) | 22 | sin marcador (mid probable) 21, senior 1 | fr 21 | 15/22 ≤90 d |
| Rothschild & Co | Paris, Marseille | Workday: [rothschildandco.wd3.myworkdayjobs.com/Rothschildandco_Lateral](https://rothschildandco.wd3.myworkdayjobs.com/Rothschildandco_Lateral) | 19 | prácticas/graduate 12, sin marcador (mid probable) 5, responsable/manager 2 | n/d (muestra: fr 3) | 7/7 ≤29 d |
| Air Liquide | Paris | Workday: [airliquidehr.wd3.myworkdayjobs.com/AirLiquideExternalCareer](https://airliquidehr.wd3.myworkdayjobs.com/AirLiquideExternalCareer) | 18 | prácticas/graduate 11, sin marcador (mid probable) 6, responsable/manager 1 | n/d (muestra: fr 2, es 1) | 14/14 ≤29 d |
| Ardian | Paris | Workday: [ardian.wd103.myworkdayjobs.com/ArdianCareers](https://ardian.wd103.myworkdayjobs.com/ArdianCareers) | 16 | prácticas/graduate 15, sin marcador (mid probable) 1 | n/d (muestra: fr 2, en 1) | 8/8 ≤29 d |
| Thales | Velizy | careers site (sitemap + JobPosting): [careers.thalesgroup.com](https://careers.thalesgroup.com/) | 16 | prácticas/graduate 1, sin marcador (mid probable) 8, responsable/manager 7 | fr 1 | 11/16 ≤90 d |
| Pernod Ricard | Paris, Marseille | Workday: [pernodricard.wd3.myworkdayjobs.com/pernod-ricard](https://pernodricard.wd3.myworkdayjobs.com/pernod-ricard) | 14 | prácticas/graduate 8, sin marcador (mid probable) 2, responsable/manager 3, director/head 1 | n/d (muestra: fr 2, en 1) | 6/6 ≤29 d |
| Allianz | Saint-Denis, Puteaux, Courbevoie | careers site (sitemap + JobPosting): [careers.allianz.com](https://careers.allianz.com/) | 11 | prácticas/graduate 7, senior 1, director/head 3 | en 4 | 11/11 ≤90 d |
| Eurofins | Nantes, Aix-En-Provence, Massy | SmartRecruiters: [jobs.smartrecruiters.com/eurofins](https://jobs.smartrecruiters.com/eurofins) | 11 | prácticas/graduate 1, sin marcador (mid probable) 8, responsable/manager 2 | fr 11 | 5/11 ≤90 d |
| Accor | Paris, Issy-Les-Moulineaux, Bordeaux | careers site (sitemap + JobPosting): [careers.accor.com](https://careers.accor.com/) | 10 | prácticas/graduate 2, sin marcador (mid probable) 3, responsable/manager 3, director/head 2 | fr 9, en 1 | 8/10 ≤90 d |
| Eiffage | Velizy, Saint-Ouen, Paris | Workday: [eiffage.wd3.myworkdayjobs.com/Eiffage_Careers](https://eiffage.wd3.myworkdayjobs.com/Eiffage_Careers) | 10 | sin marcador (mid probable) 6, responsable/manager 4 | n/d (muestra: fr 3) | sin fechas |
| EY | n/d | careers site (sitemap + JobPosting): [careers.ey.com](https://careers.ey.com/) | 9 | sin marcador (mid probable) 6, responsable/manager 3 | fr 9 | 9/9 ≤90 d |
| PwC | Neuilly, Montpellier | Workday: [pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers](https://pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers) | 8 | sin marcador (mid probable) 3, senior 2, responsable/manager 3 | n/d (muestra: en 2, it 1) | 5/5 ≤29 d |
| Coface | n/d | SmartRecruiters: [jobs.smartrecruiters.com/coface](https://jobs.smartrecruiters.com/coface) | 5 | prácticas/graduate 3, senior 2 | fr 4, en 1 | 4/5 ≤90 d |
| Qonto | Paris | Lever: [jobs.lever.co/qonto](https://jobs.lever.co/qonto) | 5 | prácticas/graduate 1, junior 1, sin marcador (mid probable) 1, responsable/manager 1, director/head 1 | fr 3, en 2 | 5/5 ≤90 d |
| AbbVie | n/d | SmartRecruiters: [jobs.smartrecruiters.com/abbvie](https://jobs.smartrecruiters.com/abbvie) | 4 | sin marcador (mid probable) 4 | en 2, fr 2 | 4/4 ≤90 d |
| Alan | Paris | Ashby: [jobs.ashbyhq.com/alan](https://jobs.ashbyhq.com/alan) | 4 | prácticas/graduate 1, sin marcador (mid probable) 1, responsable/manager 2 | en 4 | 4/4 ≤90 d |
| Capgemini | n/d | careers site (sitemap + JobPosting): [careers.capgemini.com](https://careers.capgemini.com/) | 4 | prácticas/graduate 2, sin marcador (mid probable) 1, responsable/manager 1 | fr 4 | 4/4 ≤90 d |
| Apex Group | Paris | Workday: [theapexgroup.wd3.myworkdayjobs.com/apexgroupcareers](https://theapexgroup.wd3.myworkdayjobs.com/apexgroupcareers) | 3 | responsable/manager 2, director/head 1 | n/d (muestra: en 3) | 2/2 ≤29 d |
| Bank of America | Paris | careers site (sitemap + JobPosting): [careers.bankofamerica.com](https://careers.bankofamerica.com/) | 3 | sin marcador (mid probable) 3 | en 3 | sin fechas |
| Bureau Veritas | Courbevoie, Paris | careers site (sitemap + JobPosting): [jobs.bureauveritas.com](https://jobs.bureauveritas.com/) | 3 | sin marcador (mid probable) 2, senior 1 | fr 1 | 3/3 ≤90 d |
| Doctolib | Paris | Greenhouse: [boards.greenhouse.io/doctolib](https://boards.greenhouse.io/doctolib) | 3 | prácticas/graduate 1, responsable/manager 2 | fr 1, en 1 | 2/3 ≤90 d |
| Engie | n/d | careers site (sitemap + JobPosting): [jobs.engie.com](https://jobs.engie.com/) | 3 | sin marcador (mid probable) 2, responsable/manager 1 | fr 3 | sin fechas |
| Ipsen | Paris | Workday: [ipsen.wd103.myworkdayjobs.com/Ipsen_Careers](https://ipsen.wd103.myworkdayjobs.com/Ipsen_Careers) | 3 | sin marcador (mid probable) 1, senior 1, responsable/manager 1 | n/d (muestra: en 2, fr 1) | sin fechas |
| Mirakl | Paris | Greenhouse: [boards.greenhouse.io/mirakl](https://boards.greenhouse.io/mirakl) | 3 | prácticas/graduate 2, sin marcador (mid probable) 1 | en 1 | 1/3 ≤90 d |
| Sanofi | Lyon, Tours, Paris | Workday: [sanofi.wd3.myworkdayjobs.com/SanofiCareers](https://sanofi.wd3.myworkdayjobs.com/SanofiCareers) | 3 | prácticas/graduate 2, sin marcador (mid probable) 1 | n/d (muestra: en 3) | 3/3 ≤29 d |
| Société Générale | Saint-Denis | careers site (sitemap + JobPosting): [careers.societegenerale.com](https://careers.societegenerale.com/) | 3 | prácticas/graduate 1, sin marcador (mid probable) 2 | fr 3 | sin fechas |
| Straumann | Paris | careers site (sitemap + JobPosting): [careers.straumann.com](https://careers.straumann.com/) | 3 | senior 3 | en 3 | 3/3 ≤90 d |
| Valeo | Paris | Workday: [valeo.wd3.myworkdayjobs.com/valeo_jobs](https://valeo.wd3.myworkdayjobs.com/valeo_jobs) | 3 | prácticas/graduate 3 | n/d (muestra: en 2, fr 1) | 2/2 ≤29 d |
| AXA | Nanterre, Paris | careers site (sitemap + JobPosting): [careers.axa.com](https://careers.axa.com/) | 2 | sin marcador (mid probable) 2 | fr 2 | 1/2 ≤90 d |
| Alter Domus | n/d | careers site (sitemap + JobPosting): [jobs.alterdomus.com](https://jobs.alterdomus.com/) | 2 | senior 1, responsable/manager 1 | fr 2 | 2/2 ≤90 d |
| Arcadis | n/d | careers site (sitemap + JobPosting): [jobs.arcadis.com](https://jobs.arcadis.com/) | 2 | director/head 2 | en 2 | 2/2 ≤90 d |
| Back Market | Paris, Bordeaux | Ashby: [jobs.ashbyhq.com/backmarket](https://jobs.ashbyhq.com/backmarket) | 2 | prácticas/graduate 2 | en 2 | 2/2 ≤90 d |
| Bosch | Saint-Ouen | SmartRecruiters: [jobs.smartrecruiters.com/boschgroup](https://jobs.smartrecruiters.com/boschgroup) | 2 | prácticas/graduate 2 | fr 2 | 2/2 ≤90 d |
| DSM-Firmenich | Paris | careers site (sitemap + JobPosting): [jobs.dsm-firmenich.com](https://jobs.dsm-firmenich.com/) | 2 | sin marcador (mid probable) 1, director/head 1 | fr 2 | 2/2 ≤90 d |
| Kuehne+Nagel | n/d | careers site (sitemap + JobPosting): [jobs.kuehne-nagel.com](https://jobs.kuehne-nagel.com/) | 2 | sin marcador (mid probable) 2 | fr 2 | 2/2 ≤90 d |
| Lindt | n/d | Workday: [lindtspruengli.wd103.myworkdayjobs.com/LindtSpruengliGroupCareers](https://lindtspruengli.wd103.myworkdayjobs.com/LindtSpruengliGroupCareers) | 2 | sin marcador (mid probable) 1, responsable/manager 1 | n/d (muestra: fr 2, de 1) | sin fechas |
| Marsh McLennan | Paris | careers site (sitemap + JobPosting): [careers.marshmclennan.com](https://careers.marshmclennan.com/) | 2 | senior 2 | en 2 | 2/2 ≤90 d |
| OPmobility (Plastic Omnium) | n/d | careers site (sitemap + JobPosting): [careers.opmobility.com](https://careers.opmobility.com/) | 2 | sin marcador (mid probable) 1, responsable/manager 1 | en 2 | 2/2 ≤90 d |
| Richemont | Paris | Workday: [richemont.wd3.myworkdayjobs.com/broadbean_external](https://richemont.wd3.myworkdayjobs.com/broadbean_external) | 2 | prácticas/graduate 2 | n/d (muestra: en 3) | 1/1 ≤29 d |
| AIG | Courbevoie | Workday: [aig.wd1.myworkdayjobs.com/aig](https://aig.wd1.myworkdayjobs.com/aig) | 1 | sin marcador (mid probable) 1 | n/d (muestra: fr 1, en 1) | 1/1 ≤29 d |
| Abbott | n/d | Workday: [abbott.wd5.myworkdayjobs.com/abbottcareers](https://abbott.wd5.myworkdayjobs.com/abbottcareers) | 1 | sin marcador (mid probable) 1 | n/d (muestra: en 2, de 1) | sin fechas |
| Ageras (Shine) | Paris | careers site (sitemap + JobPosting): [careers.shine.co](https://careers.shine.co/) | 1 | director/head 1 | en 1 | 0/1 ≤90 d |
| Amgen | Paris | Workday: [amgen.wd1.myworkdayjobs.com/Careers](https://amgen.wd1.myworkdayjobs.com/Careers) | 1 | responsable/manager 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| BBVA | Paris | Workday: [bbva.wd3.myworkdayjobs.com/BBVA](https://bbva.wd3.myworkdayjobs.com/BBVA) | 1 | responsable/manager 1 | n/d (muestra: es 2, en 1) | 1/1 ≤29 d |
| Biogen | Paris | Workday: [biibhr.wd3.myworkdayjobs.com/external](https://biibhr.wd3.myworkdayjobs.com/external) | 1 | responsable/manager 1 | n/d (muestra: fr 1) | 1/1 ≤29 d |
| BlaBlaCar | Paris | Lever: [jobs.lever.co/blablacar](https://jobs.lever.co/blablacar) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Boehringer Ingelheim | Lyon | careers site (sitemap + JobPosting): [jobs.boehringer-ingelheim.com](https://jobs.boehringer-ingelheim.com/) | 1 | prácticas/graduate 1 | fr 1 | 1/1 ≤90 d |
| Estée Lauder | Neuilly | careers site (sitemap + JobPosting): [careers.elcompanies.com](https://careers.elcompanies.com/) | 1 | prácticas/graduate 1 | en 1 | 1/1 ≤90 d |
| Euronext | Paris | Workday: [hrhub.wd3.myworkdayjobs.com/Euronext_Career_Page](https://hrhub.wd3.myworkdayjobs.com/Euronext_Career_Page) | 1 | prácticas/graduate 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| GSK | n/d | Workday: [gsk.wd5.myworkdayjobs.com/GSKCareers](https://gsk.wd5.myworkdayjobs.com/GSKCareers) | 1 | sin marcador (mid probable) 1 | n/d (muestra: fr 2) | 1/1 ≤29 d |
| HelloFresh | Paris | Greenhouse: [boards.greenhouse.io/hellofresh](https://boards.greenhouse.io/hellofresh) | 1 | responsable/manager 1 | en 1 | 1/1 ≤90 d |
| Ikea | n/d | careers site (sitemap + JobPosting): [jobs.ikea.com](https://jobs.ikea.com/) | 1 | responsable/manager 1 | fr 1 | 1/1 ≤90 d |
| Ledger | Paris | Ashby: [jobs.ashbyhq.com/ledger](https://jobs.ashbyhq.com/ledger) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| N26 | Paris | Greenhouse: [boards.greenhouse.io/n26](https://boards.greenhouse.io/n26) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Novartis | Paris | Workday: [novartis.wd3.myworkdayjobs.com/Novartis_Careers](https://novartis.wd3.myworkdayjobs.com/Novartis_Careers) | 1 | prácticas/graduate 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| Prada Group | n/d | careers site (sitemap + JobPosting): [jobs.pradagroup.com](https://jobs.pradagroup.com/) | 1 | sin marcador (mid probable) 1 | n/d | 1/1 ≤90 d |
| Publicis | Paris | careers site (sitemap + JobPosting): [careers.publicisgroupe.com](https://careers.publicisgroupe.com/) | 1 | senior 1 | fr 1 | 1/1 ≤90 d |
| RELX | Paris | Workday: [relx.wd3.myworkdayjobs.com/relx](https://relx.wd3.myworkdayjobs.com/relx) | 1 | sin marcador (mid probable) 1 | n/d (muestra: fr 2, nl 1) | 1/1 ≤29 d |
| SGS | n/d | SmartRecruiters: [jobs.smartrecruiters.com/sgs](https://jobs.smartrecruiters.com/sgs) | 1 | sin marcador (mid probable) 1 | fr 1 | 1/1 ≤90 d |
| Satispay | Paris | Ashby: [jobs.ashbyhq.com/satispay](https://jobs.ashbyhq.com/satispay) | 1 | director/head 1 | en 1 | 1/1 ≤90 d |
| Solvay | n/d | careers site (sitemap + JobPosting): [careers.solvay.com](https://careers.solvay.com/) | 1 | responsable/manager 1 | en 1 | 1/1 ≤90 d |
| SumUp | Paris | Greenhouse: [boards.greenhouse.io/sumup](https://boards.greenhouse.io/sumup) | 1 | prácticas/graduate 1 | en 1 | 1/1 ≤90 d |
| Umicore | n/d | careers site (sitemap + JobPosting): [careers.umicore.com](https://careers.umicore.com/) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Vistra | Paris | careers site (sitemap + JobPosting): [jobs.vistra.com](https://jobs.vistra.com/) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Willis Towers Watson | Puteaux | careers site (sitemap + JobPosting): [careers.wtwco.com](https://careers.wtwco.com/) | 1 | sin marcador (mid probable) 1 | fr 1 | 1/1 ≤90 d |
| Younited | Paris | Lever: [jobs.lever.co/younited](https://jobs.lever.co/younited) | 1 | prácticas/graduate 1 | fr 1 | 1/1 ≤90 d |

### 2.4 Alemania (96 empresas, 417 vacantes relevantes)

| Empresa | Ciudad | Tablero (URL leída 2026-10-06) | Vacantes relevantes | Niveles presentes (por título) | Idioma del texto | Fechas |
|---|---|---|---:|---|---|---|
| Bosch | Stuttgart, Berlin, Leipzig | SmartRecruiters: [jobs.smartrecruiters.com/boschgroup](https://jobs.smartrecruiters.com/boschgroup) | 46 | prácticas/graduate 38, sin marcador (mid probable) 6, senior 2 | de 40, en 6 | 46/46 ≤90 d |
| Thyssenkrupp | Kiel, Essen, Dortmund | careers site (sitemap + JobPosting): [jobs.thyssenkrupp.com](https://jobs.thyssenkrupp.com/) | 21 | prácticas/graduate 2, sin marcador (mid probable) 5, senior 4, responsable/manager 8, director/head 2 | de 21 | 17/21 ≤90 d |
| EnBW | Stuttgart, Karlsruhe | careers site (sitemap + JobPosting): [careers.enbw.com](https://careers.enbw.com/) | 16 | prácticas/graduate 6, sin marcador (mid probable) 4, responsable/manager 6 | de 12 | 15/16 ≤90 d |
| Deutsche Börse | n/d | careers site (sitemap + JobPosting): [career.deutsche-boerse.com](https://career.deutsche-boerse.com/) | 13 | prácticas/graduate 2, sin marcador (mid probable) 10, director/head 1 | en 10, de 3 | 13/13 ≤90 d |
| About You | Hamburg | careers site (sitemap + JobPosting): [corporate.aboutyou.de](https://corporate.aboutyou.de/) | 12 | prácticas/graduate 5, sin marcador (mid probable) 1, senior 2, responsable/manager 4 | de 6, en 6 | 12/12 ≤90 d |
| Deka | Frankfurt, Wiesbaden | careers site (sitemap + JobPosting): [karriere.deka.de](https://karriere.deka.de/) | 10 | prácticas/graduate 2, junior 1, sin marcador (mid probable) 5, senior 1, responsable/manager 1 | de 10 | 10/10 ≤90 d |
| Eurofins | Hamburg, Berlin, Munich | SmartRecruiters: [jobs.smartrecruiters.com/eurofins](https://jobs.smartrecruiters.com/eurofins) | 9 | prácticas/graduate 1, junior 1, sin marcador (mid probable) 6, responsable/manager 1 | de 9 | 4/9 ≤90 d |
| Puma | n/d | careers site (sitemap + JobPosting): [about.puma.com](https://about.puma.com/) | 9 | prácticas/graduate 1, junior 1, senior 4, responsable/manager 3 | en 9 | 9/9 ≤90 d |
| Signal Iduna | n/d | careers site (sitemap + JobPosting): [jobs.signal-iduna.de](https://jobs.signal-iduna.de/) | 9 | prácticas/graduate 2, sin marcador (mid probable) 3, responsable/manager 4 | de 9 | 9/9 ≤90 d |
| Abbott | Wiesbaden, Hamburg | Workday: [abbott.wd5.myworkdayjobs.com/abbottcareers](https://abbott.wd5.myworkdayjobs.com/abbottcareers) | 8 | sin marcador (mid probable) 5, senior 1, responsable/manager 2 | n/d (muestra: en 2, de 1) | 2/2 ≤29 d |
| Baloise | n/d | careers site (sitemap + JobPosting): [careers.baloise.com](https://careers.baloise.com/) | 8 | sin marcador (mid probable) 8 | de 8 | 8/8 ≤90 d |
| Infineon | Munich, Regensburg | careers site (sitemap + JobPosting): [jobs.infineon.com](https://jobs.infineon.com/) | 8 | prácticas/graduate 4, sin marcador (mid probable) 2, responsable/manager 1, director/head 1 | en 4, de 3 | 8/8 ≤90 d |
| Munich Re | Düsseldorf, München, Frankfurt | careers site (sitemap + JobPosting): [careers.munichre.com](https://careers.munichre.com/) | 8 | prácticas/graduate 1, sin marcador (mid probable) 5, responsable/manager 2 | en 4, de 4 | 8/8 ≤90 d |
| RWE | Essen | careers site (sitemap + JobPosting): [jobs.rwe.com](https://jobs.rwe.com/) | 8 | prácticas/graduate 5, sin marcador (mid probable) 2, senior 1 | de 6, en 2 | 8/8 ≤90 d |
| E.ON | Essen, Heidelberg, Frankfurt | careers site (sitemap + JobPosting): [jobs.eon.com](https://jobs.eon.com/) | 7 | prácticas/graduate 3, sin marcador (mid probable) 1, senior 1, responsable/manager 2 | de 6, en 1 | 7/7 ≤90 d |
| Moonfare | Berlin, Munich, Frankfurt | Greenhouse: [boards.greenhouse.io/moonfare](https://boards.greenhouse.io/moonfare) | 7 | sin marcador (mid probable) 1, responsable/manager 3, director/head 3 | en 7 | 5/7 ≤90 d |
| Accor | Berlin, Munich, Hamburg | careers site (sitemap + JobPosting): [careers.accor.com](https://careers.accor.com/) | 6 | sin marcador (mid probable) 3, responsable/manager 2, director/head 1 | en 4, de 2 | 6/6 ≤90 d |
| Ageras (Shine) | Berlin | careers site (sitemap + JobPosting): [careers.shine.co](https://careers.shine.co/) | 6 | prácticas/graduate 1, sin marcador (mid probable) 1, senior 1, responsable/manager 1, director/head 2 | en 5 | 5/6 ≤90 d |
| Leonardo | Darmstadt | Workday: [leonardocompany.wd3.myworkdayjobs.com/LeonardoCareerSite](https://leonardocompany.wd3.myworkdayjobs.com/LeonardoCareerSite) | 6 | prácticas/graduate 1, sin marcador (mid probable) 5 | n/d (muestra: it 3) | 1/1 ≤29 d |
| Pennylane | Berlin | Ashby: [jobs.ashbyhq.com/pennylane](https://jobs.ashbyhq.com/pennylane) | 6 | sin marcador (mid probable) 5, responsable/manager 1 | de 6 | 5/6 ≤90 d |
| Securitas | Potsdam, Düsseldorf, Berlin | SmartRecruiters: [jobs.smartrecruiters.com/securitas](https://jobs.smartrecruiters.com/securitas) | 6 | sin marcador (mid probable) 5, responsable/manager 1 | de 6 | 6/6 ≤90 d |
| Siemens Healthineers | Erlangen | careers site (sitemap + JobPosting): [careers.siemens-healthineers.com](https://careers.siemens-healthineers.com/) | 6 | prácticas/graduate 1, responsable/manager 4, director/head 1 | en 2 | 6/6 ≤90 d |
| Straumann | Freiburg | careers site (sitemap + JobPosting): [careers.straumann.com](https://careers.straumann.com/) | 6 | prácticas/graduate 3, sin marcador (mid probable) 3 | de 3 | 6/6 ≤90 d |
| Uniper | n/d | careers site (sitemap + JobPosting): [jobs.uniper.energy](https://jobs.uniper.energy/) | 6 | prácticas/graduate 3, senior 2, responsable/manager 1 | de 5, en 1 | 6/6 ≤90 d |
| Vodafone | Düsseldorf | careers site (sitemap + JobPosting): [jobs.vodafone.com](https://jobs.vodafone.com/) | 6 | prácticas/graduate 5, responsable/manager 1 | de 6 | 1/6 ≤90 d |
| Deutsche Bank | Frankfurt | Workday: [db.wd3.myworkdayjobs.com/DBWebsite](https://db.wd3.myworkdayjobs.com/DBWebsite) | 5 | prácticas/graduate 2, responsable/manager 2, director/head 1 | n/d (muestra: en 2, de 1) | 3/3 ≤29 d |
| EY | Köln, Frankfurt, München | careers site (sitemap + JobPosting): [careers.ey.com](https://careers.ey.com/) | 5 | prácticas/graduate 1, sin marcador (mid probable) 1, senior 1, responsable/manager 2 | de 5 | 5/5 ≤90 d |
| Merck KGaA | Darmstadt | careers site (sitemap + JobPosting): [careers.merckgroup.com](https://careers.merckgroup.com/) | 5 | prácticas/graduate 1, senior 2, responsable/manager 2 | en 4 | 3/3 ≤90 d |
| N26 | Berlin | Greenhouse: [boards.greenhouse.io/n26](https://boards.greenhouse.io/n26) | 5 | sin marcador (mid probable) 1, senior 2, responsable/manager 2 | en 4 | 4/5 ≤90 d |
| ProSiebenSat.1 | n/d | careers site (sitemap + JobPosting): [jobs.prosiebensat1.com](https://jobs.prosiebensat1.com/) | 5 | prácticas/graduate 2, sin marcador (mid probable) 1, responsable/manager 2 | de 5 | 5/5 ≤90 d |
| Société Générale | Frankfurt, Hamburg | careers site (sitemap + JobPosting): [careers.societegenerale.com](https://careers.societegenerale.com/) | 5 | prácticas/graduate 2, sin marcador (mid probable) 2, senior 1 | en 3, de 2 | sin fechas |
| 1&1 | n/d | careers site (sitemap + JobPosting): [jobs.1und1.de](https://jobs.1und1.de/) | 4 | prácticas/graduate 2, senior 1, director/head 1 | de 4 | 4/4 ≤90 d |
| Cargill | Berlin, Düsseldorf | careers site (sitemap + JobPosting): [jobs.cargill.com](https://jobs.cargill.com/) | 4 | sin marcador (mid probable) 2, responsable/manager 2 | en 2, de 2 | 4/4 ≤90 d |
| Coolblue | Düsseldorf, Nürnberg | SmartRecruiters: [jobs.smartrecruiters.com/coolblue](https://jobs.smartrecruiters.com/coolblue) | 4 | junior 1, sin marcador (mid probable) 2, senior 1 | de 4 | 3/4 ≤90 d |
| GetYourGuide | Berlin | Greenhouse: [boards.greenhouse.io/getyourguide](https://boards.greenhouse.io/getyourguide) | 4 | prácticas/graduate 1, sin marcador (mid probable) 1, responsable/manager 2 | en 4 | 4/4 ≤90 d |
| Hannover Re | n/d | careers site (sitemap + JobPosting): [jobs.hannover-re.com](https://jobs.hannover-re.com/) | 4 | sin marcador (mid probable) 4 | en 2, de 2 | 4/4 ≤90 d |
| Ionos | Berlin, Karlsruhe | Greenhouse: [boards.greenhouse.io/ionos](https://boards.greenhouse.io/ionos) | 4 | sin marcador (mid probable) 2, responsable/manager 2 | de 1 | 2/4 ≤90 d |
| Scalable Capital | München, Berlin | SmartRecruiters: [jobs.smartrecruiters.com/ScalableGmbH](https://jobs.smartrecruiters.com/ScalableGmbH) | 4 | prácticas/graduate 2, director/head 2 | en 4 | 4/4 ≤90 d |
| Vinci | Frankfurt | careers site (sitemap + JobPosting): [jobs.vinci.com](https://jobs.vinci.com/) | 4 | sin marcador (mid probable) 1, responsable/manager 3 | en 2, de 2 | 4/4 ≤90 d |
| ZF | n/d | careers site (sitemap + JobPosting): [jobs.zf.com](https://jobs.zf.com/) | 4 | prácticas/graduate 1, sin marcador (mid probable) 1, senior 2 | de 2, en 2 | 4/4 ≤90 d |
| AbbVie | n/d | SmartRecruiters: [jobs.smartrecruiters.com/abbvie](https://jobs.smartrecruiters.com/abbvie) | 3 | prácticas/graduate 1, senior 2 | en 2, de 1 | 3/3 ≤90 d |
| Allianz | Munich | careers site (sitemap + JobPosting): [careers.allianz.com](https://careers.allianz.com/) | 3 | director/head 3 | en 3 | 3/3 ≤90 d |
| Ayvens | Hamburg | Workday: [ayvens.wd3.myworkdayjobs.com/AyvensCareers](https://ayvens.wd3.myworkdayjobs.com/AyvensCareers) | 3 | prácticas/graduate 3 | n/d (muestra: fr 1, en 1, pt 1) | sin fechas |
| Biontech | Mainz | careers site (sitemap + JobPosting): [jobs.biontech.com](https://jobs.biontech.com/) | 3 | sin marcador (mid probable) 1, director/head 2 | de 3 | 3/3 ≤90 d |
| BlackRock | n/d | Workday: [blackrock.wd1.myworkdayjobs.com/BlackRock_Professional](https://blackrock.wd1.myworkdayjobs.com/BlackRock_Professional) | 3 | sin marcador (mid probable) 1, director/head 2 | n/d (muestra: en 3) | 3/3 ≤29 d |
| Engie | n/d | careers site (sitemap + JobPosting): [jobs.engie.com](https://jobs.engie.com/) | 3 | prácticas/graduate 3 | de 3 | sin fechas |
| HelloFresh | Berlin | Greenhouse: [boards.greenhouse.io/hellofresh](https://boards.greenhouse.io/hellofresh) | 3 | responsable/manager 3 | en 2 | 2/3 ≤90 d |
| ING | Frankfurt | careers site (sitemap + JobPosting): [careers.ing.com](https://careers.ing.com/) | 3 | prácticas/graduate 2, responsable/manager 1 | de 3 | 3/3 ≤90 d |
| Kuehne+Nagel | Bremen | careers site (sitemap + JobPosting): [jobs.kuehne-nagel.com](https://jobs.kuehne-nagel.com/) | 3 | prácticas/graduate 2, sin marcador (mid probable) 1 | n/d | 1/3 ≤90 d |
| Lanxess | Köln | careers site (sitemap + JobPosting): [career.lanxess.com](https://career.lanxess.com/) | 3 | responsable/manager 3 | n/d | 3/3 ≤90 d |
| Solaris | Berlin, Frankfurt | Greenhouse: [boards.greenhouse.io/solarisbank](https://boards.greenhouse.io/solarisbank) | 3 | senior 1, responsable/manager 2 | n/d | 1/3 ≤90 d |
| State Street | Munich, Frankfurt | Workday: [statestreet.wd1.myworkdayjobs.com/Global](https://statestreet.wd1.myworkdayjobs.com/Global) | 3 | sin marcador (mid probable) 1, senior 1, director/head 1 | n/d (muestra: en 2, de 1) | 3/3 ≤29 d |
| SumUp | Berlin | Greenhouse: [boards.greenhouse.io/sumup](https://boards.greenhouse.io/sumup) | 3 | prácticas/graduate 1, senior 1, director/head 1 | en 3 | 2/3 ≤90 d |
| Vontobel | Düsseldorf | Workday: [vontobel.wd3.myworkdayjobs.com/Vontobel_External_Career](https://vontobel.wd3.myworkdayjobs.com/Vontobel_External_Career) | 3 | sin marcador (mid probable) 2, director/head 1 | n/d (muestra: en 2, de 1) | 3/3 ≤29 d |
| Westwing | Munich | Personio: [westwing.jobs.personio.de](https://westwing.jobs.personio.de) | 3 | responsable/manager 2, director/head 1 | en 2, de 1 | 2/3 ≤90 d |
| Zalando | Berlin | Workday: [zalando.wd3.myworkdayjobs.com/ZalandoSiteWD](https://zalando.wd3.myworkdayjobs.com/ZalandoSiteWD) | 3 | sin marcador (mid probable) 1, senior 1, responsable/manager 1 | n/d (muestra: en 3) | 2/2 ≤29 d |
| Air Liquide | n/d | Workday: [airliquidehr.wd3.myworkdayjobs.com/AirLiquideExternalCareer](https://airliquidehr.wd3.myworkdayjobs.com/AirLiquideExternalCareer) | 2 | sin marcador (mid probable) 1, senior 1 | n/d (muestra: fr 2, es 1) | sin fechas |
| Autoscout24 | Munich | Greenhouse: [boards.greenhouse.io/autoscout24](https://boards.greenhouse.io/autoscout24) | 2 | responsable/manager 2 | de 1, en 1 | 1/2 ≤90 d |
| Continental | Hannover | SmartRecruiters: [jobs.smartrecruiters.com/continental](https://jobs.smartrecruiters.com/continental) | 2 | prácticas/graduate 2 | de 2 | 2/2 ≤90 d |
| Delivery Hero | Berlin | SmartRecruiters: [jobs.smartrecruiters.com/deliveryhero](https://jobs.smartrecruiters.com/deliveryhero) | 2 | senior 2 | en 2 | 2/2 ≤90 d |
| Marsh McLennan | Berlin | careers site (sitemap + JobPosting): [careers.marshmclennan.com](https://careers.marshmclennan.com/) | 2 | senior 2 | en 2 | 2/2 ≤90 d |
| OPmobility (Plastic Omnium) | n/d | careers site (sitemap + JobPosting): [careers.opmobility.com](https://careers.opmobility.com/) | 2 | sin marcador (mid probable) 1, senior 1 | de 1 | 2/2 ≤90 d |
| SGS | Hamburg | SmartRecruiters: [jobs.smartrecruiters.com/sgs](https://jobs.smartrecruiters.com/sgs) | 2 | sin marcador (mid probable) 1, responsable/manager 1 | de 2 | 2/2 ≤90 d |
| TUI | Hamburg, Hanover | careers site (sitemap + JobPosting): [careers.tuigroup.com](https://careers.tuigroup.com/) | 2 | sin marcador (mid probable) 2 | de 1, en 1 | 2/2 ≤90 d |
| Upvest | Berlin | Ashby: [jobs.ashbyhq.com/upvest](https://jobs.ashbyhq.com/upvest) | 2 | prácticas/graduate 1, sin marcador (mid probable) 1 | en 2 | 1/2 ≤90 d |
| Vattenfall | Berlin | SmartRecruiters: [jobs.smartrecruiters.com/vattenfall](https://jobs.smartrecruiters.com/vattenfall) | 2 | sin marcador (mid probable) 2 | en 1, de 1 | 2/2 ≤90 d |
| ASML | Berlin | Workday: [asml.wd3.myworkdayjobs.com/ASMLBERLIN](https://asml.wd3.myworkdayjobs.com/ASMLBERLIN) | 1 | senior 1 | n/d (muestra: en 1) | sin fechas |
| AXA | Köln | careers site (sitemap + JobPosting): [careers.axa.com](https://careers.axa.com/) | 1 | sin marcador (mid probable) 1 | de 1 | 1/1 ≤90 d |
| Alter Domus | n/d | careers site (sitemap + JobPosting): [jobs.alterdomus.com](https://jobs.alterdomus.com/) | 1 | sin marcador (mid probable) 1 | de 1 | 1/1 ≤90 d |
| Ardian | Frankfurt | Workday: [ardian.wd103.myworkdayjobs.com/ArdianCareers](https://ardian.wd103.myworkdayjobs.com/ArdianCareers) | 1 | prácticas/graduate 1 | n/d (muestra: fr 2, en 1) | 1/1 ≤29 d |
| AstraZeneca | Hamburg | Workday: [astrazeneca.wd3.myworkdayjobs.com/Careers](https://astrazeneca.wd3.myworkdayjobs.com/Careers) | 1 | responsable/manager 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| Avaloq | Berlin | careers site (sitemap + JobPosting): [avaloq.com](https://avaloq.com/) | 1 | sin marcador (mid probable) 1 | en 1 | 0/1 ≤90 d |
| Bayer | n/d | careers site (sitemap + JobPosting): [talent.bayer.com](https://talent.bayer.com/) | 1 | prácticas/graduate 1 | de 1 | 1/1 ≤90 d |
| DSM-Firmenich | n/d | careers site (sitemap + JobPosting): [jobs.dsm-firmenich.com](https://jobs.dsm-firmenich.com/) | 1 | responsable/manager 1 | en 1 | 1/1 ≤90 d |
| Gilead | Munich | Workday: [gilead.wd1.myworkdayjobs.com/gileadcareers](https://gilead.wd1.myworkdayjobs.com/gileadcareers) | 1 | responsable/manager 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| Heidelberg Materials | Heidelberg | Workday: [heidelbergmaterials.wd3.myworkdayjobs.com/Global_HM_Career_Site](https://heidelbergmaterials.wd3.myworkdayjobs.com/Global_HM_Career_Site) | 1 | sin marcador (mid probable) 1 | n/d (muestra: de 3) | sin fechas |
| Lavazza | n/d | careers site (sitemap + JobPosting): [jobs.lavazza.com](https://jobs.lavazza.com/) | 1 | prácticas/graduate 1 | de 1 | 1/1 ≤90 d |
| Maersk | n/d | Workday: [maersk.wd3.myworkdayjobs.com/APMT_Careers](https://maersk.wd3.myworkdayjobs.com/APMT_Careers) | 1 | responsable/manager 1 | n/d (muestra: en 3) | sin fechas |
| Michelin | Frankfurt | Workday: [michelinhr.wd3.myworkdayjobs.com/Michelin](https://michelinhr.wd3.myworkdayjobs.com/Michelin) | 1 | prácticas/graduate 1 | n/d (muestra: de 1, fr 1) | 1/1 ≤29 d |
| Moncler | Berlin | careers site (sitemap + JobPosting): [jobs.monclergroup.com](https://jobs.monclergroup.com/) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Moss | Munich | Ashby: [jobs.ashbyhq.com/moss](https://jobs.ashbyhq.com/moss) | 1 | senior 1 | en 1 | 1/1 ≤90 d |
| Novartis | Munich | Workday: [novartis.wd3.myworkdayjobs.com/Novartis_Careers](https://novartis.wd3.myworkdayjobs.com/Novartis_Careers) | 1 | director/head 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| Pfizer | Freiburg | Workday: [pfizer.wd1.myworkdayjobs.com/PfizerCareers](https://pfizer.wd1.myworkdayjobs.com/PfizerCareers) | 1 | prácticas/graduate 1 | n/d (muestra: de 1) | 1/1 ≤29 d |
| Pierre Fabre | Freiburg | Workday: [pierrefabre.wd3.myworkdayjobs.com/External_Career_Site](https://pierrefabre.wd3.myworkdayjobs.com/External_Career_Site) | 1 | sin marcador (mid probable) 1 | n/d (muestra: fr 2) | sin fechas |
| Prysmian | n/d | Workday: [prysmiangroup.wd3.myworkdayjobs.com/Careers](https://prysmiangroup.wd3.myworkdayjobs.com/Careers) | 1 | sin marcador (mid probable) 1 | n/d (muestra: en 3) | sin fechas |
| Quintet Private Bank | n/d | careers site (sitemap + JobPosting): [careers.quintet.com](https://careers.quintet.com/) | 1 | sin marcador (mid probable) 1 | de 1 | 1/1 ≤90 d |
| Rituals | Köln | careers site (sitemap + JobPosting): [careers.rituals.com](https://careers.rituals.com/) | 1 | senior 1 | de 1 | 1/1 ≤90 d |
| Sanofi | Frankfurt | Workday: [sanofi.wd3.myworkdayjobs.com/SanofiCareers](https://sanofi.wd3.myworkdayjobs.com/SanofiCareers) | 1 | responsable/manager 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| Scout24 | Berlin | Greenhouse: [boards.greenhouse.io/scout24](https://boards.greenhouse.io/scout24) | 1 | senior 1 | de 1 | 1/1 ≤90 d |
| Smava | Berlin | careers site (sitemap + JobPosting): [jobs.smava.de](https://jobs.smava.de/) | 1 | sin marcador (mid probable) 1 | de 1 | 1/1 ≤90 d |
| Syensqo | n/d | careers site (sitemap + JobPosting): [careers.syensqo.com](https://careers.syensqo.com/) | 1 | responsable/manager 1 | en 1 | 1/1 ≤90 d |
| Takeda | n/d | careers site (sitemap + JobPosting): [jobs.takeda.com](https://jobs.takeda.com/) | 1 | director/head 1 | en 1 | 1/1 ≤90 d |
| Targobank | Duisburg | careers site (sitemap + JobPosting): [jobs.targobank.de](https://jobs.targobank.de/) | 1 | prácticas/graduate 1 | de 1 | 1/1 ≤90 d |
| Telefónica | Nürnberg | careers site (sitemap + JobPosting): [jobs.telefonica.com](https://jobs.telefonica.com/) | 1 | prácticas/graduate 1 | de 1 | 1/1 ≤90 d |
| Trivago | Düsseldorf | Greenhouse: [boards.greenhouse.io/trivago](https://boards.greenhouse.io/trivago) | 1 | responsable/manager 1 | en 1 | 1/1 ≤90 d |
| Vistra | Frankfurt | careers site (sitemap + JobPosting): [jobs.vistra.com](https://jobs.vistra.com/) | 1 | senior 1 | en 1 | 1/1 ≤90 d |

### 2.5 Países Bajos (55 empresas, 225 vacantes relevantes)

| Empresa | Ciudad | Tablero (URL leída 2026-10-06) | Vacantes relevantes | Niveles presentes (por título) | Idioma del texto | Fechas |
|---|---|---|---:|---|---|---|
| Baker Tilly | Rotterdam, Nijmegen, Amsterdam | Recruitee: [bakertilly.recruitee.com](https://bakertilly.recruitee.com) | 61 | prácticas/graduate 12, junior 3, sin marcador (mid probable) 11, senior 17, responsable/manager 18 | nl 61 | 17/61 ≤90 d |
| Takeaway Just Eat | Amsterdam | careers site (sitemap + JobPosting): [careers.justeattakeaway.com](https://careers.justeattakeaway.com/) | 15 | sin marcador (mid probable) 6, responsable/manager 6, director/head 3 | en 12 | 15/15 ≤90 d |
| Ahold Delhaize | Zaandam | careers site (sitemap + JobPosting): [careers.aholddelhaize.com](https://careers.aholddelhaize.com/) | 12 | prácticas/graduate 4, sin marcador (mid probable) 2, senior 3, responsable/manager 1, director/head 2 | en 8, nl 4 | 10/12 ≤90 d |
| Coolblue | Rotterdam, Tilburg | SmartRecruiters: [jobs.smartrecruiters.com/coolblue](https://jobs.smartrecruiters.com/coolblue) | 10 | junior 1, sin marcador (mid probable) 8, responsable/manager 1 | nl 10 | 6/10 ≤90 d |
| SGS | Maastricht, Schiphol | SmartRecruiters: [jobs.smartrecruiters.com/sgs](https://jobs.smartrecruiters.com/sgs) | 9 | sin marcador (mid probable) 9 | nl 9 | 5/9 ≤90 d |
| Medtronic | n/d | Workday: [medtronic.wd1.myworkdayjobs.com/MedtronicCareers](https://medtronic.wd1.myworkdayjobs.com/MedtronicCareers) | 8 | sin marcador (mid probable) 4, senior 4 | n/d (muestra: en 3) | 6/6 ≤29 d |
| Boskalis | n/d | careers site (sitemap + JobPosting): [careers.boskalis.com](https://careers.boskalis.com/) | 7 | junior 1, sin marcador (mid probable) 3, senior 2, responsable/manager 1 | en 5, nl 2 | 7/7 ≤90 d |
| Achmea | Tilburg, Apeldoorn | careers site (sitemap + JobPosting): [www.werkenbijachmea.nl](https://www.werkenbijachmea.nl/) | 6 | prácticas/graduate 3, sin marcador (mid probable) 3 | nl 6 | 3/6 ≤90 d |
| CNH Industrial | n/d | careers site (sitemap + JobPosting): [join.cnh.com](https://join.cnh.com/) | 6 | sin marcador (mid probable) 6 | en 6 | sin fechas |
| ABN AMRO | Amsterdam, Utrecht | careers site (sitemap + JobPosting): [careers.abnamro.com](https://careers.abnamro.com/) | 5 | prácticas/graduate 3, responsable/manager 2 | nl 3, en 2 | 2/5 ≤90 d |
| DSM-Firmenich | Maastricht | careers site (sitemap + JobPosting): [jobs.dsm-firmenich.com](https://jobs.dsm-firmenich.com/) | 5 | senior 1, responsable/manager 4 | en 5 | 5/5 ≤90 d |
| Nationale-Nederlanden | The Hague, Amsterdam | Workday: [nngroup.wd3.myworkdayjobs.com/WDExternal](https://nngroup.wd3.myworkdayjobs.com/WDExternal) | 5 | sin marcador (mid probable) 1, senior 4 | n/d (muestra: en 2, nl 1) | 4/4 ≤29 d |
| Fastned | Amsterdam | Recruitee: [fastned.recruitee.com](https://fastned.recruitee.com) | 4 | senior 1, responsable/manager 2, director/head 1 | en 4 | 3/4 ≤90 d |
| Hema | Amsterdam | careers site (sitemap + JobPosting): [jobs.hema.com](https://jobs.hema.com/) | 4 | prácticas/graduate 2, sin marcador (mid probable) 1, responsable/manager 1 | nl 4 | 3/4 ≤90 d |
| ING | Amsterdam | careers site (sitemap + JobPosting): [careers.ing.com](https://careers.ing.com/) | 4 | senior 1, responsable/manager 3 | en 4 | 4/4 ≤90 d |
| Arcadis | Rotterdam | careers site (sitemap + JobPosting): [jobs.arcadis.com](https://jobs.arcadis.com/) | 3 | sin marcador (mid probable) 1, director/head 2 | en 2, nl 1 | 3/3 ≤90 d |
| CZ | Tilburg | Recruitee: [cz.recruitee.com](https://cz.recruitee.com) | 3 | prácticas/graduate 1, sin marcador (mid probable) 2 | nl 3 | 3/3 ≤90 d |
| Mollie | Amsterdam | Ashby: [jobs.ashbyhq.com/mollie](https://jobs.ashbyhq.com/mollie) | 3 | prácticas/graduate 1, senior 1, responsable/manager 1 | en 3 | 3/3 ≤90 d |
| Rituals | Amsterdam | careers site (sitemap + JobPosting): [careers.rituals.com](https://careers.rituals.com/) | 3 | prácticas/graduate 1, senior 1, responsable/manager 1 | en 3 | 3/3 ≤90 d |
| Satispay | Amsterdam | Ashby: [jobs.ashbyhq.com/satispay](https://jobs.ashbyhq.com/satispay) | 3 | director/head 3 | en 3 | 3/3 ≤90 d |
| Unilever | Rotterdam | Workday: [unilever.wd3.myworkdayjobs.com/Unilever_Experienced_Professionals](https://unilever.wd3.myworkdayjobs.com/Unilever_Experienced_Professionals) | 3 | prácticas/graduate 3 | n/d (muestra: en 3) | 3/3 ≤29 d |
| Adyen | Amsterdam | Greenhouse: [boards.greenhouse.io/adyen](https://boards.greenhouse.io/adyen) | 2 | sin marcador (mid probable) 1, responsable/manager 1 | en 2 | 2/2 ≤90 d |
| Capgemini | n/d | careers site (sitemap + JobPosting): [careers.capgemini.com](https://careers.capgemini.com/) | 2 | senior 2 | nl 2 | 2/2 ≤90 d |
| EY | n/d | careers site (sitemap + JobPosting): [careers.ey.com](https://careers.ey.com/) | 2 | senior 2 | nl 2 | 2/2 ≤90 d |
| Eneco | Rotterdam | careers site (sitemap + JobPosting): [www.jobsateneco.com](https://www.jobsateneco.com/) | 2 | senior 2 | en 2 | 2/2 ≤90 d |
| Eurofins | Amersfoort | SmartRecruiters: [jobs.smartrecruiters.com/eurofins](https://jobs.smartrecruiters.com/eurofins) | 2 | junior 1, sin marcador (mid probable) 1 | nl 2 | 2/2 ≤90 d |
| Givaudan | n/d | careers site (sitemap + JobPosting): [careers.givaudan.com](https://careers.givaudan.com/) | 2 | prácticas/graduate 2 | en 2 | 2/2 ≤90 d |
| HelloFresh | Amsterdam | Greenhouse: [boards.greenhouse.io/hellofresh](https://boards.greenhouse.io/hellofresh) | 2 | senior 1, responsable/manager 1 | en 2 | 2/2 ≤90 d |
| Maersk | Rotterdam | Workday: [maersk.wd3.myworkdayjobs.com/APMT_Careers](https://maersk.wd3.myworkdayjobs.com/APMT_Careers) | 2 | sin marcador (mid probable) 2 | n/d (muestra: en 3) | 1/1 ≤29 d |
| Oyster HR | n/d | Ashby: [jobs.ashbyhq.com/oyster](https://jobs.ashbyhq.com/oyster) | 2 | sin marcador (mid probable) 1, senior 1 | en 2 | 2/2 ≤90 d |
| Richemont | Amsterdam | Workday: [richemont.wd3.myworkdayjobs.com/broadbean_external](https://richemont.wd3.myworkdayjobs.com/broadbean_external) | 2 | responsable/manager 1, director/head 1 | n/d (muestra: en 3) | 2/2 ≤29 d |
| Vistra | Amsterdam | careers site (sitemap + JobPosting): [jobs.vistra.com](https://jobs.vistra.com/) | 2 | sin marcador (mid probable) 1, senior 1 | en 2 | 2/2 ≤90 d |
| bunq | Amsterdam | Recruitee: [bunq.recruitee.com](https://bunq.recruitee.com) | 2 | prácticas/graduate 2 | en 2 | 2/2 ≤90 d |
| Abbott | Zwolle | Workday: [abbott.wd5.myworkdayjobs.com/abbottcareers](https://abbott.wd5.myworkdayjobs.com/abbottcareers) | 1 | sin marcador (mid probable) 1 | n/d (muestra: en 2, de 1) | sin fechas |
| Ageras (Shine) | Amsterdam | careers site (sitemap + JobPosting): [careers.shine.co](https://careers.shine.co/) | 1 | responsable/manager 1 | en 1 | 1/1 ≤90 d |
| Aon | Rotterdam | careers site (sitemap + JobPosting): [jobs.aon.com](https://jobs.aon.com/) | 1 | sin marcador (mid probable) 1 | nl 1 | 1/1 ≤90 d |
| Apex Group | Amstelveen | Workday: [theapexgroup.wd3.myworkdayjobs.com/apexgroupcareers](https://theapexgroup.wd3.myworkdayjobs.com/apexgroupcareers) | 1 | responsable/manager 1 | n/d (muestra: en 3) | sin fechas |
| AstraZeneca | Amsterdam | Workday: [astrazeneca.wd3.myworkdayjobs.com/Careers](https://astrazeneca.wd3.myworkdayjobs.com/Careers) | 1 | sin marcador (mid probable) 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| Auxmoney | Amsterdam | Personio: [auxmoney-gmbh.jobs.personio.de](https://auxmoney-gmbh.jobs.personio.de) | 1 | sin marcador (mid probable) 1 | n/d | 1/1 ≤90 d |
| Boehringer Ingelheim | Amsterdam | careers site (sitemap + JobPosting): [jobs.boehringer-ingelheim.com](https://jobs.boehringer-ingelheim.com/) | 1 | prácticas/graduate 1 | en 1 | 1/1 ≤90 d |
| Bosch | Breda | SmartRecruiters: [jobs.smartrecruiters.com/boschgroup](https://jobs.smartrecruiters.com/boschgroup) | 1 | prácticas/graduate 1 | en 1 | 1/1 ≤90 d |
| IQ-EQ | Amsterdam | SmartRecruiters: [jobs.smartrecruiters.com/iqeq](https://jobs.smartrecruiters.com/iqeq) | 1 | responsable/manager 1 | en 1 | 1/1 ≤90 d |
| Jumbo | n/d | careers site (sitemap + JobPosting): [jobs.jumbo.com](https://jobs.jumbo.com/) | 1 | sin marcador (mid probable) 1 | nl 1 | 1/1 ≤90 d |
| KPN | Rotterdam | SmartRecruiters: [jobs.smartrecruiters.com/kpn](https://jobs.smartrecruiters.com/kpn) | 1 | prácticas/graduate 1 | nl 1 | 1/1 ≤90 d |
| Odido | Den Haag | careers site (sitemap + JobPosting): [werkenbij.odido.nl](https://werkenbij.odido.nl/) | 1 | sin marcador (mid probable) 1 | nl 1 | 1/1 ≤90 d |
| Procter & Gamble | Rotterdam | Workday: [pg.wd5.myworkdayjobs.com/1000](https://pg.wd5.myworkdayjobs.com/1000) | 1 | prácticas/graduate 1 | n/d (muestra: en 2, fr 1) | sin fechas |
| Prysmian | Delft | Workday: [prysmiangroup.wd3.myworkdayjobs.com/Careers](https://prysmiangroup.wd3.myworkdayjobs.com/Careers) | 1 | prácticas/graduate 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| RELX | Amsterdam | Workday: [relx.wd3.myworkdayjobs.com/relx](https://relx.wd3.myworkdayjobs.com/relx) | 1 | sin marcador (mid probable) 1 | n/d (muestra: fr 2, nl 1) | sin fechas |
| RWE | n/d | careers site (sitemap + JobPosting): [jobs.rwe.com](https://jobs.rwe.com/) | 1 | responsable/manager 1 | nl 1 | 1/1 ≤90 d |
| TUI | n/d | careers site (sitemap + JobPosting): [careers.tuigroup.com](https://careers.tuigroup.com/) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Thales | n/d | careers site (sitemap + JobPosting): [careers.thalesgroup.com](https://careers.thalesgroup.com/) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Vattenfall | n/d | SmartRecruiters: [jobs.smartrecruiters.com/vattenfall](https://jobs.smartrecruiters.com/vattenfall) | 1 | responsable/manager 1 | nl 1 | 1/1 ≤90 d |
| Volksbank | Utrecht | careers site (sitemap + JobPosting): [werkenbij.devolksbank.nl](https://werkenbij.devolksbank.nl/) | 1 | responsable/manager 1 | nl 1 | 1/1 ≤90 d |
| Vopak | Rotterdam | Workday: [vopak.wd3.myworkdayjobs.com/CareersAtVopak](https://vopak.wd3.myworkdayjobs.com/CareersAtVopak) | 1 | responsable/manager 1 | n/d (muestra: nl 2, en 1) | 1/1 ≤29 d |
| ZF | n/d | careers site (sitemap + JobPosting): [jobs.zf.com](https://jobs.zf.com/) | 1 | director/head 1 | en 1 | 1/1 ≤90 d |

### 2.6 Bélgica (31 empresas, 106 vacantes relevantes)

| Empresa | Ciudad | Tablero (URL leída 2026-10-06) | Vacantes relevantes | Niveles presentes (por título) | Idioma del texto | Fechas |
|---|---|---|---:|---|---|---|
| bpost | Brussel, Bruxelles, Brussels | careers site (sitemap + JobPosting): [career.bpost.be](https://career.bpost.be/) | 17 | sin marcador (mid probable) 7, senior 2, responsable/manager 8 | en 9, nl 4, fr 4 | sin fechas |
| UCB | Brussels | careers site (sitemap + JobPosting): [careers.ucb.com](https://careers.ucb.com/) | 15 | responsable/manager 13, director/head 2 | n/d | 15/15 ≤90 d |
| Belfius | Brussel, Gent | careers site (sitemap + JobPosting): [jobs.belfius.be](https://jobs.belfius.be/) | 9 | prácticas/graduate 1, senior 4, responsable/manager 2, director/head 2 | nl 5, fr 4 | 9/9 ≤90 d |
| Fluxys | Brussels | careers site (sitemap + JobPosting): [careers.fluxys.com](https://careers.fluxys.com/) | 9 | sin marcador (mid probable) 6, responsable/manager 3 | fr 4, nl 3, en 2 | 2/9 ≤90 d |
| PwC | Brussels, Antwerp | Workday: [pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers](https://pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers) | 9 | junior 1, sin marcador (mid probable) 2, senior 5, responsable/manager 1 | n/d (muestra: en 2, it 1) | 5/5 ≤29 d |
| Arcadis | n/d | careers site (sitemap + JobPosting): [jobs.arcadis.com](https://jobs.arcadis.com/) | 4 | sin marcador (mid probable) 1, responsable/manager 1, director/head 2 | en 2, nl 2 | 4/4 ≤90 d |
| Engie | n/d | careers site (sitemap + JobPosting): [jobs.engie.com](https://jobs.engie.com/) | 4 | sin marcador (mid probable) 4 | en 4 | sin fechas |
| SGS | Antwerpen | SmartRecruiters: [jobs.smartrecruiters.com/sgs](https://jobs.smartrecruiters.com/sgs) | 4 | sin marcador (mid probable) 4 | nl 3, fr 1 | 3/4 ≤90 d |
| Sanofi | Brussels | Workday: [sanofi.wd3.myworkdayjobs.com/SanofiCareers](https://sanofi.wd3.myworkdayjobs.com/SanofiCareers) | 4 | sin marcador (mid probable) 4 | n/d (muestra: en 3) | 4/4 ≤29 d |
| EY | n/d | careers site (sitemap + JobPosting): [careers.ey.com](https://careers.ey.com/) | 3 | sin marcador (mid probable) 2, responsable/manager 1 | en 1, de 1, nl 1 | 3/3 ≤90 d |
| Vopak | n/d | Workday: [vopak.wd3.myworkdayjobs.com/CareersAtVopak](https://vopak.wd3.myworkdayjobs.com/CareersAtVopak) | 3 | sin marcador (mid probable) 1, senior 1, responsable/manager 1 | n/d (muestra: nl 2, en 1) | 1/1 ≤29 d |
| Capgemini | n/d | careers site (sitemap + JobPosting): [careers.capgemini.com](https://careers.capgemini.com/) | 2 | senior 1, responsable/manager 1 | en 2 | 2/2 ≤90 d |
| Eurofins | Brussels | SmartRecruiters: [jobs.smartrecruiters.com/eurofins](https://jobs.smartrecruiters.com/eurofins) | 2 | sin marcador (mid probable) 1, director/head 1 | en 2 | 1/2 ≤90 d |
| Pernod Ricard | Brussels | Workday: [pernodricard.wd3.myworkdayjobs.com/pernod-ricard](https://pernodricard.wd3.myworkdayjobs.com/pernod-ricard) | 2 | sin marcador (mid probable) 2 | n/d (muestra: fr 2, en 1) | sin fechas |
| Securitas | Machelen | SmartRecruiters: [jobs.smartrecruiters.com/securitas](https://jobs.smartrecruiters.com/securitas) | 2 | sin marcador (mid probable) 2 | en 1, nl 1 | 2/2 ≤90 d |
| Swift | Brussels | Workday: [swift.wd3.myworkdayjobs.com/Join-Swift](https://swift.wd3.myworkdayjobs.com/Join-Swift) | 2 | sin marcador (mid probable) 1, director/head 1 | n/d (muestra: en 3) | sin fechas |
| Abbott | Zaventem | Workday: [abbott.wd5.myworkdayjobs.com/abbottcareers](https://abbott.wd5.myworkdayjobs.com/abbottcareers) | 1 | senior 1 | n/d (muestra: en 2, de 1) | 1/1 ≤29 d |
| Accor | Brussels | careers site (sitemap + JobPosting): [careers.accor.com](https://careers.accor.com/) | 1 | prácticas/graduate 1 | fr 1 | 1/1 ≤90 d |
| Ayvens | Zaventem | Workday: [ayvens.wd3.myworkdayjobs.com/AyvensCareers](https://ayvens.wd3.myworkdayjobs.com/AyvensCareers) | 1 | sin marcador (mid probable) 1 | n/d (muestra: fr 1, en 1, pt 1) | sin fechas |
| Campari | Bruxelles | careers site (sitemap + JobPosting): [careers.camparigroup.com](https://careers.camparigroup.com/) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Ebro Foods | n/d | Recruitee: [ebro.recruitee.com](https://ebro.recruitee.com) | 1 | sin marcador (mid probable) 1 | nl 1 | 1/1 ≤90 d |
| ING | Gent | careers site (sitemap + JobPosting): [careers.ing.com](https://careers.ing.com/) | 1 | sin marcador (mid probable) 1 | nl 1 | 1/1 ≤90 d |
| Lonza | n/d | Workday: [lonza.wd3.myworkdayjobs.com/Lonza_Careers](https://lonza.wd3.myworkdayjobs.com/Lonza_Careers) | 1 | director/head 1 | n/d (muestra: en 3) | sin fechas |
| Nationale-Nederlanden | Brussels | Workday: [nngroup.wd3.myworkdayjobs.com/WDExternal](https://nngroup.wd3.myworkdayjobs.com/WDExternal) | 1 | responsable/manager 1 | n/d (muestra: en 2, nl 1) | 1/1 ≤29 d |
| Oyster HR | n/d | Ashby: [jobs.ashbyhq.com/oyster](https://jobs.ashbyhq.com/oyster) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Procter & Gamble | Brussels | Workday: [pg.wd5.myworkdayjobs.com/1000](https://pg.wd5.myworkdayjobs.com/1000) | 1 | prácticas/graduate 1 | n/d (muestra: en 2, fr 1) | sin fechas |
| Roche | Brussels | careers site (sitemap + JobPosting): [careers.roche.com](https://careers.roche.com/) | 1 | sin marcador (mid probable) 1 | n/d | 1/1 ≤90 d |
| Securex | Gent | Workday: [securex.wd3.myworkdayjobs.com/Securex](https://securex.wd3.myworkdayjobs.com/Securex) | 1 | sin marcador (mid probable) 1 | n/d (muestra: nl 2, fr 1) | 1/1 ≤29 d |
| Solvay | n/d | careers site (sitemap + JobPosting): [careers.solvay.com](https://careers.solvay.com/) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Syensqo | n/d | careers site (sitemap + JobPosting): [careers.syensqo.com](https://careers.syensqo.com/) | 1 | prácticas/graduate 1 | en 1 | 1/1 ≤90 d |
| TUI | Zaventem | careers site (sitemap + JobPosting): [careers.tuigroup.com](https://careers.tuigroup.com/) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |

### 2.7 Irlanda (33 empresas, 95 vacantes relevantes)

| Empresa | Ciudad | Tablero (URL leída 2026-10-06) | Vacantes relevantes | Niveles presentes (por título) | Idioma del texto | Fechas |
|---|---|---|---:|---|---|---|
| Northern Trust | Limerick | Workday: [ntrs.wd1.myworkdayjobs.com/northerntrust](https://ntrs.wd1.myworkdayjobs.com/northerntrust) | 18 | prácticas/graduate 1, sin marcador (mid probable) 7, senior 7, responsable/manager 1, director/head 2 | n/d (muestra: en 3) | 10/10 ≤29 d |
| PwC | Dublin | Workday: [pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers](https://pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers) | 10 | sin marcador (mid probable) 1, responsable/manager 8, director/head 1 | n/d (muestra: en 2, it 1) | 6/6 ≤29 d |
| CNH Industrial | n/d | careers site (sitemap + JobPosting): [join.cnh.com](https://join.cnh.com/) | 6 | sin marcador (mid probable) 6 | es 1, it 1, en 1 | sin fechas |
| Kerry Group | n/d | careers site (sitemap + JobPosting): [jobs.kerry.com](https://jobs.kerry.com/) | 6 | prácticas/graduate 6 | en 6 | 6/6 ≤90 d |
| Abbott | Dublin, Sligo | Workday: [abbott.wd5.myworkdayjobs.com/abbottcareers](https://abbott.wd5.myworkdayjobs.com/abbottcareers) | 5 | prácticas/graduate 1, sin marcador (mid probable) 2, senior 1, responsable/manager 1 | n/d (muestra: en 2, de 1) | 5/5 ≤29 d |
| State Street | Dublin, Kilkenny | Workday: [statestreet.wd1.myworkdayjobs.com/Global](https://statestreet.wd1.myworkdayjobs.com/Global) | 4 | sin marcador (mid probable) 2, director/head 2 | n/d (muestra: en 2, de 1) | 4/4 ≤29 d |
| AkzoNobel | Dublin | careers site (sitemap + JobPosting): [careers.akzonobel.com](https://careers.akzonobel.com/) | 3 | sin marcador (mid probable) 3 | en 3 | 3/3 ≤90 d |
| ESB | Dublin | careers site (sitemap + JobPosting): [careers.esb.ie](https://careers.esb.ie/) | 3 | prácticas/graduate 1, sin marcador (mid probable) 1, senior 1 | en 3 | 3/3 ≤90 d |
| Eli Lilly | Cork | careers site (sitemap + JobPosting): [careers.lilly.com](https://careers.lilly.com/) | 3 | responsable/manager 2, director/head 1 | en 3 | 3/3 ≤90 d |
| Gilead | Cork | Workday: [gilead.wd1.myworkdayjobs.com/gileadcareers](https://gilead.wd1.myworkdayjobs.com/gileadcareers) | 3 | senior 2, director/head 1 | n/d (muestra: en 3) | 2/2 ≤29 d |
| Logitech | Cork | Workday: [logitech.wd5.myworkdayjobs.com/Logitech](https://logitech.wd5.myworkdayjobs.com/Logitech) | 3 | prácticas/graduate 1, senior 2 | n/d (muestra: en 3) | 3/3 ≤29 d |
| SumUp | Dublin | Greenhouse: [boards.greenhouse.io/sumup](https://boards.greenhouse.io/sumup) | 3 | prácticas/graduate 1, director/head 2 | en 2 | 2/3 ≤90 d |
| Alter Domus | n/d | careers site (sitemap + JobPosting): [jobs.alterdomus.com](https://jobs.alterdomus.com/) | 2 | sin marcador (mid probable) 1, senior 1 | en 2 | 2/2 ≤90 d |
| Bank of America | Dublin | careers site (sitemap + JobPosting): [careers.bankofamerica.com](https://careers.bankofamerica.com/) | 2 | sin marcador (mid probable) 2 | en 2 | sin fechas |
| Deutsche Börse | n/d | careers site (sitemap + JobPosting): [career.deutsche-boerse.com](https://career.deutsche-boerse.com/) | 2 | sin marcador (mid probable) 1, director/head 1 | en 2 | 2/2 ≤90 d |
| Glanbia | Dublin | careers site (sitemap + JobPosting): [careers.glanbia.com](https://careers.glanbia.com/) | 2 | sin marcador (mid probable) 1, senior 1 | en 2 | 2/2 ≤90 d |
| IQ-EQ | Dublin | SmartRecruiters: [jobs.smartrecruiters.com/iqeq](https://jobs.smartrecruiters.com/iqeq) | 2 | responsable/manager 2 | en 2 | 2/2 ≤90 d |
| SGS | n/d | SmartRecruiters: [jobs.smartrecruiters.com/sgs](https://jobs.smartrecruiters.com/sgs) | 2 | sin marcador (mid probable) 2 | en 2 | 2/2 ≤90 d |
| SS&C | Dublin | Workday: [ssctech.wd1.myworkdayjobs.com/SSCTechnologies](https://ssctech.wd1.myworkdayjobs.com/SSCTechnologies) | 2 | responsable/manager 1, director/head 1 | n/d (muestra: en 3) | 2/2 ≤29 d |
| AbbVie | n/d | SmartRecruiters: [jobs.smartrecruiters.com/abbvie](https://jobs.smartrecruiters.com/abbvie) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Amgen | n/d | Workday: [amgen.wd1.myworkdayjobs.com/Careers](https://amgen.wd1.myworkdayjobs.com/Careers) | 1 | senior 1 | n/d (muestra: en 3) | sin fechas |
| Barclays | Dublin | Workday: [barclays.wd3.myworkdayjobs.com/External_Career_Site_Barclays](https://barclays.wd3.myworkdayjobs.com/External_Career_Site_Barclays) | 1 | director/head 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| BlackRock | Dublin | Workday: [blackrock.wd1.myworkdayjobs.com/BlackRock_Professional](https://blackrock.wd1.myworkdayjobs.com/BlackRock_Professional) | 1 | sin marcador (mid probable) 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| Flipdish | Dublin | Greenhouse: [boards.greenhouse.io/flipdish](https://boards.greenhouse.io/flipdish) | 1 | prácticas/graduate 1 | en 1 | 1/1 ≤90 d |
| Hewlett Packard Enterprise | n/d | careers site (sitemap + JobPosting): [careers.hpe.com](https://careers.hpe.com/) | 1 | senior 1 | n/d | 1/1 ≤90 d |
| Invesco | Dublin | Workday: [invesco.wd1.myworkdayjobs.com/IVZ](https://invesco.wd1.myworkdayjobs.com/IVZ) | 1 | director/head 1 | n/d (muestra: en 3) | sin fechas |
| Medtronic | Galway | Workday: [medtronic.wd1.myworkdayjobs.com/MedtronicCareers](https://medtronic.wd1.myworkdayjobs.com/MedtronicCareers) | 1 | prácticas/graduate 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| Oyster HR | n/d | Ashby: [jobs.ashbyhq.com/oyster](https://jobs.ashbyhq.com/oyster) | 1 | director/head 1 | en 1 | 1/1 ≤90 d |
| PepsiCo | Cork | careers site (sitemap + JobPosting): [careers.pepsico.com](https://careers.pepsico.com/) | 1 | senior 1 | en 1 | 1/1 ≤90 d |
| Vanguard | Dublin | Workday: [vanguard.wd5.myworkdayjobs.com/vanguard_external](https://vanguard.wd5.myworkdayjobs.com/vanguard_external) | 1 | senior 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| Vistra | Dublin | careers site (sitemap + JobPosting): [jobs.vistra.com](https://jobs.vistra.com/) | 1 | responsable/manager 1 | n/d | 1/1 ≤90 d |
| Vodafone | Dublin | careers site (sitemap + JobPosting): [jobs.vodafone.com](https://jobs.vodafone.com/) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Wayflyer | Dublin | Ashby: [jobs.ashbyhq.com/wayflyer](https://jobs.ashbyhq.com/wayflyer) | 1 | prácticas/graduate 1 | en 1 | 1/1 ≤90 d |

### 2.8 Luxemburgo (23 empresas, 81 vacantes relevantes)

| Empresa | Ciudad | Tablero (URL leída 2026-10-06) | Vacantes relevantes | Niveles presentes (por título) | Idioma del texto | Fechas |
|---|---|---|---:|---|---|---|
| Deloitte Luxembourg | n/d | careers site (sitemap + JobPosting): [jobs.deloitte.lu](https://jobs.deloitte.lu/) | 29 | prácticas/graduate 10, junior 3, sin marcador (mid probable) 2, senior 10, responsable/manager 4 | en 27, de 2 | sin fechas |
| Apex Group | Munsbach, Luxembourg | Workday: [theapexgroup.wd3.myworkdayjobs.com/apexgroupcareers](https://theapexgroup.wd3.myworkdayjobs.com/apexgroupcareers) | 6 | prácticas/graduate 1, senior 1, responsable/manager 3, director/head 1 | n/d (muestra: en 3) | 4/4 ≤29 d |
| Northern Trust | Luxembourg | Workday: [ntrs.wd1.myworkdayjobs.com/northerntrust](https://ntrs.wd1.myworkdayjobs.com/northerntrust) | 6 | sin marcador (mid probable) 5, senior 1 | n/d (muestra: en 3) | 4/4 ≤29 d |
| ING | Luxembourg | careers site (sitemap + JobPosting): [careers.ing.com](https://careers.ing.com/) | 4 | prácticas/graduate 1, sin marcador (mid probable) 1, senior 1, director/head 1 | en 4 | 4/4 ≤90 d |
| PayPal | Luxembourg | Workday: [paypal.wd1.myworkdayjobs.com/jobs](https://paypal.wd1.myworkdayjobs.com/jobs) | 4 | sin marcador (mid probable) 1, responsable/manager 3 | n/d (muestra: en 3) | 3/3 ≤29 d |
| Satispay | Luxembourg | Ashby: [jobs.ashbyhq.com/satispay](https://jobs.ashbyhq.com/satispay) | 4 | sin marcador (mid probable) 1, senior 2, director/head 1 | en 4 | 3/4 ≤90 d |
| Ayvens | Strassen, Luxembourg | Workday: [ayvens.wd3.myworkdayjobs.com/AyvensCareers](https://ayvens.wd3.myworkdayjobs.com/AyvensCareers) | 3 | responsable/manager 3 | n/d (muestra: fr 1, en 1, pt 1) | sin fechas |
| Deutsche Börse | n/d | careers site (sitemap + JobPosting): [career.deutsche-boerse.com](https://career.deutsche-boerse.com/) | 3 | prácticas/graduate 2, sin marcador (mid probable) 1 | en 3 | 3/3 ≤90 d |
| Rothschild & Co | Luxembourg | Workday: [rothschildandco.wd3.myworkdayjobs.com/Rothschildandco_Lateral](https://rothschildandco.wd3.myworkdayjobs.com/Rothschildandco_Lateral) | 3 | prácticas/graduate 2, junior 1 | n/d (muestra: fr 3) | 1/1 ≤29 d |
| State Street | Luxembourg | Workday: [statestreet.wd1.myworkdayjobs.com/Global](https://statestreet.wd1.myworkdayjobs.com/Global) | 3 | sin marcador (mid probable) 1, director/head 2 | n/d (muestra: en 2, de 1) | 3/3 ≤29 d |
| PwC | Luxembourg | Workday: [pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers](https://pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers) | 2 | senior 1, responsable/manager 1 | n/d (muestra: en 2, it 1) | 1/1 ≤29 d |
| Quintet Private Bank | n/d | careers site (sitemap + JobPosting): [careers.quintet.com](https://careers.quintet.com/) | 2 | prácticas/graduate 1, sin marcador (mid probable) 1 | en 2 | 2/2 ≤90 d |
| SS&C | Luxembourg | Workday: [ssctech.wd1.myworkdayjobs.com/SSCTechnologies](https://ssctech.wd1.myworkdayjobs.com/SSCTechnologies) | 2 | prácticas/graduate 1, director/head 1 | n/d (muestra: en 3) | 2/2 ≤29 d |
| Alter Domus | n/d | careers site (sitemap + JobPosting): [jobs.alterdomus.com](https://jobs.alterdomus.com/) | 1 | senior 1 | en 1 | 1/1 ≤90 d |
| Arcadis | n/d | careers site (sitemap + JobPosting): [jobs.arcadis.com](https://jobs.arcadis.com/) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Ardian | Luxembourg | Workday: [ardian.wd103.myworkdayjobs.com/ArdianCareers](https://ardian.wd103.myworkdayjobs.com/ArdianCareers) | 1 | prácticas/graduate 1 | n/d (muestra: fr 2, en 1) | sin fechas |
| Coinbase | Luxembourg | Greenhouse: [boards.greenhouse.io/coinbase](https://boards.greenhouse.io/coinbase) | 1 | prácticas/graduate 1 | en 1 | 1/1 ≤90 d |
| IQ-EQ | Luxembourg | SmartRecruiters: [jobs.smartrecruiters.com/iqeq](https://jobs.smartrecruiters.com/iqeq) | 1 | senior 1 | en 1 | 1/1 ≤90 d |
| Ocorian | Luxembourg | SmartRecruiters: [jobs.smartrecruiters.com/ocorian](https://jobs.smartrecruiters.com/ocorian) | 1 | senior 1 | en 1 | 1/1 ≤90 d |
| Swissquote | Luxembourg | SmartRecruiters: [jobs.smartrecruiters.com/swissquote](https://jobs.smartrecruiters.com/swissquote) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Temenos | Bertrange | Workday: [temenos.wd103.myworkdayjobs.com/Temenoscareers](https://temenos.wd103.myworkdayjobs.com/Temenoscareers) | 1 | sin marcador (mid probable) 1 | n/d (muestra: en 3) | sin fechas |
| Unzer | Munsbach | Lever: [jobs.eu.lever.co/unzer](https://jobs.eu.lever.co/unzer) | 1 | responsable/manager 1 | en 1 | 1/1 ≤90 d |
| Vodafone | Luxembourg | careers site (sitemap + JobPosting): [jobs.vodafone.com](https://jobs.vodafone.com/) | 1 | responsable/manager 1 | en 1 | 1/1 ≤90 d |

### 2.9 Suiza (32 empresas, 75 vacantes relevantes)

| Empresa | Ciudad | Tablero (URL leída 2026-10-06) | Vacantes relevantes | Niveles presentes (por título) | Idioma del texto | Fechas |
|---|---|---|---:|---|---|---|
| Julius Baer | Zürich | Workday: [juliusbaer.wd3.myworkdayjobs.com/External](https://juliusbaer.wd3.myworkdayjobs.com/External) | 10 | prácticas/graduate 1, sin marcador (mid probable) 5, responsable/manager 4 | n/d (muestra: en 3) | 5/5 ≤29 d |
| EY | n/d | careers site (sitemap + JobPosting): [careers.ey.com](https://careers.ey.com/) | 8 | prácticas/graduate 2, senior 1, responsable/manager 5 | en 4, de 3, fr 1 | 8/8 ≤90 d |
| Coop Switzerland | Basel, Bern, Zürich | careers site (sitemap + JobPosting): [jobs.coop.ch](https://jobs.coop.ch/) | 5 | sin marcador (mid probable) 1, responsable/manager 4 | n/d | 5/5 ≤90 d |
| PwC | Zürich, Bern | Workday: [pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers](https://pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers) | 5 | sin marcador (mid probable) 1, senior 2, responsable/manager 2 | n/d (muestra: en 2, it 1) | 4/4 ≤29 d |
| Partners Group | n/d | careers site (sitemap + JobPosting): [jobs.partnersgroup.com](https://jobs.partnersgroup.com/) | 4 | sin marcador (mid probable) 1, senior 2, responsable/manager 1 | en 4 | 4/4 ≤90 d |
| Lonza | Basel | Workday: [lonza.wd3.myworkdayjobs.com/Lonza_Careers](https://lonza.wd3.myworkdayjobs.com/Lonza_Careers) | 3 | sin marcador (mid probable) 2, senior 1 | n/d (muestra: en 3) | 3/3 ≤29 d |
| Swissquote | n/d | SmartRecruiters: [jobs.smartrecruiters.com/swissquote](https://jobs.smartrecruiters.com/swissquote) | 3 | prácticas/graduate 1, sin marcador (mid probable) 1, director/head 1 | en 3 | 3/3 ≤90 d |
| Abbott | Basel | Workday: [abbott.wd5.myworkdayjobs.com/abbottcareers](https://abbott.wd5.myworkdayjobs.com/abbottcareers) | 2 | sin marcador (mid probable) 1, responsable/manager 1 | n/d (muestra: en 2, de 1) | 2/2 ≤29 d |
| Alcon | Fribourg | Workday: [alcon.wd5.myworkdayjobs.com/careers_alcon](https://alcon.wd5.myworkdayjobs.com/careers_alcon) | 2 | prácticas/graduate 1, responsable/manager 1 | n/d (muestra: en 2, es 1) | 1/1 ≤29 d |
| Ardian | Zürich | Workday: [ardian.wd103.myworkdayjobs.com/ArdianCareers](https://ardian.wd103.myworkdayjobs.com/ArdianCareers) | 2 | prácticas/graduate 2 | n/d (muestra: fr 2, en 1) | 1/1 ≤29 d |
| Bachem | n/d | careers site (sitemap + JobPosting): [careers.bachem.com](https://careers.bachem.com/) | 2 | senior 1, responsable/manager 1 | en 1, de 1 | 2/2 ≤90 d |
| Bosch | n/d | SmartRecruiters: [jobs.smartrecruiters.com/boschgroup](https://jobs.smartrecruiters.com/boschgroup) | 2 | prácticas/graduate 2 | de 2 | 2/2 ≤90 d |
| DSM-Firmenich | n/d | careers site (sitemap + JobPosting): [jobs.dsm-firmenich.com](https://jobs.dsm-firmenich.com/) | 2 | sin marcador (mid probable) 1, responsable/manager 1 | en 2 | 2/2 ≤90 d |
| E.ON | Baden | careers site (sitemap + JobPosting): [jobs.eon.com](https://jobs.eon.com/) | 2 | prácticas/graduate 1, senior 1 | de 2 | 2/2 ≤90 d |
| Givaudan | n/d | careers site (sitemap + JobPosting): [careers.givaudan.com](https://careers.givaudan.com/) | 2 | sin marcador (mid probable) 2 | en 2 | 2/2 ≤90 d |
| Logitech | Lausanne | Workday: [logitech.wd5.myworkdayjobs.com/Logitech](https://logitech.wd5.myworkdayjobs.com/Logitech) | 2 | prácticas/graduate 1, responsable/manager 1 | n/d (muestra: en 3) | 2/2 ≤29 d |
| Lombard Odier | Geneva | Workday: [lombardodier.wd3.myworkdayjobs.com/Lombard_Odier_Careers](https://lombardodier.wd3.myworkdayjobs.com/Lombard_Odier_Careers) | 2 | sin marcador (mid probable) 2 | n/d (muestra: en 3) | 2/2 ≤29 d |
| Swiss Re | Zürich | careers site (sitemap + JobPosting): [careers.swissre.com](https://careers.swissre.com/) | 2 | prácticas/graduate 2 | en 2 | 2/2 ≤90 d |
| Vontobel | Zürich | Workday: [vontobel.wd3.myworkdayjobs.com/Vontobel_External_Career](https://vontobel.wd3.myworkdayjobs.com/Vontobel_External_Career) | 2 | sin marcador (mid probable) 1, senior 1 | n/d (muestra: en 2, de 1) | sin fechas |
| Avaloq | Zürich | careers site (sitemap + JobPosting): [avaloq.com](https://avaloq.com/) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| BBVA | Zürich | Workday: [bbva.wd3.myworkdayjobs.com/BBVA](https://bbva.wd3.myworkdayjobs.com/BBVA) | 1 | prácticas/graduate 1 | n/d (muestra: es 2, en 1) | 1/1 ≤29 d |
| Banque Cantonale Vaudoise | n/d | careers site (sitemap + JobPosting): [jobs.bcv.ch](https://jobs.bcv.ch/) | 1 | responsable/manager 1 | fr 1 | sin fechas |
| Coface | Lausanne | SmartRecruiters: [jobs.smartrecruiters.com/coface](https://jobs.smartrecruiters.com/coface) | 1 | junior 1 | en 1 | 1/1 ≤90 d |
| Gunvor | Geneva | Workday: [gunvor.wd3.myworkdayjobs.com/Gunvor_Careers](https://gunvor.wd3.myworkdayjobs.com/Gunvor_Careers) | 1 | director/head 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| Ikea | n/d | careers site (sitemap + JobPosting): [jobs.ikea.com](https://jobs.ikea.com/) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Lindt | n/d | Workday: [lindtspruengli.wd103.myworkdayjobs.com/LindtSpruengliGroupCareers](https://lindtspruengli.wd103.myworkdayjobs.com/LindtSpruengliGroupCareers) | 1 | prácticas/graduate 1 | n/d (muestra: fr 2, de 1) | 1/1 ≤29 d |
| Rothschild & Co | Zürich | Workday: [rothschildandco.wd3.myworkdayjobs.com/Rothschildandco_Lateral](https://rothschildandco.wd3.myworkdayjobs.com/Rothschildandco_Lateral) | 1 | sin marcador (mid probable) 1 | n/d (muestra: fr 3) | 1/1 ≤29 d |
| SGS | Baar | SmartRecruiters: [jobs.smartrecruiters.com/sgs](https://jobs.smartrecruiters.com/sgs) | 1 | director/head 1 | en 1 | 1/1 ≤90 d |
| SIX Group | n/d | careers site (sitemap + JobPosting): [jobs.six-group.com](https://jobs.six-group.com/) | 1 | prácticas/graduate 1 | de 1 | 1/1 ≤90 d |
| Takeda | Zürich | careers site (sitemap + JobPosting): [jobs.takeda.com](https://jobs.takeda.com/) | 1 | responsable/manager 1 | en 1 | 1/1 ≤90 d |
| Unilever | n/d | Workday: [unilever.wd3.myworkdayjobs.com/Unilever_Experienced_Professionals](https://unilever.wd3.myworkdayjobs.com/Unilever_Experienced_Professionals) | 1 | sin marcador (mid probable) 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| Vistra | Zürich | careers site (sitemap + JobPosting): [jobs.vistra.com](https://jobs.vistra.com/) | 1 | sin marcador (mid probable) 1 | n/d | 1/1 ≤90 d |

### 2.10 Italia (38 empresas, 121 vacantes relevantes)

| Empresa | Ciudad | Tablero (URL leída 2026-10-06) | Vacantes relevantes | Niveles presentes (por título) | Idioma del texto | Fechas |
|---|---|---|---:|---|---|---|
| Leonardo | Roma, Genova, Pomezia | Workday: [leonardocompany.wd3.myworkdayjobs.com/LeonardoCareerSite](https://leonardocompany.wd3.myworkdayjobs.com/LeonardoCareerSite) | 15 | prácticas/graduate 3, sin marcador (mid probable) 5, senior 2, responsable/manager 5 | n/d (muestra: it 3) | 11/11 ≤29 d |
| MetLife | n/d | careers site (sitemap + JobPosting): [www.metlifecareers.com](https://www.metlifecareers.com/) | 12 | sin marcador (mid probable) 8, responsable/manager 4 | n/d | 12/12 ≤90 d |
| CNH Industrial | n/d | careers site (sitemap + JobPosting): [join.cnh.com](https://join.cnh.com/) | 10 | prácticas/graduate 1, sin marcador (mid probable) 1, senior 8 | es 2, pt 2, en 2 | sin fechas |
| Webuild | n/d | careers site (sitemap + JobPosting): [jobs.webuildgroup.com](https://jobs.webuildgroup.com/) | 9 | prácticas/graduate 4, junior 1, senior 1, responsable/manager 3 | it 9 | 9/9 ≤90 d |
| Prysmian | Milan | Workday: [prysmiangroup.wd3.myworkdayjobs.com/Careers](https://prysmiangroup.wd3.myworkdayjobs.com/Careers) | 7 | prácticas/graduate 4, sin marcador (mid probable) 2, responsable/manager 1 | n/d (muestra: en 3) | 3/3 ≤29 d |
| Campari | Sesto San Giovanni | careers site (sitemap + JobPosting): [careers.camparigroup.com](https://careers.camparigroup.com/) | 6 | prácticas/graduate 1, sin marcador (mid probable) 1, senior 4 | en 6 | 6/6 ≤90 d |
| Bureau Veritas | Milano, Bologna, Genova | careers site (sitemap + JobPosting): [jobs.bureauveritas.com](https://jobs.bureauveritas.com/) | 5 | sin marcador (mid probable) 4, senior 1 | n/d | 5/5 ≤90 d |
| Satispay | Milan | Ashby: [jobs.ashbyhq.com/satispay](https://jobs.ashbyhq.com/satispay) | 5 | sin marcador (mid probable) 2, senior 1, responsable/manager 1, director/head 1 | en 5 | 4/5 ≤90 d |
| Euronext | Milan | Workday: [hrhub.wd3.myworkdayjobs.com/Euronext_Career_Page](https://hrhub.wd3.myworkdayjobs.com/Euronext_Career_Page) | 4 | prácticas/graduate 3, sin marcador (mid probable) 1 | n/d (muestra: en 3) | 2/2 ≤29 d |
| Pirelli | n/d | careers site (sitemap + JobPosting): [jobs.pirelli.com](https://jobs.pirelli.com/) | 4 | prácticas/graduate 4 | en 4 | sin fechas |
| PwC | Milan, Naples | Workday: [pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers](https://pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers) | 4 | junior 1, sin marcador (mid probable) 2, responsable/manager 1 | n/d (muestra: en 2, it 1) | 2/2 ≤29 d |
| Allianz | Milan | careers site (sitemap + JobPosting): [careers.allianz.com](https://careers.allianz.com/) | 3 | responsable/manager 3 | n/d | 3/3 ≤90 d |
| Ayvens | Rome | Workday: [ayvens.wd3.myworkdayjobs.com/AyvensCareers](https://ayvens.wd3.myworkdayjobs.com/AyvensCareers) | 3 | prácticas/graduate 1, sin marcador (mid probable) 2 | n/d (muestra: fr 1, en 1, pt 1) | 1/1 ≤29 d |
| Moncler | Milano | careers site (sitemap + JobPosting): [jobs.monclergroup.com](https://jobs.monclergroup.com/) | 3 | prácticas/graduate 2, sin marcador (mid probable) 1 | en 3 | 3/3 ≤90 d |
| Prada Group | n/d | careers site (sitemap + JobPosting): [jobs.pradagroup.com](https://jobs.pradagroup.com/) | 3 | sin marcador (mid probable) 2, responsable/manager 1 | en 3 | 3/3 ≤90 d |
| Air Liquide | Milano | Workday: [airliquidehr.wd3.myworkdayjobs.com/AirLiquideExternalCareer](https://airliquidehr.wd3.myworkdayjobs.com/AirLiquideExternalCareer) | 2 | prácticas/graduate 1, sin marcador (mid probable) 1 | n/d (muestra: fr 2, es 1) | sin fechas |
| Bosch | Torino | SmartRecruiters: [jobs.smartrecruiters.com/boschgroup](https://jobs.smartrecruiters.com/boschgroup) | 2 | prácticas/graduate 2 | en 2 | 2/2 ≤90 d |
| Eurofins | n/d | SmartRecruiters: [jobs.smartrecruiters.com/eurofins](https://jobs.smartrecruiters.com/eurofins) | 2 | prácticas/graduate 1, sin marcador (mid probable) 1 | en 2 | 1/2 ≤90 d |
| ITA Airways | n/d | careers site (sitemap + JobPosting): [career.ita-airways.com](https://career.ita-airways.com/) | 2 | junior 1, responsable/manager 1 | it 2 | sin fechas |
| Richemont | Milan | Workday: [richemont.wd3.myworkdayjobs.com/broadbean_external](https://richemont.wd3.myworkdayjobs.com/broadbean_external) | 2 | prácticas/graduate 2 | n/d (muestra: en 3) | 2/2 ≤29 d |
| Boehringer Ingelheim | Milan | careers site (sitemap + JobPosting): [jobs.boehringer-ingelheim.com](https://jobs.boehringer-ingelheim.com/) | 1 | prácticas/graduate 1 | en 1 | 1/1 ≤90 d |
| Capgemini | n/d | careers site (sitemap + JobPosting): [careers.capgemini.com](https://careers.capgemini.com/) | 1 | senior 1 | it 1 | 1/1 ≤90 d |
| Delivery Hero | Milano | SmartRecruiters: [jobs.smartrecruiters.com/deliveryhero](https://jobs.smartrecruiters.com/deliveryhero) | 1 | responsable/manager 1 | en 1 | 1/1 ≤90 d |
| EY | Bologna | careers site (sitemap + JobPosting): [careers.ey.com](https://careers.ey.com/) | 1 | responsable/manager 1 | it 1 | 1/1 ≤90 d |
| Eli Lilly | Firenze | careers site (sitemap + JobPosting): [careers.lilly.com](https://careers.lilly.com/) | 1 | prácticas/graduate 1 | en 1 | 1/1 ≤90 d |
| Engie | n/d | careers site (sitemap + JobPosting): [jobs.engie.com](https://jobs.engie.com/) | 1 | sin marcador (mid probable) 1 | it 1 | sin fechas |
| Glovo | n/d | careers site (sitemap + JobPosting): [careers.glovoapp.com](https://careers.glovoapp.com/) | 1 | responsable/manager 1 | en 1 | 1/1 ≤90 d |
| Hiscox | Milan | Workday: [hiscox.wd3.myworkdayjobs.com/Hiscox_External_Site](https://hiscox.wd3.myworkdayjobs.com/Hiscox_External_Site) | 1 | responsable/manager 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| ING | Milan | careers site (sitemap + JobPosting): [careers.ing.com](https://careers.ing.com/) | 1 | senior 1 | en 1 | 1/1 ≤90 d |
| Ikea | Milano | careers site (sitemap + JobPosting): [jobs.ikea.com](https://jobs.ikea.com/) | 1 | prácticas/graduate 1 | it 1 | 1/1 ≤90 d |
| Lindt | n/d | Workday: [lindtspruengli.wd103.myworkdayjobs.com/LindtSpruengliGroupCareers](https://lindtspruengli.wd103.myworkdayjobs.com/LindtSpruengliGroupCareers) | 1 | sin marcador (mid probable) 1 | n/d (muestra: fr 2, de 1) | sin fechas |
| Logitech | Milan | Workday: [logitech.wd5.myworkdayjobs.com/Logitech](https://logitech.wd5.myworkdayjobs.com/Logitech) | 1 | responsable/manager 1 | n/d (muestra: en 3) | 1/1 ≤29 d |
| Munich Re | Milano | careers site (sitemap + JobPosting): [careers.munichre.com](https://careers.munichre.com/) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| Partners Group | n/d | careers site (sitemap + JobPosting): [jobs.partnersgroup.com](https://jobs.partnersgroup.com/) | 1 | sin marcador (mid probable) 1 | en 1 | 1/1 ≤90 d |
| SGS | n/d | SmartRecruiters: [jobs.smartrecruiters.com/sgs](https://jobs.smartrecruiters.com/sgs) | 1 | senior 1 | it 1 | 1/1 ≤90 d |
| Vodafone | Milan | careers site (sitemap + JobPosting): [jobs.vodafone.com](https://jobs.vodafone.com/) | 1 | responsable/manager 1 | en 1 | 0/1 ≤90 d |
| Vontobel | Milano | Workday: [vontobel.wd3.myworkdayjobs.com/Vontobel_External_Career](https://vontobel.wd3.myworkdayjobs.com/Vontobel_External_Career) | 1 | sin marcador (mid probable) 1 | n/d (muestra: en 2, de 1) | sin fechas |
| Willis Towers Watson | Milan | careers site (sitemap + JobPosting): [careers.wtwco.com](https://careers.wtwco.com/) | 1 | sin marcador (mid probable) 1 | it 1 | 1/1 ≤90 d |

### 2.11 Vacantes Workday sin país atribuible

Ofertas encontradas dentro del filtro de países objetivo del propio Workday cuyo texto de localización es «N Locations» (no se ve el país). Se suman a las cifras del lead, no a las tablas por país.

| Empresa | Tablero | Vacantes sin país | Países con ofertas según la faceta |
|---|---|---:|---|
| Accenture | Workday: [accenture.wd103.myworkdayjobs.com/AccentureCareers](https://accenture.wd103.myworkdayjobs.com/AccentureCareers) | 35 | Belgium 77, France 198, Germany 255, Ireland 106, Italy 167, Luxembourg 14, Netherlands 140, Portugal 118, Spain 314, Switzerland 11 |
| Acciona | Workday: [acciona.wd3.myworkdayjobs.com/ACCIONA_Employment_Channel](https://acciona.wd3.myworkdayjobs.com/ACCIONA_Employment_Channel) | 2 | Spain 220, Netherlands 5, Portugal 4, Italy 3, France 2 |
| Air Liquide | Workday: [airliquidehr.wd3.myworkdayjobs.com/AirLiquideExternalCareer](https://airliquidehr.wd3.myworkdayjobs.com/AirLiquideExternalCareer) | 2 | Belgium 14, France 238, Germany 56, Ireland 6, Italy 50, Netherlands 12, Portugal 34, Spain 22, Switzerland 12 |
| Apex Group | Workday: [theapexgroup.wd3.myworkdayjobs.com/apexgroupcareers](https://theapexgroup.wd3.myworkdayjobs.com/apexgroupcareers) | 1 | France 4, Germany 1, Ireland 8, Luxembourg 36, Netherlands 7, Portugal 4, Spain 17 |
| Ayvens | Workday: [ayvens.wd3.myworkdayjobs.com/AyvensCareers](https://ayvens.wd3.myworkdayjobs.com/AyvensCareers) | 1 | Belgium 9, France 25, Germany 38, Ireland 6, Italy 45, Luxembourg 5, Netherlands 24, Portugal 1, Spain 4 |
| Banco Santander | Workday: [santander.wd3.myworkdayjobs.com/SantanderCareers](https://santander.wd3.myworkdayjobs.com/SantanderCareers) | 2 | France 1, Germany 99, Italy 3, Netherlands 4, Portugal 14, Spain 73, Switzerland 4 |
| Barceló | Workday: [barcelo.wd3.myworkdayjobs.com/Barcelo_Careers](https://barcelo.wd3.myworkdayjobs.com/Barcelo_Careers) | 1 | France 2, Germany 1, Portugal 7, Spain 452 |
| Covestro | Workday: [covestro.wd3.myworkdayjobs.com/cov_external](https://covestro.wd3.myworkdayjobs.com/cov_external) | 1 | Germany 33, Italy 7, Belgium 5, Spain 5, France 1, Netherlands 1 |
| Debeka | Workday: [debeka.wd3.myworkdayjobs.com/Karriere](https://debeka.wd3.myworkdayjobs.com/Karriere) | 7 | Germany 844 |
| Eiffage | Workday: [eiffage.wd3.myworkdayjobs.com/Eiffage_Careers](https://eiffage.wd3.myworkdayjobs.com/Eiffage_Careers) | 17 | France 1990, Germany 1, Portugal 3 |
| Evonik | Workday: [evonik.wd3.myworkdayjobs.com/External_Careers](https://evonik.wd3.myworkdayjobs.com/External_Careers) | 3 | Germany 137, France 6, Belgium 5, Spain 2, Netherlands 2, Luxembourg 1 |
| Ferrovial | Workday: [ferrovial.wd3.myworkdayjobs.com/Ferrovial_Career_Site](https://ferrovial.wd3.myworkdayjobs.com/Ferrovial_Career_Site) | 1 | France 1, Portugal 3, Spain 100 |
| Ipsen | Workday: [ipsen.wd103.myworkdayjobs.com/Ipsen_Careers](https://ipsen.wd103.myworkdayjobs.com/Ipsen_Careers) | 2 | Belgium 1, France 83, Germany 7, Ireland 5, Netherlands 1, Spain 1, Switzerland 1 |
| Leonardo | Workday: [leonardocompany.wd3.myworkdayjobs.com/LeonardoCareerSite](https://leonardocompany.wd3.myworkdayjobs.com/LeonardoCareerSite) | 3 | Germany 26, Italy 389, Spain 1 |
| Logitech | Workday: [logitech.wd5.myworkdayjobs.com/Logitech](https://logitech.wd5.myworkdayjobs.com/Logitech) | 3 | France 1, Germany 5, Ireland 16, Italy 1, Netherlands 7, Spain 1, Switzerland 12 |
| Mango | Workday: [mango.wd3.myworkdayjobs.com/Mango_Work_Your_Passion](https://mango.wd3.myworkdayjobs.com/Mango_Work_Your_Passion) | 7 | Belgium 76, France 338, Germany 72, Ireland 10, Italy 93, Luxembourg 7, Netherlands 36, Portugal 26, Spain 532, Switzerland 13 |
| Michelin | Workday: [michelinhr.wd3.myworkdayjobs.com/Michelin](https://michelinhr.wd3.myworkdayjobs.com/Michelin) | 1 | France 241, Germany 175, Spain 18, Italy 3 |
| Northern Trust | Workday: [ntrs.wd1.myworkdayjobs.com/northerntrust](https://ntrs.wd1.myworkdayjobs.com/northerntrust) | 2 | Ireland 76, Luxembourg 11, Netherlands 1 |
| Novartis | Workday: [novartis.wd3.myworkdayjobs.com/Novartis_Careers](https://novartis.wd3.myworkdayjobs.com/Novartis_Careers) | 2 | Belgium 15, France 9, Germany 5, Ireland 15, Italy 10, Netherlands 9, Portugal 1, Spain 27, Switzerland 38 |
| Pernod Ricard | Workday: [pernodricard.wd3.myworkdayjobs.com/pernod-ricard](https://pernodricard.wd3.myworkdayjobs.com/pernod-ricard) | 2 | Belgium 5, France 158, Germany 2, Ireland 6, Spain 7 |
| Pierre Fabre | Workday: [pierrefabre.wd3.myworkdayjobs.com/External_Career_Site](https://pierrefabre.wd3.myworkdayjobs.com/External_Career_Site) | 5 | Belgium 11, France 120, Germany 9, Italy 1, Spain 2 |
| Pluxee | Workday: [pluxee.wd3.myworkdayjobs.com/Pluxee_Career_Site](https://pluxee.wd3.myworkdayjobs.com/Pluxee_Career_Site) | 10 | Belgium 9, France 57, Germany 4, Italy 1, Luxembourg 2, Portugal 5, Spain 13 |
| Procter & Gamble | Workday: [pg.wd5.myworkdayjobs.com/1000](https://pg.wd5.myworkdayjobs.com/1000) | 2 | Belgium 14, France 34, Germany 43, Italy 10, Netherlands 6, Portugal 2, Spain 25, Switzerland 2 |
| Prysmian | Workday: [prysmiangroup.wd3.myworkdayjobs.com/Careers](https://prysmiangroup.wd3.myworkdayjobs.com/Careers) | 1 | France 41, Germany 38, Italy 54, Netherlands 8, Portugal 2, Spain 7 |
| Sanofi | Workday: [sanofi.wd3.myworkdayjobs.com/SanofiCareers](https://sanofi.wd3.myworkdayjobs.com/SanofiCareers) | 1 | Belgium 10, France 121, Germany 50, Ireland 9, Italy 10, Netherlands 3, Spain 27, Switzerland 2 |
| Sartorius | Workday: [sartorius.wd3.myworkdayjobs.com/sartoriuscareers](https://sartorius.wd3.myworkdayjobs.com/sartoriuscareers) | 5 | Germany 62, France 15, Belgium 5, Spain 2, Ireland 2, Netherlands 2 |
| State Street | Workday: [statestreet.wd1.myworkdayjobs.com/Global](https://statestreet.wd1.myworkdayjobs.com/Global) | 1 | Ireland 49, Germany 11, Luxembourg 8, Italy 3, Netherlands 2, France 1 |
| Swiss Life | Workday: [swisslife.wd3.myworkdayjobs.com/livit-ag-career-stellenboerse](https://swisslife.wd3.myworkdayjobs.com/livit-ag-career-stellenboerse) | 1 | Switzerland 43 |
| Valeo | Workday: [valeo.wd3.myworkdayjobs.com/valeo_jobs](https://valeo.wd3.myworkdayjobs.com/valeo_jobs) | 16 | France 132, Germany 58, Ireland 7, Italy 3, Spain 45 |
| Zentiva | Workday: [zentiva.wd3.myworkdayjobs.com/Zentiva](https://zentiva.wd3.myworkdayjobs.com/Zentiva) | 1 | Germany 10, Italy 6, France 5, Switzerland 2, Spain 1 |

## 3. Empleadores sin tablero legible o sin vacantes relevantes (fuera del fichero de leads)

Un candidato sin tablero verificado queda fuera del fichero. Agrupo por motivo; cuando una cifra aparece entre corchetes es lo que sí leí.

### 3.1 Tablero verificado, pero sin vacantes de finanzas/administración en los diez países (o ninguna con fecha reciente) (144)

AB InBev [Greenhouse abinbev: 60 ofertas; Workday abinbev/JPN: 4 ofertas]; Abanca [sitio empleo.abanca.com: 1 URL de ofertas]; ACS [Workday acs/ACSCareers: 71 ofertas]; Action [Greenhouse action: 10 ofertas]; Agicap [Lever agicap: 28 ofertas]; Amadeus [Workday amadeus/jobs: 115 ofertas]; Anchorage Digital [Lever anchorage: 21 ofertas]; Applus [Recruitee applus: 2 ofertas; Workday applus/applus_careers: 3 ofertas]; Athora [Recruitee athora: 19 ofertas; Workday athora/athora-careers: 10 ofertas]; Atlantia Mundys [sitio jobs.mundys.com: 2 URL de ofertas]; Atos [sitio jobs.atos.net: 1002 URL de ofertas]; Auchan Portugal [Workday auchanportugal/auchan-retail: 235 ofertas]; Aviva [Workday aviva/External: 134 ofertas]; Banco BPI [sitio careers.bancobpi.pt: 12 URL de ofertas]; Bank for International Settlements [Lever bis: 9 ofertas; Workday bis/External: 2 ofertas]; Bank of Ireland [sitio careers.bankofireland.com: 7 URL de ofertas]; BDO [Workday bdo/BDO: 262 ofertas]; Binance [Lever binance: 302 ofertas]; Bitpanda [Greenhouse bitpanda: 24 ofertas]; Bitvavo [Ashby bitvavo: 11 ofertas]; Blip [Greenhouse blip: 2 ofertas]; Brisa [sitio recrutamento.brisa.pt: 31 URL de ofertas]; Brown & Brown [SmartRecruiters brownbrown: 2 ofertas; Workday bbinsurance/Careers: 294 ofertas]; Caixa Geral de Depositos [sitio recrutamento.cgd.pt: 14 URL de ofertas]; Capchase [Ashby capchase: 6 ofertas]; Cisco [Workday cisco/Cisco_Careers: 1365 ofertas; sitio careers.cisco.com: 2566 URL de ofertas]; Conduent [sitio careers.conduent.com: 471 URL de ofertas]; Crowe [Teamtailor crowe: 4 ofertas; sitio careers.crowe.com: 173 URL de ofertas]; DATEV [Workday datev/Datev_Careers: 54 ofertas]; DHL Group [sitio careers.dhl.com: 28870 URL de ofertas]; Dia [Personio dia: 3 ofertas]; DKV [sitio empleo.dkv.es: 1 URL de ofertas]; Dormakaba [sitio jobs.dormakaba.com: 343 URL de ofertas]; Eataly [SmartRecruiters eataly: 247 ofertas]; Esselunga [sitio esselungajob.it: 36 URL de ofertas]; EssilorLuxottica [SmartRecruiters essilorluxottica: 7 ofertas; sitio jobs.essilorluxottica.com: 993 URL de ofertas]; Exolum [sitio jobs.exolum.com: 10 URL de ofertas]; Factorial [sitio careers.factorialhr.com: 4 URL de ofertas]; Feedzai [Greenhouse feedzai: 25 ofertas]; Ferrari [sitio jobs.ferrari.com: 26 URL de ofertas]; Fiat Chrysler Automobiles [Workday fca/FCA_Careers: 15 ofertas]; Finanzguru [Personio finanzguru: 4 ofertas]; Fineco [Recruitee fineco: 4 ofertas]; Flix [Greenhouse flix: 147 ofertas]; Franklin Templeton [Workday franklintempleton/Jobs-Clarion: 12 ofertas; sitio careers.franklintempleton.com: 212 URL de ofertas]; Fresenius Medical Care [Workday freseniusmedicalcare/fme: 2000 ofertas; sitio jobs.freseniusmedicalcare.com: 3335 URL de ofertas]; Genpact [Workday genpact/External_Careers: 1896 ofertas]; Georg Fischer [Workday georgfischer/GeorgFischer_Careers: 330 ofertas; sitio georgfischer.wd103.myworkdayjobs.com: 100 URL de ofertas]; Gestamp [sitio jobs.gestamp.com: 93 URL de ofertas]; Glencore [Workday glencore/astronenergy: 7 ofertas]; Google [Recruitee google: 1 ofertas]; Greencore [sitio www.careers.greencore.com: 119 URL de ofertas]; Helsana [sitio careers.helsana.ch: 64 URL de ofertas]; Holcim [Teamtailor holcim: 50 ofertas]; Iberdrola [Workday iberdrola/Iberdrola: 205 ofertas]; ICO Instituto de Credito Oficial [Workday ico/ICO: 4 ofertas]; Intel [Workday intel/External: 608 ofertas]; Italgas [sitio carriere.italgas.it: 91 URL de ofertas]; Janus Henderson [sitio jobs.janushenderson.com: 114 URL de ofertas]; Jerónimo Martins [sitio careers.jeronimomartins.com: 1742 URL de ofertas]; Jerónimo Martins Finance [sitio careers.jeronimomartins.com: 1742 URL de ofertas]; KBC [Personio kbc: 3 ofertas]; Kellanova [sitio jobs.kellanova.com: 121 URL de ofertas]; KPMG Luxembourg [sitio careers.kpmg.lu: 40 URL de ofertas]; Kraken [Ashby kraken.com: 88 ofertas]; LCH [Workday lseg/Careers: 661 ofertas]; Legal & General [sitio careers.legalandgeneral.com: 66 URL de ofertas]; Lendable [Ashby lendable: 70 ofertas; sitio careers.lendable.com: 70 URL de ofertas]; Línea Directa [SmartRecruiters lineadirecta: 2 ofertas]; Lloyds Banking Group [Workday lbg/LBG_Careers: 81 ofertas]; Luzerner Kantonalbank [sitio careers.lukb.ch: 22 URL de ofertas]; LVMH [SmartRecruiters lvmh: 4 ofertas]; Man Group [Greenhouse mangroup: 54 ofertas]; Mars [sitio careers.mars.com: 911 URL de ofertas]; Mastercard [Workday mastercard/CorporateCareers: 1056 ofertas; sitio careers.mastercard.com: 961 URL de ofertas]; Mastercard Dublin [sitio careers.mastercard.com: 961 URL de ofertas]; Mastercard Waterloo [sitio careers.mastercard.com: 961 URL de ofertas]; Mediaset Espana [sitio jobs.mediaset.es: 1 URL de ofertas]; Memo Bank [Teamtailor memobank: 3 ofertas; sitio careers.memo.bank: 3 URL de ofertas]; Migros [sitio jobs.migros.ch: 257 URL de ofertas]; Moneris Pt [Workday moneris/Moneris: 43 ofertas]; Monzo [Greenhouse monzo: 67 ofertas]; NIBC [Workday nibcatwork/External: 4 ofertas]; NOS [sitio recrutamento.nos.pt: 17 URL de ofertas]; NOS Comunicacoes [sitio recrutamento.nos.pt: 17 URL de ofertas]; NXP [Workday nxp/careers: 795 ofertas]; Orange [Workday orange/Orange_Career: 2 ofertas]; Paack [Teamtailor paack: 12 ofertas; sitio careers.paack.co: 10 URL de ofertas]; Payconiq [Recruitee payconiq: 3 ofertas]; Pelayo [sitio trabajaenpelayo.grupopelayo.com: 3 URL de ofertas]; Penta [Personio penta: 2 ofertas]; Perk TravelPerk [Ashby perk: 128 ofertas]; Picnic [SmartRecruiters picnic: 2 ofertas]; Pigment [Lever pigment: 139 ofertas]; Pliant [Ashby pliant: 39 ofertas]; Proximus [sitio jobs.proximus.com: 452 URL de ofertas]; Proximus Group [sitio jobs.proximus.com: 452 URL de ofertas]; Prudential [Workday prudential/prudential: 491 ofertas]; Raiffeisen Schweiz [Workday raiffeisen/job-raiffeisen: 1 ofertas]; Raisin [Greenhouse raisin: 36 ofertas]; Rakuten Europe Bank [Workday rakuten/RakutenAsia: 29 ofertas]; RBC Investor Services [Workday rbc/RBCEARLYTALENT1: 35 ofertas]; Reckitt [sitio careers.reckitt.com: 425 URL de ofertas]; Remote.com [Greenhouse remote: 2 ofertas]; Renfe [sitio empleo.renfe.com: 3 URL de ofertas]; Rewe Group [sitio jobs.rewe-group.com: 2530 URL de ofertas]; Robeco [Workday robeco/robecoexternalcareers: 10 ofertas]; RSM [Workday rsm/RSMCareers: 724 ofertas]; Sacyr [Teamtailor sacyr: 100 ofertas]; Scalapay [Greenhouse scalapaysrl: 9 ofertas]; Schaeffler [sitio jobs.schaeffler.com: 661 URL de ofertas]; Schneider Electric [sitio careers.se.com: 3609 URL de ofertas]; Schwarz Gruppe [sitio jobs.schwarz: 2 URL de ofertas]; Servier [sitio jobs.servier.com: 262 URL de ofertas]; SES [Greenhouse ses: 1 ofertas]; Shell [Workday shell/ShellCareers: 138 ofertas]; Shine [Teamtailor shine: 70 ofertas]; Signify [sitio careers.signify.com: 263 URL de ofertas]; Sodexo [SmartRecruiters sodexo: 162 ofertas]; Solaria [sitio career.solariaenergia.com: 12 URL de ofertas]; Spendesk [sitio career.spendesk.com: 21 URL de ofertas]; Stada [sitio jobs.stada.com: 153 URL de ofertas]; Stellantis [Workday stellantis/External_Career_Site_ID01: 25 ofertas]; Swile [Lever swile: 28 ofertas]; Swisscom [Recruitee swisscom: 14 ofertas]; Sword Health [Greenhouse swordhealth: 40 ofertas]; Teleperformance [Recruitee teleperformance: 20 ofertas; Workday teleperformance/allianceone: 20 ofertas]; Terna [sitio jobs.terna.it: 8 URL de ofertas]; Tikehau Capital [SmartRecruiters tikehaucapital: 1 ofertas]; Tines [Greenhouse tines: 24 ofertas]; TomTom [Lever tomtom: 21 ofertas]; Trade Republic [Greenhouse traderepublic: 1 ofertas]; Triodos Bank [sitio careers.triodos.com: 18 URL de ofertas]; Valiant [sitio careers.valiant.ch: 25 URL de ofertas]; Visa [Workday visa/Visa: 781 ofertas]; Vitol [SmartRecruiters vitol: 30 ofertas]; Vivid Money [Ashby vivid: 2 ofertas]; Volkswagen Financial Services [Teamtailor volkswagenfinancialservices: 26 ofertas]; Wallapop [Greenhouse wallapop: 5 ofertas]; Wise [Greenhouse wise: 15 ofertas; sitio wise.jobs: 398 URL de ofertas]; Wise Luxembourg [sitio wise.jobs: 398 URL de ofertas]; Workday [Workday workday/Workday: 379 ofertas]; Zendesk [Workday zendesk/zendesk: 127 ofertas]; Zopa [Lever zopa: 29 ofertas]

### 3.2 Tablero verificado; las vacantes relevantes son todas anteriores a 2026-07-08 (9)

Bank Van Breda; bol.com; Mediaset MFE; Rocket Internet; Royal HaskoningDHV; Saint-Gobain; Stripe; Typeform; Van Lanschot Kempen

### 3.3 Sitio de empleo con sitemap, pero las fichas no publican JobPosting (país y fecha no verificables) (73)

A2A [www.gruppoa2a.it: 5 URL, sin JobPosting legible]; Adyen Amsterdam [careers.adyen.com: 5 URL, sin JobPosting legible]; Alphabet [werkenbij.alphabet.com: 1 URL, sin JobPosting legible]; APG [werkenbij.apg.nl: 20 URL, sin JobPosting legible]; Arvato [career.arvato.com: 1 URL, sin JobPosting legible]; Atradius [careers.atradius.com: 1 URL, sin JobPosting legible]; Axa Investment Managers [www.bnpparibas-am.com: 6 URL, sin JobPosting legible]; Banque et Caisse d'Epargne [www.spuerkeess.lu: 53 URL, sin JobPosting legible]; Banque Pictet [www.pictet.com: 10 URL, sin JobPosting legible]; BASF [karriere.basf.com: 5 URL, sin JobPosting legible]; Billin [careers.billin.net: 3 URL, sin JobPosting legible]; BMW Financial Services [jobs.bmwgroup.com: 997 URL, la ficha no expone título ni ubicación estructurados]; BMW Group [jobs.bmwgroup.com: 995 URL, la ficha no expone título ni ubicación estructurados]; BNY Mellon Luxembourg [www.bny.com: 52 URL, sin JobPosting legible]; Bolt [bolt.eu: 223 URL, sin JobPosting legible]; Carl Zeiss [zeiss.com: 4 URL, sin JobPosting legible]; CLH [exolum.com: 2 URL, sin JobPosting legible]; Cognizant [careers.cognizant.com: 24710 URL, sin JobPosting legible]; Colruyt [jobs.colruytgroup.com: 10124 URL, sin JobPosting legible]; Commerzbank [www.commerzbank.de: 3 URL, sin JobPosting legible]; Concentrix [jobs.concentrix.com: 51 URL, sin JobPosting legible]; Danone [careers.danone.com: 686 URL, sin JobPosting legible]; Deutsche Telekom [careers.telekom.com: 2 URL, sin JobPosting legible]; Die Mobiliar [jobs.mobiliar.ch: 67 URL, la ficha no expone título ni ubicación estructurados]; Elia [jobs.elia.be: 1 URL, sin JobPosting legible]; Enel [jobs.enel.com: 220 URL, sin JobPosting legible]; Engie Belgium [corporate.engie.be: 56 URL, sin JobPosting legible]; Eurofiber [careers.eurofiber.com: 2 URL, sin JobPosting legible]; European Central Bank [talent.ecb.europa.eu: 15 URL, sin JobPosting legible]; Findomestic [www.infofindomestic.it: 1 URL, sin JobPosting legible]; Foyer [groupe.foyer.lu: 6 URL, sin JobPosting legible]; Galp [jobs.galp.com: 30 URL, la ficha no expone título ni ubicación estructurados]; Galp Energia [jobs.galp.com: 30 URL, la ficha no expone título ni ubicación estructurados]; Geberit [jobs.geberit.com: 171 URL, la ficha no expone título ni ubicación estructurados]; Generali Tranquilidade [www.generalitranquilidade.pt: 2 URL, sin JobPosting legible]; Hilti [careers.hilti.group: 17042 URL, sin JobPosting legible]; IBM [careers.ibm.com: 5 URL, sin JobPosting legible]; Intesa Sanpaolo [group.intesasanpaolo.com: 15 URL, sin JobPosting legible]; Intesa Sanpaolo Group Services [group.intesasanpaolo.com: 15 URL, sin JobPosting legible]; Johnson & Johnson [careers.jnj.com: 25355 URL, sin JobPosting legible]; Kroll [careers.kroll.com: 364 URL, sin JobPosting legible]; L'Oréal [career.loreal.com: 6137 URL, la ficha no expone título ni ubicación estructurados]; Landesbank Baden-Wurttemberg [karriere.lbbw.de: 99 URL, sin JobPosting legible]; Legrand [www.legrand.com: 2 URL, sin JobPosting legible]; Linde [www.lindecareers.com: 2 URL, sin JobPosting legible]; Mediamarkt Saturn [careers.mediamarktsaturn.com: 1734 URL, la ficha no expone título ni ubicación estructurados]; Mobiliar [jobs.mobiliar.ch: 67 URL, la ficha no expone título ni ubicación estructurados]; Neinor Homes [www.trabajando.es: 216 URL, sin JobPosting legible]; Novo Nordisk [careers.novonordisk.com: 421 URL, sin JobPosting legible]; PGGM [www.werkenbijpggm.nl: 2 URL, sin JobPosting legible]; PostFinance [jobs.postfinance.ch: 296 URL, la ficha no expone título ni ubicación estructurados]; Ryanair [careers.ryanair.com: 499 URL, la ficha no expone título ni ubicación estructurados]; Ryanair Labs [careers.ryanair.com: 499 URL, la ficha no expone título ni ubicación estructurados]; Santander Totta [www.santander.pt: 4 URL, sin JobPosting legible]; SAP [jobs.sap.com: 100 URL, sin JobPosting legible]; SGG Group [iqeq.com: 82 URL, sin JobPosting legible]; Siemens [jobs.siemens.com: 20 URL, sin JobPosting legible]; Siemens Energy [jobs.siemens-energy.com: 687 URL, sin JobPosting legible]; Swiss National Bank [careers.snb.ch: 16 URL, la ficha no expone título ni ubicación estructurados]; Taxfix [taxfix.de: 1 URL, sin JobPosting legible]; Tecan [careers.tecan.com: 35 URL, la ficha no expone título ni ubicación estructurados]; Telenet [www2.telenet.be: 73 URL, sin JobPosting legible]; TenneT [careers.tennet.eu: 1080 URL, sin JobPosting legible]; TotalEnergies [jobs.totalenergies.com: 6114 URL, sin JobPosting legible]; Union Investment [karriere.union-investment.de: 3 URL, sin JobPosting legible]; UnipolSai [www.unipol.com: 33 URL, sin JobPosting legible]; Univé [vacaturesbijunive.nl: 78 URL, sin JobPosting legible]; Veolia [jobs.veolia.com: 4485 URL, sin JobPosting legible]; Vinted [careers.vinted.com: 145 URL, sin JobPosting legible]; Vonovia [jobs.vonovia.de: 581 URL, la ficha no expone título ni ubicación estructurados]; Wolters Kluwer [careers.wolterskluwer.com: 68 URL, sin JobPosting legible]; Worldline [jobs.worldline.com: 304 URL, sin JobPosting legible]; Zalando Finance [careers.zalando.com: 177 URL, sin JobPosting legible]

### 3.4 Tablero encontrado cuya identidad no pude confirmar (colisión de slug) (19)

Abante [Personio abante: no name evidence]; Ageas [Personio ageas: no name evidence]; Billie [Ashby billie: no name evidence]; BNP Paribas Fortis [Teamtailor fortis: no name evidence]; BP [Recruitee bp: board name 'Black Propeller']; CSS Versicherung [Greenhouse css: board name 'CloudKitchens']; De Nederlandsche Bank [Lever dnb: no name evidence]; Dublin Airport DAA [Personio daa: no name evidence]; Indexa Capital [Personio talento-indexa-capital: no name evidence]; Intercom [Greenhouse intercom: board name 'Fin']; Meta [Recruitee meta: board name 'Addis Ababa University']; Millennium bcp [Greenhouse bcp: board name 'Banyan Capital Partners']; Oliver Wyman [Lever oliverwyman: no name evidence]; Payhawk [Personio payhawk: no name evidence]; Personio [Personio personio: no name evidence]; Sika [Personio sika: no name evidence]; Swiss Post [Ashby post: no name evidence]; Tata Consultancy Services [Greenhouse tcs: board name 'Thornbury Community Services']; Wüstenrot [Recruitee wuestenrot: board name 'Johannes Reimer']

### 3.5 Web corporativa no legible con el dominio probado (sin respuesta, 403/418 o dominio mal acertado por mí) (132)

ABB; Adeslas SegurCaixa; Adidas; AIB; Air Europa; Air France-KLM; Airbus; Aldi; Allied Irish Banks; Altice Portugal; Alvarez & Marsal; ArcelorMittal; Arthur J. Gallagher; Arval; Ascendi; Autostrade per l'Italia; Bâloise Bank; Banca Mediolanum; Banca Sella; Banco Carregosa; Banco de Portugal; Bankinter; Banque de France; Barilla; Barry Callebaut; BGL BNP Paribas; Bitstamp; Bnext; BNP Paribas; BNP Paribas Personal Finance; BNP Paribas Securities Services; Bord Gais; Bouygues; Cajamar; Carmignac; Catalana Occidente; Cellnex; Ceratizit; Colas; Condor; Continente Modelo; Correos; Covea; Credit Suisse; CSSF; Damm; DWS; Edeka; Edmond de Rothschild; Edmond de Rothschild Asset Management; EFG International; Eir; Eroski; Euroclear; Eurowings; EVO Banco; Faurecia Forvia; FBD Insurance; FCC; Fexco; Fidelity International; Globalia; Hapag-Lloyd; HDI; Heineken; Heineken Finance; Helvetia; Hera; IAG; Ibercaja; Iberia; Iberostar; Intertrust Corporate Services; Inversis; Irish Residential; Julius Baer Group; KLM; Lano; Liberty Seguros; Lidl Nederland; Lombard International; Louis Dreyfus; Lufthansa; Lufthansa Group Business Services; Lydia Sumeria; MasOrange; Mediterranean Shipping Company; Meliá Hotels International; Mercadona; Mercedes Benz Portugal; Mercedes-Benz; Mercedes-Benz Financial Services; Mercuria; Mobile.de; Moeve (Cepsa); Mooney; MSC; Natixis; Nestle; NH Hotel Group; NN Investment Partners; Notenstein La Roche; Onfido; Oracle; Orsted; Papaya Global; Permanent TSB; PwC Luxembourg; Rabobank; Revolut; Safran; Sage; Sandoz; Santalucía; Santander Asset Management; Santander Consumer Finance; Sareb; Schiphol; Societe Generale Luxembourg; Societe Generale Securities Services; Sofina; Sonae; Standard Chartered; Sygnum; UBS; UBS Luxembourg; Vertex; Vodafone Deutschland; Vodafone Portugal; Zalando Italia; Zurich Dublin; Zurich Insurance

### 3.6 Web legible pero sin ATS soportado ni sitemap de ofertas detectables (portal propio con login, SPA sin sitemap o ATS no soportado) (334)

a.s.r.; Aareal Bank; Abertis; Aegon; Aegon Asset Management; Aena; Aer Lingus; Ageas Portugal; Ageas Seguros; Agos; Allfunds; Allianz Direct; Allianz Italia; Allianz Portugal; Alstom; Amazon Ireland; Amazon Luxembourg; American Express; Amplifon; Amundi; Amundi Asset Management; Amundi Technology; An Post; Andbank; Argenta; Atento; Atresmedia; Audi; Auren; AXA Italia; Axa Switzerland; Axel Springer; BaFin; Banca d'Italia; Banca Finint; Banca Generali; Banca Ifis; Banca Popolare di Sondrio; Banca Profilo; Banco BPM; Banco CTT; Banco Invest; Banco Sabadell; Bancontact; Bank Vontobel; Banque Cantonale de Geneve; Banque de Luxembourg; Banque Internationale a Luxembourg; Basler Kantonalbank; Beiersdorf; Bending Spoons; Berenberg; Bertelsmann; Bitpanda GmbH; BME; BNP Paribas Portugal; BNY; Booking.com; BPCE; BPER Banca; BPER Group Services; Brembo; Bundesbank; CACEIS; Candriam; Cargolux; Cargolux Airlines; Carne Group; Carrefour; Cashfree; Cassa Depositi e Prestiti; Cattolica Assicurazioni; Cecabank; Central Bank of Ireland; CESCE; Cetelem; Check24; Checkout.com; Chubb; CIE Automotive; Citco; Citco Luxembourg; Citi; Citi Ireland; Clearstream; Cleverti; CNMV; CNP Assurances; Cobee; Coca-Cola; Cofidis; Cofidis Portugal; Colonial; Compass Banca; Conad; Consorsbank; Corticeira Amorim; CPH Chemie; Credem; Credendo; Crédit Agricole; Crédit Agricole CIB; Credit Agricole Italia; Credit Mutuel; Credit Union; Crédito Agrícola; CRH; Critical Software; Crypto.com; CTT; DAF; Dalata; Davy; Deel; Defacto; Delen; Deloitte; Delta Cafes; Desigual; Deutsche Bank Dublin; DZ Bank; EBA; Edenred; EDF; Edison; EDP; EDP Renovaveis; Elecnor; Endesa; Engie Spain; Eni; Eni Portugal; Ergo; ESMA; Euler Hermes Allianz Trade; Eurazeo; European Investment Bank; European Investment Fund; European Stability Mechanism; Exact; EXL; Fastweb; Fenergo; Fenergo Dublin; Ferrero; Ferrovie dello Stato; Fidelidade; Fidelidade Seguros; Fidelity Investments Ireland; Finizens; FINMA; Fintonic; Flutter; Flywire; Fonds de Compensation; Foundever; Fresenius; FTI Consulting; Fugro; GBL; Generali; Generali Deutschland; Generali Italia; Generali Switzerland; Goldman Sachs; Goodbody; Gothaer; Grifols; Groupama; Helaba; Henkel; Holaluz; HSBC; HubSpot; Hype; Hypothekarbank Lenzburg; Hypovereinsbank; illimity; Inbestme; Inditex; ING Diba; Irish Life; Iveco; J. Safra Sarasin; JPMorgan Chase; JTC; Kantox; KBC Bank Ireland; KBC Group; Kering; KfW; Kingspan; Klarna; Knab; KPMG; Kutxabank; La Banque Postale; La Francaise; Lazard; Leaseplan; Libeo; Lidl; Logista; Lufthansa Technik; Lusitania Seguros; Luxair; Mahou San Miguel; Mambu; Mapfre Portugal; Mediobanca; Menzis; MEO Altice Portugal; Mercedes-Benz.io; Mercer; Mercer Ireland; Mercer Portugal; Merlin Properties; Metrovacesa; Microsoft; Mirabaud; Mondelez; Mondragon; Moneyfarm; Moneyfarm Italia; Monte dei Paschi di Siena; Montepio; Morgan Stanley; Mutua Madrileña; MyInvestor; National Bank of Belgium; Natixis Investment Managers; Natixis Portugal; Naturgy; NatWest; Navigator; Nespresso; Nexi; Nexi Group; Nexi Luxembourg; Nexi Payments; Nissan; Novo Banco; Ocidental Seguros; Openbank; Orange Belgium; Ostrum; Otto Group; OutSystems; Partena; Pax; PayPal Ireland; PayPal Luxembourg; Paysafe; Philip Morris International; Philips Finance; Pictet; Pingo Doce; Porsche; Post Luxembourg; Poste Italiane; Poste Vita; Prisa; Prosegur; Quipu; R+V Versicherung; Raiffeisen Luxembourg; Reale Mutua; REN Redes Energeticas; Renault Group; Renta 4; Rippling; RSA Insurance; Saipem; Salesforce; Sanitas Switzerland; Santander Portugal; Schindler; Schroders; Scor; Seat Cupra; Self Bank; Semapa; SIBS; Siemens Gamesa; Singular Bank; Sky Italia; Skype Luxembourg; Smurfit Westrock; Snam; Spuerkeess BCEE; Starling Bank; Stripe Dublin; Stuart; Suez; Sumol Compal; Super Bock; SWICA; Syngenta; Talanx; Talkdesk; TAP Air Portugal; Tchibo; Telefonica Deutschland; Tenaris; Teva; Three Ireland; TIM; Tink; TMF Group; Trenitalia; Tressis; Ulster Bank; Unbabel; Unicaja Banco; Unicre; UniCredit; Union Bancaire Privee; United Internet; Vaudoise; Verti; VGZ; Visabeira; Visana; Vodafone Ireland; Volkswagen; Wind Tre; WNS; Ypsomed; Ziggo VodafoneZiggo; Zomato; Zürcher Kantonalbank; Zurich Ireland; Zurich Italia; Zurich Switzerland

### 3.7 Empresas de trabajo temporal/selección (vacantes de terceros) (9)

Adecco; Cpl; Hays; ManpowerGroup; Page Group; Randstad; Randstad Holding; Randstad Portugal; Yacht Club

### 3.8 Mismo tablero que otra empresa ya contada (26)

Adecco Group (= Adecco); Adecco Portugal (= Adecco); Ahold Delhaize Finance (= Ahold Delhaize); Allianz Global Investors (= Allianz); Allianz Suisse (= Allianz); Allianz Technology (= Allianz); Aon Ireland (= Aon); ASN Bank (= Volksbank); AXA Belgium (= AXA); Bank of America Dublin (= Bank of America); Elsevier (= RELX); Ergo Versicherung (= Munich Re); Euronext Italia (= Euronext); EY Luxembourg (= EY); Glovo Italia (= Glovo); Kuehne Nagel Schindellegi (= Kuehne+Nagel); Mapfre Re (= Mapfre); Marsh Ireland (= Marsh McLennan); Northern Trust Luxembourg (= Northern Trust); Santander Consumer Bank (= Banco Santander); Satispay Milano (= Satispay); Tikkie ABN AMRO Services (= ABN AMRO); Unilever Rotterdam (= Unilever); Vattenfall Europe (= Vattenfall); Willis Towers Watson Ireland (= Willis Towers Watson); Zilveren Kruis (= Achmea)

### 3.9 Casos que pidió explícitamente el encargo

- **Big Four**: Deloitte España (empleo.es.deloitte.com), EY (careers.ey.com), PwC (Workday `pwc`) y Deloitte Luxemburgo (jobs.deloitte.lu) están en el catálogo cuando tienen vacantes relevantes (ver tablas). **KPMG**: `kpmg.com/es/es/home/careers.html` redirigió a `kpmg.com/es/es/careers.html`, que devolvió 404 y no enlazaba a ningún ATS detectable; no localicé tablero legible, queda fuera.
- **Banco de España**: incluido como RSS (arriba). **CNMV**: `cnmv.es/portal/Empleo/Empleo.aspx` devolvió 403 desde el entorno; solo conozco sus convocatorias por la investigación previa del repositorio (`docs/research/public-and-short-hours-2026-10.md`), sin lectura nueva. **ICO**: existe tablero Workday (`ico/ICO`), 4 ofertas el 2026-10-06 y ninguna de finanzas/administración. **CESCE**: `cesce.es/es/trabaja-con-nosotros` devolvió 404 y no encontré tablero. **BCE**: `talent.ecb.europa.eu/careers` tiene sitemap con 15 URL pero las fichas no publican JobPosting; sin país ni fecha leíbles, queda fuera.
- **Bancos españoles**: CaixaBank (`caixabankcareers.com`) sí entra. Banco Sabadell enlaza `sabadellcareers.com`, que respondió pero cuyo sitemap no listaba URL de ofertas; Bankinter, Ibercaja y Zurich España respondieron 403 a la página de empleo; Unicaja devolvió 404 en la URL probada; ninguno ofreció un ATS legible.

## 4. Títulos típicos por idioma (alimentan la plantilla del sector)

Títulos reducidos a su núcleo (sin marca de género, nivel, ciudad ni año; así «Senior Internal Auditor» y «Internal Auditor (m/f/d)» cuentan como «internal auditor») en las 2080 vacantes relevantes del catálogo, agrupados por familia de rol. Idioma = idioma del texto de la oferta cuando se detectó; si no, el idioma del propio título. Cuento **empleadores distintos** que usan cada variante (no ofertas, para que una sola empresa con muchas ofertas no domine); solo las variantes usadas por al menos dos empleadores, hasta cinco por familia, o las tres más frecuentes si ninguna llega a dos; entre paréntesis, número de empleadores.

### Inglés (745 títulos clasificados)

| Familia | Variantes frecuentes |
|---|---|
| Contabilidad | accountant (18); financial accountant (3); financial accounting (3); accounting specialist (2); accounting support specialist (2) |
| Análisis financiero / FP&A / control de gestión | financial controller (10); business controller (8); finance manager (6); financial analyst (6); controller (5) |
| Tesorería | treasury analyst (4); manager treasury (2); treasury manager (2) |
| Auditoría | internal auditor (11); internal audit manager (6); audit manager (3); internal audit (3); it auditor (3) |
| Fiscal / impuestos | tax specialist (5); tax manager (3); tax analyst (2); tax legal (2); transfer pricing manager (2) |
| Nóminas / payroll | payroll specialist (10) |
| Compras / aprovisionamiento | procurement category manager (4); procurement manager (4); procurement category (2); procurement specialist (2); purchasing (2) |
| Administración / back office | middle office analyst (2); office manager italy (2) |
| Cobros, facturación, cuentas a pagar/cobrar | accounts receivable (3); accounts payable specialist (2); accounts receivable analyst (2) |
| Operaciones bancarias y de fondos | transfer agency (3) |
| Marcadores de formación/prácticas | intern (21); internship (11); trainee (8); working student (8); graduate (4); apprentice (1) |

### Español (111 títulos clasificados)

| Familia | Variantes frecuentes |
|---|---|
| Contabilidad | técnico contable (2) |
| Análisis financiero / FP&A / control de gestión | finance controller (2) |
| Tesorería | treasury analyst (1); técnico tesoreria corporativa (1) |
| Auditoría | administrativo a de planificación de auditorías (1); auditor a (1); auditor a de energía especialista (1) |
| Fiscal / impuestos | analista fiscal industrial (1); especialista impuestos (1); finance tax (1) |
| Nóminas / payroll | p c payroll executive (1); payroll sap (1); payroll spain asesor laboral contrato temporal 6 meses inici (1) |
| Compras / aprovisionamiento | administrativo a compras-pedidos (1); clúster compras cataluña (1); dpto. compras (1) |
| Administración / back office | auxiliar administrativo a (2) |
| Marcadores de formación/prácticas | practicas (6); beca (4); intern (1); internship (1); trainee (1) |

### Francés (318 títulos clasificados)

| Familia | Variantes frecuentes |
|---|---|
| Contabilidad | comptable (4); collaborateur comptable (2); comptable clients (2); gestionnaire comptable (2); manager expertise comptable (2) |
| Análisis financiero / FP&A / control de gestión | contrôleur de gestion (7); contrôle de gestion (3); responsable contrôle de gestion (3); analyste financier (2); controleur de gestion (2) |
| Tesorería | finance treasury (1); manager manager (1); responsable administration des ventes (1) |
| Auditoría | auditeur financier (2); manager audit (2) |
| Fiscal / impuestos | fiscaliste (2) |
| Nóminas / payroll | gestionnaire de paie (4); gestionnaire paie (2) |
| Compras / aprovisionamiento | achats indirects france (1); acheteur direct (1); acquisti- base metals buyer (1) |
| Administración / back office | administratif logistique (1); administratif polyvalent (1); administratif relation client (1) |
| Cobros, facturación, cuentas a pagar/cobrar | chargé e de gestion et de recouvrement (1); processus finance (1); purchase to pay analyst (1) |
| Operaciones bancarias y de fondos | transfer agency (1) |
| Marcadores de formación/prácticas | stage (14); alternance (8); stagiaire (5); apprentice (3); apprenti (2); alternant (1) |

### Alemán (204 títulos clasificados)

| Familia | Variantes frecuentes |
|---|---|
| Contabilidad | financial accountant (3); general ledger accountant (2); kreditorenbuchhalter (2); kreditorenbuchhaltung (2) |
| Análisis financiero / FP&A / control de gestión | controller (4); business controller (3); in controlling (2) |
| Tesorería | treasury manager (1); werkstudium treasury (1) |
| Auditoría | auditor in für die lebensmittelindustrie (1); auditor wirtschaftsprüfer (1); business auditor (1) |
| Fiscal / impuestos | tax manager (3) |
| Nóminas / payroll | mitarbeiter entgeltabrechnung payroll specialist (1); payroll specialist (1); sachbearbeiter hr shared service center (1) |
| Compras / aprovisionamiento | einkauf datenanalyse ki d (1); einkäufer (1); it application manager procurement (1) |
| Administración / back office | kaufmann für büromanagement (2) |
| Cobros, facturación, cuentas a pagar/cobrar | fund invoices (1); mitarbeiter forderungsmanagement (1) |
| Marcadores de formación/prácticas | werkstudent (19); ausbildung (10); praktikant (6); praktikum (3); graduate (1); internship (1) |

### Neerlandés (106 títulos clasificados)

| Familia | Variantes frecuentes |
|---|---|
| Contabilidad | consultant accounting compliance and reporting (1); finance accounting consultant (1); financial accountant (1) |
| Análisis financiero / FP&A / control de gestión | financial controller (3) |
| Auditoría | audit manager (1); audit non profit (1); auditor brl 2506 recyclinggranulaten (1) |
| Fiscal / impuestos | consultant corporate tax (1); consultant tax (1); consultant tax advisory (1) |
| Nóminas / payroll | consultant payroll (1); manager payroll (1); mbo hbo meewerkstagiair pensioenuitkeringen salarisadministr (1) |
| Compras / aprovisionamiento | consultant procurement transformation (1); inkoop (1); inkoop mode (1) |
| Administración / back office | administratief bediende voor de technische keuringsdienst (1); administratief coördinator (1); administratief medewerker (1) |
| Cobros, facturación, cuentas a pagar/cobrar | accounts payable specialist (1) |
| Marcadores de formación/prácticas | stage (2); meewerkstage (1); stagiair (1); werkstudent (1) |

### Portugués (4 títulos clasificados)

| Familia | Variantes frecuentes |
|---|---|
| Auditoría | auditor sênior (1) |
| Fiscal / impuestos | especialista impostos (1) |
| Compras / aprovisionamiento | especialista sênior em compras de commodities (1) |
| Administración / back office | extracurricular em secretariado administrativo (1) |
| Marcadores de formación/prácticas | estagio (1) |

### Italiano (22 títulos clasificados)

| Familia | Variantes frecuentes |
|---|---|
| Contabilidad | accountant (1); accountant manager (1); contabile di cantiere (1) |
| Análisis financiero / FP&A / control de gestión | occ commercial customer controller (1); procurement controller (1) |
| Tesorería | business analyst banking treasury (1) |
| Auditoría | financial and sustainability audit (1); internal audit analyst (1); manager internal audit (1) |
| Fiscal / impuestos | tax control framework (1); tax specialist (1) |
| Compras / aprovisionamiento | responsabile technical procurement (1); specialista acquisti commodity (1) |
| Administración / back office | impiegato;a amministrativo;a nella gestione immobiliare (1); insurance back office specialist (1); responsabile amministrativo (1) |
| Marcadores de formación/prácticas | intern (1); stage (1) |

Portugués e italiano tienen pocas vacantes en el catálogo (muestra pequeña): sus títulos son orientativos.

Notas: «Controller» y «Controlling» se usan tal cual en alemán, neerlandés e inglés. El alemán añade muchos títulos de formación (`Werkstudent`, `Praktikum`, `Ausbildung zum/zur Kaufmann/-frau für Büromanagement`), el francés `Stage`, `Alternance` y `Apprenti(e)`, el español `Beca` y `Prácticas`, el italiano `Tirocinio` y el neerlandés `Stage` y `Meewerkstage`. En Francia dominan `Comptable`, `Gestionnaire de paie` y `Contrôleur de gestion`; en España `Administrativo/a`, `Contable`, `Técnico/a de` y `Analista`.

## 5. Fuentes bloqueadas o delgadas

- **Bloqueo anti-bot o 403 desde este entorno**: cnmv.es (portal de empleo), bankinter.com, ibercaja.com, zurich.es, vinci.com y, de forma intermitente, hpe.com y pluxee.com (sin respuesta) y baloise.com (504, redirige a helvetia-baloise.com). Sus tableros pueden existir, pero no los pude leer.
- **Sitios con sitemap pero sin JobPosting legible** (sección 3.3): no permiten comprobar país ni fecha sin abrir cada ficha y interpretar HTML propio; no los uso.
- **Workday**: cubre muchas multinacionales, pero no da fecha exacta (solo «30+ días»), y la ubicación es a veces «N Locations». Algunos tenants tienen varios sitios con ofertas repetidas (HPE: `Jobsathpe`, `WFMathpe`, `ACJobSite`); cuento cada sitio solo si aporta ofertas distintas y los demás van en las notas del lead.
- **Tableros finos**: más de un tercio de los incluidos tiene 1 a 3 vacantes relevantes; sirven para vigilar, no para estimar volumen. Las cifras grandes (por ejemplo Forvis Mazars, Allianz, PwC, EY, Bosch, SGS) vienen de tableros globales y grandes y las fichas leídas son una muestra.
- **Workable**: una consulta de prueba a `apply.workable.com` devolvió 429 (límite de peticiones) y el sondeo masivo no guardó el código de cada respuesta, así que puede haber tableros Workable existentes no detectados. Los que respondieron estaban vacíos o no tenían vacantes relevantes; no hay ninguno en el catálogo.
- **Clasificación por título**: la lista de términos y las exclusiones están descritas en la sección 1; revisé a mano una muestra de títulos marginales y corregí los falsos positivos más frecuentes («Night Auditor», «Account Development», `Steuer…` dentro de otras palabras, «Quality Assurance», auditorías ISO), pero queda ruido.
- **Europa del Este**: los centros de servicios compartidos tipo Cracovia quedan fuera por alcance (Polonia no está en la lista de países).

## 6. Cómo se hizo y qué no se hizo

- Los guiones de sondeo y análisis no se incluyen en el repositorio: viven en la sesión (sondeo educado multihilo con límite por host, lectores por ATS, clasificador de títulos). El resultado reproducible es este documento y el fichero de leads.
- No se envió ningún dato a ninguna empresa, no se hizo ninguna solicitud y no se tocó LinkedIn. Se leyeron solo APIs y páginas públicas.
- Los leads usan `source_type` `web_research`; `careers_url` es la URL del tablero verificado; `source_url` es la URL concreta leída (API, ficha de oferta o tablero Workday).
