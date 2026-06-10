import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "./index.css";
import { WorkbenchApp } from "./workbench/WorkbenchApp";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <WorkbenchApp />
    </BrowserRouter>
  </StrictMode>
);
