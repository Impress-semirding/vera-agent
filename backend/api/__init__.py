"""Reasonix management API package.

This package owns the agent *management* REST API (CRUD over agents,
sessions, MCP servers, skills, permissions, push tasks, WeCom config,
session settings, config files and history records) backed by SQLite.

The sibling ``reasonix_server`` package is reserved for the *agent runtime*
(command/event SSE loop). Management data lives here so the two concerns
stay decoupled.
"""
