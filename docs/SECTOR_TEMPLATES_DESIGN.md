# Plantillas de sector: inventario y diseño (fase 1, paso 1)

Estado: diseño para revisar, sin código tocado (2026-10-06). Objetivo: que lo que hoy es "búsqueda de software" sea una
plantilla de datos entre varias, sin cambiar el comportamiento actual para el propietario.

## 1. Qué está atado hoy al software

| Dónde | Qué contiene | Tipo |
| --- | --- | --- |
| `candidates/prefilter.py` (1187 líneas), líneas ~274 a 375 | Listas de palabras: marcadores no técnicos (ventas, legal, marketing, RR. HH., finanzas, sanidad...), nombres de puestos de ingeniería en 7 idiomas, tokens de IA, datos, plataforma, software núcleo, hardware, marcadores técnicos | Datos |
| `prefilter._classify_role_family` y `_clearly_non_technical_role` (líneas ~520 a 690) | Reglas en cascada que deciden si un título es TARGET, POTENCIALMENTE RELEVANTE, DESCONOCIDO o NO TARGET, con muchas excepciones ("sales engineer", "product engineer", "talent pool"...) | Lógica |
| `prefilter._evaluate_technology` | Compara tecnologías de la oferta con tu perfil (esta parte ya depende del perfil, no del sector) | Perfil |
| `services/opportunities.py`, ~línea 1636 | `STACK_CORE` (Java, Spring, Kotlin), `STACK_ADJACENT`, `STACK_FRONTEND` y sus bonus/penalizaciones | Datos de sector |
| `rubric.py` (96 líneas) | Las preguntas que Jev contesta ("¿es relevante para un candidato de software/backend?", "¿implica trabajo de sistemas backend?") y los textos de cada nivel | Texto de sector |
| `connectors/factory.py` (4 sitios) y `monitored_sources.py` | `title_may_be_relevant` como filtro barato de títulos antes de pedir el detalle de cada oferta | Uso del clasificador |
| `company_hunter/relevance.py` | Qué cargos son útiles para un candidato junior de ingeniería (reclutador, manager de ingeniería, tech lead...) | Datos de sector |
| `connectors/theirstack.py` | `DEFAULT_TITLES` de búsqueda | Datos de sector |
| `decision_engine.py` (974 líneas) | La decisión final (APPLY, REVIEW, SKIP) y el criterio de experiencia | Casi todo genérico |

Lo que **no** está atado al sector y ya sirve para cualquiera: geografía, idiomas, salario, seniority, años de experiencia,
modalidad, alertas, resumen, bot, cartas.

## 2. El problema de fondo

La clasificación de títulos no es una lista: es una **cascada de reglas con excepciones** escrita en código. Para que otro
sector funcione, no basta con sustituir listas de palabras; hay que poder expresar reglas del tipo "si el título contiene
X pero no Y, entonces Z". Y la plantilla de software tiene que seguir dando **exactamente** los mismos resultados.

## 3. Propuesta de formato

Una plantilla es un fichero JSON en `config/sectors/<id>.json` y el perfil del usuario elige una (`"sector": "software"`).
Contiene:

```json
{
  "id": "software",
  "label": "Software y datos",
  "vocabulary": {
    "role_nouns": ["engineer", "developer", "ingeniero", "..."],
    "technical_markers": ["backend", "platform", "devops", "..."],
    "non_technical_markers": {"sales": "sales", "ventas": "sales", "legal": "legal"},
    "compounds": [[["back", "end"], "backend"], [["full", "stack"], "fullstack"]]
  },
  "rules": [
    {"when": {"any": ["sales", "ventas"], "unless_any": ["engineer", "developer"]},
     "fit": "NON_TARGET", "family": "sales"},
    {"when": {"any": ["backend", "software", "platform"]},
     "fit": "TARGET", "family": "software/backend/platform engineering"}
  ],
  "stack": {"core": ["java", "spring"], "adjacent": ["python", "go"], "avoid": ["react", "angular"]},
  "rubric": {"role_relevance": "texto de la pregunta para Jev", "...": "..."},
  "company_hunter": {"useful_roles": ["technical recruiter", "engineering manager"]},
  "portal_search_titles": ["backend engineer", "software engineer"]
}
```

Las reglas se evalúan **en orden** y gana la primera que encaja; las condiciones son `any`, `all`, `none` sobre las
palabras normalizadas del título (las mismas que hoy), con `unless_*` para las excepciones. Es lo bastante expresivo para
reproducir la cascada actual sin código por plantilla.

## 4. Cómo garantizar que no cambia nada

1. **Corpus de oro.** Se extraen de la base de datos los títulos distintos (decenas de miles) con el resultado actual del
   clasificador (`fit` y `family`). Se guarda una muestra grande en `tests/fixtures/role_family_golden.json`.
2. **Dos implementaciones a la vez.** El motor nuevo se escribe sin borrar el antiguo. Un test compara ambos sobre todo el corpus y
   falla ante la primera diferencia.
3. **Solo entonces** la plantilla "software" sustituye al código antiguo, que se borra al final.
4. Las huellas de evaluación no cambian, así que no se reevalúa nada ni se reenvían alertas.

## 5. Segunda plantilla

Para un sector muy distinto (por ejemplo administración y finanzas) cambian: los sustantivos de rol ("analista",
"contable", "controller"), lo que se considera no técnico, el vocabulario de seniority, el stack ("Excel", "SAP", "Power BI"
en lugar de lenguajes de programación) y las preguntas de Jev. Se probará con ofertas reales de ese sector para ver
cuántos títulos quedan sin clasificar y qué reglas faltan.

## 6. Riesgos

| Riesgo | Mitigación |
| --- | --- |
| Reproducir la cascada actual con reglas declarativas es largo y propenso a diferencias sutiles | Corpus de oro y comparación automática entre las dos implementaciones |
| Las reglas declarativas pueden quedarse cortas | Un campo `custom` limitado para casos raros, con test, en vez de código por plantilla |
| Las preguntas de Jev dependen del sector y no se pueden verificar sin datos | Plantilla por sector y prueba con ofertas etiquetadas por el usuario |
| Sectores donde el título dice poco (sanidad, oficios, educación) | El sistema debe apoyarse más en la descripción; se añade al diseño de la segunda plantilla |

## 7. Orden de trabajo (cada paso es utilizable por sí solo)

1. Extraer el corpus de oro del servidor y comprobar que se puede reproducir (1 día).
2. Motor de reglas y carga de plantillas, con tests unitarios (2 a 3 días).
3. Plantilla "software" y equivalencia total con el clasificador antiguo (3 a 4 días).
4. Cambiar usos (`title_may_be_relevant`, factorías, monitorización) a la plantilla elegida por el perfil (1 día).
5. Mover stack, rúbrica de Jev, cargos del Company Hunter y títulos de portales a la plantilla (3 días).
6. Segunda plantilla y prueba con ofertas reales (3 a 5 días).

## 8. Ajustes tras la revisión (2026-10-06)

1. **Dos niveles: sector y puestos.** Un sector entero es demasiado amplio (en software, DevOps no encaja con todo el
   mundo). La plantilla define el vocabulario del sector y, dentro, una lista de **familias de puesto** (por ejemplo, en
   software y datos: backend, frontend, DevOps/SRE, ingeniería de datos, analítica, ciencia de datos, IA/ML, móvil, QA,
   seguridad). El usuario elige cuáles le cuadran y el resto pasa a "no encaja para este usuario". Es la idea que ya existe
   en el perfil con `preferred_roles`, pero con una lista cerrada de la que se elige.
2. **Cómo se elige.** En el alta, el bot propone sector y puestos a partir del CV (con un modelo) y el usuario los confirma o
   cambia tocando botones. Si el CV no aclara, el usuario elige a mano. Los sectores con puestos muy claros (por ejemplo
   sanidad) tendrán listas cortas; los amplios, listas largas.
3. **Hoy DevOps y SRE cuentan como puesto objetivo** (`_CORE_SOFTWARE_TOKENS`). La selección de familias lo resuelve: quien
   no quiera DevOps lo desmarca.
4. **Catálogo de empresas por sector y país.** Criterio, verificable y sin valoraciones subjetivas: empresa con tablero público
   legible, país y ciudad, y al menos una oferta en una familia de puesto del sector en los últimos 90 días; con etiquetas
   de tamaño y de si contrata a juniors. Se construye con investigaciones en la nube por sector y país. En sectores donde las
   ofertas no están en ATS (sanidad pública, hostelería, construcción), el catálogo apunta a portales y organismos, y hacen
   falta conectores distintos: el sistema actual cubre bien los sectores corporativos y tecnológicos, y peor el resto.
5. **Añadir empresas por nombre.** El usuario escribe el nombre; el sistema lo busca primero en el catálogo y, si no está,
   prueba los identificadores habituales de los ATS (como ya hace la búsqueda del enlace directo de una oferta). Si no la
   encuentra, queda en una cola de revisión del propietario. Con límite por usuario.
6. **Sectores de la beta:** (a) software y datos, para un ingeniero de datos que lo ha pedido, con familias de datos
   bien cubiertas; (b) finanzas y administración (contabilidad, análisis financiero, control de gestión, administración),
   un sector corporativo con tableros en Workday, SuccessFactors y Greenhouse, que sí encaja con la lectura actual y es
   muy distinto del software.
7. **Formato y ubicación (por defecto, a menos que se diga otra cosa):** JSON, una plantilla por sector con todos los idiomas,
   en `config/sectors/` y con posibilidad de sobreescribirlas desde la carpeta privada.

## 8. Decisiones que necesito

- **Formato:** JSON (recomendado, sin dependencias nuevas) o YAML (más legible, una dependencia).
- **Dónde viven las plantillas:** en el repositorio (`config/sectors/`) o también en la carpeta privada de cada usuario para
  poder tener las suyas.
- **Idioma de las plantillas:** el vocabulario ya es multilingüe; ¿mantenemos una plantilla por sector con todos los
  idiomas o una por sector e idioma? Recomendado: una por sector.
