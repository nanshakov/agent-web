import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Theme } from "@radix-ui/themes";
import "@radix-ui/themes/styles.css";
import "./style.css";
import { App } from "./App";
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Theme
      appearance="light"
      accentColor="jade"
      grayColor="slate"
      radius="medium"
    >
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </Theme>
  </React.StrictMode>,
);
