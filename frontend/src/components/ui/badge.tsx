import { cva } from "class-variance-authority";
import type { VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-semibold tracking-wide whitespace-nowrap transition-colors",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-[#dbeafe] text-[#1e40af]",
        secondary:
          "border-transparent bg-[#f3f4f6] text-[#6b7280]",
        destructive:
          "border-transparent bg-[#fee2e2] text-[#991b1b]",
        outline:
          "border-[#e5e7eb] text-[#6b7280]",
        structural:
          "border-transparent bg-[#dbeafe] text-[#1e40af]",
        filtered:
          "border-transparent bg-[#fef3c7] text-[#92400e]",
        derived:
          "border-transparent bg-[#ede9fe] text-[#5b21b6]",
        high:
          "border-transparent bg-[#dcfce7] text-[#166534]",
        medium:
          "border-transparent bg-[#fef3c7] text-[#92400e]",
        low:
          "border-transparent bg-[#fee2e2] text-[#991b1b]",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

type BadgeVariant = NonNullable<VariantProps<typeof badgeVariants>["variant"]>;

interface BadgeProps
  extends React.ComponentProps<"span">,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
export type { BadgeVariant };
