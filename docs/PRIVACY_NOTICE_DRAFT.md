# Aviso de privacidad (borrador para la beta)

Borrador redactado por Claude, no es asesoría legal. Para una beta cerrada con conocidos sirve como punto de partida;
antes de abrir el servicio al público debe revisarlo alguien con conocimientos de RGPD. Los textos entre corchetes
son datos que tienes que rellenar.

## Lo esencial, en pocas líneas (lo que el bot muestra en `/start`)

- Este servicio te avisa por Telegram de ofertas de empleo que encajan con tu perfil y te ayuda a preparar borradores
  de cartas. Nunca envía nada por ti.
- Para hacerlo guardo el perfil que sale de tu CV y un resumen de tu experiencia sin nombre ni contacto (no el archivo del CV), y las preferencias que me das. Los uso solo para eso, incluido escribir tus cartas y tus guiones de entrevista.
- Tu CV y tus preguntas se envían a un proveedor de inteligencia artificial para extraer tu perfil y escribir borradores.
- Puedes ver qué guardo con `/my_data` y borrarlo todo con `/erase`, cuando quieras.
- No envíes por este chat datos sensibles (salud, creencias, DNI, contraseñas). Telegram no cifra de extremo a extremo
  los mensajes con bots.
- Al responder "Acepto" confirmas que has leído este aviso.

## Aviso completo

### 1. Quién es el responsable

[NOMBRE Y APELLIDOS], con correo de contacto [CORREO]. Es un proyecto personal en fase de pruebas, sin ánimo de lucro
en esta etapa.

### 2. Qué datos trato

| Dato | De dónde sale |
| --- | --- |
| Identificador de tu chat de Telegram e idioma (no guardo tu nombre ni tu usuario) | Telegram, al hablar con el bot |
| Perfil sacado de tu CV: puesto, años de experiencia, habilidades, estudios, idiomas, país y ciudad. Un resumen de tu experiencia (puestos, empresas, fechas, logros, formación) para escribir tus cartas y guiones de entrevista; lo ves completo con `/my_data`. El archivo del CV no se guarda y no se extrae tu nombre ni tu contacto | Lo subes tú y lo confirmas |
| Preferencias: puesto buscado, lugares, sueldo, modalidad, idiomas | Las indicas tú |
| Tus valoraciones de ofertas (me interesa, no me interesa) y tus candidaturas | Tus acciones en el bot |
| Borradores de cartas y respuestas generadas | Los genera el servicio a petición tuya |

No pido ni quiero datos de categorías especiales. Si aparecen en tu CV (por ejemplo, una foto o datos de salud),
puedes eliminarlos antes de subirlo.

### 3. Para qué y con qué base legal

| Finalidad | Base legal |
| --- | --- |
| Crear tu perfil y enviarte avisos de ofertas | Tu consentimiento (art. 6.1.a RGPD), al aceptar este aviso |
| Preparar borradores de cartas y candidaturas | Tu consentimiento, cuando los pides |
| Mantener el servicio seguro y evitar abusos | Interés legítimo (art. 6.1.f RGPD) |

Puedes retirar el consentimiento en cualquier momento con `/erase`. No afecta a lo hecho antes de retirarlo.

### 4. Con quién se comparten los datos

No vendo ni cedo tus datos. Intervienen estos proveedores, que tratan datos por cuenta del servicio:

- **Telegram**: transporta los mensajes del bot.
- **Proveedor de inteligencia artificial** ([Anthropic, modelo Claude]): recibe tu CV y el texto de la oferta para extraer el
  perfil y escribir borradores. Según las condiciones comerciales de su API, no usa esos datos para entrenar sus modelos
  por defecto; compruébalo en sus condiciones vigentes antes de publicar este aviso.
- **TypeSafe (motor de decisión Jev)**: recibe tu perfil resumido (puesto, años de experiencia, habilidades, país,
  preferencias salariales) y el texto de cada oferta para valorar el encaje. No recibe tu nombre ni tu contacto.
  Verifica sus condiciones vigentes antes de publicar este aviso.
- **Proveedor del servidor** ([Oracle Cloud, región REGIÓN]): aloja la base de datos y el servicio.

Esos proveedores pueden estar fuera de la Unión Europea (por ejemplo, en Estados Unidos). Cuando es así, la transferencia
se apoya en las garantías que ofrezca cada uno (cláusulas contractuales tipo o equivalentes) [verificar cada una].

### 5. Cuánto tiempo se conservan

- Perfil y preferencias: mientras uses el servicio y durante tu prueba. Al terminar la prueba el perfil se conserva unos días; el borrado automático de cuentas con la prueba terminada aún no está programado (hoy se hace a mano).
- Valoraciones y candidaturas: lo mismo.
- Copias de seguridad: se guardan 14 días, así que tus datos desaparecen de ellas como máximo 14 días después del borrado.
- Si pides el borrado con `/erase`, se eliminan tus datos de la base de datos de inmediato.

### 6. Tus derechos

Acceso, rectificación, supresión, limitación, oposición y portabilidad. Los dos primeros y el borrado los tienes
directamente en el bot (`/my_data`, `/erase`). Para el resto escribe a [CORREO]. Si no estás conforme,
puedes reclamar ante la Agencia Española de Protección de Datos (aepd.es).

### 7. Decisiones automatizadas

Las alertas se ordenan automáticamente por encaje con tu perfil, pero no toman decisiones con efectos legales sobre ti:
tú decides si aplicas. Las ofertas que el sistema descarta no llegan a las empresas.

### 8. Seguridad

Tu perfil se guarda en una base de datos en un servidor en la nube con acceso restringido y copias de seguridad privadas. [Verificar: cifrado en reposo del disco del proveedor.] Aun así, ningún
sistema es perfectamente seguro, y los mensajes con bots de Telegram no tienen cifrado de extremo a extremo.

### 9. Menores

El servicio no está dirigido a menores de 16 años.

### 10. Cambios

Si este aviso cambia de forma importante, el bot te lo dirá y te pedirá aceptarlo de nuevo.

## Pendiente antes de publicar

- Rellenar responsable, correo, región del servidor y plazos.
- Verificar las condiciones vigentes de cada proveedor (tratamiento de datos y transferencias).
- Hacer realidad lo que promete: `/my_data` y `/erase` existen y están probados; falta programar el borrado automático de cuentas con la prueba terminada.
- Revisión legal si el servicio se abre más allá de la beta cerrada.
