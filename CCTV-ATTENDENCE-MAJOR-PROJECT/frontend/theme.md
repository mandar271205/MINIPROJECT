# SPIT Theme Guide
## Bharatiya Vidya Bhavan's Sardar Patel Institute of Technology

---

## 🎨 Color Palette

| Role | Color | Hex | HSL |
|------|-------|-----|-----|
| Primary Red (SPIT brand) | Deep Red | `#C0272D` | `358 63% 45%` |
| Primary Red Hover | Bright Red | `#E02D2D` | `0 73% 53%` |
| Dark Red (header/footer) | Maroon | `#8B1A1A` | `0 67% 32%` |
| Background | Pure White | `#FFFFFF` | `0 0% 100%` |
| Surface / Card | Off White | `#F9F9F9` | `0 0% 98%` |
| Border | Light Gray | `#E2E2E2` | `0 0% 89%` |
| Text Primary | Near Black | `#1A1A1A` | `0 0% 10%` |
| Text Secondary | Dark Gray | `#555555` | `0 0% 33%` |
| Muted Text | Medium Gray | `#888888` | `0 0% 53%` |
| Accent Gold | Gold (Bhavan's) | `#B8860B` | `43 87% 38%` |
| Success | Green | `#16A34A` | `142 71% 36%` |
| Destructive | Red | `#DC2626` | `0 84% 50%` |

---

## 🔤 Typography

- **Font Family**: `'Inter', 'Segoe UI', sans-serif`
- **Headings**: Bold (`700`), dark (`#1A1A1A`)
- **Body**: Regular (`400`), dark gray (`#555`)
- **Labels / Badges**: Semibold (`600`), uppercase, letter-spacing

---

## 🧱 Component Tokens (CSS Variables for `index.css`)

Replace the existing `:root` block with:

```css
:root {
  --background: 0 0% 100%;
  --foreground: 0 0% 10%;

  --card: 0 0% 98%;
  --card-foreground: 0 0% 10%;

  --popover: 0 0% 100%;
  --popover-foreground: 0 0% 10%;

  --primary: 358 63% 45%;          /* SPIT Red #C0272D */
  --primary-foreground: 0 0% 100%; /* White text on red */

  --secondary: 0 0% 96%;
  --secondary-foreground: 0 0% 10%;

  --muted: 0 0% 95%;
  --muted-foreground: 0 0% 45%;

  --accent: 43 87% 38%;            /* Bhavan's Gold */
  --accent-foreground: 0 0% 100%;

  --destructive: 0 84% 50%;
  --destructive-foreground: 0 0% 100%;

  --border: 0 0% 89%;
  --input: 0 0% 89%;
  --ring: 358 63% 45%;

  --radius: 0.5rem;
}
```

Remove the `.dark { ... }` block entirely — SPIT site is light mode only.

Update the body class to remove `dark`:
```css
body {
  @apply bg-background text-foreground;
}
```

---

## 🖼️ Logo

- **Path**: `src/assets/image.png` (copy from `C:\Users\Asim\OneDrive\Desktop\projects\cctv-attendence\frontend\assets\image.png`)
- **Usage**: Import as `import spitLogo from "@/assets/image.png"`
- **Display**: Always show on a **white** background; do not place on dark or colored backgrounds
- **Size on Login**: `h-16` (64px height, auto width)
- **Size on Navbar**: `h-10` (40px height)

---

## 🔐 Login Page Design

```
┌─────────────────────────────────────────┐
│  [SPIT Logo - centered, white bg]       │
│  Sardar Patel Institute of Technology   │
│  ─────────────────────────────────────  │
│  Professor Portal                       │
│                                         │
│  [ Email / Username input ]             │
│  [ Password input ]                     │
│  [ Login Button — red bg, white text ]  │
│  "New here? Create account"             │
└─────────────────────────────────────────┘
```

- **Page background**: White (`#FFFFFF`) or very light gray (`#F5F5F5`)
- **Card**: White, subtle shadow, red top border accent (`border-t-4 border-red-700`)
- **Button**: `bg-[#C0272D] text-white hover:bg-[#8B1A1A]`
- **Input focus ring**: Red (`ring-red-600`)
- **Remove**: All dark/teal/slate colors from current login page

---

## 📊 Dashboard / Main App Design

### Header / Navbar
- Background: `#C0272D` (SPIT Red)
- Text: White
- Logo: Left-aligned SPIT logo (white bg strip if needed)
- Title: "CCTV Attendance System — SPIT"

### Cards
- Background: White (`#FFFFFF`)
- Border: `1px solid #E2E2E2`
- Shadow: `shadow-sm` (subtle)
- Hover: slight red left-border accent

### Buttons
| Type | Style |
|------|-------|
| Primary | `bg-[#C0272D] text-white hover:bg-[#8B1A1A]` |
| Secondary | `border border-[#C0272D] text-[#C0272D] hover:bg-red-50` |
| Destructive | `bg-red-600 text-white` |
| Ghost | `text-[#C0272D] hover:bg-red-50` |

### Status Badges
- Present: Green (`bg-green-100 text-green-700`)
- Absent: Red (`bg-red-100 text-red-700`)
- Late: Yellow (`bg-yellow-100 text-yellow-700`)

---

## 🗂️ Files to Modify

| File | What Changes |
|------|-------------|
| `src/index.css` | Replace CSS variables (see above), remove dark mode |
| `src/pages/login.jsx` | Full redesign — white card, SPIT logo, red button |
| `src/pages/register.jsx` | Same style as login |
| `src/pages/dashboard.jsx` | Red navbar, white cards, red primary buttons |
| `src/pages/classes/[id].jsx` | White bg, red accents |
| `src/pages/attendance/[id].jsx` | White bg, red accents |
| `src/components/ui/button.jsx` | Update variant colors to SPIT red |
| `src/components/ui/card.jsx` | White bg, light border |
| `src/components/Modal.jsx` | White modal, red header/confirm button |
| `src/assets/image.png` | ADD: Copy SPIT logo here |
| `tailwind.config.js` | Add `spit` color shorthand (optional) |

---

## 💡 Tailwind Custom Colors (optional addition to `tailwind.config.js`)

```js
colors: {
  spit: {
    red: '#C0272D',
    dark: '#8B1A1A',
    light: '#FFF0F0',
    gold: '#B8860B',
  },
  // ...existing token colors
}
```

---

## ✅ Design Checklist

- [ ] Logo visible on login and dashboard header
- [ ] All dark/slate/teal backgrounds replaced with white/light gray
- [ ] All primary buttons are SPIT red
- [ ] Input focus rings are red
- [ ] No dark mode — force light mode only
- [ ] College name "Sardar Patel Institute of Technology" shown on login
- [ ] Login card has red top accent border
- [ ] Dashboard header is SPIT red with white text

---

*Theme based on spit.ac.in — white & red institutional color scheme of Bharatiya Vidya Bhavan's SPIT, Mumbai.*