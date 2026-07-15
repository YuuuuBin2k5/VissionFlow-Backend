# VisionFlow Prism Flow — UI System

**Status:** Approved visual direction for VisionFlow Studio
**Audience:** creators, reviewers and operators producing AI video
**Applies to:** web product, design tokens, component library, motion and data visualization

## 1. Design position

VisionFlow should feel like a **cinematic post-production operating room**, not a generic SaaS dashboard and not a decorative cyberpunk terminal.

The visual language is called **Prism Flow**:

- **Prism** represents the transformation of one brief into many controlled creative signals: script, scene, voice, timeline, render and publication.
- **Flow** makes the production state legible at a glance, using a calm directional line and meaningful depth rather than constant neon animation.
- The emotional tone is precise, editorial and confident: closer to a professional color-grading suite than a hacker console.

The current CRT scanlines, infinite green shimmer, global cursor spotlight and pseudo-terminal labels are retired. They consume attention without communicating workflow state.

## 2. Product experience principles

1. **Creative work is central; system controls are peripheral.** The current brief, video, timeline or approval decision occupies the focus plane. Navigation, telemetry and configuration recede.
2. **Depth communicates hierarchy, never decoration.** Elevation distinguishes canvas, persistent rail, focused inspector and modal decision. Text always remains on a flat readable surface.
3. **Motion explains causality.** A panel moves only when it opens, changes ownership, advances a workflow or confirms a direct manipulation.
4. **Real data earns visual intensity.** Green/spectral flow, shimmer or pulse is reserved for a live backend-confirmed job. Empty, unavailable and unknown states are quiet and explicit.
5. **Adaptive, never unpredictable.** The interface can suggest a focused layout based on the active task, but users opt in and retain control. AI never silently rearranges navigation or hides needed controls.
6. **Progressive enhancement.** The complete workflow works with CSS/DOM, keyboard, reduced motion, low-end GPUs and no WebGL. Graphics amplify understanding; they never gate it.

## 3. Visual foundation

### Color roles

| Role | Token | Value | Use |
| --- | --- | --- | --- |
| Canvas | `vf-canvas` | `#090B12` | Calm near-black background with a subtle blue warmth |
| Surface 1 | `vf-surface` | `#111723` | Primary work panels |
| Surface 2 | `vf-surface-raised` | `#182131` | Inspector, active cards and menus |
| Surface 3 | `vf-surface-overlay` | `#202C40` | Modals and high-attention review surfaces |
| Text primary | `vf-ink` | `#F4F7FB` | Reading and decisive actions |
| Text secondary | `vf-ink-muted` | `#9EACC2` | Metadata and labels |
| Prism violet | `vf-prism` | `#9A8CFF` | Primary action and selected workflow |
| Signal cyan | `vf-signal` | `#64D7FF` | Live system/data connection |
| Frame gold | `vf-frame` | `#F2C875` | Review and attention, never generic warning text |
| Success | `vf-success` | `#35D39E` | Confirmed completed state |
| Warning | `vf-warning` | `#F0AE57` | Needs attention |
| Danger | `vf-danger` | `#FF7A75` | Error, destructive action and blocked state |

Prism violet is the only primary CTA. Cyan is informational and must not compete with primary actions. Status is always shown by text/icon plus color, never color alone.

### Typography and rhythm

- **Display:** Space Grotesk, 600–700. Use for page titles, project names and key metrics.
- **Reading/UI:** Inter, 400–600. Use for forms, descriptions and tables.
- **Technical metadata:** JetBrains Mono, 500. Use for IDs, timestamps, job state and prompt variables only.
- Base spacing is 4 px. Core spacing: 8, 12, 16, 24, 32, 48.
- Radius expresses hierarchy: 10 px control, 16 px panel, 24 px focus canvas. Do not use arbitrary per-component radii.
- Contrast meets WCAG AA for normal text and interactive states. No low-opacity text is used for essential status or input labels.

### Spatial depth model

| Plane | Visual treatment | Examples |
| --- | --- | --- |
| `P0 / Canvas` | No shadow, faint grain/grid only | workspace background |
| `P1 / Work` | 1 px cool edge, solid surface | cards, timeline, tables |
| `P2 / Focus` | subtle ambient shadow and prism edge | selected project, editor inspector |
| `P3 / Decision` | dimmed backdrop, strong outline, fixed focus trap | approval dialog, destructive confirmation |

This takes the useful part of spatial UI—depth as hierarchy—without pretending the web dashboard is an XR application. Apple similarly recommends using depth sparingly to clarify hierarchy and warns that depth on text reduces readability. [Apple spatial layout](https://developer.apple.com/design/human-interface-guidelines/spatial-layout?changes=latest_min_2_3__1)

## 4. Layout grammar

### Application shell

```text
┌─────────────────────────────────────────────────────────────────────┐
│ VisionFlow / project context        Command palette · profile       │
├───────────────┬─────────────────────────────────────┬───────────────┤
│ Signal Rail   │ Focus Canvas                        │ Context Rail  │
│ - Home        │ Current task or video/timeline      │ selected item │
│ - Create      │                                      │ live status   │
│ - Library     │                                      │ audit/actions │
│ - Review      │                                      │               │
│ - Publish     │                                      │               │
└───────────────┴─────────────────────────────────────┴───────────────┘
```

- **Signal Rail:** persistent navigation and a small, truthful system indicator. It contains no fake alerts, pseudo-uptime or disabled promotional controls.
- **Focus Canvas:** the primary working area. One dominant task exists per screen.
- **Context Rail:** opens only when a selected job, asset, scene or prompt benefits from context. On narrow screens it becomes a modal sheet.
- **Command palette:** `Ctrl/Cmd + K` searches real projects, jobs, prompts and available actions; it never presents unimplemented commands.

### Screen compositions

| Surface | Composition | Visual signature |
| --- | --- | --- |
| Control Tower | one production horizon plus concise exception queue | thin multi-stage flow line, not a metric wall |
| Create Short | Brief → Director plan → Render profile | stepper and editable scene cards on the focus canvas |
| Video Workbench | asset tray + timeline + inspector | film-frame handles, time ruler and waveform only when backend asset exists |
| Prompt Registry | prompt navigator + editor + evaluation/result panel | version lineage and a clear promoted-version beacon |
| Review & Publish | large signed preview + QA facts + decision rail | gold review plane; approval has deliberate confirmation motion |
| Analytics | Post-V1, not an active V1 navigation destination | add only after publication metrics have a trustworthy backend contract |

Use bento grouping only for a compact overview of independent facts. Do not use bento grids for a linear editing, approval or error-recovery task.

## 5. Motion, 3D and graphics budget

### Motion tokens

| Intent | Duration | Curve | Example |
| --- | --- | --- | --- |
| Direct feedback | 120 ms | ease-out | button press, status-chip change |
| Surface transition | 180 ms | cubic-bezier(.2,.8,.2,1) | panel/inspector open |
| Workflow handoff | 260 ms | cubic-bezier(.16,1,.3,1) | confirmed stage advances |
| Long progress | data-driven | linear | actual render progress only |

No infinite decorative motion, auto-playing parallax, cursor trails, text glitch, scanlines, bouncing buttons or animated background runs in the authenticated workspace.

### 3D/WebGL policy

| Tier | Allowed use | Implementation | Rule |
| --- | --- | --- | --- |
| Tier 0 | All product controls | CSS, SVG, DOM and Motion | Required baseline |
| Tier 1 | Timeline depth, subtle data transition | CSS transforms/SVG/Motion | Default enhancement |
| Tier 2 | Login, empty library or optional project-cover scene | lazy React Three Fiber scene | Never in the critical editing/render/publish loop |
| Tier 3 | Experimental shader lab | isolated opt-in route/feature flag | No V1 dependency |

React Three Fiber is useful only when a measured visual concept needs it. The scene must be lazy loaded, capped by a performance monitor, use on-demand rendering where possible, reuse geometry/materials and provide a static fallback. Its own documentation warns that continuous render loops are costly and that mounting/creating graphics objects repeatedly is expensive. [R3F scaling](https://r3f.docs.pmnd.rs/advanced/scaling-performance), [R3F pitfalls](https://r3f.docs.pmnd.rs/advanced/pitfalls)

WebAssembly is **not** a UI styling tool. It is deferred until profiling proves that a local visual computation cannot meet the interaction budget in TypeScript/Web Workers. Any future Wasm module must run off the main thread, have an audited source/license and retain a functional non-Wasm fallback.

### Accessibility and performance gates

- Respect `prefers-reduced-motion`; replace transitions with instant state changes and stop all nonessential motion.
- Keep keyboard focus visible, logical and trapped inside modal decisions. Every icon button has an accessible label.
- Do not use color, hover or 3D position as the only signal. Touch, keyboard and screen-reader paths remain complete.
- The authenticated Studio has no layout-shifting hero animation and no WebGL requirement.
- Enforce performance budgets in CI/Lighthouse: LCP <= 2.5 s on the staging reference profile, CLS <= 0.1, interaction responsiveness monitored, and no render-loop canvas on workbench routes by default.

Reduced-motion support is a platform preference, not an optional theme; web.dev recommends honoring it and avoiding uncontrolled animation. [web.dev motion guidance](https://web.dev/learn/accessibility/motion/)

## 6. Component system

Each component has semantic variants driven by tokens, not page-specific utility-class copies.

| Component | Required variants | Behavioral contract |
| --- | --- | --- |
| `VfButton` | primary, secondary, ghost, danger, loading | disables only during confirmed in-flight action; preserves label and accessible status |
| `VfStatusChip` | queued, active, review, success, warning, failed | maps from the canonical workflow state machine |
| `VfPanel` | work, focus, decision | applies the P1/P2/P3 depth model consistently |
| `VfFlowLine` | idle, live, blocked, complete | animation is permitted only with a real linked workflow event |
| `VfDataTable` | compact, reviewable | keyboard navigation, sticky header and empty/error/loading states |
| `VfTimeline` | short, long | renders actual scenes/assets; no placeholder clips presented as production data |
| `VfInspector` | job, asset, prompt, review | opens through URL/state so it is shareable and recoverable |
| `VfEmptyState` | no-project, no-search-result, unavailable | states the actual reason and available next action |

## 7. Adaptive UI rules

Adaptive behavior is restricted to reversible, explicit choices:

- Offer **Focus mode** while editing a script/timeline and **Review mode** while approving exports; remember the user preference per device.
- Suggest a relevant action from live workflow state, for example “Review export” when an export is actually QA-passed.
- Preserve route, navigation, keyboard shortcuts and undo/close paths. Never auto-move a destructive action or hide an error because an AI inferred a different intent.
- Any AI-generated suggestion is labeled as a suggestion, references its source workflow/prompt and requires user confirmation before mutation.

## 8. Implementation sequence

1. Replace the existing cyber-terminal global tokens and shell with Prism Flow tokens, a static ambient canvas, reduced-motion support and VisionFlow identity.
2. Build primitive components (`VfPanel`, `VfButton`, `VfStatusChip`, `VfFlowLine`) with Storybook-style isolated examples and accessibility tests.
3. Recompose Control Tower and Short Studio around Focus Canvas + Context Rail; remove visual states without backend data.
4. Apply the system to Prompt Registry and Review/Publish. Add scheduling, analytics and command palette only after their API-backed contracts enter scope.
5. Add optional lazy WebGL only after the DOM experience meets accessibility and measured performance budgets.

## 9. UI acceptance criteria

- A first-time operator can identify the current project, workflow state, primary action and blocking error within five seconds on desktop.
- All short-form creation, review and approval work at 200% browser zoom, keyboard-only, reduced motion and without WebGL.
- No visual animation or badge asserts a system state not returned by the backend.
- A screen has one primary action and no more than three competing high-emphasis elements.
- The component library has tokenized colors, spacing, type, focus state and state variants; no new page introduces hard-coded brand colors without a documented token.
- Lighthouse/accessibility and manual screen-reader checks pass before staging release.

## 10. Inspiration handling

Codrops/WebGL experiments are treated as a source of craft, not a component catalogue. The relevant lesson from current creative-coding work is intentional art direction and disciplined optimization—not putting every impressive effect into one experience. [Codrops developer spotlight](https://tympanus.net/codrops/2025/04/17/developer-spotlight-andrea-biason/)

Muzli/Prototypr/award-gallery references may inform mood boards, but VisionFlow decisions are validated against user task clarity, accessibility, measurable performance and actual backend capability.
