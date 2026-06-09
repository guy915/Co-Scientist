import { useDomain } from "@/context/DomainContext";
import { getConcept, getText, resolveTemplate } from "@/utils/domainResolver";

/**
 * hook for accessing domain-specific text and terminology
 *
 * @example
 * const { t, c, item, goal } = useDomainText();
 *
 * // get configured UI text
 * <h1>{t('page_title')}</h1>
 *
 * // get concept values
 * <span>{item.plural}</span> // "hypotheses" or "ideas"
 *
 * // use template with variables
 * <p>{t('results_title', undefined, { count: 5 })}</p>
 */
export function useDomainText() {
  const { config } = useDomain();

  return {
    /**
     * main text getter with fallback support
     *
     * @param key - dot-separated path like 'ui.page_title' or 'submit_button'
     * @param fallback - optional fallback template if key not found
     * @param variables - optional variables for template substitution like {count}, {n}
     */
    t: (key: string, fallback?: string, variables?: Record<string, string | number>) =>
      getText(key, config, fallback, variables),

    /**
     * direct concept access
     *
     * @param path - dot-separated concept path like 'item.plural' or 'action.Verb'
     */
    c: (path: string) => getConcept(config, path),

    /**
     * template resolution for inline templates
     *
     * @param template - template string like 'Enter {goal.singular} to {action.verb}'
     * @param variables - optional variables for substitution
     */
    template: (template: string, variables?: Record<string, string | number>) =>
      resolveTemplate(template, config, variables),

    /**
     * direct config access for complex cases
     */
    config,

    /**
     * commonly used concept shortcuts for convenience
     */
    item: {
      singular: getConcept(config, "item.singular"),
      plural: getConcept(config, "item.plural"),
      Singular: getConcept(config, "item.Singular"),
      Plural: getConcept(config, "item.Plural"),
    },
    goal: {
      singular: getConcept(config, "goal.singular"),
      plural: getConcept(config, "goal.plural"),
      Singular: getConcept(config, "goal.Singular"),
      Plural: getConcept(config, "goal.Plural"),
    },
    action: {
      verb: getConcept(config, "action.verb"),
      gerund: getConcept(config, "action.gerund"),
      past: getConcept(config, "action.past"),
      noun: getConcept(config, "action.noun"),
      Verb: getConcept(config, "action.Verb"),
      Gerund: getConcept(config, "action.Gerund"),
      Past: getConcept(config, "action.Past"),
      Noun: getConcept(config, "action.Noun"),
    },
    process: {
      singular: getConcept(config, "process.singular"),
      plural: getConcept(config, "process.plural"),
      Singular: getConcept(config, "process.Singular"),
      Plural: getConcept(config, "process.Plural"),
    },
    record: {
      singular: getConcept(config, "record.singular"),
      plural: getConcept(config, "record.plural"),
      Singular: getConcept(config, "record.Singular"),
      Plural: getConcept(config, "record.Plural"),
    },
  };
}
