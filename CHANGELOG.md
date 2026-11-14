# Registro de cambios

Registro de los cambios efectuados y los cambios pendientes.

## Pendientes

- [ ] Página de "Acerca de": Sección de privacidad y FAQ.
- [ ] Página de docs: Endpoints disponibles, como usar, limitantes respecto a la GUI.
- [ ] Descargar los resultados (json, md o pdf).

## Versiones

### v0.23.0

- Cambios menores para accesibilidad en la web principal.
- Cambiado el título de `/dns-leak/{token}` -> `/dns-leak/{test_id}` en vista _RAW_ para consistencia con la API.

### v0.22.0

- Añadida `AbortSignal` para la medida `RTT` del _endpoint_ opcional.
- Añadida `AbortSignal` para cancelar el diagnostico en caso de navegación del usuario.

### v0.21.2

- Actualización del _lockfile_ de `pnpm`.

### v0.21.1 (fallido)

- Actualización de dependencias (UI kit).

### v0.21.0

- Se puede agregar una URL especifica a la cual hacer medida `RTT` desde la variable `REALTIME_URL`.
- Eliminado el _speedtest_ por complejidad y posible explotación.
- Añadida la sección _Metrics_ a la vista principal.

### v0.20.0

- Añadido `/all.txt`: Devuelve la información de `/all` en texto plano formateado.
- Añadido la linea `TIMEZONE` a la sección _IP info_ en la vista principal.
- Cambios en el _rate limit_ para `/speed/start`.

### v0.19.3

- Eliminación del `test_id` de los logs a nivel de proxy.

### v0.19.2

- Cambio de destino de los logs de producción a la RAM (según el [ejemplo de despliegue](./deploy/docker-compose.yml))
- Eliminación del `test_id` de los logs a nivel de API.

### v0.19.1

- Cambios menores en las barras de desplazamiento.
- Cambio en el título de la página.

### v0.19.0

- Añadido ECS a la vista principal.

### v0.18.0

- Soporte para ECS en el servidor DNS.
- Intercambio entre vista principal y vista cruda de la GUI por medio de hash para persistir la vista a una recarga.
- Añadido ECS a los resultados de `/dns-leak/{test_id}`.

### v0.17.2

- Cambio de estilos para las barras de desplazamiento en la vista principal.

### v0.17.1 (versión v0.17.0 saltada por typo)

- Añadida la sección _Client headers_ a la vista principal.

### v0.16.1

- Bug corregido al renderizar la información de RDAP.

### v0.16.0

- Añadida la sección _RDAP info_ a la vista principal.

### v0.15.2

- Reemplazo de `N/A` por `-` como _default/fallback_ en caso un dato no exista o no se haya obtenido.
- Añadido al _footer_ de la vista principal la fecha de construcción de las MMDB.

### v0.15.1

- Generación de enlace de _OpenStreetMap_ con círculo correspondiente al radio de precisión dado por la base MMDB.

### v0.15.0

- Añadida la sección _IP info_ a la vista principal, que muestra los datos de `/ip/detail` de las versiones obtenidas.
- Generación de enlace de [_OpenStreetMap_](https://www.openstreetmap.org/) para las coordenadas de _location_ de la IP.
- Añadido al _footer_ de la vista principal las atribuciones de los datos obtenidos.

### v0.14.0

- Actualizado la dependencia de UI-Kit.
- Implementada la _RAW VIEW_ en la GUI, para ver los JSON crudos desde la web, sin el inspector.

### v0.13.0

- Añadido _DNS leak test_ en la web principal. Solo lógica, sin cambios visuales.
- Deduplicación de las atribuciones de las fuentes.
- Añadido lógica de obtención de `/client/headers` en la web principal.
- Añadido lógica de procesamiento para el _RDAP_ en la web principal.
- La web principal consulta ambas versiones de IP, parecido a _happy eyeballs_.
- Deduplicación de resultados del _DNS leak test_ por resolvers conocidos, obtenidos de las fuentes oficiales y descargado por el mismo sistema que el _RDAP Bootstrap_.

### v0.12.2

- Bug corregido de excepción en _logger_ en nivel `DEBUG`.

### v0.12.1

- Actualización de dependencias (UI kit).
- Cambios menores en el _logger_ para `DEBUG`.

### v0.12.0

- Añadida la medida `RTT` a nivel de datos. No hay cambios en la GUI.

### v0.11.0

- Creación de la GUI principal.
- Muestra IPv4 y/o IPv6 según disponibilidad.

### v0.10.1

- Correcciones menores en las políticas CORS.
- Habilitación de respuesta `OPTIONS`.

### v0.10.0

- Deshabilita la documentación de FastAPI por defecto.
- Permite habilitar la documentación de FastAPI desde la variable de entorno `ENABLE_DOCS`
- Permite añadir rangos CIDR y _headers_ confiables desde las variables de entorno `TRUSTED_PROXIES` y `TRUSTED_HEADERS`.
- Añadido `/download`: Genera un _stream_ incompresible de entre 1B y 500MiB para descarga.
- Añadido `/upload`: Recibe un _stream_ de datos que se drena sin almacenar.

### v0.9.0

- Deduplicación de las IPs, CIDRs y ASNs que devuelve el _DNS leak test_.

### v0.8.2

- Cambios menores en la extracción de la IP de la cabecera `X-Forwarded-For`.

### v0.8.1

- Cambios menores en el _middleware_ de la API para acoplarse al sistema de registros actuales.

### v0.8.0

- Reemplazo del registro por defecto de _Uvicorn_ por registros por _logger_ de Python.

### v0.7.3

- Corregido bugs menores de escritura en el _RDAP Bootstrap_.

### v0.7.2

- Servidor DNS descarta las peticiones sin el _Proxy Protocol header_.
- Servidor DNS no registra las IPs invalidas (privadas o mal formadas).

### v0.7.1

- Cambios menores en los registros y sus niveles.

### v0.7.0

- Creado el servidor DNS para los _Leak DNS Test_.
- Añadido `/dns-leak/{test_id}`: Devuelve los detalles de las IPs que realizaron las consultas DNS al servidor con el ID correspondiente.

### v0.6.1

- Añadido políticas de _Cross Timing_ autorizadas para `MAIN_HOST`.

### v0.6.0

- Añadido políticas de caché la web principal y los resultados de API.
- Añadido políticas CORS autorizadas para `MAIN_HOST`.

### v0.5.1

- Actualizado ruta del `Caddyfile` en `web/Dockerfile`.

### v0.5.0 (fallido)

- Añadido _rate limit_ a nivel de proxy para toda la API, excepto por `/ready` e `/info`.

### v0.4.1

- Creado lista negra de _endpoints_ que no pasan por el _middleware_: `/ready` y `/info`.

### v0.4.0

- Añadido RDAP BOOTSTRAP: Devuelve la URL correspondiente a la consulta RDAP de la IP según la IANA.
- Actualización periódica del RDAP BOOTSTRAP en base a la caché y _max-age_ declarado por el servidor de la IANA.
- Añadido `/all` como alias de `/ip/all` y `/client/all`.
- Removido del proxy inverso la cabecera `X-Client-XFF`.

### v0.3.2

- Removido `X-Forwarded-For` y `X-Client-XFF` de la lista blanca de cabeceras por no aportar info util, al ser sobre-escrita por los proxies superiores.

### v0.3.1

- Removida la confianza en `CF-Connecting-IP` por defecto.

### v0.3.0

- Añadido `/ip/details` como alias de `/ip/detail`.
- Añadido `/client/headers`: Devuelve los _headers_ enviados por el cliente, filtrados por lista blanca.
- Añadido `/client/all` e `/ip/all`: Devuelve el contenido de `/ip/detail` y de `/client/headers` en uno solo.
- Añadida la cabecera `X-Client-XFF` con el contenido original de `X-Forwarded-For`.

### v0.2.1

- Habilitación de `/info` como _endpoint_ de API.

### v0.2.0

- Soporte para las bases MMDB CITY y ASN ([MaxMind GeoLite2](https://www.maxmind.com)) y reemplazo en caliente por el contenedor de actualización oficial.
- Añadido `/ready`: Verifica que las bases MMDB sean funcionales.
- Añadido `/info`: Devuelve las _build epoch_ de las bases MMDB.
- Añadido `/ip/detail`: Devuelve la info de la IP obtenida de las bases MMDB.
- Proxy inverso sobre-escribe `X-Forwarded-For` con `{client_ip}`.

### v0.1.1

- Agregado _endpoint_ de health `/ready`.

### v0.1.0

- Refleja IP del cliente en `/ip` y en `/` de los hosts de IP dedicados.
- No redirige a HTTPS en los hosts de IP dedicados (IPv4 e IPv6).
- No redirige a HTTPS con USER-AGENT curl, wget, python, httpie, aria2 y vacío.
- Proxy inverso confía en `CF-Connecting-IP` y `X-Forwarded-For` desde rangos CIDR privados.
