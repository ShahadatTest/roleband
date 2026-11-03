import React from "react";
import { createRoot } from "react-dom/client";
import { Deck } from "./Deck";
import "@fontsource-variable/ibm-plex-sans";
import "@fontsource/ibm-plex-mono/400.css";
import "../../design/tokens.css";
import "./review.css";
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Deck />
  </React.StrictMode>,
);
