/**
 * Oculta `.placeholder` del elemento apuntado por el selector
 */
export function hidePlaceholders(selector: string) {
  document
    .querySelectorAll(`${selector} .placeholder`)
    .forEach((ele) => ele.classList.add("hidden"));
}

/**
 * Remueve la clase `.hidden` a todos los elementos que
 * coinciden con el selector
 */
export function unhideAll(selector: string) {
  document
    .querySelectorAll(selector)
    .forEach((ele) => ele.classList.remove("hidden"));
}
