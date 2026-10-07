# Rúbrica de Jev para finanzas y administración (borrador, 2026-10-07)

Solo investigación y redacción: no hay código. Entregables: este informe y `docs/research/finance-rubric-2026-10.json` (`job_decision_finance_v1`). El texto de la rúbrica está en inglés porque el motor lee prompts en inglés.

## 0. Lee esto primero

**Faltaban tres de los archivos que pediste leer.** En la rama `claude/blissful-noether-vwfhdt` (y en lo que pude ver de `main`) no existen `docs/SECTOR_TEMPLATES_DESIGN.md`, `src/ai_job_hunter/sectors/templates/software.json` ni `docs/research/sector-templates-2026-10.md` (sección 4). `git fetch` falló con 503 y no pude comprobar otras ramas remotas. Consecuencias:

- Tomé como plantilla `src/ai_job_hunter/rubric.py` (`RUBRIC_SPEC`, versión `job_decision_v1`), que contiene las mismas siete preguntas, los tres criterios de cinco niveles y los tipos `noul`/`score`. El JSON copia esa forma: `question_types`, `questions`, `score_criteria`.
- **No he visto el objeto `stack` del software.** El `stack` del JSON tiene forma supuesta y está marcado así dentro del propio archivo. Si el real tiene otra forma, hay que adaptarlo.
- No leí la sección 4 de `sector-templates-2026-10.md`; si fija decisiones (por ejemplo familias o umbrales), este borrador puede contradecirlas.
- Leí `AGENTS.md`, `CLAUDE.md` y `docs/JEV.md`. No hice ninguna llamada a Jev: los "resultados esperados" de la sección 3 son mi juicio, no salidas del motor.

**Límites de la evidencia.**

- Todas las ofertas se leyeron el 2026-10-07. De las 12 principales, 10 estaban abiertas y **2 cerradas** pero con el texto legible (Factorial, Infojobs fiscalista); BDO, usada solo como apoyo, también estaba cerrada. Van marcadas. Muchas páginas de Michael Page, Crowe, BNP, WTW, Tetra Pak, Bureau Veritas (cerrada, sin contenido) devolvieron 403/404/410 y no las uso.
- Las ofertas de Ebury, Cabify, N26, Celonis y Typeform las leí íntegras por la API pública de Greenhouse. Sesgo de muestra: salen de empresas tech/fintech con tablero Greenhouse en Madrid y Barcelona. **No he visto ninguna oferta de asesoría pequeña, pyme, nóminas o banca tradicional presencial**; las conclusiones para esas familias son más débiles.
- No encontré una oferta abierta y legible de **nóminas** ni de **administración/back office** pura. La familia "compras" solo tiene un trainee (extra E2). Elegí las seis familias donde sí había dos ofertas legibles: contabilidad/controlling, FP&A, auditoría, fiscal, tesorería, crédito y riesgo.
- El candidato de referencia para las respuestas esperadas es **mío**, porque el perfil real de finanzas no está definido: ~2 años en contabilidad de una empresa (PGC, ERP, Excel), grado ADE, inglés B2, sin ACCA/CPA/CIA/CFA/ROAC. Con otro perfil cambian `experience_accessibility` y `stack_transferability`.
- Supongo que el motor normaliza los scores 0-4 a 0-1 (no lo verifiqué): 3 = 0,75 pasa el umbral `backend >= 0,60` de APPLY; 2 = 0,50 no.

## 1. Qué cambia respecto al software y por qué

Principio: mismas siete claves, mismos tipos, mismo contrato con `decision_engine.py`. Solo cambia el significado. Tres decisiones no obvias:

1. **La clave `backend_relevance` pasa a significar "centralidad del trabajo financiero".** Renombrarla rompería el motor; la clave es heredada y hay que documentarlo en `docs/DOMAIN.md` si se adopta.
2. **`stack_transferability` es la pregunta que peor se traslada.** En software el stack es un conjunto de herramientas con transferencia amplia. En finanzas pesan más los regímenes (normativa fiscal, regulación bancaria) y las certificaciones, que no se transfieren. La pregunta se reescribe como "herramientas, estándares y régimen", con una regla explícita de qué transfiere y qué no, y con `unknown` cuando solo hay herramientas genéricas.
3. **`experience_accessibility` incorpora dos puertas que el software no tiene:** certificación obligatoria y elegibilidad de programas de cohorte (año de graduación, ser estudiante). Ambas aparecen en las ofertas reales.

### 1.1 role_relevance y "núcleo del puesto" (`backend_relevance`)

Qué hace central el trabajo en cada familia (según las ofertas leídas):

| Familia | Trabajo central | Evidencia |
|---|---|---|
| Contabilidad / reporting / controlling | cierre, consolidación, estados bajo IFRS, control interno | Ebury Financial Controller; Morgan Philips Sr Finance Controller |
| FP&A | presupuesto, forecast, varianzas, modelos | Celonis Lead Finance Business Partner; Factorial FP&A |
| Auditoría | procedimientos de auditoría, papeles de trabajo, informes | EY Auditor/a Junior; Ebury Senior Internal Audit Manager |
| Fiscal | declaraciones, cumplimiento, análisis de normativa | Cabify Global Tax Trainee; Infojobs Fiscalista Senior |
| Tesorería | posición bancaria, cash flow, deuda, liquidez | Cabify Treasury Analyst; N26 Treasury Senior Associate |
| Crédito y riesgo | solvencia, límites, comité de riesgos | IMC (banca) Analista Riesgo Crediticio |

Qué penalizar, con lo que vi:

- **Datos con etiqueta de finanzas.** El "Senior Data Analyst - Treasury" de Ebury (SQL, dbt, flujos agénticos de IA) tiene "Treasury" en el título pero el trabajo es de datos: role_relevance debe ser `no`. Es el caso que justifica la frase "no tratar una palabra compartida como suficiente".
- **Trabajo rutinario transaccional.** Revisión de facturas y creación de pedidos (Cabify Procurement Analyst Trainee) es finanzas, pero soporte: nota 2, no 3.
- Venta de software o producto financiero, consultoría ERP/TI, atención al cliente bancaria, siniestros, selección de personal y asistente genérico: no aparecieron en mi muestra de ofertas, así que **esas penalizaciones están en la rúbrica por tu indicación y por lógica del dominio, no por evidencia mía**. Conviene probarlas con ofertas reales antes de fiarse de ellas.
- "Controller" y "Audit" son ambiguos (controller industrial o de TI; auditoría de TI o de calidad). Lo dejé explícito en el texto.

Niveles 0-4 de núcleo: 0 ausente; 1 periférico (datos, atención, entrada de datos); 2 apoyo con trabajo financiero real pero no central (conciliar facturas, preparar documentación); 3 procesos propios nombrados (cierre, caja, forecast, declaraciones); 4 responsabilidad principal con producto de juicio (estados consolidados, informes de auditoría, decisiones de crédito).

### 1.2 stack_transferability

Qué transfiere y qué no (resumen; detalle en la pregunta):

- **Sí:** ERP/contabilidad entre sí (SAP, Oracle, NetSuite, Dynamics, Sage, A3); Excel hacia Power BI/Tableau/Anaplan/Pigment; herramientas de consolidación entre sí; PGC, IFRS y US GAAP **en lo que es disciplina de partida doble y de cierre**.
- **No:** fiscalidad de un país a otra; contabilidad corporativa a firma de auditoría o de auditor (ROAC); tesorería corporativa a tesorería bancaria, repo o ALM; regulación (CRR, ICAAP, MaRisk, PSD2); Bloomberg o mesa de trading; temas específicos de norma (IFRS 9 con derivados, reconocimiento de ingresos SaaS). El N26 Treasury Senior Associate junta Bloomberg obligatorio, TARGET/ESMIG, MaRisk, CRR III y KWG: casi nada transfiere desde tesorería corporativa.
- **Certificaciones son puertas, no habilidades.** Ebury Internal Audit exige una de CIA, ACCA/CPA/ACA, CFA/FRM, ACT/PRMIA/CISA. Una coincidencia de herramientas no compensa.

### 1.3 experience_accessibility: cómo se escriben años y niveles

Observaciones (todas de ofertas leídas):

- **El título no calibra los años.** IMC publica "Analista Riesgo Crediticio" con "al menos 3 años" y "Analista Sr" con "10+ años" para el mismo trabajo. Cabify "Treasury Analyst" pide "entre 2 y 6 años". N26 "Senior Associate" no da años pero pide repo y ejecución autónoma. Ebury "Financial Controller" pide 7+ años y cualificación; Morgan Philips "Sr. Finance Controller" pide 5+. Celonis "Lead FBP" pide 8+ y 5 específicos en GTM de SaaS B2B.
- **Flexibilidad real:** rangos ("2-6"), "or equivalent", "desirable", "valued", "ideally", "no se requiere experiencia". **No es flexible:** "at least", "mínimo", "más de", certificaciones "required", años en un contexto estrecho.
- **Cohortes:** EY Auditor/a Junior (septiembre 2027) pide estar en último año con graduación en verano 2027, B2 de inglés, sin experiencia. Para un candidato ya graduado con 2 años, la oferta parece baja en nivel y es **inaccesible por elegibilidad**. Lo mismo vale para el trainee fiscal y el de compras de Cabify (¿convenio de prácticas?, no se dice).
- **"Mínimo 3 años" y "cualificación ACCA"** en español: el texto del software dice que 2-3 años no es bloqueo automático; lo mantengo, pero "al menos N" se trata como duro y se deja a `unknown` cuando el candidato está a un año de distancia (IMC 3 años con candidato de 2 años).

### 1.4 requirements_flexibility, career_value, observable_role_quality

- **requirements_flexibility:** distingue duros (certificación o licencia obligatoria, "al menos N años", régimen normativo, idioma) de deseos (lista "such as", "desirable"). Celonis es el ejemplo: lista de herramientas con "such as ... or" (flexible) junto a tres requisitos de años (rígidos).
- **career_value:** progresión a puestos senior, IFRS/consolidación/auditoría, entornos regulados, mentoría, patrocinio de ACCA/CPA/CFA, camino definido. **Regla sobre Big 4:** el texto solo la cuenta cuando la propia oferta describe formación o carrera (EY: "100+ horas anuales de formación", "plan de carrera", buddy y counselor). Es la lectura coherente con "hints are not facts" y con la regla de la rúbrica de calidad de no usar conocimiento previo de la empresa. Es una decisión humana (§4).
- **observable_role_quality:** procesos y entregables nombrados, entidades/mercados, sistemas y estándares, nivel coherente con años, retribución u horario. Añadí la señal de alcance mezclado (contabilidad + RRHH + recepción) como mala señal; **no la vi en ninguna oferta de mi muestra**, queda como hipótesis.

### 1.5 Bloque `stack`: ¿tiene sentido un bonus o penalización por herramienta?

**No como modificador numérico.** Razones con evidencia:

- En las 12 ofertas las herramientas son "deseables" o van en listas "such as". Ebury: "consolidation tools and ERP systems is desirable". Cabify: Excel/Sheets. Celonis: "Pigment, Salesforce, Workday, Adaptive, Tableau, or PowerBI". Ninguna oferta decide por SAP frente a NetSuite.
- Las dos excepciones son prácticamente puertas, no puntos: Bloomberg (N26, "required") y A3 avanzado (Infojobs fiscalista). Eso se resuelve con `requirements_flexibility = no` y `stack_transferability = no`, no con un bonus.
- Un bonus por herramienta premiaría ofertas que nombran SAP, que suelen ser las que más describen su stack, no las mejores.

Lo que sí incluí: un `stack` con **grupos** (ERP, análisis y planificación, tesorería y mercados, estándares, regímenes fiscales, regulación bancaria, certificaciones) y una nota por grupo de si transfiere dentro del grupo. Sirve de pista para el prompt o el extractor determinista, no como puntuación. Su forma es supuesta (§0).

## 2. Reglas del motor que esta rúbrica toca

Leído en `decision_engine.py`: `role < 0,20` → SKIP; `experience < 0,15` → SKIP; APPLY exige `role >= 0,70`, `experience >= 0,60`, `backend >= 0,60`, `stack >= 0,55` (0,45 con career >= 0,80), `flexibility >= 0,45`, `quality >= 0,35`. Dos efectos para finanzas:

- **`stack_transferability` pesa mucho en APPLY** y en finanzas es la pregunta más propensa a `unknown`. Con la regla "solo herramientas genéricas → unknown", muchas ofertas legítimas de finanzas caerán en REVIEW. Eso es coherente con "UNKNOWN stays UNKNOWN", pero hay que medirlo (§4, punto 3).
- Un puesto sénior de buena calidad (Ebury Controller, nota 4/4/4) queda en SKIP por experiencia, que es lo correcto.

## 3. Doce ofertas para probar la rúbrica

Candidato de referencia: ver §0. Respuestas: S = yes, N = no, ? = unknown. "Núcleo" = `backend_relevance` (0-4); Carrera = `career_value`; Calidad = `observable_role_quality`. Los datos entre comillas son del texto de la oferta.

| # | Familia | Oferta (estado 2026-10-07) | Rol | Exp. | Núcleo | Stack | Flex. | Carrera | Calidad |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Contab./controlling | [Ebury, Financial Controller, Madrid](https://job-boards.eu.greenhouse.io/ebury/jobs/4988620101) (abierta) | S | N | 4 | ? | N | 4 | 4 |
| 2 | Contab./controlling | [Morgan Philips, Sr. Finance Controller, Madrid](https://jobs2.morganphilips.com/en-es/sr-finance-controller-madrid-153954) (abierta) | S | N | 4 | ? | ? | 3 | 3 |
| 3 | FP&A | [Celonis, Lead Finance Business Partner, Madrid](https://job-boards.greenhouse.io/celonis/jobs/7802389003) (abierta) | S | N | 4 | ? | N | 3 | 4 |
| 4 | FP&A | [Factorial, FP&A Analyst, Barcelona](https://jobs.generalcatalyst.com/companies/factorial-2-c935a743-fbc6-456b-b258-e6cd1d93b9ca/jobs/84979644-fp-a-analyst) (**cerrada**; mismo texto en [Fuell](https://careers.theventure.city/companies/fuell-corporate-cards/jobs/84974083-fp-a-analyst), también cerrada) | S | ? | 4 | S | S | 2 | 3 |
| 5 | Auditoría | [EY, Auditor/a Junior Madrid sept. 2027](https://careers.ey.com/ey/job/Madrid-Auditora-Junior-Madrid-Septiembre-2027-M-28020/1437713133/) (abierta) | S | N | 4 | S | S | 4 | 3 |
| 6 | Auditoría | [Ebury, Senior Internal Audit Manager, Treasury/FX/Payments, Madrid](https://job-boards.eu.greenhouse.io/ebury/jobs/4977530101) (abierta) | S | N | 4 | N | N | 4 | 4 |
| 7 | Fiscal | [Cabify, Global Tax Trainee, Madrid](https://job-boards.greenhouse.io/cabify/jobs/8785634002) (abierta) | S | ? | 3 | S | S | 3 | 3 |
| 8 | Fiscal | [Infojobs, Fiscalista Senior asesoría, Barcelona](https://www.infojobs.net/barcelona/fiscalista-senior.-asesor-fiscal-contable-asesoria-empresas.-barcelona/of-i54e1110e7f4750a564da4fd2026f25) (**cerrada**) | S | N | 4 | S | N | 2 | 3 |
| 9 | Tesorería | [Cabify, Treasury Analyst, Madrid](https://job-boards.greenhouse.io/cabify/jobs/8454680002) (abierta) | S | ? | 4 | S | ? | 3 | 4 |
| 10 | Tesorería | [N26, Treasury Senior Associate, Barcelona](https://n26.com/en-eu/careers/positions/8170588?gh_jid=8170588) (abierta) | S | N | 4 | N | N | 4 | 3 |
| 11 | Crédito y riesgo | [IMC Human Capital (banca), Analista Riesgo Crediticio, Madrid](https://www.infojobs.net/madrid/analista-riesgo-crediticio/of-if40b574c914876a266b1d2a2f37bc3) (abierta) | S | ? | 4 | S | ? | 2 | 3 |
| 12 | Crédito y riesgo | [IMC Human Capital (banca), Analista Sr Riesgo Crediticio Factoring, Madrid](https://www.infojobs.net/madrid/analista-sr-riesgo-crediticio-factoring/of-i6a7205cbb74b3f81017a90d02d634e) (abierta) | S | N | 4 | S | N | 2 | 3 |

Justificación de lo no evidente (para que una persona discrepe con motivo):

1. **Ebury Controller.** Exige "ACA, ACCA, CIMA, CPA, ROAC or equivalent", "at least 7 years", IFRS 9/15/16 y consolidación. Rol y carrera altos, pero experiencia inaccesible: debería terminar en SKIP por `experience`. Stack `?`: IFRS general transfiere, IFRS 9 con derivados no.
2. **Morgan Philips.** "5+ years in audit or controlling roles" sin certificación obligatoria. Employer anónimo (búsqueda de ejecutivos), sin salario ni equipo: calidad 3, no 4.
3. **Celonis.** FP&A puro, pero "8+ years", "at least 5 years ... GTM ... B2B SaaS", "5+ years working alongside executive leadership". Herramientas flexibles, años rígidos: flex N.
4. **Factorial (cerrada).** "Prior FP&A experience" sin años: `experience = ?`. Carrera 2: solo habla de "structured career development" en beneficios, sin contenido. Sirve para probar una oferta de buen núcleo y poca señal de carrera.
5. **EY (cohorte).** Sin experiencia requerida, pero "final-year students graduating summer 2027". Para el candidato de referencia, `experience = N` por elegibilidad. Es el caso que justifica la regla de cohortes. Calidad 3: lista de tareas genérica, pero oferta de formación concreta (100+ horas, buddy, counselor).
6. **Ebury Internal Audit.** "5+ years" y certificación obligatoria ("Professional Certification Required (at least one of the following)"). Es el caso limpio de puerta de certificación. Núcleo 4 y carrera 4 no ayudan: SKIP por experiencia.
7. **Cabify Tax Trainee.** Tareas de apoyo ("recopilación y preparación de documentación", "soporte administrativo") pero en fiscalidad internacional: núcleo 3, no 4. `experience = ?` porque un trainee con 2 años de experiencia puede no ser elegible si es contrato en prácticas, y la oferta no lo dice.
8. **Infojobs Fiscalista Senior (cerrada).** "Más de 5 años" y "A3 avanzado": fiscalidad española, el candidato del referencia domina el régimen → stack S. Carrera 2: el texto solo dice "formación continua" y "desarrollo profesional". Salario 33.000-36.000 € publicado.
9. **Cabify Treasury Analyst.** "Entre 2 y 6 años de trayectoria en departamentos de Tesorería": el límite inferior es alcanzable, pero la experiencia debe ser de tesorería y el candidato de referencia viene de contabilidad. Por eso `?`, no S. Es la oferta que mejor discrimina si la rúbrica aplica bien la regla del rango.
10. **N26 Treasury Senior Associate.** Sin años pero pide "Bloomberg experience required", repo/reverse repo, TARGET/ESMIG/MACCS, MaRisk/CRR III/KWG. Stack N y flex N. Carrera 4 (banco, banco central, auditoría y 1LoD) no rescata la experiencia.
11. **IMC Analista Riesgo Crediticio.** "Al menos 3 años" frente a 2 años del candidato: `?` con inclinación a S según el criterio de que 2-3 años no es bloqueo automático. Employer anónimo ("entidad bancaria"): calidad 3. Carrera 2: el texto describe el trabajo, no el desarrollo.
12. **IMC Analista Sr.** Mismas tareas con "Minimum 10+ years". El par 11/12 comprueba que la rúbrica separa por años y no por tareas.

### Extras de penalización (no cuentan en las 12)

| Extra | Oferta | Respuesta esperada |
|---|---|---|
| E1 | [Ebury, Senior Data Analyst - Treasury](https://job-boards.eu.greenhouse.io/ebury/jobs/4990667101) (abierta) | Rol **N** (SQL, dbt, flujos de IA para datos de tesorería), exp. N ("6+ years Data/Business Analytics"), núcleo 1, stack N |
| E2 | [Cabify, Procurement Analyst Trainee](https://job-boards.greenhouse.io/cabify/jobs/8863024002) (abierta) | Rol S, exp. S ("No se requiere experiencia previa"), núcleo 2 (revisar facturas y crear pedidos), carrera 1-2 |
| E3 | [Ebury, Financial Accountant Intern](https://job-boards.greenhouse.io/ebury/jobs/4998228101) (abierta) | Rol S, exp. ? (estudiante o recién graduado), núcleo 2 (gestión de gastos, conciliaciones), carrera 2 |
| E4 | [Typeform, Director of Accounting & Controlling](https://job-boards.greenhouse.io/typeform/jobs/7811563) (abierta) | Rol S, exp. N ("Significant experience leading"), núcleo 4. **Elegibilidad contradictoria**: la ubicación incluye "Spain (Remote)" pero el texto dice "we can hire candidates based in the UK, Ireland, Germany, Portugal or The Netherlands" |

Otras ofertas leídas pero no usadas en las 12: BDO Auditores junior ([Infojobs](https://www.infojobs.net/madrid/auditores-cuentas-junior/of-i4850c001084593814d114ed58a8836), cerrada, 27 inscritos para 15 plazas), que confirma que auditoría junior es de cohorte.

## 4. Ambigüedades sin resolver y qué debe decidir una persona

1. **Perfil del candidato de finanzas.** Todo lo de experiencia y stack depende de él (años, certificaciones, si tiene exposición a IFRS o a un régimen concreto). Hay que definirlo antes de calibrar. Mi candidato de referencia es una suposición.
2. **Familias a cubrir.** Faltan nóminas y administración/back office con ofertas legibles; compras apenas. Decide si entran en el primer lanzamiento o si se prueban con ofertas reales antes. Las penalizaciones por venta de software, consultoría ERP, atención bancaria, siniestros, selección y asistencia genérica no se contrastaron con ofertas.
3. **`stack_transferability` y `unknown`.** La regla "herramientas genéricas → unknown" empuja a REVIEW. Hay que medir con ofertas reales cuántas caen ahí y decidir si es aceptable o si hay que bajar el umbral de stack para finanzas en el motor (que es código y fuera del alcance).
4. **Programas de cohorte y prácticas.** ¿Una oferta cuya elegibilidad excluye al candidato es `experience_accessibility = no` o un filtro determinista previo? La guía de Jev dice que no se mueva lo determinista a Jev sin motivo; "ser estudiante" y "graduación en 2027" son datos extraíbles. Recomiendo filtrarlo antes de Jev, pero es decisión de arquitectura.
5. **Big 4 y marca de empleador.** Mi texto solo cuenta la formación que describe la oferta. Si quieres que "firma de auditoría" valga por sí misma, hay que permitir conocimiento previo, lo que choca con la regla de calidad y con "hints are not facts".
6. **"Al menos 3 años" con 2 años.** Lo dejé en `unknown` con inclinación a sí. Una persona debe decir si en finanzas un año de diferencia es salvable (en sector regulado es menos probable).
7. **Certificaciones en curso.** "ACCA part-qualified", "estudiando CFA" no aparecieron en mi muestra, pero son comunes. La rúbrica no sabe si el candidato las está cursando; hay que decidir si el perfil recoge eso.
8. **Ubicación y elegibilidad remota** (E4 Typeform): es un problema del extractor, no de la rúbrica, pero afecta a la decisión.
9. **Calidad de la oferta anónima.** Empresas de selección (IMC, Morgan Philips) ocultan al empleador pero describen bien el trabajo. Yo no penalicé; se puede discutir si "entidad bancaria" sin nombre debe restar.
10. **Proyección de los scores.** Supuse 0-4 → 0-1. Si no es así, los umbrales de §2 cambian.

## 5. Siguientes pasos que recomiendo (no hechos)

1. Que una persona puntúe estas 12 ofertas sin ver mis columnas y comparar. Si discrepa en más de 3, revisar la pregunta correspondiente antes de usar Jev.
2. Usar fixtures de estas ofertas para un test sin Jev real. No lancé llamadas a Jev (regla de `docs/JEV.md`).
3. Ampliar la muestra con ofertas de asesoría, pyme, nóminas, banca tradicional y compras antes de cualquier adopción.
4. No tocar `rubric.py`, el motor ni las plantillas hasta cerrar §4.

## 6. Comprobaciones hechas

- JSON validado con el parser de Python y revisado en busca de bytes de control; el informe también. Resultado en el mensaje de entrega.
- No he ejecutado la suite de tests porque no hay cambios de código.
