# Herramienta de diagnostico interno + whoami

Esta herramienta es un whoami (te dice tu IP pública, tanto IPv4 como IPv6) pero con algunos adicionales que la vuelven útil para diagnostico de red propia (DNS leak) como de infraestructura (RTT hacia el host de la app)

## Funcionalidades

Este es un placeholder solo para saber la parte avanzada hasta el momento, conforme se añadan más funciones se ira expandiendo la descripción y marcando el avance.

- [x] Limitar el reflejo puro solo para herramientas cli, UA vació u endpoint `/ip`.
- [x] No redirigir a https herramientas cli o endpoint `/ip` (no siguen las re-direcciones por defecto).
- [x] Raíz de diag sirve html, pero si detecta cli, acepta http y refleja IP (equivalente a `/ip`).
- [x] https forzado para todos los demás accesos.
- [x] implementar mmdb para datos de IP (front solo pide IPv4 detail).
- [x] DualSocket (viene dictado por el proxy superior).
- [x] IPv4, IPv6 y diag comparten endpoints, el front decide solo pedir detalles a IPv4 por estabilidad.
- [x] Endpoints comunes: `/ip` -> refleja IP plana siempre, `/ip/detail` devuelve JSON con datos de mmdb, `/ip/full` devuelve todo lo anterior + UA y headers del cliente. `/ready` para declarar estado listo para recibir peticiones. Todos estos soportan http y https para cli.
- [x] 400 en IP privada
- [x] Rate limit para todos los endpoints ~~(FastAPI con slowapi)~~ de la API a nivel de _reverse proxy_.
- [x] Asegurar CORS para los endpoints fuera de diag.
- [x] Caché efímera en los endpoints API. Caché estática para el front estático
- [x] DNS Leak, solo responde a A y AAAA, rechaza cualquier otro formato, limitado por IP (nftables en nodo edge).
- [x] `/dns-leak/{uuid}` devuelve la IP obtenida en redis o 404 en caso no existir registro (front intenta 3 peticiones).
- [x] Redis de DNS Leak limitado a memoria 64mb y solo 1 min de TTL.
- [x] Mini refactor a Routes.
- [x] Dedup de DNSLeak en base a ASN/Network. Añadir lista de IPs detectadas.
- [x] Speedtest. ~~Archivo estático~~ Endpoint que genera basura para descarga y endpoint POST vacío para subida. Medición de múltiples conexiones paralelas desde el front.
- [x] Front siempre pide `/ip/detail` para ipv4 e ipv6, se muestra ambos campos.
- [x] Front muestra en grande IPv4, de no existir, se reemplaza por IPv6.
- [x] Front consulta y parsea RDAP vCard para obtener sub-asignación.
- [x] Front pide headers por `diag.50512.dev/client/headers`.
- [x] RTT se mide en el cliente, depende del front. Se mide para cada petición (`ipv4`, `ipv6`, `diag/headers`)
- [ ] Front muestra las secciones: IP Info (cada linea con las ips obtenidas), Sub-asignación (desde RDAP), DNS Leak (ASN Resolvers), botón de speedtest (RX/TX)
