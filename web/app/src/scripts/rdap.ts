import { type IPVersion, IP_VERSIONS, type IPDetail } from "./ip";
import type { JsonViewElement } from "@50512/ui/json";
import { hidePlaceholders, unhideAll } from "./lib/dom";

/** Estructura de información de RDAP (solo datos utilizados en el script) */
interface RDAPInfo {
  registrant: string | null;
  network: string | null;
}

/** Estructura del objeto Cidr0 de RDAP */
interface RDAPCidr0 {
  v4prefix?: string;
  v6prefix?: string;
  length: number;
}

/** Estructura de entidad RDAP */
interface RDAPEntity {
  handle: string | null;
  roles: Array<string>;
  vcardArray: {
    0: "vcard";
    1: Array<Array<string | Object | Array<string>>>;
  } | null;
}

/** Estructura de respuesta de RDAP acotado al uso del script */
interface RDAPResponse {
  name: string | null;
  cidr0_cidrs: Array<RDAPCidr0> | null;
  startAddress: string;
  endAddress: string;
  handle: string | null;
  entities: Array<RDAPEntity> | null;
}

/** Resultados de peticiones hacia RDAP */
interface RDAPFetchResults {
  data: RDAPResponse | null;
  url: string | null;
}

/**
 * Plantilla de bloques de RDAP procesado
 */
const propertyTemplatesRDAP: Record<string, (data: RDAPInfo) => string> = {
  "registrant-block": (data) => data.registrant ?? "-",
  "rdap-net-block": (data) => data.network ?? "-",
};

/**
 * Obtiene los datos RDAP y los dibuja en pantalla
 */
export async function loadRDAPInfo(
  data: Record<IPVersion, IPDetail | null>,
): Promise<Record<IPVersion, RDAPFetchResults>> {
  const RDAPData = await getRDAPInfo(data);
  renderRDAP(RDAPData);
  return RDAPData;
}

/**
 * Regresa el RDAP completo de las IPs
 */
export async function getRDAPInfo(
  data: Record<IPVersion, IPDetail | null>,
): Promise<Record<IPVersion, RDAPFetchResults>> {
  const results: Record<IPVersion, RDAPFetchResults> = {
    ipv4: { data: null, url: null },
    ipv6: { data: null, url: null },
  };
  await Promise.all(
    IP_VERSIONS.map(async (version) => {
      const currentVersion = data[version];
      if (!currentVersion || !currentVersion.rdap_url) return;
      const url = currentVersion.rdap_url;

      try {
        const res = await fetch(url);
        results[version].url = url;
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        results[version].data = (await res.json()) as RDAPResponse;
      } catch (err) {
        console.error(`No se pudo obtener RDAP de ${version}: ${err}`);
      }
    }),
  );
  return results;
}

/**
 * Extrae de la respuesta original el RDAP Net y RDAP Registrant
 */
function extractRDAP(
  rdapRaw: Record<IPVersion, RDAPFetchResults>,
): Record<IPVersion, RDAPInfo> {
  const results: Record<IPVersion, RDAPInfo> = {
    ipv4: {
      registrant: null,
      network: null,
    },
    ipv6: {
      registrant: null,
      network: null,
    },
  };

  IP_VERSIONS.map(async (version) => {
    const currentVersion = rdapRaw[version];
    if (!currentVersion || !currentVersion.data) return;
    try {
      results[version].registrant = extractRDAPRegistrant(currentVersion.data);
      results[version].network = extractRDAPNetwork(currentVersion.data);
    } catch (err) {
      console.error(`No se pudo obtener RDAP de ${version}: ${err}`);
    }
  });

  return results;
}

/**
 * Extrae el `registrant` de la respuesta RDAP. No se garantiza funcionalidad total.
 */
function extractRDAPRegistrant(info: RDAPResponse): string | null {
  let registrant = null;

  if (!info.entities || !Array.isArray(info.entities)) return null;

  const relevantEntity = info.entities.find(
    (e) => e.roles && e.roles.includes("registrant"),
  );

  if (relevantEntity && relevantEntity.vcardArray) {
    const attributes = relevantEntity.vcardArray[1];
    const attrName = attributes.find((attr) => attr[0] == "fn");

    if (attrName && attrName[3]) registrant = (attrName[3] as string).trim();
  }

  return registrant;
}

/**
 * Obtiene el bloque de red desde RDAP
 */
function extractRDAPNetwork(info: RDAPResponse): string | null {
  let network = null;
  // Apostar por bloque existente
  if (info.cidr0_cidrs && info.cidr0_cidrs.length > 0) {
    const block = info.cidr0_cidrs[0];
    const ipBase = block.v4prefix || block.v6prefix;
    if (ipBase && block.length) return `${ipBase}/${block.length}`;
  }

  // Fallback
  const cidrRegex = /([0-9a-f:\.]+)\/([0-9]{1,3})/i;
  if (info.handle && cidrRegex.test(info.handle)) {
    let match = info.handle.match(cidrRegex);
    if (match) return match[0];
  }
  if (info.name && cidrRegex.test(info.name)) {
    let match = info.name.match(cidrRegex);
    if (match) return match[0];
  }

  if (info.startAddress && info.endAddress)
    return `${info.startAddress} - ${info.endAddress}`;

  return network;
}

/**
 * Escribe la data de RDAP (bloque procesado e información cruda)
 */
export function renderRDAP(rdap: Record<IPVersion, RDAPFetchResults>) {
  const rawElement = document.getElementById(
    "raw-rdap",
  ) as JsonViewElement | null;
  const rawInfoElement = document.getElementById(
    "raw-registrant-rdap",
  ) as JsonViewElement | null;

  const rdapInfo = extractRDAP(rdap);
  if (rawElement) rawElement.data = rdap;
  if (rawInfoElement) rawInfoElement.data = rdapInfo;

  hidePlaceholders(".rdap-info-block");

  IP_VERSIONS.forEach((version) => {
    const currentDataRaw = rdap[version].data;
    const currentDetail = rdapInfo[version];

    if (!currentDataRaw) return;

    unhideAll(`.rdap-info-block>.${version}`);

    // Ejecuta las templates en cada bloque
    Object.entries(propertyTemplatesRDAP).forEach(([id, formatter]) => {
      const target = document.querySelector(
        `#${id}>.${version}>.block-content`,
      ) as HTMLSpanElement | null;
      if (target) target.textContent = formatter(currentDetail);
    });
  });
}
