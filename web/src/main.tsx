import "@fontsource-variable/heebo";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { captureInvite } from "./lib/invite";
import "./styles/base.css";
import "./styles/components.css";

captureInvite(); // before anything else can read or leak the URL
document.documentElement.lang = "he";
document.documentElement.dir = "rtl";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
