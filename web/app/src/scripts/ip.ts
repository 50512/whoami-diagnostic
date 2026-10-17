import type { JsonViewElement } from "@50512/ui/json";
import { type Attributions } from "./meta";
import { measureRTT, fetchJSON } from "./lib/net";
import { hidePlaceholders, unhideAll } from "./lib/dom";

export const IP_VERSIONS = ["ipv4", "ipv6"] as const;
export type IPVersion = (typeof IP_VERSIONS)[number];

/** Estructura de información de geolocation por MaxMind */
export interface IPGeolocation {
  country: {
    name: string | null;
    iso_code: string | null;
  };
  region: string | null;
  city: string | null;
  continent_code: string | null;
  zip_code: string | null;
}

/** Estructura de coordenadas y radio de precisión para location por MaxMind */
interface IPLocation {
  latitude: number | null;
  longitude: number | null;
  accuracy_radius: number | null;
  timezone: string | null;
}

/** Estructura de información detallada de IP */
export interface IPDetail {
  ip: string;
  asn: number | null;
  asn_org: string | null;
  cidr: string | null;
  geolocation: IPGeolocation;
  location: IPLocation;
  attributions: Record<string, Attributions> | null;
  rdap_url: string | null;
}

/** Estructura de resultado de fetch a detalle de una IP (data + RTT) */
export interface IPFetchResult {
  data: IPDetail | null;
  rtt: number | null;
}

/**
 * Plantilla de bloques de IP info simples
 */
const propertyTemplatesIP: Record<string, (data: IPDetail) => string> = {
  "asn-block": (data) => `AS${data.asn ?? "-"} - ${data.asn_org ?? ""}`,
  "cidr-block": (data) => data.cidr ?? "-",
  "geo-block": (data) =>
    `${data.geolocation.country.name ?? "-"}/${data.geolocation.region ?? "-"}/${data.geolocation.city ?? "-"}`,
  "tz-block": (data) => data.location.timezone ?? "-",
  "zip-block": (data) => data.geolocation.zip_code ?? "-",
};

/**
 * Obtiene los datos de IP de la API y los dibuja en pantalla
 */
export async function loadIPInfo(): Promise<Record<IPVersion, IPFetchResult>> {
  const data = await getIPInfo();
  renderIPHeader(data);
  renderIPInfo(data);
  return data;
}

/**
 * Regresa el objeto de resultados para las peticiones detalladas de IPv4 e IPv6 con la medida RTT
 */
export async function getIPInfo(): Promise<Record<IPVersion, IPFetchResult>> {
  const results: Record<IPVersion, IPFetchResult> = {
    ipv4: {
      data: null,
      rtt: null,
    },
    ipv6: {
      data: null,
      rtt: null,
    },
  };

  const FETCH_URLS = {
    ipv4: `https://${window.__ENV__.IPV4_HOST}/ip/detail`,
    ipv6: `https://${window.__ENV__.IPV6_HOST}/ip/detail`,
  };

  const HARD_TIMEOUT_MS = 8000;
  const GRACE_MS = 1500;

  const grace = new AbortController();
  let graceTimer: number | undefined;

  await Promise.all(
    IP_VERSIONS.map(async (version) => {
      const url = FETCH_URLS[version];
      const signal = AbortSignal.any([
        grace.signal,
        AbortSignal.timeout(HARD_TIMEOUT_MS),
      ]);

      const data = await fetchJSON<IPDetail>(url, { signal });
      const rtt = measureRTT(url);
      results[version] = { data, rtt };
      graceTimer ??= window.setTimeout(() => grace.abort(), GRACE_MS);
    }),
  );

  return results;
}

/**
 * Escribe toda la info de IP
 */
export function renderIPInfo(data: Record<IPVersion, IPFetchResult>) {
  const rawElement = document.getElementById(
    "raw-ip-detail",
  ) as JsonViewElement | null;
  if (rawElement) rawElement.data = data;

  hidePlaceholders(".ip-info-block");

  IP_VERSIONS.forEach((version) => {
    const currentDetail = data[version].data;

    // Solo muestra la versión si esta disponible
    if (!currentDetail) return;
    unhideAll(`.ip-info-block>.${version}`);

    // Ejecuta las templates en cada bloque
    Object.entries(propertyTemplatesIP).forEach(([id, formatter]) => {
      const target = document.querySelector(
        `#${id}>.${version}>.block-content`,
      ) as HTMLSpanElement | null;
      if (target) target.textContent = formatter(currentDetail);
    });

    renderLocation(currentDetail, version);
  });
}

/**
 * Escribe las IP a la cabecera de la vista principal
 */
function renderIPHeader(data: Record<IPVersion, IPFetchResult>) {
  const mainIP = document.getElementById("ip-h2");
  const secondIP = document.getElementById("ip-h3");
  const { ipv4, ipv6 } = data;

  if (!mainIP || !secondIP) return;
  // Si no hay IPv4, se pone IPv6 en principal
  if (ipv4.data) mainIP.textContent = ipv4.data.ip;
  else if (ipv6.data) mainIP.textContent = ipv6.data.ip;

  // Si hay IPv4 e IPv6, pone la IPv6 en la 2da linea
  if (ipv6.data && ipv4.data) {
    secondIP.textContent = ipv6.data.ip;
    secondIP.classList.remove("hidden");
  }
}

/**
 * Escribe los enlaces posición en su bloque
 */
function renderLocation(data: IPDetail, version: IPVersion) {
  const { latitude, longitude, accuracy_radius } = data.location;
  const locationElement = document.querySelector(
    `#loc-block>.${version}>.block-content`,
  ) as HTMLSpanElement | null;

  if (!locationElement) return;
  if (latitude == null || longitude == null)
    return locationElement.replaceChildren("-");

  const url = genLinkOSM(latitude, longitude, accuracy_radius);

  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.target = "_blank";
  anchor.textContent = `${latitude}, ${longitude} ±${accuracy_radius ?? 50}Km`;
  anchor.classList.add("location-link");

  locationElement.replaceChildren(anchor);
}

/**
 * Genera el enlace para OpenStreetMap con los parámetros definidos
 */
function genLinkOSM(
  latitude: number,
  longitude: number,
  accuracy_radius: number | null,
): string {
  const radius = accuracy_radius ?? 50;
  const params = new URLSearchParams({
    geouri: `geo:${latitude},${longitude};u=${radius * 1000}`,
  });
  return `https://www.openstreetmap.org/?${params}`;
}
