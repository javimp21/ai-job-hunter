# Portales de empleo en España: acceso legal y técnico a las ofertas (2026-10)

Fecha de lectura: 2026-10-07 (todas las páginas, ficheros `robots.txt` y respuestas citadas se leyeron ese día; donde una página no se pudo leer se dice "no verificado" y por qué).

Objetivo: saber si una herramienta que consulta unas pocas veces por hora y guarda las ofertas para un usuario (más adelante, un grupo pequeño) puede obtener ofertas de cada portal de forma legal y técnicamente estable.

## Cómo leer este informe

- **Verificado** = lo leí en la URL indicada el 2026-10-07. Nada más se afirma como hecho.
- **No verificado** = no pude leerlo (bloqueo 403, desafío anti-bot, página inexistente) o solo lo vi en un resumen de buscador o en un blog de terceros. Esas afirmaciones se marcan y no se usan para decidir.
- Las citas textuales son una frase corta por portal, en el idioma original.
- Los `robots.txt` solo se **descargaron y leyeron**; no se rastreó ninguna página de ofertas ni se llamó a ninguna API que exija clave. No se hizo ninguna acción externa (registros, formularios, correos).
- Los resúmenes de la herramienta de lectura web pueden ser imprecisos; cuando fue posible se descargó la página y se comprobó el texto exacto (anotado como "texto descargado").
- Esto no es asesoramiento jurídico. Los veredictos son una lectura práctica de las condiciones publicadas.
- Los veredictos usan solo estas cuatro etiquetas: **integrar ya**, **integrar tras registrarse**, **solo vía agregador**, **no usar**.

## Tabla comparativa

| Portal | API o feed oficial | Acceso | Coste | Límites | ¿Guardar ofertas permitido? | Veredicto |
|---|---|---|---|---|---|---|
| InfoJobs | API REST (`api.infojobs.net`, JSON/XML) | Registrar app con cuenta InfoJobs; Basic con Client ID/secret | No indicado | Solo se cita el umbral de 250.000 llamadas/día (Partners) | Caché sí ("mantener actualizados"); "almacenar o exportar" datos exige Partners; prohíbe apps "agregadores de ofertas" | Integrar tras registrarse (solo caché y uso personal; multiusuario y archivo largo: pedir Partners) |
| Indeed (ES) | Ninguna pública para leer ofertas (Job Sync/Apply son para socios que publican); Publisher API "Get Job" marcada Deprecated | Solo socios con acuerdo | No verificado | n/a | No hay licencia pública; `robots.txt` bloquea `/viewjob`, `/rc/` | No usar |
| Tecnoempleo | No verificado (existe enlace "API, integraciones y partners", página tras desafío Cloudflare) | No verificado | No verificado | n/a | No verificado; todos los derechos reservados | No usar (hasta preguntar) |
| Infoempleo | No verificado | n/a | n/a | n/a | Solo "uso personal, privado y no lucrativo"; prohíbe reproducir | No usar |
| Jooble | API REST de búsqueda | Formulario de clave (nombre, cargo, email, web, teléfono) | No indicado | No documentados públicamente | No verificado (términos de la API tras registro); los términos del sitio prohíben bots | Integrar tras registrarse |
| Manfred | Ninguna encontrada; `sitemap-offers.xml` público | Abierto (solo sitemap) | n/a | n/a | No: copiar contenido exige consentimiento escrito | No usar |
| LinkedIn Jobs | Job Posting API (solo publicar, socios aprobados, no acepta nuevos socios); Apply Connect | Acuerdo con LinkedIn | Acuerdo | n/a | No hay API de lectura; prohíbe scraping | No usar |
| Trabajando.com | Ninguna verificada | n/a | n/a | n/a | n/a | No usar (cobertura LatAm; sin ofertas de España verificadas) |
| Opcionempleo | No verificado (anti-bot) | n/a | n/a | n/a | No verificado | No usar (no verificado) |
| Jobtoday | Ninguna encontrada | n/a | n/a | n/a | Prohíbe robots y extracción de datos | No usar |
| Talent.com | Programa de publishers: feeds XML, Job API, URLs de afiliado (para job boards) | Contacto/alta de publisher | No verificado | No verificado | Prohíbe scraping | No usar (programa pensado para job boards; elegibilidad no verificada) |
| Joblift | No verificado (CloudFront 403 a todo) | n/a | n/a | n/a | No verificado | No usar (no verificado) |
| Adzuna (ES) | API REST pública; `es` está en la especificación oficial | Clave gratuita (app_id/app_key) por registro; Adzuna puede denegar | Gratis (límites por defecto) | 25/min, 250/día, 1.000/semana, 2.500/mes | Uso permitido: publicar anuncios con atribución e investigación personal; al terminar hay que borrar los datos | Integrar tras registrarse |
| Careerjet | API v4 de publishers | Cuenta de publisher y clave por sitio web | No verificado | `page_size` ≤ 100, páginas ≤ 10; sin cuota publicada | Términos no verificados; exige IP y user-agent del usuario final | Integrar tras registrarse (solo si los términos permiten consultas de fondo: no verificado) |
| Glassdoor | No verificado en fuente primaria | n/a | n/a | n/a | No verificado | No usar |
| Google for Jobs | Ninguna para leer; Indexing API es para quien publica ofertas | n/a | n/a | n/a | Los términos de Google prohíben ir contra `robots.txt`, que bloquea `/search` | Solo vía agregador |
| Fantastic.jobs (agregador) | API con hora de ingestión documentada | Prueba gratuita; clave Bearer | Desde 95 USD/mes (web) | Por créditos | Cede al usuario la responsabilidad de cumplir los términos de la fuente | Solo vía agregador |
| TheirStack (agregador) | API de búsqueda, nombra InfoJobs, Indeed y LinkedIn como fuentes | Registro y prueba gratuita | Desde 49 USD/mes (1.500 créditos) | 4 peticiones/s, 1 crédito por oferta | Términos no localizados: no verificado | Solo vía agregador |

Lectura rápida: solo dos vías tienen acceso oficial, gratuito y documentado para ofertas españolas: **InfoJobs** (API propia) y **Adzuna** (clave gratuita, pero con tope bajo de 2.500 llamadas al mes). **Jooble** y **Careerjet** son viables si se registran y se leen sus términos tras el registro. El resto no ofrece acceso legal verificable para una herramienta de este tipo.

---

## InfoJobs

**1. API, feed o export.** Sí, API oficial: https://developer.infojobs.net/ (leído 2026-10-07). Operaciones de búsqueda: `GET https://api.infojobs.net/offer` (lista) y `GET https://api.infojobs.net/offer/{offerId}` (detalle), JSON o XML (https://developer.infojobs.net/documentation/operation-list/index.xhtml, leído 2026-10-07).

- Lista (https://developer.infojobs.net/documentation/operation/offer-list-9.xhtml, leído 2026-10-07): título, empresa (`author`), ciudad, provincia, `published` (RFC 3339), `updated`, salario mínimo/máximo y periodo, `link` al portal, `requirementMin` (requisitos mínimos), categoría, tipo de contrato, jornada, experiencia, teletrabajo. Orden por fecha de actualización; filtro por antigüedad (24 h, 7, 15 días). Por defecto 20 resultados; 50 recomendado como máximo.
- Detalle (https://developer.infojobs.net/documentation/operation/offer-get-7.xhtml, leído 2026-10-07): descripción completa (máx. 3.500 caracteres), fechas de creación y actualización, salario, `link`, URL de solicitud externa si existe, coordenadas, número de solicitudes.
- Hora exacta: sí (RFC 3339, hora de publicación y actualización). Frescura/retraso de la API: no documentado.
- La lista no trae la descripción completa; para tenerla hace falta una llamada de detalle por oferta.

**2. Acceso, coste, límites.** Hay que iniciar sesión con una cuenta de InfoJobs y registrar una aplicación para obtener credenciales (https://developer.infojobs.net/, leído 2026-10-07). Autenticación de la app: HTTP Basic con Client ID y Client secret; OAuth con consentimiento del usuario solo para datos privados (https://developer.infojobs.net/documentation/quick-start/index.xhtml, leído 2026-10-07). Coste: no indicado en lo leído. Aprobación manual: no indicada. Límite por minuto/día: no documentado; la única cifra es el umbral de Partners (250.000 llamadas/día).

**3. Términos.** "Condiciones de uso de la API de InfoJobs" (texto fechado "Noviembre 2012"): https://developer.infojobs.net/legal/legal/terms-of-use.xhtml (texto descargado y leído 2026-10-07).

- Cita: "Puedes almacenar en la memoria caché los datos que recibas a través del uso de la API de InfoJobs".
- La caché es "con objeto de mejorar la experiencia de los candidatos de la aplicación" y obliga a "mantener dichos datos actualizados"; no se pueden almacenar datos de usuarios.
- Prohíbe usar los datos "para crear otro portal de empleo" y las "aplicaciones que sean agregadores de ofertas".
- No se pueden vender ni ceder datos a terceros; si se desactiva la app hay que borrar los datos recibidos.
- Uso comercial (3.5): hay que ser Partner si la app hace más de 250.000 llamadas diarias, supera 50.000 usuarios/mes en el login o "desea almacenar o exportar datos de InfoJobs" (contacto indicado en los términos: gestiondatos@infojobs.net).
- Enlace de vuelta: la marca solo puede usarse como "para InfoJobs"; el `link` de cada oferta apunta al portal.
- Tiempo máximo de caché: no se fija una cifra.

**4. robots.txt** (https://www.infojobs.net/robots.txt, leído 2026-10-07). Para `User-agent: *` prohíbe, entre otras, `/ofertas_lista.cfm`, `/ver-oferta.xhtml`, `/visualizar_oferta.cfm` y `/buscar.empleo/`; el fichero también bloquea por nombre varios bots de IA. Es decir: las páginas de lista y detalle no son rastreables por un bot educado; la vía legítima es la API.

**5. Veredicto: integrar tras registrarse.** Es la única fuente española de volumen con API oficial. Riesgo a resolver por escrito: los términos permiten caché para mejorar la app del candidato, pero consideran que "almacenar o exportar" datos y los agregadores requieren acuerdo de Partners; para un historial persistente o varios usuarios conviene preguntar a InfoJobs antes de depender de ello.

---

## Indeed (España)

**1. API, feed o export.** No hay API pública para leer ofertas.

- La documentación oficial `docs.indeed.com` devolvió 403 a mis descargas; solo vi títulos y resúmenes en el buscador (2026-10-07): "Job Sync API" (crear y gestionar ofertas, para socios con acuerdo de desarrollador), "Indeed Apply" y "Partner Console" (https://docs.indeed.com/job-sync-api/job-sync-api-guide, https://docs.indeed.com/indeed-apply/). Contenido de esas páginas: no verificado (403).
- La página "Get Job (Deprecated)" de la antigua Publisher API (https://developer.indeed.com/docs/publisher-jobs/get-job) redirige (301) a https://partners.indeed.com/, que tampoco pude leer (403). Que la Publisher API está retirada para integraciones nuevas: no verificado en página, solo inferido del título "Deprecated".
- Un blog de un competidor (jobspipe.dev) afirma que no hay clave pública y que el programa de datos es solo para empresas; es fuente de terceros y comercial: no se usa como prueba.

**2. Acceso y coste.** Solo socios con acuerdo. Coste y límites: no verificado.

**3. Términos.** Condiciones de servicio (última actualización 1 de abril de 2026): https://es.indeed.com/legal (texto descargado y leído 2026-10-07). Cita: "Se prohíbe el uso de cualquier tipo de automatización, script o bot para automatizar el proceso de Solicitud vía Indeed". Esa cláusula trata de automatizar candidaturas. Busqué en todo el texto las palabras robot, scrap, araña, crawler, spider y rastreo y no encontré una cláusula explícita de scraping de ofertas; eso no es concluyente (puede haber condiciones en otros documentos). Almacenar, mostrar a otros, caché y uso comercial de ofertas: no regulado en lo leído.

**4. robots.txt** (https://es.indeed.com/robots.txt, leído 2026-10-07). Para `User-agent: *` prohíbe, entre otras, `/viewjob`, `/m/viewjob`, `/rc/`, `/job/`, `/trabajo/`, `/empleo/`, `/ofertas/ES/` y `/jobs/title`; solo permite explícitamente la paginación de resultados con `start=0` a `start=90`. La ficha completa de cada oferta no es rastreable por un bot educado.

**5. Veredicto: no usar.** No hay API de lectura ni licencia; las fichas están vetadas en `robots.txt`. Aparece como fuente en agregadores de terceros (ver sección de agregadores), con el riesgo legal que se explica allí.

---

## Tecnoempleo

**1. API, feed o export.** No verificado. El pie de página de la portada enlaza a "API, integraciones y partners" (https://www.tecnoempleo.com/api-integraciones.php), pero esa página devolvió un desafío de Cloudflare ("Just a moment...") y no pude leerla (2026-10-07). Existen rastros de un RSS (`alertas-empleo-rss.php`), pero ese camino figura como `Disallow` en `robots.txt`; que el RSS devuelva unas 80 ofertas lo dicen solo scrapers de terceros en Apify (no verificado).

**2. Acceso, coste, límites.** No verificado.

**3. Términos.** "Marco normativo" (https://www.tecnoempleo.com/politicaymarco.php, texto descargado y leído 2026-10-07). Cita: "Quedan reservados todos los derechos de explotación". No encontré cláusula explícita sobre bots, almacenamiento de ofertas ni caché; tampoco autorización.

**4. robots.txt** (https://www.tecnoempleo.com/robots.txt, leído 2026-10-07). Para `User-agent: *` no veta las páginas de ofertas por nombre, pero sí `/alertas-empleo-rss.php`, `/profesionales/` y `/_ajax/select_ajax.php`; bloquea por nombre a ClaudeBot, anthropic-ai, GPTBot y otros bots de IA; publica `sitemap.xml`. El sitio responde 403 con desafío Cloudflare a clientes sin navegador.

**5. Veredicto: no usar** hasta preguntar por la vía "API, integraciones y partners": no hay acceso documentado y el RSS está vetado en `robots.txt`.

---

## Infoempleo

**1. API, feed o export.** No verificado. No encontré página de API en la portada. El RSS (`/ver_rss/`, `/rss/`) está en `Disallow` de `robots.txt`.

**2. Acceso, coste, límites.** No verificado.

**3. Términos.** Aviso legal (https://www.infoempleo.com/avisolegal/, texto descargado y leído 2026-10-07). Cita: "exclusivamente para su uso personal, privado y no lucrativo". La cláusula permite descargar y almacenar los contenidos solo con ese fin y con indicación del origen; prohíbe reproducir, distribuir o comunicar con fines comerciales o lucrativos, y la cláusula 2.2 prohíbe reproducir o copiar contenidos sin autorización. Mostrarlos a otros usuarios queda fuera de lo permitido.

**4. robots.txt** (https://www.infoempleo.com/robots.txt, leído 2026-10-07). Para `User-agent: *` veta, entre otras, `/ver_rss/`, `/rss/`, `/trabajo/fecha_*/*`, `/trabajo/palabra_`, `/trabajo/*/_*`, `/busqueda_ofertas_resultados.cfm` y las rutas de candidato. Publica `sitemap-ofertas-activas-recientes.xml`.

**5. Veredicto: no usar.** Sin API ni feed autorizado, el RSS está vetado y los términos limitan el almacenamiento a un uso personal sin ánimo de lucro (no a un producto para un grupo).

---

## Jooble

**1. API, feed o export.** Sí, API REST de búsqueda: https://jooble.org/api/about (leído 2026-10-07 con la herramienta de lectura web; la descarga directa devolvió 403). La página dice que permite hacer consultas a Jooble y publicar los resultados "on your web with custom design". Campos de la respuesta, frescura y ejemplos: no verificado (la página no los incluye; están tras el registro). Una fuente de terceros (publicapis.io) dice que los enlaces pasan por Jooble: no verificado en fuente primaria.

**2. Acceso, coste, límites.** Hay que rellenar un formulario para obtener la clave (nombre, cargo, email, sitio web, teléfono). Coste y límites de peticiones: no documentados en la página (no verificado). El formulario pide datos personales y un sitio web: lo debe rellenar el usuario.

**3. Términos.** Condiciones del sitio: https://es.jooble.org/info/terms (leído 2026-10-07). Cita (sección 4.m): "You may not use any web spiders, bots, indexers, robots, crawlers, harvesters, or any other automatic process to access, acquire, copy or monitor any portion of the Site". Esta cláusula habla del sitio web; los términos específicos de la API se ven tras el registro: no verificado.

**4. robots.txt** (https://es.jooble.org/robots.txt, leído 2026-10-07). Para `User-agent: *` veta `/SearchResult*`, `/desc/`, `/away/`, `/redir`, `/search1-*`, `/Export/`, `/employer/api` y otras. Es decir, ni las búsquedas ni las fichas son rastreables.

**5. Veredicto: integrar tras registrarse**, pero solo por la API y después de leer los términos de la API que entrega el registro. Jooble no es la fuente de las ofertas: agrega las de otros portales y no he verificado cuáles de la lista de este informe incluye.

---

## Manfred

**1. API, feed o export.** No encontré API ni feed de ofertas. La portada (https://www.getmanfred.com/, leída con la herramienta web 2026-10-07) no menciona acceso para desarrolladores. `robots.txt` publica `https://www.getmanfred.com/sitemap-offers.xml` (descargado 2026-10-07: 1.665 entradas `<loc>` de la forma `/ofertas-empleo/{id}/{slug}`, con `lastmod` de hasta 2026-10-06T10:40:32Z). Es un sitemap de descubrimiento, no un feed de datos: no trae título, empresa, salario ni descripción.

**2. Acceso, coste, límites.** Abierto solo el sitemap. No hay límites publicados.

**3. Términos.** Términos de uso: https://www.getmanfred.com/terminos-de-uso (texto descargado y leído 2026-10-07). Cita (6.3): "sin el previo consentimiento expreso y por escrito de MANFRED" (el contenido no puede utilizarse, reproducirse, copiarse ni transmitirse sin él). No encontré mención específica de bots, caché ni almacenamiento.

**4. robots.txt** (https://www.getmanfred.com/robots.txt, leído 2026-10-07). `User-agent: *` con `Allow: /`; sin restricciones y con dos sitemaps. El permiso de `robots.txt` no sustituye al consentimiento por escrito que piden los términos.

**5. Veredicto: no usar** salvo permiso escrito: no hay API y los términos exigen consentimiento para copiar contenido. Pedir permiso es la única vía (el sitio enlaza a `/contacto`).

---

## LinkedIn Jobs (solo para documentar lo oficial)

**1. API, feed o export.** Oficial: **Job Posting API**, que sirve para que ATS y distribuidores *publiquen* ofertas en LinkedIn en nombre de clientes, no para leerlas (https://learn.microsoft.com/en-us/linkedin/talent/job-postings/api/overview, leído 2026-10-07). Aviso textual de la página: "We are currently not accepting new partnerships for LinkedIn's Job Posting API"; remite a *Apply Connect*. El uso está "restricted to those developers approved by LinkedIn" y exige firmar un acuerdo de API con restricciones de datos. El catálogo de APIs de Talent Solutions (https://learn.microsoft.com/en-us/linkedin/talent/, leído 2026-10-07) lista Apply Connect, Apply with LinkedIn, Job Posting, CRM Connect y Recruiter System Connect; ninguna es una API de búsqueda o lectura de ofertas públicas.

**2. Acceso y coste.** Acuerdo con LinkedIn y alta de socio ATS; coste: no indicado. Límites: no aplicable.

**3. Términos.** Acuerdo de usuario: https://www.linkedin.com/legal/user-agreement (leído 2026-10-07). Cita (8.2): "scrape or copy the Services" (prohíbe usar software, scripts, robots, crawlers o plugins para ello).

**4. robots.txt** (https://www.linkedin.com/robots.txt, leído 2026-10-07). La cabecera dice que el acceso automatizado sin permiso expreso "is strictly prohibited". Para todos los agentes figuran `Disallow` en `/jobs?runSearch*`, `/jobs-guest/` y `/api/jobPostings/jobs*`; solo LinkedInBot y buscadores aprobados tienen permiso.

**5. Veredicto: no usar.** No existe vía oficial de lectura para terceros y los términos prohíben el scraping. Las ofertas de LinkedIn solo llegarían por agregadores (que cargan con ese riesgo).

---

## Trabajando.com

**1. API, feed o export.** Ninguna verificada.

**2. Cobertura de España.** `https://www.trabajando.com/` redirige a https://www.trabajando.cl/ (leído 2026-10-07), cuya portada menciona Chile (12 veces) y no menciona España. `https://www.trabajando.es/` existe y responde, pero su portada (leída 2026-10-07) es un sitio de artículos y guías (entrevistas, currículum, carta de presentación, "Trabajar en España") y no vi un buscador de ofertas; no verificado que pertenezca a la misma empresa.

**3. Términos.** No leídos (`https://www.trabajando.es/aviso-legal/` existe; no se extrajo ninguna cláusula relevante).

**4. robots.txt.** https://www.trabajando.cl/robots.txt (leído 2026-10-07): `Allow: /` salvo `/recomendadas/`, `/ingresa-a-tu-cuenta/`, `/crea-tu-curriculum/`. https://www.trabajando.es/robots.txt: solo `Disallow: /wp-admin/`.

**5. Veredicto: no usar.** No hay evidencia de ofertas de España ni de API.

---

## Opcionempleo

**1. API, feed o export.** No verificado. La portada devolvió una página de "Verificación requerida ... tráfico inusual de tu red informática" (2026-10-07); no se insistió ni se intentó evitarla. El `robots.txt` lista rutas como `/partners/jssearchbox.html` y `/partners/api/dotnet/doc/Client.html`, lo que sugiere que existe un programa de partners con API, pero eso es una inferencia, no un hecho verificado. Observación: la lista de reglas de ese `robots.txt` es textualmente igual a la de www.careerjet.com (se anota solo como coincidencia observada).

**2. Acceso, coste, límites, términos.** No verificado.

**4. robots.txt** (https://www.opcionempleo.com/robots.txt, leído 2026-10-07). Para `User-agent: *` veta `/job/`, `/jobview/`, `/jobviewx/`, `/clk/`, `/apply/`, `/search/query.html`, `/search/rss.html`, y las URLs con parámetros `p`, `sort`, `radius`, etc.

**5. Veredicto: no usar.** No pude verificar ninguna vía legítima; el RSS y las fichas están vetados.

---

## Jobtoday

**1. API, feed o export.** No encontré. Tiene página de España (https://jobtoday.com/es, "Ofertas en España (octubre 2026)", leída 2026-10-07), pero no hay referencia a API en la portada ni en sus términos.

**2. Acceso, coste, límites.** No verificado.

**3. Términos.** https://jobtoday.com/es/legal/tos (texto descargado y leído 2026-10-07). Cita: "page-scrape o extracción de datos". La cláusula prohíbe, sin autorización expresa, copiar la Plataforma para fines comerciales propios usando enlaces profundos, robots, arañas o extracción de datos.

**4. robots.txt** (https://jobtoday.com/robots.txt, leído 2026-10-07). `User-agent: *` solo veta `/*_ext_*`; publica sitemaps; veta por nombre a DataForSeoBot y Yandex.

**5. Veredicto: no usar.** No hay API y los términos prohíben la extracción automática.

---

## Talent.com

**1. API, feed o export.** Programa de publishers para job boards: feeds XML, "self-serve job API" y URLs de afiliado, con "30M+ jobs in 79 countries" (https://employers.talent.com/publishers, leído 2026-10-07). La página es de marketing: no describe campos, límites, requisitos de aprobación ni modelo de pago (no verificado). El panel de publishers (https://www.talent.com/publishers) pide inicio de sesión. Existe `es.talent.com` (responde 200); cobertura detallada de España: no verificado.

**2. Acceso, coste, límites.** No verificado; la página invita a contactar con el equipo.

**3. Términos.** https://www.talent.com/terms-of-service (texto descargado y leído 2026-10-07). Cita: `by any automated or non-automated "scraping" for any purpose` (también prohíbe usar robots que envíen más peticiones que un humano con un navegador y reformatear, enmarcar o enlazar contenido de los servicios).

**4. robots.txt** (https://www.talent.com/robots.txt y es.talent.com, leídos 2026-10-07). Veta `/search-jobs/*`, `/services/api-new/search`, `/redirect*` y `/convert*` por idioma.

**5. Veredicto: no usar.** Su programa está pensado para quien monetiza un job board; para una herramienta personal no hay acceso documentado y los términos prohíben el scraping.

---

## Joblift

**1. API, feed o export.** No verificado. Todas las peticiones (portada, `/es`, `robots.txt`, dominios `.es` y `.de`) devolvieron 403 de CloudFront ("Request blocked") el 2026-10-07. No pude leer ni robots, ni términos, ni programa de partners, ni si opera en España. Un resumen de buscador la describe como un buscador de empleo con sede en Hamburgo (antes Everyjob); es información de terceros, no verificada.

**5. Veredicto: no usar** (no verificado: sin acceso a ninguna fuente primaria).

---

## Adzuna (España)

**1. API, feed o export.** Sí, API REST pública con registro: https://developer.adzuna.com/overview (leído 2026-10-07). Raíz `https://api.adzuna.com/v1/api`; formatos JSON, JSONP o XML.

- España confirmada: la especificación OpenAPI oficial (https://developer.adzuna.com/swagger/spec/test2.json, descargada 2026-10-07) enumera los países `gb, us, at, au, be, br, ca, ch, de, es, fr, in, it, mx, nl, nz, pl, sg, za`.
- Endpoints: búsqueda (`/jobs/{country}/search/{page}`), categorías, histograma, principales empresas, geodatos, historial de salarios y versión.
- Búsqueda (https://developer.adzuna.com/docs/search, leída 2026-10-07): devuelve `id`, `title`, `description`, `created` (ISO 8601 con hora), `redirect_url`, `company.display_name`, `location`, `salary_min`/`salary_max`, `salary_is_predicted`, `contract_type`, `category`, latitud/longitud. Aviso textual: la descripción es solo un fragmento ("we currently only provide a snipped of the job description"). Parámetros útiles: `max_days_old`, `sort_by`, `what`, `where`, `category`, `full_time`/`part_time`/`permanent`/`contract`.
- Frescura: `created` es la fecha del anuncio; el retraso entre publicación en la fuente y respuesta de la API no está documentado.
- No hay texto completo de la oferta: para leerlo hay que ir a `redirect_url`.

**2. Acceso, coste, límites.** Registro para obtener `app_id` y `app_key` (obligatorios en cada petición). Los términos dicen que Adzuna tiene "absolute discretion over granting access to users". Límites por defecto (https://developer.adzuna.com/docs/terms_of_service, leído 2026-10-07): 25 impactos por minuto, 250 por día, 1.000 por semana y 2.500 por mes. Coste: no se indica precio para estos límites. Cálculo propio: 2.500 al mes son unos 83 al día (unos 3 por hora en total); el tope mensual es el que manda si se consulta varias veces por hora. Se pueden pedir más límites contactando con Adzuna para quien publica sus anuncios.

**3. Términos.** https://developer.adzuna.com/docs/terms_of_service (leído 2026-10-07). Cita: "Adzuna has absolute discretion over granting access to users". Usos permitidos: publicar anuncios de Adzuna, publicar estimaciones salariales "Jobsworth" e investigación personal; cualquier otro uso comercial, público o académico solo con prueba de 14 días y, después, posible licencia. Atribución obligatoria: etiquetar cada anuncio con "Adzuna" (al menos 116 x 23 píxeles) con enlace al dominio de Adzuna. Almacenar: no se fija tiempo de caché, pero al terminar el acuerdo hay que eliminar "all insertion codes and data acquired from Adzuna". Mostrar a otros usuarios: permitido si se publica con atribución.

**4. robots.txt.** https://api.adzuna.com/robots.txt (leído 2026-10-07): `User-agent: *` con `Disallow: /` (aplica a rastreadores; la API está pensada para uso con clave). https://www.adzuna.es/robots.txt: no verificado (403).

**5. Veredicto: integrar tras registrarse.** Acceso oficial y gratuito con España, atribución clara. Límites: poco volumen (2.500/mes) y descripciones recortadas, útil como fuente de descubrimiento, no de texto completo.

---

## Careerjet

**1. API, feed o export.** Sí, API v4 para publishers: https://www.careerjet.com/partners/api/ (leída 2026-10-07). Endpoint `https://search.api.careerjet.net/v4/query`; autenticación Basic con la clave como usuario; parámetros `locale_code` (formato `es_ES` para España; que `es_ES` esté en la lista de locales soportados: no verificado, la página remite a una lista), `keywords`, `location`, `contract_type`, `work_hours`, `sort` (`relevance`, `date`, `salary`), `page` (1 a 10) y `page_size` (1 a 100). Campos por oferta: `title`, `company`, `date` (con hora y GMT), `description` (solo un fragmento; `fragment_size` por defecto 120 caracteres), `locations`, `salary`, `salary_min`, `salary_max`, `salary_type`, `url` (enlace de seguimiento `jobviewtrack.com`). Frescura: no documentada.

**2. Acceso, coste, límites.** Cada sitio web publisher necesita su propia clave desde una cuenta de publisher (https://www.careerjet.com/partners/register/as-publisher, enlazada en la página). Los parámetros `user_ip` y `user_agent` son obligatorios y deben ser los del **usuario final que provocó la llamada**; sin ellos devuelve 403. Para un proceso programado que consulta de fondo no hay usuario final: ese requisito choca con el uso previsto. Cuotas de peticiones y coste: no publicados en esa página.

**3. Términos.** No verificado. La página del programa (https://www.careerjet.com/partners/publishers) habla de "Monetize your web traffic by displaying Careerjet's job listings" (modelo de afiliación: mostrar y enlazar), sin condiciones. La URL de términos que cita un buscador (http://public.api.careerjet.net/terms) devolvió 404 en mi descarga; `https://www.careerjet.com/partners/terms` también 404.

**4. robots.txt** (https://www.careerjet.com/robots.txt, leído 2026-10-07). Para `User-agent: *` veta `/job/`, `/jobview/`, `/clk/`, `/search/query.html`, `/search/rss.html` y URLs con `sort`, `radius`, etc. El de `www.careerjet.es` no se pudo leer (certificado TLS caducado).

**5. Veredicto: integrar tras registrarse**, con una reserva: solo si los términos de publisher (no verificados) admiten consultas de fondo sin usuario final. Es una API de afiliados, no un feed de datos.

---

## Glassdoor

**1. API, feed o export.** No verificado en fuente primaria. `glassdoor.com/developer/` y los términos (`/about/terms/`) devolvieron 403 el 2026-10-07. Blogs de terceros comerciales (jobspipe.dev, zuplo.com) dicen que la API pública se cerró y solo queda acceso comercial a socios: no verificado, no se usa como prueba.

**3. Términos.** No leídos (403).

**4. robots.txt** (https://www.glassdoor.es/robots.txt, leído 2026-10-07). Para `User-agent: *` veta `/job-listing/details.htm?*`, `/job-listing/JV.htm?*`, `/Empleo/*_IP*`, `/Empleos/*_P*.htm*` y `/Empleos/*_IP*.htm*`; también `/jobview/` y `/partners/jobs/`. Las páginas de resultados paginadas y las fichas quedan vetadas para bots.

**5. Veredicto: no usar** (sin API verificada; fichas y paginación vetadas).

---

## Google for Jobs

**1. API, feed o export.** No hay API de lectura de Google for Jobs. La documentación oficial está dirigida a quien publica: https://developers.google.com/search/docs/appearance/structured-data/job-posting (leída 2026-10-07). La **Indexing API** sirve para que el dueño de una página avise a Google de que una oferta se añadió o se quitó, y solo para páginas con `JobPosting` o `BroadcastEvent`; cuota por defecto de 200 (https://developers.google.com/search/apis/indexing-api/v3/quickstart, leída 2026-10-07). No devuelve ofertas.

**3. Términos.** Condiciones de Google (en vigor desde 30 de julio de 2026): https://policies.google.com/terms?hl=en (texto descargado 2026-10-07). Cita: "using automated means to access content from any of our services in violation of the machine-readable instructions on our web pages".

**4. robots.txt** (https://www.google.com/robots.txt, leído 2026-10-07): `User-agent: *` con `Disallow: /search`; la experiencia de empleos vive bajo la búsqueda, por lo que un bot educado no debe consultarla.

**5. Veredicto: solo vía agregador.** No hay vía directa. Algunos agregadores de pago (por ejemplo JSearch, ver sección siguiente) dicen usar Google for Jobs como fuente; su base legal no está verificada.

---

## Agregadores: Fantastic.jobs, TheirStack y similares

Solo se usó documentación pública y muestras gratuitas. No se creó ninguna cuenta ni se llamó a ninguna API con clave.

### Cuadro de cobertura para España

| Portal de la lista | Fantastic.jobs | TheirStack | Adzuna | Jooble | Careerjet | JSearch |
|---|---|---|---|---|---|---|
| InfoJobs | No lo nombra como fuente | Sí, nombrado como fuente; "Spain on InfoJobs" | Es otro agregador: no verificado | No verificado | No verificado | No verificado |
| Indeed | No lo lista | Sí, nombrado | No verificado | No verificado | No verificado | Dice incluirlo (no verificado) |
| LinkedIn | Sí (feed de job board: "mostly LinkedIn") | Sí, nombrado | No verificado | No verificado | No verificado | Dice incluirlo (no verificado) |
| Tecnoempleo, Infoempleo, Manfred, Trabajando.com, Opcionempleo, Jobtoday, Talent.com, Joblift | No verificado | No verificado (no aparecen en las páginas leídas) | No verificado | No verificado | No verificado | No verificado |
| Glassdoor | No verificado | No verificado | No verificado | No verificado | No verificado | Dice incluirlo (no verificado) |
| Google for Jobs | No | No verificado | No | No verificado | No verificado | Dice usarlo como fuente principal |

Adzuna, Jooble y Careerjet son a la vez portales y agregadores; de ninguno he podido verificar qué portales de esta lista incluye, porque sus páginas públicas no lo detallan.

### Fantastic.jobs

- **Productos** (https://fantastic.jobs/, leído 2026-10-07): API de ofertas, feeds y acceso a base de datos. Fuentes: ATS ("200,000+ career sites") y portales "LinkedIn, Wellfound y YCombinator"; Indeed no figura. Pone "Hourly refresh".
- **Cómo funciona** (https://developer.fantastic.jobs/documentation/how-fantastic-jobs-api-works, leído 2026-10-07): comprueba más de 200.000 empresas de 58 plataformas ATS cada hora; endpoints de ofertas nuevas, modificadas y expiradas; "This API is designed for recurring requests where the results are stored in your own database."
- **Cobertura de España** (https://developer.fantastic.jobs/documentation/country-job-statistics, "Last updated September 8th 2026", leído 2026-10-07): ofertas nuevas estimadas al mes en España: 25.000 a 31.000 de ATS, 83.000 a 100.000 de portales (sobre todo LinkedIn) y 96.000 a 120.000 combinadas sin duplicados. No se reparte por portales españoles.
- **Frescura documentada** (https://developer.fantastic.jobs/documentation/time-fields, "Last modified on October 2, 2026", leído 2026-10-07): `date_posted` = cuándo dice la fuente que se publicó; `date_created` = cuándo la indexó el sistema; hay "1 to 2 hour ingestion delay" entre la publicación en la fuente y su aparición en la API; con `time_frame` de 1 h y 24 h, `date_created` va siempre al menos una hora por detrás del tiempo real. Los LinkedIn de países de habla inglesa y de roles técnicos se actualizan cada hora; "other regions experience slight delays" (resumen de la página de funcionamiento).
- **Muestras gratuitas medidas** (https://files.fantastic.jobs/sample-jb.json y https://files.fantastic.jobs/sample-ats.json, descargadas 2026-10-07; son ficheros estáticos de 100 ofertas cada uno, no respuestas de la API): diferencia `date_created` menos `date_posted`: portales (todos de LinkedIn) mediana 0,0 h y máximo 0,4 h; ATS (Greenhouse y Lever) mediana 0,3 h y máximo 1,9 h. En el fichero de portales, 5 de 100 ofertas son de España. La hora de la respuesta de la API no se pudo medir sin clave: **no verificado** el retraso real entre publicación y respuesta; solo consta el "1 a 2 horas" de la documentación. La publicación `date_posted` de los portales viene con segundos, lo que sugiere hora de detección más que hora de publicación (inferencia; no verificado).
- **Precio y acceso:** "Pricing starts at $95/month" (autoservicio) y 1.000 USD/mes (volumen alto), con prueba gratuita (https://fantastic.jobs/, leído 2026-10-07); la página de precios no se pudo extraer (contenido dinámico). Autenticación Bearer (https://developer.fantastic.jobs/documentation/authentication).
- **Términos** (https://developer.fantastic.jobs/terms, "Last updated: May 19, 2026", leído 2026-10-07). Cita: "You are responsible for ensuring Your use of the data complies with any applicable terms imposed by the original source". Dicen que no reclaman propiedad de los datos; el riesgo legal de la fuente original (por ejemplo LinkedIn) se traslada al cliente.
- **robots.txt:** https://fantastic.jobs/robots.txt permite todo (`Allow: /`).

### TheirStack

- **Fuentes** (https://theirstack.com/en/docs/data/job, leído 2026-10-07): "major job boards like Indeed, Linkedin, Workable, Greenhouse, Lever, Infojobs, Otta, StartupJobs", 195 países. En https://theirstack.com/en/docs/data/job/sources: "Spain on InfoJobs" como fuente dominante. Su página de InfoJobs dice: "Thousands of fresh job posts arrive hourly. 90% of new tech postings discovered within 24 hours, 73% same-day." (https://theirstack.com/en/job-posting-api/data-source/infojobs, leído 2026-10-07).
- **Frescura:** "We discover 73% of jobs the same day they are posted and 91% by the end of the next day" (https://theirstack.com/en/docs/data/job). La API distingue `date_posted` y `discovered_at` (campos y filtros `discovered_at_gte` y similares, https://theirstack.com/en/docs/api-reference/jobs/search_jobs_v1, leído 2026-10-07). No hay muestras gratuitas de respuesta que permitan medir el retraso: **no verificado** el valor numérico real.
- **Acceso y coste** (https://theirstack.com/en/pricing, leído 2026-10-07): suscripción desde 49 USD/mes por 1.500 créditos; 1 crédito por oferta devuelta; límite de 4 peticiones por segundo; los créditos sin usar se acumulan 12 meses; prueba gratuita sin cifra. La búsqueda exige un filtro de antigüedad, por ejemplo `posted_at_max_age_days`; para España, `country_code_or: ["ES"]`.
- **Términos:** no localizados (las URLs probadas devolvieron 404): no verificado qué permiten sobre guardar o mostrar. **robots.txt:** https://theirstack.com/robots.txt veta solo `/api/search`.
- **Legalidad:** su blog dice que recopila datos públicos "scraping some websites directly" (resumen de buscador de https://theirstack.com/en/blog/the-ultimate-guide-to-job-scraping); eso incluye portales cuyos términos prohíben el scraping (InfoJobs, Indeed, LinkedIn). Al comprar los datos no se heredan permisos de esos portales.

### Otros agregadores revisados

- **JSearch (OpenWebNinja)** (https://www.openwebninja.com/api/jsearch, leído 2026-10-07): dice agregar "Google for Jobs and public job boards" incluidos LinkedIn, Indeed, Glassdoor y ZipRecruiter, en tiempo real; plan gratis 200 peticiones/mes; 25 USD/mes por 10.000. No trae ejemplo para España ni cláusula sobre almacenamiento (no verificado).
- **Adzuna, Jooble y Careerjet:** ver sus secciones; son las únicas fuentes agregadoras con acceso gratuito y oficial para España.
- **Talent.com y WhatJobs:** programas para publishers (ver arriba); WhatJobs (https://www.whatjobs.com/affiliates) ofrece una "Job Feed API" en JSON o XML sin información específica de España.

### Veredicto sobre agregadores

Fantastic.jobs y TheirStack dan comodidad (un solo contrato, campos normalizados, `date_posted` y fecha de detección), pero: (a) cuestan desde 49 a 95 USD/mes, (b) incluyen datos de portales cuyos términos prohíben el scraping y las condiciones de Fantastic.jobs trasladan al cliente la responsabilidad, (c) no he podido medir el retraso real. Para el objetivo "menos ruido, trazabilidad, seguridad" encajan como **fuente secundaria opcional**, no como base. Ninguno cubre de forma verificada Tecnoempleo, Infoempleo ni Manfred.

---

## Qué debe hacer el usuario a mano

Todo lo siguiente lo debe hacer el usuario; en esta investigación no se hizo ningún registro, formulario ni envío. Las claves van solo en `.env` (nunca en Git, ver `AGENTS.md`).

1. **InfoJobs (prioridad alta).**
   - Entrar en https://developer.infojobs.net/ con su cuenta de InfoJobs y registrar una aplicación (Client ID y Client secret).
   - Preguntar por escrito a gestiondatos@infojobs.net (dirección que figura en las condiciones de la API) si guardar las ofertas en una base de datos propia y usarlas para un grupo pequeño de usuarios entra en "almacenar o exportar datos" (Partners) o se admite como caché de una app personal.
   - Mientras no haya respuesta, tratar los datos como caché con borrado si se desactiva la app.
2. **Adzuna (prioridad alta).** Registrarse en https://developer.adzuna.com/ para obtener `app_id` y `app_key`. Revisar que los límites por defecto (2.500 al mes) bastan; si no, pedir ampliación. Mostrar siempre la atribución "Adzuna" con enlace si se enseñan las ofertas.
3. **Jooble.** Rellenar el formulario de https://jooble.org/api/about (nombre, cargo, email, web, teléfono: datos personales, decide el usuario si los da). Leer los términos de la API que reciba tras el registro y comprobar límites y campos.
4. **Careerjet.** Crear una cuenta de publisher en https://www.careerjet.com/partners/register/as-publisher, declarar el sitio web, y leer los términos de publisher (no localizados en esta investigación) para confirmar si se admiten consultas programadas sin usuario final (la API exige `user_ip` y `user_agent` del usuario).
5. **Escribir a los portales sin acceso verificado** (opcional; no se ha enviado nada): Tecnoempleo (página "API, integraciones y partners", que requiere navegador), Manfred (página `/contacto` del sitio; sus términos piden consentimiento por escrito) e Infoempleo (la cláusula 2.3 de su aviso legal indica atencioncliente@infoempleo.com para solicitar enlaces; para otros usos no hay canal indicado). Hasta tener permiso, no integrarlos.
6. **Opcional, agregadores de pago.** Decidir si merece la pena una prueba gratuita de Fantastic.jobs (https://fantastic.jobs/) o TheirStack (https://theirstack.com/) después de aceptar que sus datos de LinkedIn, Indeed e InfoJobs vienen de terceros cuyos términos prohíben el scraping. Medir con la prueba el retraso real entre `date_posted` y la hora de respuesta antes de pagar.
7. **Verificar a mano lo que aquí quedó "no verificado"** desde un navegador normal (sin evitar protecciones): documentación de Indeed (`docs.indeed.com`), términos y API de Glassdoor, Joblift, Opcionempleo, términos de Careerjet y de TheirStack, página de precios de Fantastic.jobs.

## Resumen para el diseño (propuesta, no implementada)

- Fase 1: InfoJobs API (descubrimiento por `updated` y detalle por oferta) más Adzuna (descubrimiento, con presupuesto de unas 3 llamadas por hora) como únicas fuentes de portal con acceso oficial; guardar `source`, `source_url`, `fetched_at` y los campos originales para conservar la procedencia.
- Fase 2: Jooble y Careerjet solo tras leer sus términos de API.
- Se mantiene fuera todo lo que sea scraping de HTML de portales con `robots.txt` o términos en contra (Indeed, LinkedIn, Glassdoor, Infoempleo, Tecnoempleo, Manfred, Talent.com, Jobtoday).
- Cualquier dato derivado (antigüedad, `published`) se guarda tal cual lo da la fuente; si falta, queda UNKNOWN.
