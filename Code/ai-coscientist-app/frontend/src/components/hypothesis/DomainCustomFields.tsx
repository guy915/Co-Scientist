import { ExternalLink } from "lucide-react";
import React from "react";
import { Badge } from "@/components/ui/badge";
import { useDomain } from "@/context/DomainContext";
import type { CustomFieldConfig, FieldSubConfig } from "@/domains/types";

interface DomainCustomFieldsProps {
  /** The hypothesis object (cast to access dynamic keys) */
  hypothesis: Record<string, unknown>;
  compact?: boolean;
  /** Which UI location is rendering (filters customFields by showIn). Defaults to "hypothesis". */
  location?: string;
}

// =============================================================================
// Tooltip
// =============================================================================

function TooltipHint({ children, tip }: { children: React.ReactNode; tip: string }) {
  return (
    <span className="relative group cursor-help inline-flex items-center gap-0.5">
      {children}
      <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 z-50 hidden group-hover:block w-56 rounded-md bg-th-fg text-th-bg text-xs px-2 py-1.5 shadow-lg pointer-events-none leading-relaxed">
        {tip}
      </span>
    </span>
  );
}

// =============================================================================
// List layout sub-field renderers (unchanged, used by non-table domains)
// =============================================================================

function FieldBadge({ value }: { value: string }) {
  return (
    <Badge variant="outline" className="text-xs w-fit">
      {value}
    </Badge>
  );
}

function FieldText({ value, label }: { value: string; label?: string }) {
  return (
    <p className="text-xs leading-relaxed">
      {label && <span className="font-semibold text-th-fg">{label}: </span>}
      {value}
    </p>
  );
}

function FieldLinkList({ links, label }: { links: string[]; label?: string }) {
  if (!links || links.length === 0) return null;
  return (
    <div>
      {label && <span className="text-xs font-semibold text-th-fg">{label}:</span>}
      <ul className="flex flex-wrap gap-2 pt-1">
        {links.map((url, idx) => (
          <li key={idx}>
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-th-link hover:text-th-link-hover hover:underline"
            >
              <ExternalLink className="w-3 h-3" />
              {links.length > 1 ? `Link ${idx + 1}` : "Link"}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

function renderSubField(item: Record<string, unknown>, field: FieldSubConfig) {
  const value = item[field.key];
  if (value === undefined || value === null) return null;

  switch (field.display) {
    case "heading":
      return <div className="font-medium text-sm text-th-fg">{String(value)}</div>;
    case "badge":
      return <FieldBadge value={String(value)} />;
    case "text":
      return <FieldText value={String(value)} label={field.label} />;
    case "link_list":
      if (!Array.isArray(value)) return null;
      return <FieldLinkList links={value as string[]} label={field.label} />;
    default:
      return null;
  }
}

function ListCustomFieldSection({
  config,
  items,
  compact,
}: {
  config: CustomFieldConfig;
  items: unknown[];
  compact?: boolean;
}) {
  return (
    <div>
      <h4
        className={
          compact
            ? "text-sm font-semibold text-th-fg mb-1"
            : "text-sm font-semibold text-th-fg mb-2"
        }
      >
        {config.label}
      </h4>
      <div className="space-y-3">
        {items.map((item, idx) => {
          const record = item as Record<string, unknown>;
          return (
            <div key={idx} className="space-y-1 pl-2">
              {config.fields.map((field) => (
                <React.Fragment key={field.key}>{renderSubField(record, field)}</React.Fragment>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// =============================================================================
// Table layout
// =============================================================================

function TableColumnHeader({ field }: { field: FieldSubConfig }) {
  const label = field.label ?? field.key;
  if (field.tooltip) {
    return (
      <TooltipHint tip={field.tooltip}>
        <span>{label}</span>
        <span className="text-th-muted-fg opacity-60 text-[10px]">ⓘ</span>
      </TooltipHint>
    );
  }
  return <>{label}</>;
}

function TableCell({ value, field }: { value: string; field: FieldSubConfig }) {
  switch (field.display) {
    case "heading":
      return <span className="font-medium text-th-fg">{value}</span>;
    case "badge":
      return (
        <Badge variant="outline" className="text-xs">
          {value}
        </Badge>
      );
    default:
      return <span className="text-th-muted-fg">{value}</span>;
  }
}

function TableCustomFieldSection({
  config,
  items,
  compact,
}: {
  config: CustomFieldConfig;
  items: unknown[];
  compact?: boolean;
}) {
  return (
    <div className="max-w-[800px]">
      <h4
        className={
          compact
            ? "text-sm font-semibold text-th-fg mb-1"
            : "text-sm font-semibold text-th-fg mb-2"
        }
      >
        {config.label}
      </h4>
      <table className="text-xs border-collapse">
        <thead>
          <tr className="border-b border-th-border">
            {config.fields.map((col) => (
              <th
                key={col.key}
                className="text-left pb-1.5 pr-4 font-semibold text-th-muted-fg whitespace-nowrap"
              >
                <TableColumnHeader field={col} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => {
            const record = item as Record<string, unknown>;
            return (
              <tr
                key={idx}
                className="border-b border-th-border/40 last:border-0 hover:bg-th-muted/40 transition-colors"
              >
                {config.fields.map((col) => {
                  const value = record[col.key];
                  if (value === undefined || value === null) {
                    return (
                      <td key={col.key} className="py-1.5 pr-4 text-th-muted-fg">
                        —
                      </td>
                    );
                  }
                  return (
                    <td key={col.key} className="py-1.5 pr-4 align-middle">
                      <TableCell value={String(value)} field={col} />
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// =============================================================================
// Data resolution + entry point
// =============================================================================

/**
 * Resolve field data from either top-level (normalized) or nested enrichments (raw).
 * normalizeHypothesis() flattens enrichments to top-level, but some components
 * (e.g. ReflectionAgent) receive raw hypothesis objects where it's still nested.
 */
function resolveFieldData(hypothesis: Record<string, unknown>, key: string): unknown[] | null {
  const direct = hypothesis[key];
  if (Array.isArray(direct) && direct.length > 0) return direct;

  const enrichments = hypothesis.enrichments;
  if (enrichments && typeof enrichments === "object" && !Array.isArray(enrichments)) {
    const nested = (enrichments as Record<string, unknown>)[key];
    if (Array.isArray(nested) && nested.length > 0) return nested;
  }

  return null;
}

export function DomainCustomFields({
  hypothesis,
  compact = false,
  location = "hypothesis",
}: DomainCustomFieldsProps) {
  const { config } = useDomain();
  const customFields = config.customFields;
  if (!customFields || customFields.length === 0) return null;

  const sections = customFields
    .filter((cf) => {
      const targets = cf.showIn || ["hypothesis"];
      return targets.includes(location);
    })
    .map((cf) => ({ config: cf, items: resolveFieldData(hypothesis, cf.key) }))
    .filter((s): s is { config: CustomFieldConfig; items: unknown[] } => s.items !== null);

  if (sections.length === 0) return null;

  return (
    <>
      {sections.map((s) =>
        s.config.layout === "table" ? (
          <TableCustomFieldSection
            key={s.config.key}
            config={s.config}
            items={s.items}
            compact={compact}
          />
        ) : (
          <ListCustomFieldSection
            key={s.config.key}
            config={s.config}
            items={s.items}
            compact={compact}
          />
        )
      )}
    </>
  );
}
