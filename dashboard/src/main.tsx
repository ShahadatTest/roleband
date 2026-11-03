import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { shellApi } from "./api/shell";
import { setCompanyNames } from "./format";
import { installGlobalErrorCapture } from "./diagnostics/clientErrors";
import { intentRevision, storedChoice } from "./copy/runtime";
import { preloadRoute } from "./routeRegistry";
import { readUnconfigured } from "./routing/setupMode";
// The app typeface: IBM Plex Sans + Plex Mono everywhere. Bundled here, not in a feature — every
// route renders it.
import "@fontsource-variable/ibm-plex-sans";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
// 700 because the signed system asks for it: `--app-type-whisper-weight` is
// 700 and mono declarations request 640-800. IBM Plex Mono ships as STATIC
// faces, so an unloaded weight is not synthesised: without this file every one
// of those would paint 600, the heaviest face present.
import "@fontsource/ibm-plex-mono/700.css";
// One vocabulary: tokens.css is the app's only :root scope.
import "./design/tokens.css";
import "./design/overlays.css";
import "./design/surfaces.css";
import "./design/dataviz.css";
import "./shell.css";

// Before the tree mounts, so a throw during the first render is recorded too.
installGlobalErrorCapture();

/* The first screen's code, and at "/" the setup question the shell asks
   before it draws, start now beside the names: started from the tree, each
   would wait for the reads below and then for the one before it. */
preloadRoute(window.location.pathname);
if (window.location.pathname === "/") void readUnconfigured();

/* Company names are read BEFORE the first render: `companyName` is
   a plain function called all over the app, so a name that arrived after the tree
   painted would reach only what happened to re-render. The wait is capped:
   a slow or absent API must never hold the app back, and the shell has its
   own way of saying the API is down. A late answer still names everything
   rendered after it. */
const NAMES_WAIT_MS = 1500;
const names = shellApi.companyNames().then((read) => setCompanyNames(read.names), () => undefined);

/* The stored language is activated before the first render too, for the same
   reason: messages are plain functions (docs/copy.md, section 3).
   English on the system region needs no table and no wait. */
const copy = () => import("./copy/activate");
const stored = storedChoice();
const bootRevision = intentRevision();
const language =
  stored && (stored.language !== "en" || stored.region !== null)
    ? copy().then((c) => c.activate(stored.language, { region: stored.region, revision: bootRevision })).catch(() => undefined)
    : !stored && navigator.languages.some(tag => !/^en(?:-|$)/i.test(tag))
      ? copy().then(c => c.activate(c.negotiate(navigator.languages), {revision: bootRevision})).catch(() => undefined)
      : Promise.resolve();

void Promise.race([Promise.all([names, language]), new Promise((resolve) => setTimeout(resolve, NAMES_WAIT_MS))]).then(() =>
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </React.StrictMode>
  ),
);

/* The account's choice wins over this device's memory, once it is known. A
   failed read leaves the device's choice in place. */
void language.then(() => {
  const revision = bootRevision;
  return shellApi.locale().then((saved) => copy().then((c) => c.adopt({ language: saved.language, region: saved.region ?? null }, revision)));
}).catch(() => undefined);
