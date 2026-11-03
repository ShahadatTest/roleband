// Dev-only: builds the deck's data off Vite's request loop, so checking every
// pattern never delays the app or a lazy language import (vite-plugin.mjs).
import { parentPort } from "node:worker_threads";
import { changedMessages, reviewData } from "./review.mjs";

const data = reviewData();
const changed = changedMessages("HEAD").changed.map((m) => m.id);
parentPort.postMessage(JSON.stringify({ ...data, changed }));
