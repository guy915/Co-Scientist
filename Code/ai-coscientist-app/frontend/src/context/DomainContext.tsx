import React, { createContext, useContext } from "react";
import type { DomainConfig } from "@/domains/types";
import scientificConfig from "@/domains/scientific.json";
import businessConfig from "@/domains/business.json";
import militaryOrdersConfig from "@/domains/military_orders.json";
import cybersecurityConfig from "@/domains/cybersecurity.json";

// load domain config based on build-time environment variable
// defaults to scientific if not set
const DOMAIN_ID = import.meta.env.VITE_DOMAIN || "scientific";

// dynamically import domain config based on DOMAIN_ID
function loadDomainConfig(domainId: string): DomainConfig {
  switch (domainId) {
    case "scientific":
      return scientificConfig as DomainConfig;
    case "business":
      return businessConfig as DomainConfig;
    case "military_orders":
      return militaryOrdersConfig as DomainConfig;
    case "cybersecurity":
      return cybersecurityConfig as DomainConfig;
    default:
      console.warn(`unknown domain "${domainId}", falling back to scientific`);
      return scientificConfig as DomainConfig;
  }
}

interface DomainContextValue {
  config: DomainConfig;
  domainId: string;
}

const DomainContext = createContext<DomainContextValue | undefined>(undefined);

export function DomainProvider({ children }: { children: React.ReactNode }) {
  const config = loadDomainConfig(DOMAIN_ID);

  return (
    <DomainContext.Provider value={{ config, domainId: DOMAIN_ID }}>
      {children}
    </DomainContext.Provider>
  );
}

export function useDomain() {
  const context = useContext(DomainContext);
  if (!context) {
    throw new Error("useDomain must be used within DomainProvider");
  }
  return context;
}
