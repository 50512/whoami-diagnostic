import { type IPVersion, type IPFetchResult } from "./ip";
import { hidePlaceholders, unhideAll } from "./lib/dom";

/** Interfaz del resultado de /speed/start */
interface SpeedStart {
  conns: number;
  ttl: number;
  max_size: number;
}

/**
 * Setea la cookie de speedtest y regresa los datos de la cookie
 */
async function getSpeedToken(
  version: IPVersion,
  conns: number,
): Promise<SpeedStart | null> {
  let results: SpeedStart | null = null;

  const FETCH_URLS = {
    ipv4: `https://${window.__ENV__.IPV4_HOST}/speed/start?conns=${conns}`,
    ipv6: `https://${window.__ENV__.IPV6_HOST}/speed/start?conns=${conns}`,
  };

  try {
    const res = await fetch(FETCH_URLS[version], {
      credentials: "include",
      method: "POST",
    });
    results = (await res.json()) as SpeedStart;
  } catch (err) {
    console.error("Error al obtener el token del speedtest", err);
  }

  return results;
}

/**
 * Activa el botón de speedtest y prepara los resultados
 */
export function initSpeedtest(data: Record<IPVersion, IPFetchResult>) {
  if (!data.ipv4.data && !data.ipv6.data) return;
  hidePlaceholders(".speed-info-block");
  unhideAll(".speed-info-block>.empty-line");

  let speedTargetVersion: IPVersion | null = null;

  // El target del test es el que tenga menor RTT de ser posible
  if (data.ipv4.rtt && data.ipv6.rtt)
    speedTargetVersion = data.ipv4.rtt < data.ipv6.rtt ? "ipv4" : "ipv6";
  else if (data.ipv4.data || data.ipv6.data)
    speedTargetVersion = data.ipv4.data != null ? "ipv4" : "ipv6";

  if (!speedTargetVersion)
    return document
      .querySelector("#speed-block>.empty-line")
      ?.replaceChildren("-");

  const speedtestButton = document.querySelector(
    "#speed-block>.empty-line>button",
  ) as HTMLButtonElement | null;
  if (!speedtestButton) return;

  speedtestButton.addEventListener("click", async () => {
    const data = await getSpeedToken(speedTargetVersion, 1);
    console.log(data);
  });
}
