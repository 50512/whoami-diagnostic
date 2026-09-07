# Herramienta de diagnostico interno + whoami

Esta herramienta es un whoami (te dice tu IP pública, tanto IPv4 como IPv6) pero con algunos adicionales que la vuelven útil para diagnostico de red propia (DNS leak) como de infraestructura (RTT hacia el host de la app)

## Funcionalidades

Este es un placeholder solo para saber la parte avanzada hasta el momento, conforme se añadan más funciones se ira expandiendo la descripción y marcando el avance.

- [x] Limitar el reflejo puro solo para herramientas cli, UA vació u endpoint `/ip`.
- [x] No redirigir a https herramientas cli o endpoint `/ip` (no siguen las re-direcciones por defecto).
- [x] Raíz de diag sirve html, pero si detecta cli, acepta http y refleja IP (equivalente a `/ip`).
- [x] https forzado para todos los demás accesos.
- [x] implementar mmdb para datos de IP (front solo pide IPv4 detail).
- [ ] Rate limit para todos los endpoints (FastAPI con slowapi).
- [ ] DualSocket (viene dictado por el proxy superior).
- [ ] Asegurar CORS para los endpoints fuera de diag.
- [ ] IPv4, IPv6 y diag comparten endpoints, el front decide solo pedir detalles a IPv4 por estabilidad.
- [ ] Endpoints comunes: `/ip` -> refleja IP plana siempre, `/ip/detail` devuelve JSON con datos de mmdb, `/ip/full` devuelve todo lo anterior + UA y headers del cliente. `/ready` para declarar estado listo para recibir peticiones. Todos estos soportan http y https para cli.
- [ ] Endpoints exclusivos de diag: `/dns-leak/{uuid}` devuelve la IP obtenida en redis o 404 en caso no existir registro (front intenta 3 peticiones).
- [ ] Fallback ordenado ipv4 -> ipv6 (si falla ipv4, pide full de ipv6)
- [ ] DNS Leak, solo responde a A y AAAA, rechaza cualquier otro formato, limitado por IP.
- [ ] Redis de DNS Leak limitado a memoria 2M y solo 1 min de TTL.
- [ ] RTT se mide en el cliente, depende del front.
