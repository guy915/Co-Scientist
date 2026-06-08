# Domain Terminology System

This directory contains domain-specific terminology configurations that allow the UI to adapt to different use cases beyond scientific hypothesis generation.

## Overview

The domain terminology system provides a flexible way to customize all user-facing text in the application without modifying component code. This enables using the same codebase for:
- Scientific hypothesis generation (default)
- Business idea generation
- Military course of action planning
- Any other brainstorming/ideation domain

## How It Works

### 1. Domain Configuration Files

Each domain is defined in a JSON file (e.g., `scientific.json`, `business.json`) that specifies:

- **Branding**: App name and icon customization
- **Concepts**: Core terminology like "hypothesis" → "idea", "research goal" → "business goal"
- **Agents**: Display names for AI agents
- **UI Text**: Labels, placeholders, button text
- **Export Labels**: Headers and titles for CSV/Markdown exports

### 2. Template System

Domain configs support template strings with variable substitution:

```json
{
  "agents": {
    "HypothesisGenerator": "{item.Singular} Generator"
  },
  "ui": {
    "results_title": "{action.Past} {item.Plural} ({count})"
  }
}
```

Templates automatically resolve to:
- Scientific: "Hypothesis Generator", "Generated Hypotheses (5)"
- Business: "Idea Generator", "Generated Ideas (5)"

### 3. Build-Time Configuration

The domain is set at build time via the `VITE_DOMAIN` environment variable:

```bash
# Build for scientific domain (default)
npm run build

# Build for business domain
VITE_DOMAIN=business npm run build

# Build for military domain
VITE_DOMAIN=military npm run build
```

## Branding Customization

Each domain can customize the application name and icon displayed in the header and forms.

### App Name

Set the `appName` field to customize the main application title:

```json
{
  "id": "business",
  "appName": "Business Strategy AI"
}
```

If not specified, defaults to "Open Coscientist".

### App Icon

Set the `appIcon` field to customize the icon displayed in the header and form titles. Supports:

1. **Lucide icon names** (e.g., "Sparkles", "Lightbulb", "Compass")
2. **Absolute URLs** (e.g., "https://example.com/logo.png")
3. **Relative URLs** (e.g., "/assets/logo.png", "./logo.png")
4. **File URLs** (e.g., "file:///path/to/logo.png")

```json
{
  "id": "business",
  "appIcon": "Lightbulb"
}
```

Or with an image URL:

```json
{
  "id": "custom",
  "appIcon": "https://example.com/custom-logo.png"
}
```

If not specified, defaults to "Sparkles" icon.

## Theme Customization

Each domain can specify a default color theme and allow users to switch between multiple themes.

### Default Theme

Set the `defaultTheme` field to specify the initial theme:

```json
{
  "id": "business",
  "defaultTheme": "business"
}
```

### Available Themes

Set the `availableThemes` array to specify which themes users can cycle through:

```json
{
  "id": "business",
  "defaultTheme": "business",
  "availableThemes": ["business", "scientific", "ocean"]
}
```

Users can cycle through themes using the theme switcher button in the top-right of the header.

### Built-in Themes

The application includes 4 built-in themes:

1. **scientific**: Clean, minimalist scientific research theme (default)
2. **navy**: US Navy operational theme with naval colors
3. **business**: Modern marketing and AI business theme with purple accents
4. **ocean**: Deep ocean teal and cyan theme

### Theme Persistence

The user's selected theme is saved to localStorage and persists across sessions. When a user returns to the app, their last selected theme is restored (if still available in the domain's `availableThemes` list).

### Example Domain with Theming

```json
{
  "id": "military_orders",
  "name": "Naval Operations Planning",
  "appName": "Naval Operations Planner",
  "appIcon": "Compass",
  "defaultTheme": "navy",
  "availableThemes": ["navy", "ocean"],
  "concepts": {
    ...
  }
}
```

This configuration will:
- Start with the navy theme by default
- Allow users to switch between navy and ocean themes
- Save the user's preference for future visits

## Creating a New Domain

### Step 1: Create Domain Config

Create a new JSON file in this directory (e.g., `military.json`):

```json
{
  "id": "military",
  "name": "Military Planning",
  "description": "course of action generation and evaluation",
  "appName": "Naval Operations Planner",
  "appIcon": "Compass",
  "concepts": {
    "item": {
      "singular": "course of action",
      "plural": "courses of action",
      "Singular": "Course of Action",
      "Plural": "Courses of Action"
    },
    "goal": {
      "singular": "mission objective",
      "plural": "mission objectives",
      "Singular": "Mission Objective",
      "Plural": "Mission Objectives"
    },
    "action": {
      "verb": "develop",
      "gerund": "developing",
      "past": "developed",
      "noun": "development",
      "Verb": "Develop",
      "Gerund": "Developing",
      "Past": "Developed",
      "Noun": "Development"
    },
    "process": {
      "singular": "assessment",
      "plural": "assessments",
      "Singular": "Assessment",
      "Plural": "Assessments"
    },
    "record": {
      "singular": "refinement",
      "plural": "refinements",
      "Singular": "Refinement",
      "Plural": "Refinements"
    }
  },
  "agents": {
    "Supervisor": "Planning Supervisor",
    "HypothesisGenerator": "{item.Singular} Generator",
    "HypothesisReflector": "Assessment Officer",
    "HypothesisRanker": "{item.Singular} Ranker",
    "RankingJudge": "Ranking Judge",
    "MetaReviewer": "Meta Assessor",
    "HypothesisEvolver": "{item.Singular} Refiner",
    "ProximityAnalyzer": "Similarity Analyzer",
    "LiteratureReview": "Intelligence Review",
    "Reflection": "Operational Analysis"
  },
  "ui": {
    "page_title": "Military {item.Singular} {action.Noun}",
    "form_title": "Military {item.Singular} {action.Noun}",
    "input_label": "{goal.Singular}",
    "input_placeholder": "Enter your {goal.singular}...",
    "submit_button": "{action.Verb} {item.Plural}",
    "results_title": "{action.Past} {item.Plural} ({count})",
    "evolved_label": "Refined {n}x",
    "cluster_label": "Cluster",
    "evolution_history": "{record.Singular} History"
  },
  "metrics": {
    "items_generated": "{item.Plural} {action.Verb}d",
    "reviews_count": "{process.Plural}",
    "evolutions_count": "{record.Plural}"
  },
  "export": {
    "csv_headers": {
      "rank": "Rank",
      "text": "Text",
      "score": "Score",
      "elo": "Elo Rating"
    },
    "markdown": {
      "title": "{item.Singular} {action.Noun} Results",
      "goal_label": "{goal.Singular}",
      "results_label": "Top {item.Plural}"
    }
  }
}
```

### Step 2: Register the Domain

Add your domain to `DomainContext.tsx`:

TODO can this be auto-discovered/injected using babel or some preprocessor, or nodejs script?

```typescript
import militaryConfig from '@/domains/military.json';

function loadDomainConfig(domainId: string): DomainConfig {
  switch (domainId) {
    case 'scientific':
      return scientificConfig as DomainConfig;
    case 'business':
      return businessConfig as DomainConfig;
    case 'military':
      return militaryConfig as DomainConfig;
    default:
      console.warn(`unknown domain "${domainId}", falling back to scientific`);
      return scientificConfig as DomainConfig;
  }
}
```

### Step 3: Build and Deploy

Build the UI with your domain:

```bash
VITE_DOMAIN=military npm run build
```

The resulting build will use military terminology throughout the UI.

## Template Syntax

### Concept References

Use dot notation to reference concept properties:

- `{item.singular}` → "hypothesis" or "idea"
- `{item.plural}` → "hypotheses" or "ideas"
- `{item.Singular}` → "Hypothesis" or "Idea" (title case)
- `{item.Plural}` → "Hypotheses" or "Ideas" (title case)

### Variables

Templates support runtime variables:

- `{count}` → number passed at runtime
- `{n}` → number passed at runtime

Example:
```json
{
  "ui": {
    "results_title": "{action.Past} {item.Plural} ({count})"
  }
}
```

Used in component:
```tsx
const { t } = useDomainText();
<h2>{t('results_title', undefined, { count: 5 })}</h2>
// Renders: "Generated Hypotheses (5)"
```

## Available Concepts

### Required Concepts

Every domain config must define:

1. **item**: The main thing being generated (hypothesis, idea, course of action)
2. **goal**: What the user provides as input (research goal, business goal, mission objective)
3. **action**: The verb for generating items (generate, develop, create)

### Optional Concepts

4. **process**: Review/evaluation terminology (review, evaluation, assessment)
5. **record**: History/evolution terminology (evolution, refinement, iteration)

## UI Integration

Components use the `useDomainText()` hook to access domain-specific text:

```tsx
import { useDomainText } from '@/hooks/useDomainText';

function MyComponent() {
  const { t, item, goal, action } = useDomainText();

  return (
    <div>
      <h1>{t('page_title')}</h1>
      <p>Enter your {goal.singular}</p>
      <button>{action.Verb} {item.Plural}</button>
    </div>
  );
}
```

## Testing

To test a domain locally:

```bash
# Terminal 1: Build with domain
VITE_DOMAIN=business npm run build

# Terminal 2: Preview the build
npm run preview

# Or run dev server (hot reload)
VITE_DOMAIN=business npm run dev
```

## Best Practices

1. **Consistency**: Use the same capitalization patterns across all domains
2. **Completeness**: Define all required sections even if some text doesn't change
3. **Testing**: Test all major UI flows with your domain to ensure text reads naturally
4. **Fallbacks**: Always provide fallback text in templates in case resolution fails

## Examples

See existing domain configs:
- `scientific.json` - Default scientific hypothesis generation
- `business.json` - Business idea generation example

## Troubleshooting

**Problem**: Text shows as `{item.plural}` instead of resolving

**Solution**: Check that:
1. The concept is defined in your domain config
2. The property name matches exactly (case-sensitive)
3. The domain config is properly imported in `DomainContext.tsx`

**Problem**: Domain not loading

**Solution**: Verify:
1. `VITE_DOMAIN` environment variable is set correctly
2. Domain ID in config matches the environment variable
3. Domain is registered in `DomainContext.tsx` switch statement
