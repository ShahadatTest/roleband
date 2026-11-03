// Single UI icon set for the whole dashboard.
//
// Backed by `lucide-react` (Feather's maintained continuation, ISC).
//
// NAMES ARE OURS, not Lucide's. The indirection is the point: it keeps call
// sites off upstream's naming churn (upstream renames glyphs, such as
// `help-circle` -> `circle-question-mark`), so a rename there is a one-line
// edit here.
//
// Brand/company marks are NOT in this set — Lucide carries no company logos.
// Those live in `CompanyIcon.tsx`, backed by Simple Icons.
// Canonical Lucide names only — the older `XCircle`/`HelpCircle`/`CheckCircle2`
// aliases still resolve but are deprecated upstream.
import {
  Activity,
  Undo2,
  Cloud,
  ArrowDown,
  ArrowLeft,
  ArrowLeftRight,
  ArrowRight,
  ArrowUp,
  ArrowUpRight,
  Bell,
  Building2,
  ChartColumn,
  Check,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  CircleCheck,
  CircleHelp,
  CircleX,
  Clock,
  Columns2,
  Compass,
  Copy,
  Laptop,
  ExternalLink,
  Eye,
  EyeOff,
  Files,
  Gem,
  Globe,
  Info,
  LayoutGrid,
  MapPin,
  Minus,
  Moon,
  OctagonX,
  PanelLeftClose,
  PanelLeftOpen,
  Pause,
  Play,
  Pencil,
  Plus,
  Puzzle,
  RefreshCw,
  Search,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Star,
  Sun,
  Trash2,
  TrendingDown,
  TrendingUp,
  TriangleAlert,
  UserRound,
  X,
  type LucideIcon,
} from "lucide-react";

// Our stable name -> upstream component. Adding a glyph means adding a row here
// and nothing else.
const ICONS = {
  activity: Activity,
  alert: TriangleAlert,
  alertCircle: CircleAlert,
  arrowDown: ArrowDown,
  arrowLeft: ArrowLeft,
  arrowLeftRight: ArrowLeftRight,
  arrowRight: ArrowRight,
  arrowUp: ArrowUp,
  arrowUpRight: ArrowUpRight,
  bell: Bell,
  building: Building2,
  chart: ChartColumn,
  check: Check,
  checkCircle: CircleCheck,
  chevronDown: ChevronDown,
  chevronUp: ChevronUp,
  clock: Clock,
  close: X,
  columns: Columns2,
  undo: Undo2,
  compass: Compass,
  copy: Copy,
  edit: Pencil,
  errorOctagon: OctagonX,
  external: ExternalLink,
  eye: Eye,
  eyeOff: EyeOff,
  // Two postings stacked: the Duplicates tab. `copy` is the copy action.
  files: Files,
  gear: Settings,
  gem: Gem,
  globe: Globe,
  grid: LayoutGrid,
  help: CircleHelp,
  info: Info,
  minus: Minus,
  moon: Moon,
  panelCollapse: PanelLeftClose,
  panelExpand: PanelLeftOpen,
  cloud: Cloud,
  laptop: Laptop,
  pause: Pause,
  play: Play,
  // A plugin: an add-on piece that fits into RoleBand.
  plugin: Puzzle,
  person: UserRound,
  pin: MapPin,
  plus: Plus,
  refresh: RefreshCw,
  search: Search,
  sliders: SlidersHorizontal,
  sparkle: Sparkles,
  star: Star,
  sun: Sun,
  trash: Trash2,
  trendDown: TrendingDown,
  trendUp: TrendingUp,
  xCircle: CircleX,
  // `cluster` reads as "related things joined" — a share/node graph, not a grid.
} satisfies Record<string, LucideIcon>;

/** Every glyph the dashboard may render. Carriers type against this, so a typo
 *  fails the build instead of silently rendering an empty <svg>. */
export type IconName = keyof typeof ICONS;


export function Icon({
  name,
  size = 16,
  filled = false,
}: {
  name: IconName;
  size?: number;
  /** Solid-fill variant. Only meaningful for glyphs with an enclosed area
   *  (`star`, `gem`); used for on/off affordances like the favorite toggle. */
  filled?: boolean;
}) {
  const Glyph = ICONS[name];
  return (
    <Glyph
      width={size}
      height={size}
      strokeWidth={2}
      fill={filled ? "currentColor" : "none"}
      aria-hidden="true"
      focusable="false"
    />
  );
}
