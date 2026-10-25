import { hidePlaceholders, unhideAll } from "./lib/dom";
import { measureRTT } from "./lib/net";

/** Estructura de RTT Data */
interface RTTData {
  ipv4: number | null;
  ipv6: number | null;
  host: number | null;
  realtime: number | null;
}

/** Para pasar las claves a strings dedicadas */
const rttKeyString = {
  ipv4: "IPv4",
  ipv6: "IPv6",
  host: "HOST",
  realtime: "EDGE-RT",
} as const;

/** Máximo de 8s para medida externa */
const MAX_TIMEOUT = 8000;

/**
 * Realiza una petición al endpoint `realtime` y devuelve la medida RTT
 */
export async function measureRealtimeEndpoint(
  ctrlSignal: AbortSignal | null = null,
): Promise<number | null> {
  if (!window.__ENV__.REALTIME_URL) return null;
  const signals = [AbortSignal.timeout(MAX_TIMEOUT)];
  if (ctrlSignal) signals.push(ctrlSignal);
  const signal = AbortSignal.any(signals);
  try {
    const res = await fetch(window.__ENV__.REALTIME_URL, {
      cache: "no-store",
      signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await res.text();
  } catch (err) {
    console.error("Error al medir realtime", err);
    return null;
  }
  return measureRTT(window.__ENV__.REALTIME_URL);
}

/**
 * Escribe la información de las métricas
 */
export function renderMetrics(data: RTTData) {
  hidePlaceholders(".rtt-info-block");

  const rttStrings: Array<string> = [];

  Object.entries(data).forEach(([key, rtt]) => {
    const label = rttKeyString[key as keyof typeof rttKeyString];
    if (rtt && label) {
      rttStrings.push(`${label}:${rtt}ms`);
    }
  });

  unhideAll(".rtt-info-block>.empty-line");

  const rttEle = document.querySelector(`#rtt-block>.empty-line`);
  if (!rttEle) return;
  if (rttStrings.length > 0) rttEle.textContent = rttStrings.join(" | ");
  else rttEle.textContent = "-";
}
