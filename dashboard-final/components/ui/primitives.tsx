// Small presentational primitives (shadcn/ui conventions).
import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export function Card({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("rounded-xl border bg-card text-card-foreground shadow-xs", className)} {...props} />;
}

export function CardHeader({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("flex flex-col gap-1 p-4 pb-2", className)} {...props} />;
}

export function CardTitle({ className, ...props }: ComponentProps<"h3">) {
  return <h3 className={cn("text-sm font-semibold leading-none tracking-tight", className)} {...props} />;
}

export function CardDescription({ className, ...props }: ComponentProps<"p">) {
  return <p className={cn("text-xs text-muted-foreground", className)} {...props} />;
}

export function CardContent({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("p-4 pt-2", className)} {...props} />;
}

const badgeVariants = cva("inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap", {
  variants: {
    variant: {
      default: "border-transparent bg-secondary text-secondary-foreground",
      outline: "text-foreground",
      fire: "border-transparent bg-fire text-white",
      smoke: "border-transparent bg-smoke text-white",
      risk: "border-transparent bg-risk text-black",
      safe: "border-transparent bg-safe text-white",
      info: "border-transparent bg-info text-white",
      muted: "border-transparent bg-muted text-muted-foreground",
    },
  },
  defaultVariants: { variant: "default" },
});

export function Badge({ className, variant, ...props }: ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export function Input({ className, ...props }: ComponentProps<"input">) {
  return (
    <input
      className={cn(
        "flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 file:border-0 file:bg-transparent file:text-sm file:font-medium",
        className,
      )}
      {...props}
    />
  );
}

export function Select({ className, ...props }: ComponentProps<"select">) {
  return (
    <select
      className={cn(
        "flex h-9 w-full rounded-md border border-input bg-background px-2 py-1 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

export function Label({ className, ...props }: ComponentProps<"label">) {
  return <label className={cn("text-xs font-medium text-muted-foreground", className)} {...props} />;
}

export function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function Progress({ value, className, tone = "info" }: { value: number; className?: string; tone?: "info" | "fire" | "smoke" | "safe" | "risk" }) {
  const v = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
  const color = { info: "bg-info", fire: "bg-fire", smoke: "bg-smoke", safe: "bg-safe", risk: "bg-risk" }[tone];
  return (
    <div className={cn("h-2 w-full overflow-hidden rounded-full bg-muted", className)} role="progressbar" aria-valuenow={v} aria-valuemin={0} aria-valuemax={100}>
      <div className={cn("h-full transition-all", color)} style={{ width: `${v}%` }} />
    </div>
  );
}

export function Skeleton({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} {...props} />;
}

export function Table({ className, ...props }: ComponentProps<"table">) {
  return (
    <div className="relative w-full overflow-x-auto">
      <table className={cn("w-full caption-bottom text-sm", className)} {...props} />
    </div>
  );
}
export function THead(props: ComponentProps<"thead">) {
  return <thead className="[&_tr]:border-b" {...props} />;
}
export function TBody(props: ComponentProps<"tbody">) {
  return <tbody className="[&_tr:last-child]:border-0" {...props} />;
}
export function TR({ className, ...props }: ComponentProps<"tr">) {
  return <tr className={cn("border-b transition-colors hover:bg-muted/40", className)} {...props} />;
}
export function TH({ className, ...props }: ComponentProps<"th">) {
  return <th className={cn("h-9 px-2 text-left align-middle text-xs font-medium text-muted-foreground whitespace-nowrap", className)} {...props} />;
}
export function TD({ className, ...props }: ComponentProps<"td">) {
  return <td className={cn("px-2 py-2 align-middle", className)} {...props} />;
}

export function EmptyState({ title, description, children }: { title: string; description?: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-8 text-center">
      <p className="text-sm font-medium">{title}</p>
      {description && <p className="max-w-sm text-xs text-muted-foreground">{description}</p>}
      {children}
    </div>
  );
}
