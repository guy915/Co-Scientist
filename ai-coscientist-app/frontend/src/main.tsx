import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "./index.css";
import { WorkbenchApp } from "./workbench/WorkbenchApp";

// biome-ignore lint/style/noNonNullAssertion: root element is always present in index.html
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <WorkbenchApp />
    </BrowserRouter>
  </StrictMode>
);
