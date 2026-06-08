# Theme System

This directory contains the theme definitions and utilities for the application's color schemes.

## Overview

The theme system uses custom CSS variables with a `th-` prefix to avoid conflicting with Tailwind's built-in color palette. This allows theme-aware components to use our custom colors while preserving Tailwind's standard colors (like `bg-blue-50`, `bg-gray-100`) for components that need specific colors.

## Architecture

### Theme Definition

Themes are defined in `themes.ts` as TypeScript objects:

```typescript
{
  id: "light",
  name: "Light",
  description: "clean, neutral light theme",
  colors: {
    bg: "hsl(0 0% 100%)",           // Full HSL values
    fg: "hsl(0 0% 3.9%)",
    primary: "hsl(0 0% 9%)",
    // ... other color variables
  }
}
```

### Color Format

Colors are specified as complete HSL values:
- Format: `"hsl(hue saturation% lightness%)"`
- Example: `"hsl(210 100% 20%)"` (navy blue)
- Usage in CSS: `var(--color-th-primary)`

### CSS Variables

Each color is mapped to a CSS variable with `th-` prefix:
- `bg` → `--color-th-bg`
- `fg` → `--color-th-fg`
- `primary` → `--color-th-primary`
- `primaryFg` → `--color-th-primary-fg`

The `applyTheme()` function sets these variables on the document root.

### Tailwind Integration

The CSS variables are registered in `@theme` in `index.css`, which creates Tailwind utility classes:
- `bg-th-bg` - theme background
- `text-th-fg` - theme foreground text
- `bg-th-primary` - primary color background
- etc.

## Built-in Themes

### 1. Light (Default)
**ID**: `light`

Clean, neutral theme matching original pre-theming appearance.
- Black buttons and badges
- High contrast for readability
- Professional appearance

### 2. Dark
**ID**: `dark`

Dark mode theme for reduced eye strain.
- Deep blue-gray background
- Muted phase colors for softer appearance
- High contrast text

### 3. Navy
**ID**: `navy`

US Navy operational theme with naval colors.
- Deep navy blues with gold accents
- Professional military aesthetic

### 4. Business
**ID**: `business`

Modern corporate theme.
- Corporate blues and greens
- Professional appearance

### 5. Ocean
**ID**: `ocean`

Calm teal and slate theme.
- Cyan/teal colors
- Refreshing and calming

## Color Variable Reference

### Core Colors
- `bg`: Main background color
- `fg`: Main text color
- `card`: Card background color
- `cardFg`: Text color on cards

### Interactive Elements
- `primary`: Primary action color (buttons, links)
- `primaryFg`: Text color on primary elements
- `secondary`: Secondary action color
- `secondaryFg`: Text color on secondary elements

### States & Feedback
- `muted`: Muted/disabled state color
- `mutedFg`: Text color for muted elements
- `accent`: Hover/focus accent color
- `accentFg`: Text color on accent elements
- `destructive`: Destructive action color
- `destructiveFg`: Text color on destructive elements
- `success`: Success state color
- `warning`: Warning state color
- `info`: Info state color

### Phase Colors
- `phase0` through `phase4`: Colors for iteration phases

### UI Elements
- `border`: Border color
- `input`: Input field border color
- `ring`: Focus ring color
- `link`: Link color
- `linkHover`: Link hover color

## Theme Usage in Components

### Using CSS Variables

```tsx
// Using Tailwind classes (preferred)
<div className="bg-th-bg text-th-fg">...</div>

// Using inline styles
<div style={{ color: "var(--color-th-primary)" }}>...</div>

// Using color-mix for opacity
<div style={{ backgroundColor: "color-mix(in srgb, var(--color-th-primary) 50%, transparent)" }}>
  ...
</div>
```

### When to Use Theme Colors vs Tailwind Colors

**Use theme colors (`th-` prefix)** for:
- Body/page background
- Primary buttons and actions
- Badges that should adapt to theme
- Cards and containers that should follow theme
- Any color that should change when theme switches

**Use Tailwind colors** for:
- Specific design elements that should stay constant
- Components with deliberate color coding

## Domain Configuration

Domains can specify default theme and available themes:

```json
{
  "id": "my-domain",
  "defaultTheme": "navy",
  "availableThemes": ["navy", "light", "dark"]
}
```

## Switching Themes

Users can switch themes using the theme switcher button in the header. The selected theme is persisted to localStorage.

Programmatically:

```tsx
import { useTheme } from "@/context/ThemeContext";

function MyComponent() {
  const { currentTheme, setTheme, cycleTheme } = useTheme();

  return (
    <button onClick={cycleTheme}>
      Current: {currentTheme}
    </button>
  );
}
```
