import * as React from "react";
import { cn } from "@/lib/utils";
import { ChevronDown } from "lucide-react";

interface CollapsibleProps {
  trigger: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  defaultOpen?: boolean;
}

export function Collapsible({
  trigger,
  children,
  className,
  defaultOpen = false,
}: CollapsibleProps) {
  const [isOpen, setIsOpen] = React.useState(defaultOpen);

  return (
    <div className={cn("space-y-2", className)}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 text-sm font-medium hover:text-primary transition-colors"
      >
        {trigger}
        <ChevronDown
          className={cn("h-4 w-4 transition-transform", isOpen && "transform rotate-180")}
        />
      </button>
      {isOpen && <div className="pt-2 space-y-4">{children}</div>}
    </div>
  );
}
