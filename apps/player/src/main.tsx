import * as Sentry from "@sentry/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { config } from "./config";
import "./index.css";
import { readInitData, setupTelegramUi } from "./telegram";

if (config.sentryDsn) {
  Sentry.init({ dsn: config.sentryDsn, environment: config.env });
}

const initData = readInitData();
if (initData) {
  try {
    setupTelegramUi();
  } catch (error) {
    console.error("Telegram UI setup failed", error);
    Sentry.captureException(error);
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App initData={initData} />
  </StrictMode>,
);
