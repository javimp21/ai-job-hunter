# Plan: de herramienta personal a servicio compartido (beta cerrada primero)

Estado: borrador de planificación (2026-10-06). Nada de esto está construido salvo lo marcado como hecho.
Las estimaciones son orientativas, para una persona trabajando con ayuda de Claude.

## Objetivo

Que alguien sin conocimientos técnicos pueda usar el cazador de ofertas: habla con un bot de Telegram, sube su CV,
responde unas preguntas y empieza a recibir alertas. Sin instalar nada y sin montar un servidor propio.

## Principios

1. **Leer una vez, filtrar por persona.** Los tableros de empleo se leen una sola vez para todos; la evaluación es
   por usuario. Así el coste casi no crece con cada usuario nuevo.
2. **Fuentes públicas primero, TheirStack incluido.** ATS, webs de empleo y portales con feed abierto son el núcleo.
   TheirStack se mantiene como fuente integrada en el producto, dentro de lo que permiten sus términos (apartados 4.3,
   4.11 y 4.12): cada usuario recibe solo las ofertas que encajan con su perfil, nunca el conjunto de datos, y el
   proyecto no ofrece sus datos como feed ni compite con ellos.
3. **Nada de personas guardadas.** El Company Hunter da enlaces de búsqueda y plantillas de nota, no listas de nombres.
4. **Mínimo de datos personales.** CV y preferencias se guardan cifrados, con borrado a petición.
5. **Nada se envía solo.** Cartas, notas y candidaturas son borradores que la persona revisa.
6. **Una beta pequeña antes de abrir.** 5 a 10 personas, de sectores distintos al tuyo.

## Fases

| # | Fase | Resultado | Esfuerzo |
| --- | --- | --- | --- |
| 0 | Decisiones previas | Alcance, nombre, modelo de coste y aviso de privacidad | 1 semana |
| 1 | Núcleo genérico | Perfiles por sector configurables; textos en varios idiomas | 2 a 3 semanas |
| 2 | Modelo multiusuario | Cada dato pertenece a un usuario; el perfil vive en la base de datos | 2 semanas |
| 3 | Lectura compartida y evaluación por usuario | Un ciclo de lectura sirve a todos; cuotas por usuario | 2 semanas |
| 4 | Alta por Telegram | `/start`, consentimiento, subir CV, perfil extraído y confirmado | 2 semanas |
| 5 | Cartas y proveedor de IA | Capa de proveedor intercambiable, validadores, cuotas | 1 a 2 semanas |
| 6 | Privacidad, seguridad y operación | RGPD, cifrado, borrado, límites, vigilancia de costes | 2 semanas |
| 7 | Beta cerrada | 5 a 10 usuarios, métricas y ajustes | 4 semanas |
| 8 | Decidir | Abrir, cobrar, seguir personal o parar | 1 semana |

### Fase 0: decisiones previas

- A quién va dirigido: a cualquiera que busque trabajo. En la práctica, la beta debe mezclar perfiles de software con
  2 o 3 personas de otros sectores para ver qué se rompe, porque las plantillas de sector (fase 1) son lo que más pesa.
- Modelo de coste: gratis con cuotas, o de pago desde el principio. Recomendación: gratis con cuotas en la beta.
- Aviso de privacidad y base legal (consentimiento explícito al subir el CV). Decidir qué se guarda y cuánto tiempo.
- TheirStack se mantiene (decisión del propietario). Sus términos permiten usar los datos como componente de un producto
  propio; hay que respetar tres límites de diseño: no exportar ni mostrar conjuntos de datos completos, no ofrecerlo como
  feed y no competir con su servicio. Los créditos se reparten entre usuarios con un presupuesto diario global.
- Regla de activación de TheirStack: durante la beta no se usa para otras personas (sale una búsqueda por persona y el plan
  más barato, 49 $ al mes por 1.500 créditos, no la cubre). Se activa solo para búsquedas compartidas por unas 10 personas o
  más, donde el coste por persona baja a céntimos. Para el uso personal del propietario sigue activo hasta agotar el crédito
  gratuito de la cuenta (el conector consulta el saldo y se detiene sin errores).
- Revisar los términos de cada portal con API pública (atribución, límites) antes de mostrar sus ofertas a terceros.

### Fase 1: núcleo genérico

- Sacar el filtro de familias de rol de `candidates/prefilter.py` a datos: un fichero de "plantilla de sector"
  (títulos que cuentan, títulos que no, palabras de seniority, idiomas). Ejemplos iniciales: software, datos, marketing,
  administración, sanidad, ingeniería civil.
- Parametrizar los pesos y la rúbrica de encaje (hoy orientados a stack y backend) por plantilla.
- Alertas y mensajes del bot con textos traducibles (español e inglés al principio).
- Company Hunter en modo "solo enlaces": búsquedas de LinkedIn por cargo del sector, sin guardar personas.
- Hecho ya: penalizaciones, guía de sueldos, idiomas hablados, zona horaria y filtros de TheirStack en configuración;
  asistente `ai-job-hunter-init` (ver `docs/SETUP.md`).

### Fase 2: modelo multiusuario

- Tabla de usuarios (identificador de Telegram, idioma, zona horaria, estado, fecha de consentimiento).
- El perfil (hoy `candidate.local.json`) pasa a una tabla; el fichero queda como importación para uso personal.
- `user_id` en evaluaciones, notificaciones, candidaturas, borradores y cola del Company Hunter. Las ofertas y las
  fuentes siguen siendo comunes.
- Huella de evaluación por par oferta × perfil, para no recalcular lo que no ha cambiado.
- Migraciones con copia de seguridad y prueba de restauración antes de tocar los datos reales.

### Fase 3: lectura compartida y evaluación por usuario

- Un ciclo de lectura por fuente, sin importar cuántos usuarios haya.
- Filtro determinista por usuario (barato) y solo si pasa se llama al motor de encaje (Jev), con tope por usuario y día.
- Cuotas: alertas máximas por día, evaluaciones por ronda, cartas por semana.
- Planificación por lotes de usuarios para que una ronda no se alargue con la base de usuarios.
- Vigilancia: duración por fase de la ronda y coste por usuario (ahora una ronda ya se ha pasado del límite de 55 minutos
  al ingerir un volumen grande de golpe; con varios usuarios hay que repartir la carga).

### Fase 4: alta por Telegram

- `/start`: explicación corta, aviso de privacidad y consentimiento explícito.
- El usuario sube su CV (PDF o Word). Un modelo extrae el perfil y el bot lo enseña para confirmarlo o corregirlo.
- Preguntas que el CV no responde: ciudades, mudanza, sueldo, modalidad, idiomas, sector y rol buscado.
- Alerta de prueba para validar que el filtro funciona antes de activar el envío continuo.
- Comandos para cambiar el perfil, pausar, ver qué se guarda (`/mis_datos`) y borrarlo todo (`/borrar`).

### Fase 5: cartas y proveedor de IA

- Capa de proveedor intercambiable (Claude, otros modelos de pago baratos, modelos gratuitos o locales).
- Validadores en código, que ya existen: no inventar cifras, empleos ni tecnologías que no estén en el CV; longitud;
  idioma; lista de expresiones de relleno de IA. Si el borrador no pasa, se reintenta o se avisa.
- Guía de estilo por usuario, generada a partir de textos suyos (opcional) o de una plantilla sobria.
- Cuotas de cartas por usuario y registro de coste por usuario.

### Fase 6: privacidad, seguridad y operación

- Registro de tratamientos, aviso de privacidad, plazos de conservación y procedimiento de borrado verificable.
- CV y datos del perfil cifrados en reposo; claves fuera del repositorio; acceso mínimo al servidor.
- Los registros no deben contener datos personales.
- Límites de abuso (altas por persona, tamaño de ficheros, frecuencia de comandos).
- Copias de seguridad cifradas y prueba de restauración.
- Alertas de fallo y de coste; un panel simple de salud.

### Fase 7: beta cerrada

- 5 a 10 personas de confianza, al menos 3 sectores distintos.
- Métricas: alertas por día, proporción de 👍 y 👎, tiempo hasta la primera alerta útil, quejas de ruido, coste por usuario.
- Revisión semanal de lo que se cuela y de lo que se pierde; ajuste de las plantillas de sector.
- Criterio de salida: la mayoría de los usuarios abre las alertas y marca alguna como interesante, y el coste por usuario
  es asumible.

### Fase 8: decidir

Opciones: abrir con cuotas, cobrar una cuota pequeña, mantenerlo como herramienta personal con instalación guiada, o
parar. La decisión se toma con los datos de la beta.

## Riesgos principales

| Riesgo | Mitigación |
| --- | --- |
| Datos personales de terceros (RGPD) | Consentimiento, cifrado, borrado, sin guardar personas |
| Coste de IA que crece con los usuarios | Cuotas, modelo barato por defecto, validadores, medición por usuario |
| Condiciones de TheirStack y de portales | Núcleo en fuentes públicas; TheirStack solo con alertas individuales y sin exportar datos; revisar cada portal |
| Filtro pensado para software | Plantillas de sector y beta con perfiles distintos |
| Mantenimiento de conectores (los portales cambian) | Vigilancia automática de fallos por fuente; priorizar pocas fuentes buenas |
| Rondas largas con muchos usuarios | Lectura compartida, evaluación por lotes y medición de fases |

## Qué no hacer todavía

- Cobrar, hacer web o aplicación propia, o lanzar abiertamente.
- Más fuentes a ciegas: más no es mejor si añade ruido.
- Automatizar candidaturas o mensajes: sigue siendo siempre un borrador que la persona envía.
