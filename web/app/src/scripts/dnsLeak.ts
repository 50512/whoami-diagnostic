import type { JsonViewElement } from "@50512/ui/json";
import type { IPGeolocation } from "./ip";
import type { Attributions } from "./meta";
import { fetchJSON } from "./lib/net";
import { hidePlaceholders, unhideAll } from "./lib/dom";

/** Estructura de filtraciones ECS */
interface ECSLeak {
  ecs_cidr: string;
  asn: number | null;
  asn_org: string | null;
  cidr: string | null;
  geolocation: IPGeolocation;
}

/** Estructura de información de los resolvers detectados por DNS leak */
interface ResolverInfo {
  asns: Array<number> | null;
  asns_org: Array<string> | null;
  ips: Array<string> | null;
  cidrs: Array<string> | null;
  ecs: Array<ECSLeak>;
}

/** Estructura de información de la API de DNS leak */
export interface DNSLeak {
  test_id: string;
  count: number;
  resolvers: Record<string, ResolverInfo>;
  attributions: Record<string, Attributions> | null;
}

/**
 * Obtiene los datos de DNS Leak y los dibuja en pantalla
 */
export async function loadDNSLeak(): Promise<DNSLeak | null> {
  const data = await getDNSLeak();
  renderDNSLeak(data);
  return data;
}

/**
 * Ejecuta las peticiones al UUID en la zona de leak DNS y luego consulta
 * al endpoint del leak la información de los resolvers que consultaron el
 * UUID
 */
export async function getDNSLeak(): Promise<DNSLeak | null> {
  const test_id = crypto.randomUUID().replaceAll("-", "");
  let results: DNSLeak | null = null;

  for (let j = 0; j < 4; j++) {
    const signal = AbortSignal.timeout(2500);
    const requests = [];

    for (let i = 0; i < 10; i++) {
      const url = `https://${j}.${i}.${test_id}.${window.__ENV__.LEAK_ZONE}`;
      requests.push(
        fetch(url, {
          mode: "no-cors",
          signal,
        }).catch(() => {}),
      );
    }

    await Promise.allSettled(requests);
  }

  results = await fetchJSON<DNSLeak>(`/dns-leak/${test_id}`);

  return results;
}

/**
 * Escribe las filtraciones DNS + ECS
 */
export function renderDNSLeak(leak: DNSLeak | null) {
  const dnsLeakElement = document.getElementById(
    "raw-dns-leak",
  ) as JsonViewElement | null;

  if (!leak || leak.count <= 0)
    return document
      .querySelectorAll(".dns-info-block>.placeholder")
      .forEach((ele) => ele.replaceChildren("-"));
  if (dnsLeakElement) dnsLeakElement.data = leak;

  hidePlaceholders(".dns-info-block");
  unhideAll(".dns-info-block>.empty-line");

  document
    .querySelectorAll(".dns-info-block>.empty-line")
    .forEach((ele) => ele.replaceChildren(""));

  const ecsCache: Record<string, Array<ECSLeak>> = {};
  Object.entries(leak.resolvers).map(([key, value]) => {
    const resolverLine = document.createElement("span");

    let asnOrgs: Array<string> | null = null;
    let partners: string | null = null;
    if (value.asns_org && value.asns_org.length > 0) asnOrgs = value.asns_org;

    if (asnOrgs) {
      asnOrgs = asnOrgs.filter((item) => item !== key);
      if (asnOrgs.length > 0) partners = `(${asnOrgs.join(", ")})`;
    }

    resolverLine.textContent = `${key} ${partners ?? ""}`;
    document
      .querySelector("#resolvers-block>.empty-line")
      ?.appendChild(resolverLine);

    if (value.ecs.length > 0) {
      ecsCache[key] = value.ecs;
    }
  });

  const ecsCacheList = Object.entries(ecsCache);
  if (ecsCacheList.length <= 0)
    return document
      .querySelector("#ecs-block>.empty-line")
      ?.replaceChildren("-");
  ecsCacheList.forEach(([resolver, ecsList]) => {
    ecsList.forEach((ecs) => {
      const ecsLine = document.createElement("span");
      ecsLine.textContent = `${resolver}: ${ecs.ecs_cidr} - ${ecs.geolocation.country.name ?? "-"}/${ecs.geolocation.region ?? "-"}/${ecs.geolocation.city ?? "-"}`;

      document.querySelector("#ecs-block>.empty-line")?.appendChild(ecsLine);
    });
  });
}
