"use strict";
(() => {
  const data = JSON.parse(document.getElementById("guide-data").textContent);
  const panels = [...document.querySelectorAll("[data-step]")];
  const steps = panels.map(panel => panel.dataset.step);
  const language = document.getElementById("language");
  const back = document.getElementById("back");
  const trail = [];
  let current;
  let locale = data.initial;
  let acknowledged = false;

  function readLocation() {
    const [code, step] = location.hash.slice(1).split("/");
    return { code: Object.hasOwn(data.tables, code) ? code : data.initial,
      step: steps.includes(step) ? step : steps.includes(code) ? code : "copy" };
  }
  function show(step, focus = true) {
    current = steps.includes(step) ? step : "copy";
    const table = data.tables[locale];
    document.documentElement.lang = locale;
    document.title = table["guide-title"] + " · RoleBand";
    language.value = locale;
    document.querySelectorAll("[data-copy]").forEach(node => { node.textContent = table[node.dataset.copy]; });
    document.querySelectorAll("[data-alt]").forEach(node => { node.alt = table[node.dataset.alt]; });
    document.querySelectorAll("[data-label]").forEach(node => { node.setAttribute("aria-label", table[node.dataset.label]); });
    panels.forEach(panel => { panel.hidden = panel.dataset.step !== current; });
    document.querySelectorAll(".steps [data-go]").forEach(node => {
      if (node.dataset.go === current) node.setAttribute("aria-current", "step");
      else node.removeAttribute("aria-current");
    });
    back.hidden = current === "copy";
    document.getElementById("finished").hidden = !acknowledged;
    document.getElementById("finish-guide").hidden = acknowledged;
    try { history.replaceState(null, "", "#" + locale + "/" + current); } catch { /* File viewers can restrict history changes. */ }
    if (focus) { document.querySelector("[data-step='" + current + "'] h1").focus(); window.scrollTo(0, 0); }
  }
  document.querySelectorAll("[data-go]").forEach(node => node.addEventListener("click", event => {
    event.preventDefault();
    if (node.dataset.go !== current) { trail.push(current); acknowledged = false; }
    show(node.dataset.go);
  }));
  back.addEventListener("click", () => {
    acknowledged = false;
    show(trail.pop() ?? steps[Math.max(0, steps.indexOf(current) - 1)]);
  });
  language.addEventListener("change", () => { locale = language.value; show(current); });
  document.getElementById("finish-guide").addEventListener("click", () => { acknowledged = true; show(current, false); });
  addEventListener("hashchange", () => {
    const requested = readLocation(); locale = requested.code; trail.length = 0; acknowledged = false; show(requested.step);
  });
  const initial = readLocation(); locale = initial.code;
  document.documentElement.classList.add("enhanced");
  show(initial.step, false);
})();
