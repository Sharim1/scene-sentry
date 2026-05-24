# Changelog

All notable changes to this project will be documented in this file.
See [Conventional Commits](https://www.conventionalcommits.org/) for commit guidelines.

## v2.2.2 (2026-05-24)

### Refactor

- **tasks**: remove manual task system and gossip feed polling

## v2.2.1 (2026-05-24)

### Fix

- **test**: mock Clerk settings in auth tests for CI compatibility
- **auth**: resolve Clerk session timeout and preserve login redirect destination

## v2.2.0 (2026-05-23)

### Feat

- **tasks**: replace APScheduler with Celery + Redis

## v2.1.8 (2026-05-21)

### Fix

- **ui**: add x-cloak CSS rule and remove redundant search page

## v2.1.7 (2026-05-21)

### Refactor

- **providers**: inline TMDbService HTTP logic into TMDbProvider

## v2.1.6 (2026-05-21)

### Fix

- **lint**: remove unused imports and fix import sorting

### Refactor

- **auth**: extract IdentitySync service from ClerkAuthMiddleware

## v2.1.5 (2026-05-21)

### Refactor

- **services**: strip pass-through methods from Gossip and Ranking services

## v2.1.4 (2026-05-21)

### Refactor

- **agents**: inject session factory to decouple from db_session

## v2.1.3 (2026-05-21)

### Fix

- **notifications**: prevent SSE reconnection storm and battery drain

## v2.1.2 (2026-05-21)

### Fix

- **ui**: eliminate full-page reloads on library mutations and tab switching

## v2.1.1 (2026-05-20)

### Fix

- **auth**: replace Clerk UserButton with custom profile dropdown

## v2.1.0 (2026-05-20)

### Feat

- **library**: add card management menu and remove-from-library UI

### Fix

- **ui**: move status dropdown out of button element on detail page

## v2.0.2 (2026-05-20)

### Refactor

- **library**: extract LibraryService for all Library Item mutations

## v2.0.1 (2026-05-20)

### Fix

- **security**: harden application against audit findings

## v2.0.0 (2026-05-19)

Initial tracked release.
