import type { LucideIcon } from "lucide-react";
import * as LucideIcons from "lucide-react";

interface IconRendererProps {
  icon?: string;
  className?: string;
  style?: React.CSSProperties;
  fallback?: LucideIcon;
}

/**
 * renders an icon from either a lucide-react icon name or an image URL
 *
 * supports:
 * - lucide icon names (e.g., "Sparkles", "Lightbulb")
 * - absolute URLs (e.g., "https://example.com/icon.png")
 * - relative URLs (e.g., "/assets/icon.png", "./icon.png")
 * - file:// URLs (e.g., "file:///path/to/icon.png")
 *
 * if the icon string is not found or is undefined, renders the fallback icon (default: Sparkles)
 */
export function IconRenderer({ icon, className = "", style, fallback }: IconRendererProps) {
  const FallbackIcon = fallback || LucideIcons.Sparkles;

  if (!icon) {
    return <FallbackIcon className={className} style={style} />;
  }

  // check if it's a URL (starts with http://, https://, file://, /, or ./)
  const isUrl =
    icon.startsWith("http://") ||
    icon.startsWith("https://") ||
    icon.startsWith("file://") ||
    icon.startsWith("/") ||
    icon.startsWith("./") ||
    icon.startsWith("../");

  if (isUrl) {
    return <img src={icon} alt="" className={className} style={style} />;
  }

  // try to resolve as a lucide icon name
  const IconComponent = (LucideIcons as any)[icon] as LucideIcon | undefined;

  if (IconComponent) {
    return <IconComponent className={className} style={style} />;
  }

  // fallback if icon name not found
  console.warn(`icon "${icon}" not found in lucide-react, using fallback`);
  return <FallbackIcon className={className} style={style} />;
}
