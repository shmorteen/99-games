# Decisions

This file records architecture decisions that should remain stable unless a new
decision supersedes them.

## ADR-001: Use One Shared Game Platform

Status: Accepted

The platform will use shared lobby, realtime, spectator, bot, streaming, and
rating infrastructure instead of creating one isolated Django app per game.

Reasoning:

- The platform must eventually support at least 99 games.
- Repeated lobby and WebSocket implementations would increase maintenance cost.
- Shared services make authorization, concurrency, observability, and streaming
  behavior easier to audit.

## ADR-002: PostgreSQL Is Authoritative

Status: Accepted

PostgreSQL is the durable source of truth for users, lobbies, memberships,
sessions, actions, results, and game definitions.

Redis may support coordination and cache data, but the application must be able
to rebuild durable truth from PostgreSQL.

## ADR-003: Server-Authoritative Game Actions

Status: Accepted

All game actions are validated and applied on the server. Clients can request an
action, but they cannot decide winners, scores, roles, turn order, balances,
timestamps, or final results.

## ADR-004: Separate Public, Private, and Spectator State

Status: Accepted

Every game engine must expose separate serializers for public state, private
player state, and spectator state. Hidden information must not be present in
spectator-safe or public payloads.
