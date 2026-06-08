import type { DomainConfig } from "@/domains/types";

/**
 * resolves template strings like "{item.plural}" or "{action.Verb}"
 * supports nested paths and capitalization variants
 */
export function resolveTemplate(
  template: string,
  config: DomainConfig,
  variables?: Record<string, string | number>
): string {
  return template.replace(/\{([^}]+)\}/g, (match, path) => {
    // handle variables like {count}, {n}
    if (variables && path in variables) {
      return String(variables[path]);
    }

    // handle concept paths like {item.plural}, {action.Verb}
    const parts = path.split(".");
    let value: any = config.concepts;

    for (const part of parts) {
      if (value && typeof value === "object" && part in value) {
        value = value[part];
      } else {
        return match; // keep original if path not found
      }
    }

    return typeof value === "string" ? value : match;
  });
}

/**
 * gets text with fallback order: override -> template -> fallback
 */
export function getText(
  key: string,
  config: DomainConfig,
  fallback?: string,
  variables?: Record<string, string | number>
): string {
  // 1. check for direct override in ui/export/metrics/phases sections
  const sections = ["ui", "metrics", "phases"] as const;

  for (const section of sections) {
    const sectionData = config[section];
    if (sectionData && typeof sectionData === "object") {
      const value = getNestedValue(sectionData, key);
      if (value) {
        return resolveTemplate(value, config, variables);
      }
    }
  }

  // 2. check export section (nested structure)
  if (config.export) {
    const value = getNestedValue(config.export, key);
    if (value) {
      return resolveTemplate(value, config, variables);
    }
  }

  // 3. check agents section
  if (key.startsWith("agent.")) {
    const agentKey = key.replace("agent.", "");
    const agentName = config.agents?.[agentKey];
    if (agentName) {
      return resolveTemplate(agentName, config, variables);
    }
  }

  // 4. fallback to provided default
  if (fallback) {
    return resolveTemplate(fallback, config, variables);
  }

  return key; // worst case, return the key itself
}

function getNestedValue(obj: any, path: string): string | undefined {
  const keys = path.split(".");
  let current = obj;

  for (const key of keys) {
    if (current && typeof current === "object" && key in current) {
      current = current[key];
    } else {
      return undefined;
    }
  }

  return typeof current === "string" ? current : undefined;
}

/**
 * direct access to concept values
 */
export function getConcept(config: DomainConfig, path: string): string {
  const result = resolveTemplate(`{${path}}`, config);
  // if template couldn't resolve, return empty string instead of the template
  return result.startsWith("{") && result.endsWith("}") ? "" : result;
}
