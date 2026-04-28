# User Preferences

Accumulated styling and UX preferences. This file starts broad and evolves as the user's taste becomes clearer. Max 50 entries — replace outdated preferences when adding beyond the limit.

## Design Philosophy

1. **Every visual choice should have intent.** Do not accept framework defaults without evaluating whether they serve the app's purpose. Color, spacing, and layout should be deliberate.
2. **Each app should have its own visual identity.** Avoid generic patterns (uniform gray backgrounds, single blue accent, identical rounded corners). Derive the visual language from the app's domain and purpose.

## Icons & Visual Elements

3. **Use an icon library, never emoji for functional UI.** Default: Lucide React (`lucide-react`). Emoji are for content, not for buttons, nav, or labels.
4. **Prefer meaningful whitespace over decoration.** Use generous spacing to separate content. Avoid dense layouts.

## Color

5. **Derive the color palette from the app's domain.** A finance app might use deep greens and golds; a timer app might use warm reds and ambers. Don't pick colors arbitrarily — let the subject matter guide the palette.
6. **Build a full color scale, not a single accent.** At minimum: a primary color with light/dark variants, a neutral scale for text and backgrounds, and a semantic set (success, warning, error). Use CSS custom properties so the palette is easy to adjust.

## Typography & Spacing

7. **System font stack by default.** `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`. Only add custom fonts when they serve a clear design purpose.
8. **Establish a clear type hierarchy.** At least 3 distinct levels: heading, body, caption. Size differences should be noticeable, not subtle.
9. **Consistent spacing scale.** Use multiples of 4px or 8px. Pick a base unit and stick to it throughout the app.

## Layout

10. **Card-based layout with subtle shadows.** Cards for grouping related content. Keep shadows light — the card should feel elevated, not floating.
11. **Responsive by default.** CSS Grid or Flexbox. Design for mobile first when the app is consumer-facing.
12. **Centered content with max-width.** Main content area should not exceed 1200px. Avoid full-width layouts that stretch content thin.

## Components & Interaction

13. **Transitions on interactive elements.** Buttons, links, cards — anything clickable should have a subtle hover/active transition. No jarring state changes.
14. **Meaningful empty states.** Include a description of what will appear and a call-to-action to get started. Avoid bare "no data" messages.
15. **Form validation: inline, on blur or submit.** Don't validate on every keystroke. Show errors below the field, clear them when the user starts fixing.
16. **Loading: skeleton screens for content, spinners for actions.** Skeleton for page loads, small spinner for button submissions.

## Theme

17. **Dark mode if the framework supports it easily.** Use CSS variables for theming. Default to light mode.

## Quality Checklist (applied during build)

18. **Numbers should be formatted.** Currency with symbols, large numbers with separators, dates in locale-appropriate format.
19. **Hover states, focus rings, and transitions must be present.** If you can click it, it needs visual feedback.
20. **No orphaned styles.** Every CSS rule should serve a visible purpose. Remove unused styles before shipping.
