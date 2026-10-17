/**
 * Mide el _Round Trip Time_ de una petición efectuada a la URL ingresada
 */
export function measureRTT(url: string): number | null {
  const absoluteUrl = new URL(url, window.location.origin).href;

  const entries = performance.getEntriesByName(
    absoluteUrl,
    "resource",
  ) as PerformanceResourceTiming[];
  const metric = entries[entries.length - 1];

  if (!metric) return null;

  if (metric.responseStart > 0 && metric.requestStart > 0)
    return Math.round(metric.responseStart - metric.requestStart);

  return null;
}

/**
 * Devuelve el `JSON|null` hacia la URL asignada.
 */
export async function fetchJSON<T>(
  url: string,
  init?: RequestInit,
): Promise<T | null> {
  try {
    const res = await fetch(url, init);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as T;
  } catch (err) {
    console.error(`Error al obtener ${url}`, err);
    return null;
  }
}
