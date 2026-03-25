# ContextGraph AI — Design System

## Direction

**Clean Workspace** — light, spacious, modern SaaS. Approachable for non-technical users exploring ERP data. White surfaces, soft shadows, pastel graph nodes. Matches the Dodge AI product reference.

## Who

Data analysts and operations people exploring SAP Order-to-Cash entity relationships. They need to trace orders through deliveries, invoices, payments. They're investigating patterns, not writing code.

## Feel

Like a well-designed SaaS product — calm, trustworthy, professional. White and light gray surfaces with subtle borders. Comfortable enough to leave open all day.

---

## Palette

Light gray base. Blue accent. Pastel graph nodes.

| Token | Value | Usage |
|---|---|---|
| `background` | `#f7f8fa` | Page background, graph canvas |
| `surface` | `#ffffff` | Cards, panels, chat, header |
| `surface-hover` | `#f9fafb` | Button/card hover states |
| `border` | `#e5e7eb` (gray-200) | Panel borders, card borders |
| `border-light` | `#f3f4f6` (gray-100) | Subtle dividers, row separators |
| `border-hover` | `#d1d5db` (gray-300) | Hover borders |
| `text-primary` | `#111827` (gray-900) | Headings, titles, strong labels |
| `text-body` | `#374151` (gray-700) | Body text, values |
| `text-muted` | `#6b7280` (gray-500) | Breadcrumbs, secondary labels |
| `text-dim` | `#9ca3af` (gray-400) | Timestamps, hints, status text |
| `text-faint` | `#d1d5db` (gray-300) | Placeholders, empty dashes |
| `accent` | `#3b82f6` (blue-500) | Selected nodes, links, spinners |
| `accent-dark` | `#1e40af` (blue-800) | Selected node labels |
| `accent-bg` | `#dbeafe` (blue-100) | Badge backgrounds |
| `node-default` | `#e8a0a0` | Default graph node fill (pastel pink/salmon) |
| `node-border` | `#d48a8a` | Default graph node stroke |
| `node-dimmed` | `#e8d5d5` | Dimmed node fill |
| `link` | `#93c5fd` (blue-300) | Graph link color |
| `success` | `#22c55e` (green-500) | Status dots (online) |
| `warning` | `#f59e0b` (amber-500) | Status dots (busy), limit warnings |
| `error` | `#ef4444` (red-500) | Error states |
| `dark-button` | `#1e293b` (slate-800) | Active toggle, send button |

---

## Typography

**Typeface:** Inter (system-ui fallback)

| Role | Size | Weight | Color |
|---|---|---|---|
| Header breadcrumb | 14px | 400/600 | `#6b7280` / `#111827` (strong) |
| Card title | 16px | 700 | `#111827` |
| Key-value key | 13px | 600 | `#111827` |
| Key-value value | 13px | 400 | `#374151` |
| Chat message | 14px | 400 | `#374151` |
| Chat sender | 13px | 600 | `#111827` |
| Chat role | 11px | 400 | `#9ca3af` |
| Status text | 12px | 500 | `#6b7280` |
| Control button | 12px | 500 | `#374151` |
| Graph stats | 11px mono | 400 | `#9ca3af` |

---

## Spacing

| Context | Value |
|---|---|
| Card inner padding | 16-20px |
| Header height | 52px |
| Chat panel width | 360px (300-420 range) |
| Control button padding | 8px 14px |
| Message gap | 20px |
| Input area padding | 16px |

---

## Depth

| Elevation | Treatment |
|---|---|
| Base (graph) | `#f7f8fa`, no shadow |
| Header | `#ffffff`, bottom border `#e5e7eb` |
| Panel (chat) | `#ffffff`, left border `#e5e7eb` |
| Inspector card | `#ffffff`, 1px `#e5e7eb` border, `shadow: 0 8px 30px rgba(0,0,0,0.12)` |
| Control buttons | `#ffffff`, 1px `#e5e7eb` border, `shadow: 0 1px 3px rgba(0,0,0,0.06)` |
| Tooltip | `#ffffff`, 1px `#e5e7eb` border, `shadow: 0 8px 24px rgba(0,0,0,0.1)` |
| Status bar | `rgba(247,248,250,0.9)`, `backdrop-blur: 8px` |

---

## Radius

| Element | Radius |
|---|---|
| Inspector card | 12px |
| Chat message bubbles | 12px |
| Control buttons | 8px |
| Input container | 12px |
| Send button | 8px |
| Agent avatar | 8px |
| User avatar | 50% |
| Header icon | 6px |
| Badges | 6px (rounded-md) |

---

## Components

### Header
- White background, 52px, bottom border
- Icon in gray rounded box + pipe separator + breadcrumb
- Breadcrumb: "Mapping / **Order to Cash**" — muted + bold pattern

### Control buttons (graph overlay)
- Top-left of graph area
- White pill buttons with icon + label
- Active state: dark slate background (#1e293b), white text
- "Minimize" = zoom-to-fit, "Hide/Show Granular Overlay" = toggle edge labels

### Graph nodes
- Default: pastel pink (#e8a0a0), 6px radius
- Selected: solid blue (#3b82f6), 10px radius, blue border
- Neighbour: default color, 7px radius
- Dimmed: faded pink (#e8d5d5), 25% opacity
- Labels: only visible at zoom >= 1.5 or for selected node

### Graph links
- Uniform light blue (#93c5fd)
- Width: 1px default, 2.5px when connected to selected
- Edge labels: gray, only at zoom >= 1.5, controlled by overlay toggle

### Inspector card (floating)
- White card, rounded-12, soft shadow
- Title (bold, 16px) + key-value list
- Keys are bold, values are normal weight
- Rows separated by light gray lines (#f3f4f6)
- "Additional fields hidden for readability" in italic gray for overflow
- No close button — background click dismisses

### Chat panel (branded)
- Header: "Chat with Graph" / "Order to Cash" subtitle
- Messages: avatar + name/role header + content block
- Agent: dark rounded-8 avatar icon + "Dodge AI" / "Graph Agent"
- User: gray circle avatar + "You" + gray bubble background
- Initial greeting message on mount
- Status bar: green/amber dot + "Dodge AI is awaiting instructions"
- Input: textarea + dark "Send" button
- Placeholder: "Analyze anything"

### Status bar (DebugPanel)
- Frosted glass: light background at 90% + backdrop-blur
- Mono, small dot indicators (blue/gray/green)

---

## Animations

| Name | Duration | Easing | Usage |
|---|---|---|---|
| `inspector-in` | 200ms | cubic-bezier(0.16, 1, 0.3, 1) | Inspector card slide-up |
| `spin` | 800ms | linear | Loading spinners |
| Transitions | 150ms | ease | Hover states, button interactions |
