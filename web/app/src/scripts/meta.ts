import type { JsonViewElement } from "@50512/ui/json";

import { type IPVersion, type IPDetail } from "./ip";
import type { DNSLeak } from "./dnsLeak";
import { fetchJSON } from "./lib/net";

/** Estructura de atribuciones para cumplir con los ToS de algunas DB */
export interface Attributions {
  source: string;
  text: string;
  url: string;
}

/** Interfaz de `/info` de la API */
interface MetaAPI {
  status: string;
  asn_last_update: string;
  city_last_update: string;
}

/**
 * Obtiene los metadatos de la API y los dibuja en pantalla
 */
export async function loadMetadata(
  signal: AbortSignal | null = null,
): Promise<MetaAPI | null> {
  const data = await getMetaAPI(signal);
  if (data) renderMetadata(data);
  return data;
}

/**
 * Obtiene la metadata de la API (estado y última actualización)
 */
export async function getMetaAPI(
  signal: AbortSignal | null = null,
): Promise<MetaAPI | null> {
  return await fetchJSON<MetaAPI>("/info", { signal });
}

/**
 * Extrae las atribuciones y las dibuja en pantalla
 */
export function loadAttributions(
  data: Record<IPVersion | string, IPDetail | DNSLeak | null>,
) {
  const attributions = readAttributions(data);
  if (attributions) renderAttributions(attributions);
}

/**
 * Recibe un objeto que contenga información `IPDetail` o `DNSLeak` y
 * devuelve sus atribuciones únicas (para cumplimiento de ToS de algunas fuentes)
 */
export function readAttributions(
  data: Record<IPVersion | string, IPDetail | DNSLeak | null>,
): Record<string, Attributions> | null {
  const attributions: Record<string, Attributions> | null = {};

  Object.values(data).map((value) => {
    if (!value || !value.attributions) return;
    const attr_value = value.attributions;
    Object.keys(attr_value).map((key) => {
      if (!attr_value[key]) return;
      attributions[key] = attr_value[key];
    });
  });

  return attributions;
}

/**
 * Escribe el small inferior de atribuciones
 */
export function renderAttributions(attributions: Record<string, Attributions>) {
  const attrEle = document.getElementById("attributions");
  if (!attrEle) return;
  const lines: Array<HTMLAnchorElement> = [];
  Object.values(attributions).forEach((v) => {
    const anchor = document.createElement("a");

    anchor.href = v.url;
    anchor.textContent = v.text;
    anchor.target = "_blank";

    lines.push(anchor);
  });

  attrEle.replaceChildren(...lines);
}

/**
 * Escribe el small inferior de metadata
 */
export function renderMetadata(data: MetaAPI) {
  const rawElement = document.getElementById(
    "raw-metadata",
  ) as JsonViewElement | null;

  if (rawElement) rawElement.data = data;

  const metaEle = document.getElementById("metadata");
  if (!metaEle) return;

  let text = "Datos: ";

  Object.entries(data).forEach(([k, v]) => {
    if (k == "status") return;

    const name = k.split("_")[0].toUpperCase();
    const date = new Date(v);

    const year = date.getUTCFullYear();
    const month = String(date.getUTCMonth() + 1).padStart(2, "0");
    const day = String(date.getUTCDate()).padStart(2, "0");

    text += `${name}-${year}.${month}.${day} `;
  });

  metaEle.textContent = text;
}
