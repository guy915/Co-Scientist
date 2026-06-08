// domain terminology configuration types

export type FieldDisplayType = "heading" | "badge" | "text" | "link_list";

export interface FieldSubConfig {
  key: string;
  display: FieldDisplayType;
  label?: string;
  /** Tooltip text shown on hover for this column header (table layout) or value (list layout). */
  tooltip?: string;
}

export interface CustomFieldConfig {
  key: string;
  label: string;
  fields: FieldSubConfig[];
  /** Which UI locations render this field (e.g. "hypothesis", "reflection"). Defaults to ["hypothesis"]. */
  showIn?: string[];
  /** Rendering layout. "list" (default) stacks items vertically; "table" renders items as table rows with column headers. */
  layout?: "list" | "table";
}

export interface ConceptVariants {
  singular: string;
  plural: string;
  Singular: string;
  Plural: string;
  SINGULAR?: string;
  PLURAL?: string;
}

export interface ActionConcept {
  verb: string;
  gerund: string;
  past: string;
  noun: string;
  Verb: string;
  Gerund?: string;
  Past?: string;
  Noun: string;
}

export interface DomainConfig {
  id: string;
  name: string;
  description?: string;
  appName?: string;
  appIcon?: string;
  defaultTheme?: string;
  availableThemes?: string[];
  showPubmedBadge?: boolean;
  concepts: {
    item: ConceptVariants;
    goal: ConceptVariants;
    action: ActionConcept;
    process?: ConceptVariants;
    record?: ConceptVariants;
  };
  agents?: Record<string, string>;
  phases?: Record<string, string>;
  ui?: Record<string, string | null>;
  metrics?: Record<string, string>;
  customFields?: CustomFieldConfig[];
  export?: {
    csv_headers?: Record<string, string>;
    markdown?: Record<string, string>;
    [key: string]: any;
  };
}
