# Applying the Siniristi design to Local SportsReel

This folder holds the shared design system for **Local SportsReel** (discover) and **Fan Companion**
(follow your team), so both features look like one product.

| File | What it is |
|---|---|
| `siniristi.css` | The design system: colour tokens for light and dark, type, buttons, chips, badges, cards, notices, table. |
| `example.html` | A small page showing the components, with a light/dark toggle. Open it in a browser. |
| `streamlit-config.toml` | The same colours for the Streamlit app (Fan Companion only). |

## Goal

Restyle the Next.js frontend (`frontend/app/globals.css`, `frontend/app/page.tsx`, `frontend/app/layout.tsx`)
to Siniristi with **two themes, light (default) and dark**, without changing what the app does or the
backend.

## Steps

1. **Fonts.** Load Plus Jakarta Sans (400–800) and IBM Plex Mono (500, 600): either `next/font/google` in
   `layout.tsx`, or keep the `@import` at the top of `siniristi.css`.
2. **Tokens.** Replace the current `:root` variables in `globals.css` with the Siniristi tokens: copy sections
   1–2 of `siniristi.css` (`:root` for light, `[data-theme="dark"]` for dark). Remove hard-coded colours
   (`#0b1018`, `#141b24`, `#d3fa5b`, `#ff9b63`, `#272719`, `#e8dba2`, …) and use tokens instead.
3. **Theme switch.**
   - Put `data-theme="light"` or `"dark"` on `<html>`.
   - Default to the visitor's system setting (`prefers-color-scheme`); remember their choice in `localStorage`.
   - Set the attribute in a small inline script in `<head>` (in `layout.tsx`) before the page paints, so there
     is no flash of the wrong theme. Add `suppressHydrationWarning` on `<html>`.
   - Add a toggle button in the top bar (`.topbarRight`), styled as `.btn .btn-secondary` or `.chip`, with an
     accessible label ("Switch to dark theme").
4. **Components.** Map the existing classes to Siniristi styles (keep the class names in `page.tsx` if that's
   simpler; just restyle them with tokens):

| Current class | Siniristi style |
|---|---|
| `.brandMark`, `.brandDot` | `--primary` background / colour, `--on-primary` text |
| `.sectionLabel`, `.eyebrow`, `.visionKicker` | `.kicker` (12px, 700, uppercase, `--primary`) |
| `.hero h1` | `.display-xl` (800, −0.03em); the `em` accent uses `--primary` |
| `.sectionHeading h2` | `.display-l` |
| `.heroPills span`, `.artChip` | `.tag` (static) |
| `.filters select`, range | inputs on `--surface` with `--line-strong` borders, 44px touch targets |
| `.resultCount` | `.kicker` style |
| `.momentCard` | `.card` (surface, 18px radius, inset `--line`); hover `--surface-2` |
| `.momentArt.*` gradients | keep, but tone them to the blue palette so text stays readable in both themes |
| `.storyButton` | link style using `--link` |
| `.demoBanner`, `.storyNotice` | `.notice .notice-demo` with a "Demo" `.notice-label` |
| `.storyModal` | `.card` + `--shadow-modal`; `.closeButton` as `.btn-secondary` |
| `.evidenceList small` (source IDs) | `.mono` / fact-chip look (IBM Plex Mono, `--primary`) |
| `.storyMeta` | `.badge .badge-ai` ("AI-written") |
| `.vision` banner | `.banner` (`--primary` background, `--on-primary` text) |
| `.heroSticker`, `.visionStamp` | `--team` (#fcd116) accent on `--team-ink` text: identity only |
| `.errorMessage` | `.notice .notice-stale` |
| `.footer` | `--muted` text, `--line` top border |

5. **Honest labels.** AI-written, demo/synthetic data and ads must stay visually distinct: use only the
   `--label-ai`, `--label-demo` and `--label-ad` colours for those, never for anything else.
6. **Bridge to the companion.** Optionally add a `.follow-card` on moment cards: "Follow {team} with your AI
   companion →" linking to the Fan Companion app.

## Done when

- Light and dark both look right: no white-on-white or dark-on-dark text, WCAG AA contrast.
- The theme toggle works, is remembered after reload, and there's no flash of the wrong theme.
- Phone width (390px) still works: one card per row, filters stacked.
- `npm run build` and `npm run lint` pass; the backend is untouched.
