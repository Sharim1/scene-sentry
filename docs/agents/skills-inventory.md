# Agent skills inventory

Generated: 2026-05-28

This report lists skills installed for Claude Code / Cursor agents on this machine.

## How skills are stored

| Layer | Path | Role |
|-------|------|------|
| **Canonical** | `~/.agents/skills/<name>/` | Source skill content (`SKILL.md` + references) |
| **Claude Code** | `~/.claude/skills/<name>` | Symlink → `~/.agents/skills/<name>` (invoke as `/name`) |
| **Cursor (Clerk plugin)** | `~/.cursor/plugins/cache/cursor-public/clerk/.../skills/` | Plugin-bundled copy; separate from this inventory |

**Total skills in `~/.agents/skills`:** 91
**Linked in `~/.claude/skills`:** 91 (all agents skills symlinked)

---

## Quick guide by development stage

Use this to pick a skill by *when* you are in the workflow. Invoke in chat with `/skill-name` (Claude Code) or attach/reference the skill in Cursor.

### 1. Discovery & requirements

*Clarify what to build before writing code*

| Skill | Invoke | When to use |
|-------|--------|-------------|
| `interview-me` | `/interview-me` | Extracts what the user actually wants instead of what they think they should want. Achieves this through one-question-at-a-time interview until ~95% confidence about the underlying intent. |
| `idea-refine` | `/idea-refine` | Refines ideas iteratively. Refine ideas through structured divergent and convergent thinking. |
| `spec-driven-development` | `/spec-driven-development` | Creates specs before coding. |
| `planning-and-task-breakdown` | `/planning-and-task-breakdown` | Breaks work into ordered tasks. |
| `grill-me` | `/grill-me` | Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. |
| `grill-with-docs` | `/grill-with-docs` | Grilling session that challenges your plan against the existing domain model, sharpens terminology, and updates documentation (CONTEXT.md, ADRs) inline as decisions crystallise. |
| `to-prd` | `/to-prd` | Turn the current conversation context into a PRD and publish it to the project issue tracker. |
| `prototype` | `/prototype` | Build a throwaway prototype to flesh out a design before committing to it. Routes between two branches — a runnable terminal app for state/business-logic questions, or several radically different UI variations toggleable from one route. |
| `zoom-out` | `/zoom-out` | Tell the agent to zoom out and give broader context or a higher-level perspective. |
| `find-skills` | `/find-skills` | Helps users discover and install agent skills when they ask questions like "how do I do X", "find a skill for X", "is there a skill that can...", or express interest in extending capabilities. |

### 2. Design & architecture

*Shape APIs, structure, and documented decisions*

| Skill | Invoke | When to use |
|-------|--------|-------------|
| `api-and-interface-design` | `/api-and-interface-design` | Guides stable API and interface design. |
| `improve-codebase-architecture` | `/improve-codebase-architecture` | Find deepening opportunities in a codebase, informed by the domain language in CONTEXT.md and the decisions in docs/adr/. |
| `documentation-and-adrs` | `/documentation-and-adrs` | Records decisions and documentation. |
| `context-engineering` | `/context-engineering` | Optimizes agent context setup. |
| `setup-matt-pocock-skills` | `/setup-matt-pocock-skills` | Sets up an `## Agent skills` block in AGENTS.md/CLAUDE.md and `docs/agents/` so the engineering skills know this repo's issue tracker (GitHub or local markdown), triage label vocabulary, and domain doc layout. |
| `doubt-driven-development` | `/doubt-driven-development` | Subjects every non-trivial decision to a fresh-context adversarial review before it stands. |

### 3. Implementation

*Write and refine application code*

| Skill | Invoke | When to use |
|-------|--------|-------------|
| `incremental-implementation` | `/incremental-implementation` | Delivers changes incrementally. |
| `frontend-ui-engineering` | `/frontend-ui-engineering` | Builds production-quality UIs. |
| `source-driven-development` | `/source-driven-development` | Grounds every implementation decision in official documentation. |
| `code-simplification` | `/code-simplification` | Simplifies code for clarity. |
| `caveman` | `/caveman` | Ultra-compressed replies — less tokens, same technical accuracy |
| `here-now` | `/here-now` | Publish sites or store private files on here.now (cloud Drive + live URLs) |

### 4. Authentication (Clerk)

*Add and integrate Clerk auth across stacks*

| Skill | Invoke | When to use |
|-------|--------|-------------|
| `clerk` | `/clerk` | Router — start here for any Clerk task; routes to the right skill |
| `clerk-android` | `/clerk-android` | Native Android — Kotlin/Compose (not Expo) |
| `clerk-astro-patterns` | `/clerk-astro-patterns` | Astro — SSR, islands, middleware, API routes |
| `clerk-backend-api` | `/clerk-backend-api` | Admin/API — browse and call Clerk REST API |
| `clerk-billing` | `/clerk-billing` | Monetization — plans, PricingTable, entitlements, seat billing |
| `clerk-chrome-extension-patterns` | `/clerk-chrome-extension-patterns` | Chrome extensions — popup, syncHost, service workers |
| `clerk-custom-ui` | `/clerk-custom-ui` | UI — custom sign-in/up flows, themes, branding |
| `clerk-expo` | `/clerk-expo` | Expo/RN setup — prebuilt or hook-driven flows (@clerk/expo) |
| `clerk-expo-patterns` | `/clerk-expo-patterns` | Expo/RN patterns — SecureStore, deep links, Expo Router |
| `clerk-nextjs-patterns` | `/clerk-nextjs-patterns` | Next.js — middleware, Server Actions, server/client auth |
| `clerk-nuxt-patterns` | `/clerk-nuxt-patterns` | Nuxt 3 — middleware, SSR, server API routes |
| `clerk-orgs` | `/clerk-orgs` | B2B — organizations, RBAC, org switching, enterprise SSO |
| `clerk-react-patterns` | `/clerk-react-patterns` | React SPA — Vite/CRA, hooks, React Router protected routes |
| `clerk-react-router-patterns` | `/clerk-react-router-patterns` | React Router v7 — loaders, SSR auth, rootAuthLoader |
| `clerk-setup` | `/clerk-setup` | Greenfield — add Clerk to a new or existing project (any framework) |
| `clerk-swift` | `/clerk-swift` | Native iOS — Swift/SwiftUI, ClerkKit |
| `clerk-tanstack-patterns` | `/clerk-tanstack-patterns` | TanStack Start — server functions, route guards |
| `clerk-testing` | `/clerk-testing` | E2E — Playwright/Cypress auth flows |
| `clerk-vue-patterns` | `/clerk-vue-patterns` | Vue 3 — composables, router guards, Pinia |
| `clerk-webhooks` | `/clerk-webhooks` | Events — user/org sync, notifications, database sync |

### 5. Data (Supabase)

*Database, auth platform, and Postgres tuning*

| Skill | Invoke | When to use |
|-------|--------|-------------|
| `supabase` | `/supabase` | Use when doing ANY task involving Supabase. |
| `supabase-postgres-best-practices` | `/supabase-postgres-best-practices` | Postgres performance optimization and best practices from Supabase. |

### 6. Research (Tavily)

*Web search, extract, crawl, and deep research*

| Skill | Invoke | When to use |
|-------|--------|-------------|
| `tavily-search` | `/tavily-search` | | |
| `tavily-research` | `/tavily-research` | | |
| `tavily-extract` | `/tavily-extract` | | |
| `tavily-crawl` | `/tavily-crawl` | | |
| `tavily-map` | `/tavily-map` | | |
| `tavily-cli` | `/tavily-cli` | | |
| `tavily-best-practices` | `/tavily-best-practices` | Build production-ready Tavily integrations with best practices baked in. |

### 7. Testing

*Test-first development and browser verification*

| Skill | Invoke | When to use |
|-------|--------|-------------|
| `tdd` | `/tdd` | Test-driven development with red-green-refactor loop. |
| `test-driven-development` | `/test-driven-development` | Drives development with tests. |
| `browser-testing-with-devtools` | `/browser-testing-with-devtools` | Tests in real browsers. |
| `clerk-testing` | `/clerk-testing` | E2E — Playwright/Cypress auth flows |

### 8. Quality & debugging

*Review, harden, diagnose, and optimize*

| Skill | Invoke | When to use |
|-------|--------|-------------|
| `code-review-and-quality` | `/code-review-and-quality` | Conducts multi-axis code review. |
| `security-and-hardening` | `/security-and-hardening` | Hardens code against vulnerabilities. |
| `debugging-and-error-recovery` | `/debugging-and-error-recovery` | Guides systematic root-cause debugging. |
| `diagnose` | `/diagnose` | Disciplined diagnosis loop for hard bugs and performance regressions. Reproduce → minimise → hypothesise → instrument → fix → regression-test. |
| `performance-optimization` | `/performance-optimization` | Optimizes application performance. |

### 9. Delivery & launch

*Git workflow, CI/CD, and production launch*

| Skill | Invoke | When to use |
|-------|--------|-------------|
| `git-workflow-and-versioning` | `/git-workflow-and-versioning` | Structures git workflow practices. |
| `push-changes` | `/push-changes` | Commit and push code changes following Conventional Commits and branch-per-change workflow. |
| `ci-cd-and-automation` | `/ci-cd-and-automation` | Automates CI/CD pipeline setup. |
| `shipping-and-launch` | `/shipping-and-launch` | Prepares production launches. |

### 10. Hosting (Render)

*Deploy, configure, and operate on Render*

| Skill | Invoke | When to use |
|-------|--------|-------------|
| `render-background-workers` | `/render-background-workers` | Queue consumers — async jobs, graceful shutdown |
| `render-blueprints` | `/render-blueprints` | IaC — author and validate render.yaml |
| `render-cli` | `/render-cli` | CLI — deploy, logs, SSH, psql, validate |
| `render-cron-jobs` | `/render-cron-jobs` | Scheduled tasks — cron expressions |
| `render-debug` | `/render-debug` | Failed deploys — logs, OOM, env, port binding |
| `render-deploy` | `/render-deploy` | First deploy — Blueprints, service setup, dashboard links |
| `render-disks` | `/render-disks` | Persistent storage — mount paths, scaling limits |
| `render-docker` | `/render-docker` | Container builds and deploy constraints |
| `render-domains` | `/render-domains` | Custom domains and TLS |
| `render-env-vars` | `/render-env-vars` | Secrets and env groups in Blueprints/Dashboard |
| `render-keyvalue` | `/render-keyvalue` | Redis/Valkey — cache, sessions, queues |
| `render-mcp` | `/render-mcp` | Render MCP server setup and troubleshooting |
| `render-migrate-from-heroku` | `/render-migrate-from-heroku` | Heroku → Render migration |
| `render-monitor` | `/render-monitor` | Health, metrics, logs after deploy |
| `render-networking` | `/render-networking` | Private network between services |
| `render-postgres` | `/render-postgres` | Managed Postgres — connection strings, HA, backups |
| `render-private-services` | `/render-private-services` | Internal-only APIs on private network |
| `render-scaling` | `/render-scaling` | Autoscaling and instance sizing |
| `render-static-sites` | `/render-static-sites` | Static/CDN — SPAs, publish path, redirects |
| `render-web-services` | `/render-web-services` | Web services — ports, health checks, domains, deploy lifecycle |
| `render-workflows` | `/render-workflows` | Render Workflows — multi-step jobs, fan-out |

### 11. Issues & handoff

*Tracker workflow, triage, and agent handoffs*

| Skill | Invoke | When to use |
|-------|--------|-------------|
| `triage` | `/triage` | Triage issues through a state machine driven by triage roles. |
| `to-issues` | `/to-issues` | Break a plan, spec, or PRD into independently-grabbable issues on the project issue tracker using tracer-bullet vertical slices. |
| `handoff` | `/handoff` | Compact the current conversation into a handoff document for another agent to pick up. |

### 12. Migration & sunset

*Move off legacy systems safely*

| Skill | Invoke | When to use |
|-------|--------|-------------|
| `deprecation-and-migration` | `/deprecation-and-migration` | Manages deprecation and migration. |
| `render-migrate-from-heroku` | `/render-migrate-from-heroku` | Heroku → Render migration |

### 13. Meta

*Discover, author, and manage skills*

| Skill | Invoke | When to use |
|-------|--------|-------------|
| `using-agent-skills` | `/using-agent-skills` | Discovers and invokes agent skills. |
| `write-a-skill` | `/write-a-skill` | Create new agent skills with proper structure, progressive disclosure, and bundled resources. |

---

## Clerk skills (detail)

Start with `/clerk` (router) if unsure. Full set from [clerk/skills](https://github.com/clerk/skills).

| Skill | Location | Stage | Usage |
|-------|----------|-------|-------|
| `clerk` | `~/.agents/skills/clerk/` | Auth | Router — start here for any Clerk task; routes to the right skill |
| `clerk-android` | `~/.agents/skills/clerk-android/` | Auth | Native Android — Kotlin/Compose (not Expo) |
| `clerk-astro-patterns` | `~/.agents/skills/clerk-astro-patterns/` | Auth | Astro — SSR, islands, middleware, API routes |
| `clerk-backend-api` | `~/.agents/skills/clerk-backend-api/` | Auth | Admin/API — browse and call Clerk REST API |
| `clerk-billing` | `~/.agents/skills/clerk-billing/` | Auth | Monetization — plans, PricingTable, entitlements, seat billing |
| `clerk-chrome-extension-patterns` | `~/.agents/skills/clerk-chrome-extension-patterns/` | Auth | Chrome extensions — popup, syncHost, service workers |
| `clerk-custom-ui` | `~/.agents/skills/clerk-custom-ui/` | Auth | UI — custom sign-in/up flows, themes, branding |
| `clerk-expo` | `~/.agents/skills/clerk-expo/` | Auth | Expo/RN setup — prebuilt or hook-driven flows (@clerk/expo) |
| `clerk-expo-patterns` | `~/.agents/skills/clerk-expo-patterns/` | Auth | Expo/RN patterns — SecureStore, deep links, Expo Router |
| `clerk-nextjs-patterns` | `~/.agents/skills/clerk-nextjs-patterns/` | Auth | Next.js — middleware, Server Actions, server/client auth |
| `clerk-nuxt-patterns` | `~/.agents/skills/clerk-nuxt-patterns/` | Auth | Nuxt 3 — middleware, SSR, server API routes |
| `clerk-orgs` | `~/.agents/skills/clerk-orgs/` | Auth | B2B — organizations, RBAC, org switching, enterprise SSO |
| `clerk-react-patterns` | `~/.agents/skills/clerk-react-patterns/` | Auth | React SPA — Vite/CRA, hooks, React Router protected routes |
| `clerk-react-router-patterns` | `~/.agents/skills/clerk-react-router-patterns/` | Auth | React Router v7 — loaders, SSR auth, rootAuthLoader |
| `clerk-setup` | `~/.agents/skills/clerk-setup/` | Auth | Greenfield — add Clerk to a new or existing project (any framework) |
| `clerk-swift` | `~/.agents/skills/clerk-swift/` | Auth | Native iOS — Swift/SwiftUI, ClerkKit |
| `clerk-tanstack-patterns` | `~/.agents/skills/clerk-tanstack-patterns/` | Auth | TanStack Start — server functions, route guards |
| `clerk-testing` | `~/.agents/skills/clerk-testing/` | Auth | E2E — Playwright/Cypress auth flows |
| `clerk-vue-patterns` | `~/.agents/skills/clerk-vue-patterns/` | Auth | Vue 3 — composables, router guards, Pinia |
| `clerk-webhooks` | `~/.agents/skills/clerk-webhooks/` | Auth | Events — user/org sync, notifications, database sync |

---

## Render skills (detail)

| Skill | Location | Stage | Usage |
|-------|----------|-------|-------|
| `render-background-workers` | `~/.agents/skills/render-background-workers/` | Hosting | Queue consumers — async jobs, graceful shutdown |
| `render-blueprints` | `~/.agents/skills/render-blueprints/` | Hosting | IaC — author and validate render.yaml |
| `render-cli` | `~/.agents/skills/render-cli/` | Hosting | CLI — deploy, logs, SSH, psql, validate |
| `render-cron-jobs` | `~/.agents/skills/render-cron-jobs/` | Hosting | Scheduled tasks — cron expressions |
| `render-debug` | `~/.agents/skills/render-debug/` | Hosting | Failed deploys — logs, OOM, env, port binding |
| `render-deploy` | `~/.agents/skills/render-deploy/` | Hosting | First deploy — Blueprints, service setup, dashboard links |
| `render-disks` | `~/.agents/skills/render-disks/` | Hosting | Persistent storage — mount paths, scaling limits |
| `render-docker` | `~/.agents/skills/render-docker/` | Hosting | Container builds and deploy constraints |
| `render-domains` | `~/.agents/skills/render-domains/` | Hosting | Custom domains and TLS |
| `render-env-vars` | `~/.agents/skills/render-env-vars/` | Hosting | Secrets and env groups in Blueprints/Dashboard |
| `render-keyvalue` | `~/.agents/skills/render-keyvalue/` | Hosting | Redis/Valkey — cache, sessions, queues |
| `render-mcp` | `~/.agents/skills/render-mcp/` | Hosting | Render MCP server setup and troubleshooting |
| `render-migrate-from-heroku` | `~/.agents/skills/render-migrate-from-heroku/` | Hosting | Heroku → Render migration |
| `render-monitor` | `~/.agents/skills/render-monitor/` | Hosting | Health, metrics, logs after deploy |
| `render-networking` | `~/.agents/skills/render-networking/` | Hosting | Private network between services |
| `render-postgres` | `~/.agents/skills/render-postgres/` | Hosting | Managed Postgres — connection strings, HA, backups |
| `render-private-services` | `~/.agents/skills/render-private-services/` | Hosting | Internal-only APIs on private network |
| `render-scaling` | `~/.agents/skills/render-scaling/` | Hosting | Autoscaling and instance sizing |
| `render-static-sites` | `~/.agents/skills/render-static-sites/` | Hosting | Static/CDN — SPAs, publish path, redirects |
| `render-web-services` | `~/.agents/skills/render-web-services/` | Hosting | Web services — ports, health checks, domains, deploy lifecycle |
| `render-workflows` | `~/.agents/skills/render-workflows/` | Hosting | Render Workflows — multi-step jobs, fan-out |

---

## Full inventory (alphabetical)

| Skill | Invoke | `~/.agents/skills` | `~/.claude/skills` | Description |
|-------|--------|--------------------|--------------------|-------------|
| `api-and-interface-design` | `/api-and-interface-design` | `~/.agents/skills/api-and-interface-design/` | Yes | Guides stable API and interface design. Use when designing APIs, module boundaries, or any public interface. Use when creating REST or GraphQL endpoints, def… |
| `browser-testing-with-devtools` | `/browser-testing-with-devtools` | `~/.agents/skills/browser-testing-with-devtools/` | Yes | Tests in real browsers. Use when building or debugging anything that runs in a browser. Use when you need to inspect the DOM, capture console errors, analyze… |
| `caveman` | `/caveman` | `~/.agents/skills/caveman/` | Yes | > |
| `ci-cd-and-automation` | `/ci-cd-and-automation` | `~/.agents/skills/ci-cd-and-automation/` | Yes | Automates CI/CD pipeline setup. Use when setting up or modifying build and deployment pipelines. Use when you need to automate quality gates, configure test … |
| `clerk` | `/clerk` | `~/.agents/skills/clerk/` | Yes | Clerk authentication router. Use when user asks about adding authentication, setting up Clerk, custom sign-in flows, Swift or native iOS auth, native Android… |
| `clerk-android` | `/clerk-android` | `~/.agents/skills/clerk-android/` | Yes | Implement Clerk authentication for native Android apps using Kotlin and Jetpack Compose with clerk-android source-guided patterns. Use for prebuilt AuthView/… |
| `clerk-astro-patterns` | `/clerk-astro-patterns` | `~/.agents/skills/clerk-astro-patterns/` | Yes | Astro patterns with Clerk — middleware, SSR pages, island components, |
| `clerk-backend-api` | `/clerk-backend-api` | `~/.agents/skills/clerk-backend-api/` | Yes | Clerk backend REST API |
| `clerk-billing` | `/clerk-billing` | `~/.agents/skills/clerk-billing/` | Yes | Clerk Billing for subscription management - render Clerk's PricingTable |
| `clerk-chrome-extension-patterns` | `/clerk-chrome-extension-patterns` | `~/.agents/skills/clerk-chrome-extension-patterns/` | Yes | Chrome Extension auth with @clerk/chrome-extension -- popup/sidepanel |
| `clerk-custom-ui` | `/clerk-custom-ui` | `~/.agents/skills/clerk-custom-ui/` | Yes | Custom authentication flows and component appearance - hooks (useSignIn, useSignUp), themes, colors, fonts, CSS. Use for custom sign-in/sign-up flows, appear… |
| `clerk-expo` | `/clerk-expo` | `~/.agents/skills/clerk-expo/` | Yes | Implement Clerk authentication for Expo and React Native apps using @clerk/expo |
| `clerk-expo-patterns` | `/clerk-expo-patterns` | `~/.agents/skills/clerk-expo-patterns/` | Yes | Expo / React Native patterns with Clerk — SecureStore token cache, OAuth |
| `clerk-nextjs-patterns` | `/clerk-nextjs-patterns` | `~/.agents/skills/clerk-nextjs-patterns/` | Yes | Advanced Next.js patterns - middleware, Server Actions, caching with Clerk. |
| `clerk-nuxt-patterns` | `/clerk-nuxt-patterns` | `~/.agents/skills/clerk-nuxt-patterns/` | Yes | Nuxt 3 auth patterns with @clerk/nuxt - middleware, composables, server |
| `clerk-orgs` | `/clerk-orgs` | `~/.agents/skills/clerk-orgs/` | Yes | Clerk Organizations for B2B SaaS - create multi-tenant apps with org switching, role-based access, verified domains, and enterprise SSO. Use for team workspa… |
| `clerk-react-patterns` | `/clerk-react-patterns` | `~/.agents/skills/clerk-react-patterns/` | Yes | React SPA auth patterns with @clerk/react for Vite/CRA - ClerkProvider |
| `clerk-react-router-patterns` | `/clerk-react-router-patterns` | `~/.agents/skills/clerk-react-router-patterns/` | Yes | React Router v7 patterns with Clerk — rootAuthLoader, getAuth in loaders, |
| `clerk-setup` | `/clerk-setup` | `~/.agents/skills/clerk-setup/` | Yes | Add Clerk authentication to any project by following the official quickstart guides. |
| `clerk-swift` | `/clerk-swift` | `~/.agents/skills/clerk-swift/` | Yes | Implement Clerk authentication for native Swift and iOS apps using ClerkKit and ClerkKitUI source-guided patterns. Use for prebuilt AuthView or custom native… |
| `clerk-tanstack-patterns` | `/clerk-tanstack-patterns` | `~/.agents/skills/clerk-tanstack-patterns/` | Yes | TanStack React Start auth patterns with @clerk/tanstack-react-start |
| `clerk-testing` | `/clerk-testing` | `~/.agents/skills/clerk-testing/` | Yes | E2E testing for Clerk apps. Use with Playwright or Cypress for auth flow tests. |
| `clerk-vue-patterns` | `/clerk-vue-patterns` | `~/.agents/skills/clerk-vue-patterns/` | Yes | Vue 3 patterns with Clerk — composables (useAuth, useUser, |
| `clerk-webhooks` | `/clerk-webhooks` | `~/.agents/skills/clerk-webhooks/` | Yes | Clerk webhooks for real-time events and data syncing. Listen for user creation, updates, deletion, and organization events. Build event-driven features like … |
| `code-review-and-quality` | `/code-review-and-quality` | `~/.agents/skills/code-review-and-quality/` | Yes | Conducts multi-axis code review. Use before merging any change. Use when reviewing code written by yourself, another agent, or a human. Use when you need to … |
| `code-simplification` | `/code-simplification` | `~/.agents/skills/code-simplification/` | Yes | Simplifies code for clarity. Use when refactoring code for clarity without changing behavior. Use when code works but is harder to read, maintain, or extend … |
| `context-engineering` | `/context-engineering` | `~/.agents/skills/context-engineering/` | Yes | Optimizes agent context setup. Use when starting a new session, when agent output quality degrades, when switching between tasks, or when you need to configu… |
| `debugging-and-error-recovery` | `/debugging-and-error-recovery` | `~/.agents/skills/debugging-and-error-recovery/` | Yes | Guides systematic root-cause debugging. Use when tests fail, builds break, behavior doesn't match expectations, or you encounter any unexpected error. Use wh… |
| `deprecation-and-migration` | `/deprecation-and-migration` | `~/.agents/skills/deprecation-and-migration/` | Yes | Manages deprecation and migration. Use when removing old systems, APIs, or features. Use when migrating users from one implementation to another. Use when de… |
| `diagnose` | `/diagnose` | `~/.agents/skills/diagnose/` | Yes | Disciplined diagnosis loop for hard bugs and performance regressions. Reproduce → minimise → hypothesise → instrument → fix → regression-test. Use when user … |
| `documentation-and-adrs` | `/documentation-and-adrs` | `~/.agents/skills/documentation-and-adrs/` | Yes | Records decisions and documentation. Use when making architectural decisions, changing public APIs, shipping features, or when you need to record context tha… |
| `doubt-driven-development` | `/doubt-driven-development` | `~/.agents/skills/doubt-driven-development/` | Yes | Subjects every non-trivial decision to a fresh-context adversarial review before it stands. Use when correctness matters more than speed, when working in unf… |
| `find-skills` | `/find-skills` | `~/.agents/skills/find-skills/` | No | Helps users discover and install agent skills when they ask questions like "how do I do X", "find a skill for X", "is there a skill that can...", or express … |
| `frontend-ui-engineering` | `/frontend-ui-engineering` | `~/.agents/skills/frontend-ui-engineering/` | Yes | Builds production-quality UIs. Use when building or modifying user-facing interfaces. Use when creating components, implementing layouts, managing state, or … |
| `git-workflow-and-versioning` | `/git-workflow-and-versioning` | `~/.agents/skills/git-workflow-and-versioning/` | Yes | Structures git workflow practices. Use when making any code change. Use when committing, branching, resolving conflicts, or when you need to organize work ac… |
| `grill-me` | `/grill-me` | `~/.agents/skills/grill-me/` | Yes | Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Use when user wants t… |
| `grill-with-docs` | `/grill-with-docs` | `~/.agents/skills/grill-with-docs/` | Yes | Grilling session that challenges your plan against the existing domain model, sharpens terminology, and updates documentation (CONTEXT.md, ADRs) inline as de… |
| `handoff` | `/handoff` | `~/.agents/skills/handoff/` | Yes | Compact the current conversation into a handoff document for another agent to pick up. |
| `here-now` | `/here-now` | `~/.agents/skills/here-now/` | Yes | > |
| `idea-refine` | `/idea-refine` | `~/.agents/skills/idea-refine/` | Yes | Refines ideas iteratively. Refine ideas through structured divergent and convergent thinking. Use "idea-refine" or "ideate" to trigger. |
| `improve-codebase-architecture` | `/improve-codebase-architecture` | `~/.agents/skills/improve-codebase-architecture/` | Yes | Find deepening opportunities in a codebase, informed by the domain language in CONTEXT.md and the decisions in docs/adr/. Use when the user wants to improve … |
| `incremental-implementation` | `/incremental-implementation` | `~/.agents/skills/incremental-implementation/` | Yes | Delivers changes incrementally. Use when implementing any feature or change that touches more than one file. Use when you're about to write a large amount of… |
| `interview-me` | `/interview-me` | `~/.agents/skills/interview-me/` | Yes | Extracts what the user actually wants instead of what they think they should want. Achieves this through one-question-at-a-time interview until ~95% confiden… |
| `performance-optimization` | `/performance-optimization` | `~/.agents/skills/performance-optimization/` | Yes | Optimizes application performance. Use when performance requirements exist, when you suspect performance regressions, or when Core Web Vitals or load times n… |
| `planning-and-task-breakdown` | `/planning-and-task-breakdown` | `~/.agents/skills/planning-and-task-breakdown/` | Yes | Breaks work into ordered tasks. Use when you have a spec or clear requirements and need to break work into implementable tasks. Use when a task feels too lar… |
| `prototype` | `/prototype` | `~/.agents/skills/prototype/` | Yes | Build a throwaway prototype to flesh out a design before committing to it. Routes between two branches — a runnable terminal app for state/business-logic que… |
| `push-changes` | `/push-changes` | `~/.agents/skills/push-changes/` | Yes | Commit and push code changes following Conventional Commits and branch-per-change workflow. Use when the user asks to push, commit, ship, send changes, creat… |
| `render-background-workers` | `/render-background-workers` | `~/.agents/skills/render-background-workers/` | Yes | >- |
| `render-blueprints` | `/render-blueprints` | `~/.agents/skills/render-blueprints/` | Yes | >- |
| `render-cli` | `/render-cli` | `~/.agents/skills/render-cli/` | Yes | >- |
| `render-cron-jobs` | `/render-cron-jobs` | `~/.agents/skills/render-cron-jobs/` | Yes | >- |
| `render-debug` | `/render-debug` | `~/.agents/skills/render-debug/` | Yes | Debug failed Render deployments by analyzing logs, metrics, and database state. Identifies errors (missing env vars, port binding, OOM, etc.) and suggests fi… |
| `render-deploy` | `/render-deploy` | `~/.agents/skills/render-deploy/` | Yes | Deploy applications to Render by analyzing codebases, generating render.yaml Blueprints, and providing Dashboard deeplinks. Use when the user wants to deploy… |
| `render-disks` | `/render-disks` | `~/.agents/skills/render-disks/` | Yes | >- |
| `render-docker` | `/render-docker` | `~/.agents/skills/render-docker/` | Yes | >- |
| `render-domains` | `/render-domains` | `~/.agents/skills/render-domains/` | Yes | >- |
| `render-env-vars` | `/render-env-vars` | `~/.agents/skills/render-env-vars/` | Yes | >- |
| `render-keyvalue` | `/render-keyvalue` | `~/.agents/skills/render-keyvalue/` | Yes | >- |
| `render-mcp` | `/render-mcp` | `~/.agents/skills/render-mcp/` | Yes | >- |
| `render-migrate-from-heroku` | `/render-migrate-from-heroku` | `~/.agents/skills/render-migrate-from-heroku/` | Yes | Migrate from Heroku to Render by reading local project files and generating equivalent Render services. Triggers: any mention of migrating from Heroku, movin… |
| `render-monitor` | `/render-monitor` | `~/.agents/skills/render-monitor/` | Yes | Monitor Render services in real-time. Check health, performance metrics, logs, and resource usage. Use when users want to check service status, view metrics,… |
| `render-networking` | `/render-networking` | `~/.agents/skills/render-networking/` | Yes | >- |
| `render-postgres` | `/render-postgres` | `~/.agents/skills/render-postgres/` | Yes | >- |
| `render-private-services` | `/render-private-services` | `~/.agents/skills/render-private-services/` | Yes | >- |
| `render-scaling` | `/render-scaling` | `~/.agents/skills/render-scaling/` | Yes | >- |
| `render-static-sites` | `/render-static-sites` | `~/.agents/skills/render-static-sites/` | Yes | >- |
| `render-web-services` | `/render-web-services` | `~/.agents/skills/render-web-services/` | Yes | >- |
| `render-workflows` | `/render-workflows` | `~/.agents/skills/render-workflows/` | Yes | Sets up, develops, tests, and deploys Render Workflows. Covers first-time scaffolding (via CLI or manual), SDK installation (Python or TypeScript), task patt… |
| `security-and-hardening` | `/security-and-hardening` | `~/.agents/skills/security-and-hardening/` | Yes | Hardens code against vulnerabilities. Use when handling user input, authentication, data storage, or external integrations. Use when building any feature tha… |
| `setup-matt-pocock-skills` | `/setup-matt-pocock-skills` | `~/.agents/skills/setup-matt-pocock-skills/` | Yes | Sets up an `## Agent skills` block in AGENTS.md/CLAUDE.md and `docs/agents/` so the engineering skills know this repo's issue tracker (GitHub or local markdo… |
| `shipping-and-launch` | `/shipping-and-launch` | `~/.agents/skills/shipping-and-launch/` | Yes | Prepares production launches. Use when preparing to deploy to production. Use when you need a pre-launch checklist, when setting up monitoring, when planning… |
| `source-driven-development` | `/source-driven-development` | `~/.agents/skills/source-driven-development/` | Yes | Grounds every implementation decision in official documentation. Use when you want authoritative, source-cited code free from outdated patterns. Use when bui… |
| `spec-driven-development` | `/spec-driven-development` | `~/.agents/skills/spec-driven-development/` | Yes | Creates specs before coding. Use when starting a new project, feature, or significant change and no specification exists yet. Use when requirements are uncle… |
| `supabase` | `/supabase` | `~/.agents/skills/supabase/` | Yes | Use when doing ANY task involving Supabase. Triggers: Supabase products (Database, Auth, Edge Functions, Realtime, Storage, Vectors, Cron, Queues); client li… |
| `supabase-postgres-best-practices` | `/supabase-postgres-best-practices` | `~/.agents/skills/supabase-postgres-best-practices/` | Yes | Postgres performance optimization and best practices from Supabase. Use this skill when writing, reviewing, or optimizing Postgres queries, schema designs, o… |
| `tavily-best-practices` | `/tavily-best-practices` | `~/.agents/skills/tavily-best-practices/` | No | Build production-ready Tavily integrations with best practices baked in. Reference documentation for developers using coding assistants (Claude Code, Cursor,… |
| `tavily-cli` | `/tavily-cli` | `~/.agents/skills/tavily-cli/` | No | \| |
| `tavily-crawl` | `/tavily-crawl` | `~/.agents/skills/tavily-crawl/` | No | \| |
| `tavily-extract` | `/tavily-extract` | `~/.agents/skills/tavily-extract/` | No | \| |
| `tavily-map` | `/tavily-map` | `~/.agents/skills/tavily-map/` | No | \| |
| `tavily-research` | `/tavily-research` | `~/.agents/skills/tavily-research/` | No | \| |
| `tavily-search` | `/tavily-search` | `~/.agents/skills/tavily-search/` | No | \| |
| `tdd` | `/tdd` | `~/.agents/skills/tdd/` | Yes | Test-driven development with red-green-refactor loop. Use when user wants to build features or fix bugs using TDD, mentions "red-green-refactor", wants integ… |
| `test-driven-development` | `/test-driven-development` | `~/.agents/skills/test-driven-development/` | Yes | Drives development with tests. Use when implementing any logic, fixing any bug, or changing any behavior. Use when you need to prove that code works, when a … |
| `to-issues` | `/to-issues` | `~/.agents/skills/to-issues/` | Yes | Break a plan, spec, or PRD into independently-grabbable issues on the project issue tracker using tracer-bullet vertical slices. Use when user wants to conve… |
| `to-prd` | `/to-prd` | `~/.agents/skills/to-prd/` | Yes | Turn the current conversation context into a PRD and publish it to the project issue tracker. Use when user wants to create a PRD from the current context. |
| `triage` | `/triage` | `~/.agents/skills/triage/` | Yes | Triage issues through a state machine driven by triage roles. Use when user wants to create an issue, triage issues, review incoming bugs or feature requests… |
| `using-agent-skills` | `/using-agent-skills` | `~/.agents/skills/using-agent-skills/` | Yes | Discovers and invokes agent skills. Use when starting a session or when you need to discover which skill applies to the current task. This is the meta-skill … |
| `write-a-skill` | `/write-a-skill` | `~/.agents/skills/write-a-skill/` | Yes | Create new agent skills with proper structure, progressive disclosure, and bundled resources. Use when user wants to create, write, or build a new skill. |
| `zoom-out` | `/zoom-out` | `~/.agents/skills/zoom-out/` | Yes | Tell the agent to zoom out and give broader context or a higher-level perspective. Use when you're unfamiliar with a section of code or need to understand ho… |

---

## Skills in `.agents` but not symlinked in `.claude/skills`

All skills under `~/.agents/skills` are symlinked in `~/.claude/skills`. `fastapi` was moved from `~/.cursor/skills` into agents; both Claude and Cursor now point at `~/.agents/skills/fastapi`.

---

## Related project docs

- [Issue tracker](./issue-tracker.md)
- [Triage labels](./triage-labels.md)
- [Domain context](./domain.md)
- [AGENTS.md](../../AGENTS.md)