import { measureRTT, fetchJSON } from "./lib/net";
import type { JsonViewElement } from "@50512/ui/json";
import { hidePlaceholders, unhideAll } from "./lib/dom";

/** Estructura de salida de la API */
interface HeadersAPIResult {
  headers: HeadersInfo;
}

/** Estructura de los headers usados en el front */
interface HeadersInfo {
  "user-agent"?: string;
  "accept-language"?: string;
  "sec-ch-ua"?: string;
  "sec-ch-ua-platform"?: string;
  [key: string]: string | undefined;
}

/** Estructura de resultado de fetch a cabeceras del cliente (headers + RTT) */
interface HeadersFetchResult {
  headers: HeadersInfo | null;
  rtt: number | null;
}

/**
 * Plantilla de bloques de cabeceras
 */
const headersTemplates: Record<string, (data: HeadersInfo) => string> = {
  "ua-block": (data) => data["user-agent"] ?? "-",

  "language-block": (data) =>
    data["accept-language"]
      ?.split(",")
      .map((lang) => lang.split(";")[0].trim())
      .join(", ") ?? "-",

  "sec-ch-ua-block": (data) =>
    data["sec-ch-ua"]
      ?.replaceAll('"', "")
      .replaceAll(";", " ")
      .replaceAll("=", "") ?? "-",

  "sec-ch-ua-platform-block": (data) =>
    data["sec-ch-ua-platform"]?.replaceAll('"', "") ?? "-",
};

/**
 * Obtiene los datos de las cabeceras de los clientes y los escribe en pantalla
 */
export async function loadClientHeaders(
  signal: AbortSignal | null = null,
): Promise<HeadersFetchResult> {
  const data = await getClientHeaders(signal);
  renderHeaders(data);
  return data;
}

/**
 * Devuelve las cabeceras recibidas por el servidor con la medida RTT
 * por el host actual/principal
 */
export async function getClientHeaders(
  signal: AbortSignal | null = null,
): Promise<HeadersFetchResult> {
  const results: HeadersFetchResult = {
    headers: null,
    rtt: null,
  };

  const url = "/client/headers";
  const headers = await fetchJSON<HeadersAPIResult>(url, { signal });

  if (headers) results.headers = headers.headers;
  results.rtt = measureRTT(url);

  return results;
}

/**
 * Escribe las cabeceras en el bloque correspondiente
 */
export function renderHeaders(headers: HeadersFetchResult) {
  const clientHeaders = document.getElementById(
    "raw-client-headers",
  ) as JsonViewElement | null;

  if (clientHeaders) clientHeaders.data = headers;

  hidePlaceholders(".client-info-block");

  unhideAll(".client-info-block>.empty-line");

  Object.entries(headersTemplates).forEach(([id, formatter]) => {
    const target = document.querySelector(
      `#${id}>.empty-line`,
    ) as HTMLSpanElement | null;
    if (target)
      target.textContent =
        headers.headers != null ? formatter(headers.headers) : "-";
  });
}
