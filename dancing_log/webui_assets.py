"""Static HTML/JS asset for the Local Web UI."""

from __future__ import annotations

import json


CSRF_TOKEN_PLACEHOLDER = "__DANCING_LOG_CSRF_TOKEN__"
ROUTES_PLACEHOLDER = "__DANCING_LOG_ROUTES__"
WEBUI_ROUTE_BY_VIEW = {
    "home": "/home",
    "timeline": "/timeline",
    "catalog": "/catalog",
    "lists": "/lists",
    "insights": "/insights",
    "operations": "/data-operations",
    "settings": "/settings",
}
WEBUI_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>dancing-log</title>
<style>
:root {
  color-scheme: light;

  /* Fluent 2 semantic aliases. Components consume these rather than palette values. */
  --color-neutral-background-1: #ffffff;
  --color-neutral-background-1-hover: #f5f5f5;
  --color-neutral-background-1-pressed: #e0e0e0;
  --color-neutral-background-2: #fafafa;
  --color-neutral-background-3: #f5f5f5;
  --color-neutral-background-4: #f0f0f0;
  --color-neutral-foreground-1: #242424;
  --color-neutral-foreground-2: #424242;
  --color-neutral-foreground-3: #616161;
  --color-neutral-stroke-1: #d1d1d1;
  --color-neutral-stroke-1-hover: #b3b3b3;
  --color-neutral-stroke-2: #e0e0e0;
  --color-brand-background: #0f6cbd;
  --color-brand-background-hover: #115ea3;
  --color-brand-background-pressed: #0c3b5e;
  --color-brand-foreground-1: #0f6cbd;
  --color-brand-foreground-link: #0f548c;
  --color-neutral-foreground-on-brand: #ffffff;
  --color-focus-stroke-outer: #000000;
  --color-focus-stroke-inner: #ffffff;
  --color-status-success-foreground: #0e700e;
  --color-status-success-border: #9fd89f;
  --color-status-success-background: #f1faf1;
  --color-status-warning-foreground: #8a3707;
  --color-status-warning-border: #f2c661;
  --color-status-warning-background: #fff9f0;
  --color-status-danger-foreground: #b10e1c;
  --color-status-danger-border: #eeacb2;
  --color-status-danger-background: #fdf3f4;
  --color-status-informative-foreground: #0f548c;
  --color-status-informative-border: #a9d3f2;
  --color-status-informative-background: #f0f6fa;
  --color-status-accent-foreground: #5c2e91;
  --color-status-accent-border: #c6b1de;
  --color-status-accent-background: #f7f2fb;
  --shadow-2: 0 1px 2px rgba(0, 0, 0, 0.14), 0 0 2px rgba(0, 0, 0, 0.12);
  --shadow-4: 0 2px 4px rgba(0, 0, 0, 0.14), 0 0 2px rgba(0, 0, 0, 0.12);
  --border-radius-small: 4px;
  --border-radius-medium: 6px;
  --border-radius-large: 8px;

  /* Short aliases keep the existing renderer compact. */
  --bg: var(--color-neutral-background-2);
  --panel: var(--color-neutral-background-1);
  --panel-alt: var(--color-neutral-background-3);
  --line: var(--color-neutral-stroke-2);
  --line-strong: var(--color-neutral-stroke-1);
  --text: var(--color-neutral-foreground-1);
  --muted: var(--color-neutral-foreground-3);
  --blue: var(--color-brand-foreground-1);
  --green: var(--color-status-success-foreground);
  --orange: var(--color-status-warning-foreground);
  --red: var(--color-status-danger-foreground);
  --violet: var(--color-status-accent-foreground);
  --shadow: var(--shadow-2);
  --sidebar: var(--color-neutral-background-3);
  --sidebar-text: var(--color-neutral-foreground-1);
  --sidebar-muted: var(--color-neutral-foreground-3);
  --sidebar-hover: var(--color-neutral-background-1-hover);
  --sidebar-hover-line: var(--color-neutral-stroke-1-hover);
  --nav-active-bg: #e6f2fb;
  --nav-active-text: var(--color-neutral-foreground-1);
  --input-bg: var(--color-neutral-background-1);
  --input-readonly: var(--color-neutral-background-4);
  --primary-text: var(--color-neutral-foreground-on-brand);
  --code-bg: #242424;
  --code-text: #f5f5f5;
  --blue-line: var(--color-status-informative-border);
  --blue-bg: var(--color-status-informative-background);
  --green-line: var(--color-status-success-border);
  --green-bg: var(--color-status-success-background);
  --orange-line: var(--color-status-warning-border);
  --orange-bg: var(--color-status-warning-background);
  --red-line: var(--color-status-danger-border);
  --red-bg: var(--color-status-danger-background);
  --violet-line: var(--color-status-accent-border);
  --violet-bg: var(--color-status-accent-background);
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --color-neutral-background-1: #292929;
  --color-neutral-background-1-hover: #3d3d3d;
  --color-neutral-background-1-pressed: #525252;
  --color-neutral-background-2: #1f1f1f;
  --color-neutral-background-3: #141414;
  --color-neutral-background-4: #333333;
  --color-neutral-foreground-1: #ffffff;
  --color-neutral-foreground-2: #d6d6d6;
  --color-neutral-foreground-3: #adadad;
  --color-neutral-stroke-1: #666666;
  --color-neutral-stroke-1-hover: #8a8a8a;
  --color-neutral-stroke-2: #525252;
  --color-brand-background: #115ea3;
  --color-brand-background-hover: #0f6cbd;
  --color-brand-background-pressed: #2886de;
  --color-brand-foreground-1: #62abf5;
  --color-brand-foreground-link: #96c6fa;
  --color-neutral-foreground-on-brand: #ffffff;
  --color-focus-stroke-outer: #ffffff;
  --color-focus-stroke-inner: #000000;
  --color-status-success-foreground: #7fdb76;
  --color-status-success-border: #107c10;
  --color-status-success-background: #173b17;
  --color-status-warning-foreground: #fce100;
  --color-status-warning-border: #c19c00;
  --color-status-warning-background: #4a3f00;
  --color-status-danger-foreground: #ff99a4;
  --color-status-danger-border: #c50f1f;
  --color-status-danger-background: #420610;
  --color-status-informative-foreground: #96c6fa;
  --color-status-informative-border: #0f6cbd;
  --color-status-informative-background: #082338;
  --color-status-accent-foreground: #d7bff0;
  --color-status-accent-border: #8764b8;
  --color-status-accent-background: #2f1f45;
  --shadow-2: 0 1px 2px rgba(0, 0, 0, 0.48), 0 0 2px rgba(0, 0, 0, 0.36);
  --shadow-4: 0 2px 4px rgba(0, 0, 0, 0.48), 0 0 2px rgba(0, 0, 0, 0.36);
  --nav-active-bg: #0f548c;
  --code-bg: #0f0f0f;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --color-neutral-background-1: #292929;
    --color-neutral-background-1-hover: #3d3d3d;
    --color-neutral-background-1-pressed: #525252;
    --color-neutral-background-2: #1f1f1f;
    --color-neutral-background-3: #141414;
    --color-neutral-background-4: #333333;
    --color-neutral-foreground-1: #ffffff;
    --color-neutral-foreground-2: #d6d6d6;
    --color-neutral-foreground-3: #adadad;
    --color-neutral-stroke-1: #666666;
    --color-neutral-stroke-1-hover: #8a8a8a;
    --color-neutral-stroke-2: #525252;
    --color-brand-background: #115ea3;
    --color-brand-background-hover: #0f6cbd;
    --color-brand-background-pressed: #2886de;
    --color-brand-foreground-1: #62abf5;
    --color-brand-foreground-link: #96c6fa;
    --color-neutral-foreground-on-brand: #ffffff;
    --color-focus-stroke-outer: #ffffff;
    --color-focus-stroke-inner: #000000;
    --color-status-success-foreground: #7fdb76;
    --color-status-success-border: #107c10;
    --color-status-success-background: #173b17;
    --color-status-warning-foreground: #fce100;
    --color-status-warning-border: #c19c00;
    --color-status-warning-background: #4a3f00;
    --color-status-danger-foreground: #ff99a4;
    --color-status-danger-border: #c50f1f;
    --color-status-danger-background: #420610;
    --color-status-informative-foreground: #96c6fa;
    --color-status-informative-border: #0f6cbd;
    --color-status-informative-background: #082338;
    --color-status-accent-foreground: #d7bff0;
    --color-status-accent-border: #8764b8;
    --color-status-accent-background: #2f1f45;
    --shadow-2: 0 1px 2px rgba(0, 0, 0, 0.48), 0 0 2px rgba(0, 0, 0, 0.36);
    --shadow-4: 0 2px 4px rgba(0, 0, 0, 0.48), 0 0 2px rgba(0, 0, 0, 0.36);
    --nav-active-bg: #0f548c;
    --code-bg: #0f0f0f;
  }
}
* { box-sizing: border-box; }
html { overflow-y: auto; scrollbar-gutter: stable; }
html, body { margin: 0; min-height: 100%; background: var(--bg); color: var(--text); }
body {
  font-family: "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif;
  font-size: 14px;
  line-height: 20px;
  letter-spacing: 0;
}
button, input, select { font: inherit; letter-spacing: 0; }
button { cursor: pointer; }
.skip-link {
  position: fixed;
  z-index: 100;
  top: 8px;
  left: 8px;
  transform: translateY(-160%);
  border: 2px solid var(--color-focus-stroke-outer);
  border-radius: var(--border-radius-medium);
  background: var(--panel);
  color: var(--text);
  padding: 8px 12px;
}
.skip-link:focus { transform: translateY(0); }
.sr-only {
  position: absolute !important;
  width: 1px !important;
  height: 1px !important;
  padding: 0 !important;
  margin: -1px !important;
  overflow: hidden !important;
  clip: rect(0, 0, 0, 0) !important;
  white-space: nowrap !important;
  border: 0 !important;
}
:where(a, button, input, select, textarea, [tabindex]):focus-visible {
  outline: 2px solid var(--color-focus-stroke-outer);
  outline-offset: 2px;
  box-shadow: 0 0 0 1px var(--color-focus-stroke-inner);
}
.app {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
}
.sidebar {
  background: var(--sidebar);
  color: var(--sidebar-text);
  border-right: 1px solid var(--line);
  padding: 20px 12px 12px;
  display: grid;
  grid-template-rows: auto 1fr auto;
  gap: 20px;
}
.brand { display: grid; gap: 2px; padding: 0 8px; }
.brand strong { font-size: 20px; line-height: 28px; font-weight: 600; }
.brand span { color: var(--sidebar-muted); font-size: 12px; line-height: 16px; }
.nav { display: grid; align-content: start; gap: 4px; }
.nav a {
  position: relative;
  min-height: 40px;
  border: 1px solid transparent;
  border-radius: var(--border-radius-medium);
  background: transparent;
  color: var(--sidebar-text);
  text-align: left;
  padding: 0 12px 0 16px;
  display: flex;
  align-items: center;
  text-decoration: none;
}
.nav a:hover { border-color: var(--sidebar-hover-line); background: var(--sidebar-hover); }
.nav a:active { background: var(--color-neutral-background-1-pressed); }
.nav a.active { background: var(--nav-active-bg); color: var(--nav-active-text); font-weight: 600; }
.nav a.active::before {
  content: "";
  position: absolute;
  inset: 8px auto 8px 3px;
  width: 3px;
  border-radius: 2px;
  background: var(--color-brand-background);
}
.sidebar-foot {
  color: var(--sidebar-muted);
  font-size: 12px;
  line-height: 16px;
  padding: 0 8px;
  overflow-wrap: anywhere;
}
.main { min-width: 0; padding: 24px 28px 32px; display: grid; gap: 20px; align-content: start; }
.topbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  min-width: 0;
}
.title-block { min-width: 0; }
h1 { margin: 0; font-size: 24px; line-height: 32px; font-weight: 600; }
.subtitle { margin-top: 4px; color: var(--muted); overflow-wrap: anywhere; }
.top-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}
.toolbar { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.timeline-date-nav {
  display: inline-grid;
  grid-template-columns: repeat(2, 32px) 120px repeat(2, 32px);
  gap: 3px;
  align-items: center;
}
.timeline-step {
  min-height: 32px;
  border-radius: 6px;
  border: 1px solid var(--line-strong);
  background: var(--panel);
  color: var(--text);
  padding: 0;
}
.timeline-step:hover { border-color: var(--blue); }
.timeline-icon-button {
  flex: 0 0 34px;
  width: 34px;
  min-height: 34px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  line-height: 1;
}
.timeline-sort-part { color: var(--muted); opacity: 0.42; font-weight: 700; }
.timeline-sort-button[data-sort="asc"] .timeline-sort-asc,
.timeline-sort-button[data-sort="desc"] .timeline-sort-desc {
  color: var(--blue);
  opacity: 1;
}
.language-switch {
  display: inline-grid;
  grid-template-columns: repeat(2, minmax(44px, auto));
  border: 1px solid var(--line-strong);
  border-radius: var(--border-radius-medium);
  overflow: hidden;
  background: var(--panel);
}
.language-switch button {
  min-height: 34px;
  border: 0;
  border-right: 1px solid var(--line-strong);
  background: transparent;
  color: var(--muted);
  padding: 0 10px;
}
.language-switch button:last-child { border-right: 0; }
.language-switch button.active {
  background: var(--color-brand-background);
  color: var(--primary-text);
}
.language-switch button:hover { background: var(--color-neutral-background-1-hover); color: var(--text); }
.language-switch button.active:hover { background: var(--color-brand-background-hover); color: var(--primary-text); }
.theme-picker { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); }
.theme-picker select { width: auto; min-width: 96px; }
.button {
  min-height: 36px;
  border-radius: var(--border-radius-medium);
  border: 1px solid var(--line-strong);
  background: var(--panel);
  color: var(--text);
  padding: 0 12px;
}
.button:hover, .mini-button:hover { background: var(--color-neutral-background-1-hover); border-color: var(--color-neutral-stroke-1-hover); }
.button:active, .mini-button:active { background: var(--color-neutral-background-1-pressed); }
.button.primary, .mini-button.primary {
  background: var(--color-brand-background);
  border-color: var(--color-brand-background);
  color: var(--primary-text);
}
.button.primary:hover, .mini-button.primary:hover {
  background: var(--color-brand-background-hover);
  border-color: var(--color-brand-background-hover);
}
.button.primary:active, .mini-button.primary:active {
  background: var(--color-brand-background-pressed);
  border-color: var(--color-brand-background-pressed);
}
.button.danger { color: var(--red); border-color: var(--red-line); }
.button:disabled { opacity: 0.55; cursor: default; }
.button.timeline-icon-button:hover,
.button.timeline-icon-button:focus-visible {
  border-color: var(--blue);
  background: var(--panel);
  box-shadow: none;
}
.view { display: none; gap: 16px; align-content: start; }
.view.active { display: grid; }
.grid { display: grid; gap: 14px; }
.summary-grid { grid-template-columns: repeat(4, minmax(150px, 1fr)); }
.two-col { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--border-radius-large);
  box-shadow: var(--shadow);
  min-width: 0;
}
.panel-head {
  min-height: 48px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.panel-head h2 { margin: 0; font-size: 16px; line-height: 22px; font-weight: 600; }
.panel-body { padding: 16px; display: grid; gap: 12px; min-width: 0; overflow-x: auto; }
.table-scroll { min-width: 0; max-width: 100%; overflow-x: auto; }
.metric { display: grid; gap: 4px; padding: 14px; }
.metric span { color: var(--muted); font-size: 12px; }
.metric strong { font-size: 24px; line-height: 1.1; }
.status-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.status-item {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel-alt);
  padding: 10px;
  display: grid;
  gap: 8px;
}
.status-item span { color: var(--muted); font-size: 12px; }
.pill-row { display: flex; flex-wrap: wrap; gap: 6px; }
.pill {
  min-height: 24px;
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--panel-alt);
  padding: 0 9px;
  color: var(--muted);
  font-size: 12px;
}
.pill.green { color: var(--green); border-color: var(--green-line); background: var(--green-bg); }
.pill.blue { color: var(--blue); border-color: var(--blue-line); background: var(--blue-bg); }
.pill.orange { color: var(--orange); border-color: var(--orange-line); background: var(--orange-bg); }
.pill.red { color: var(--red); border-color: var(--red-line); background: var(--red-bg); }
.pill.violet { color: var(--violet); border-color: var(--violet-line); background: var(--violet-bg); }
.timeline-record { display: grid; gap: 5px; }
.timeline-record-title {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  min-width: 0;
}
.timeline-record-title span:first-child { overflow-wrap: anywhere; }
.timeline-system { border-radius: 6px; }
.timeline-source {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.25;
  overflow-wrap: anywhere;
}
.timeline-source strong { color: var(--text); font-weight: 600; }
.timeline-status { display: grid; gap: 5px; justify-items: start; }
.status-detail { color: var(--muted); font-size: 12px; }
.row-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.mini-button {
  min-height: 30px;
  border-radius: var(--border-radius-medium);
  border: 1px solid var(--line-strong);
  background: var(--panel);
  color: var(--text);
  padding: 0 9px;
  font-size: 12px;
}
.mini-button.danger { color: var(--red); border-color: var(--red-line); }
.mini-button:disabled { opacity: 0.48; cursor: default; }
.settings-grid { display: grid; gap: 14px; }
.field-row {
  display: grid;
  grid-template-columns: minmax(160px, 230px) minmax(0, 1fr);
  gap: 12px;
  align-items: start;
  padding: 12px 0;
  border-bottom: 1px solid var(--line);
}
.field-row:last-child { border-bottom: 0; }
.field-label { display: grid; gap: 4px; }
.field-label strong, .field-name { color: var(--text); font-weight: 600; }
.field-label code { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.field-summary { color: var(--muted); font-size: 12px; line-height: 1.35; }
.operation-summary { margin: 0; color: var(--muted); }
.field-control { display: grid; gap: 7px; min-width: 0; }
.input-line { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
.path-mode-line { grid-template-columns: auto minmax(0, 1fr) auto auto; align-items: center; }
input[type="text"], input[type="number"], input[type="date"], input[type="time"], select {
  width: 100%;
  min-height: 36px;
  border-radius: var(--border-radius-medium);
  border: 1px solid var(--line-strong);
  background: var(--input-bg);
  color: var(--text);
  padding: 0 10px;
}
input.timeline-date-input {
  min-height: 32px;
  padding: 0 28px 0 5px;
  text-align: center;
  font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.timeline-date-field {
  position: relative;
  min-width: 0;
}
.timeline-date-field .timeline-date-input { width: 100%; }
input.timeline-date-picker {
  position: absolute;
  inset: 0 0 0 auto;
  width: 28px;
  max-width: 28px;
  min-height: 32px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font-size: 12px;
  overflow: hidden;
  cursor: pointer;
}
input.timeline-date-picker:focus-visible {
  outline: 2px solid var(--color-focus-stroke-outer);
  outline-offset: 0;
}
input.timeline-date-picker::-webkit-datetime-edit,
input.timeline-date-picker::-webkit-datetime-edit-fields-wrapper,
input.timeline-date-picker::-webkit-datetime-edit-text,
input.timeline-date-picker::-webkit-datetime-edit-month-field,
input.timeline-date-picker::-webkit-datetime-edit-day-field,
input.timeline-date-picker::-webkit-datetime-edit-year-field {
  display: none;
}
input.timeline-date-picker::-webkit-calendar-picker-indicator {
  cursor: pointer;
  margin: 0;
  padding: 0;
  opacity: 0.7;
  display: block;
}
input.timeline-date-picker:hover::-webkit-calendar-picker-indicator {
  opacity: 1;
}
input[type="checkbox"] { accent-color: var(--blue); }
input[readonly], input:disabled { background: var(--input-readonly); color: var(--muted); }
.toggle-line {
  min-height: 36px;
  display: inline-flex;
  align-items: center;
  gap: 9px;
}
.toggle-line input { width: 18px; height: 18px; }
.resolved { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.resolved.ok { color: var(--green); }
.resolved.missing { color: var(--orange); }
.message {
  display: none;
  border-radius: var(--border-radius-large);
  border: 1px solid var(--line);
  background: var(--panel-alt);
  padding: 10px 12px;
  color: var(--muted);
}
.message.show { display: block; }
.message.error { color: var(--red); border-color: var(--red-line); background: var(--red-bg); }
.message.success { color: var(--green); border-color: var(--green-line); background: var(--green-bg); }
.readonly-json {
  margin: 0;
  overflow: auto;
  background: var(--code-bg);
  color: var(--code-text);
  border-radius: var(--border-radius-medium);
  padding: 12px;
  max-height: 240px;
}
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
th, td {
  text-align: left;
  padding: 10px;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
  overflow-wrap: anywhere;
}
th { color: var(--muted); font-size: 12px; font-weight: 650; background: var(--panel-alt); }
tr:last-child td { border-bottom: 0; }
.empty { color: var(--muted); padding: 14px; }
.list-stack { display: grid; gap: 8px; }
.list-item {
  border: 1px solid var(--line);
  border-radius: var(--border-radius-large);
  padding: 10px;
  display: grid;
  gap: 5px;
  background: var(--panel-alt);
}
.list-item strong { overflow-wrap: anywhere; }
.list-item code { color: var(--muted); overflow-wrap: anywhere; }
@media (max-width: 980px) {
  .app { grid-template-columns: 1fr; }
  .sidebar { position: sticky; top: 0; z-index: 2; grid-template-rows: auto auto; }
  .nav { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sidebar-foot { display: none; }
  .summary-grid, .two-col, .status-grid { grid-template-columns: 1fr; }
}
@media (max-width: 680px) {
  .main { padding: 14px; }
  .topbar { align-items: stretch; flex-direction: column; }
  .top-actions { justify-content: flex-start; }
  .toolbar { justify-content: flex-start; }
  .timeline-date-nav { grid-template-columns: repeat(2, 32px) 120px repeat(2, 32px); }
  .field-row { grid-template-columns: 1fr; }
  .input-line { grid-template-columns: 1fr; }
  .nav { grid-template-columns: 1fr; }
  .timeline-table { min-width: 680px; }
}
@media (forced-colors: active) {
  .panel, .status-item, .list-item, .pill, .message { box-shadow: none; }
  .nav a.active { border-color: Highlight; color: CanvasText; }
  .nav a.active::before { background: Highlight; }
  .button.primary, .mini-button.primary, .language-switch button.active {
    border-color: ButtonText;
    background: ButtonFace;
    color: ButtonText;
  }
  :where(a, button, input, select, textarea, [tabindex]):focus-visible {
    outline-color: Highlight;
    box-shadow: none;
  }
}
</style>
</head>
<body>
<a class="skip-link" href="#main-content">Skip to main content</a>
<div class="app">
  <aside class="sidebar" aria-label="Application navigation">
    <div class="brand"><strong>dancing-log</strong><span id="brand-subtitle">Local Web UI</span></div>
    <nav class="nav" id="nav" aria-label="Primary"></nav>
    <div class="sidebar-foot" id="sidebar-path"></div>
  </aside>
  <main class="main" id="main-content" tabindex="-1">
    <div class="topbar">
      <div class="title-block">
        <h1 id="view-title" tabindex="-1">Home</h1>
        <div class="subtitle" id="view-subtitle"></div>
      </div>
      <div class="top-actions">
        <label class="theme-picker" for="theme-select"><span id="theme-label">Theme</span><select id="theme-select"></select></label>
        <div class="language-switch" id="language-switch" role="group" aria-label="Language"></div>
        <div class="toolbar" id="view-toolbar"></div>
      </div>
    </div>
    <section class="view active" id="view-home" aria-labelledby="view-title"></section>
    <section class="view" id="view-timeline" aria-labelledby="view-title"></section>
    <section class="view" id="view-catalog" aria-labelledby="view-title"></section>
    <section class="view" id="view-lists" aria-labelledby="view-title"></section>
    <section class="view" id="view-insights" aria-labelledby="view-title"></section>
    <section class="view" id="view-operations" aria-labelledby="view-title"></section>
    <section class="view" id="view-settings" aria-labelledby="view-title"></section>
  </main>
</div>
<script>
const LANGUAGE_KEY = "dancing-log.language";
const THEME_KEY = "dancing-log.theme";
const CSRF_TOKEN = "__DANCING_LOG_CSRF_TOKEN__";
const NAV = ["home", "timeline", "catalog", "lists", "insights", "operations", "settings"];
const LIVE_STATE_POLL_INTERVAL_MS = 250;
const LIVE_STATE_POLL_LIMIT = 20;
const ROUTES = __DANCING_LOG_ROUTES__;
const TEXT = {
  en: {
    brandSubtitle: "Local Web UI",
    languageLabel: "Language",
    themeLabel: "Theme",
    themeSystem: "System",
    themeLight: "Light",
    themeDark: "Dark",
    skipToMain: "Skip to main content",
    applicationNavigation: "Application navigation",
    primaryNavigation: "Primary",
    nav_home: "Home",
    nav_timeline: "Timeline",
    nav_catalog: "Catalog",
    nav_lists: "Lists",
    nav_insights: "Insights",
    nav_operations: "Data Operations",
    nav_settings: "Settings",
    title_home: "Home",
    subtitle_home: "Runtime status and recent activity",
    title_timeline: "Timeline",
    subtitle_timeline: "Chronological playback records",
    title_catalog: "Catalog",
    subtitle_catalog: "Dance tracks and local preferences",
    title_lists: "Lists",
    subtitle_lists: "Planned dance lists",
    title_insights: "Insights",
    subtitle_insights: "Confirmed-history summaries",
    title_operations: "Data Operations",
    subtitle_operations: "Controlled bulk workflows",
    title_settings: "Settings",
    subtitle_settings: "Saved local configuration",
    reset: "Reset",
    resetTitle: "Reload saved configuration",
    save: "Save",
    saveTitle: "Save configuration",
    browse: "Browse",
    browseTitle: "Open native {kind} picker",
    enabled: "Enabled",
    disabled: "Disabled",
    loadingConfig: "Loading configuration...",
    saved: "Saved",
    unsaved: "Unsaved",
    saveFailed: "Save failed",
    savedNull: "Saved as null",
    automatic: "Automatic",
    customPath: "Custom",
    useAsManual: "Use as manual",
    exists: "exists",
    missing: "missing",
    inaccessible: "inaccessible",
    detectedSources: "Automatic source path previews",
    defaultVrcxDb: "Standard VRCX database",
    defaultVrcLogDir: "Default VRChat log directory",
    unsupportedKeys: "Unsupported configuration keys",
    preserved: "Preserved",
    loading: "Loading...",
    danceTracks: "Dance tracks",
    playbackRecords: "Playback records",
    acceptedRecords: "Accepted",
    attentionRecords: "Needs attention",
    runtimeState: "Runtime state",
    dbFound: "DB found",
    noDb: "No DB",
    noLiveRow: "No live playback row",
    recentAccepted: "Recent accepted records",
    local: "local",
    noRecords: "No records",
    time: "Time",
    track: "Track",
    source: "Source",
    accepted: "Accepted",
    live: "Live-derived",
    load: "Load",
    timelineDate: "Timeline date",
    openDatePicker: "Open date picker",
    previousMonth: "Previous month",
    previousDay: "Previous day",
    nextDay: "Next day",
    nextMonth: "Next month",
    timelineSortChronological: "Chronological",
    timelineSortReverse: "Reverse",
    reverseTimelineOrder: "Reverse timeline order",
    copyDailyDancesTitle: "Copy valid events",
    copiedDailyDances: "Copied valid events",
    noAcceptedTimelineRecords: "No valid dance events for this day",
    timelineLoadFailed: "Timeline load failed",
    copyDailyDancesFailed: "Copy failed",
    sourceRandom: "Random",
    sourceOther: "Other",
    sourceSelf: "Self",
    sourceRecommend: "Recommended",
    sourceQueuedSelf: "Reserved",
    sourceUnknown: "Unknown",
    noTimelineRecords: "No timeline records",
    record: "Record",
    reviewStatus: "Status",
    actions: "Actions",
    accept: "Accept",
    exclude: "Exclude",
    restoreDefault: "Restore default",
    manual: "Manual",
    defaultResult: "Default",
    reviewUpdateFailed: "Review update failed",
    status_accepted: "accepted",
    status_excluded: "excluded",
    status_needs_attention: "needs attention",
    status_pending: "pending",
    searchCatalog: "Search catalog",
    search: "Search",
    noTracks: "No tracks",
    title: "Title",
    artist: "Artist",
    preferences: "Preferences",
    favorite: "favorite",
    wantToLearn: "want to learn",
    queuedSelfManifests: "Queued-self manifests",
    found: "found",
    noManifests: "No manifests",
    sourceDistribution: "Source distribution",
    topTracks: "Top tracks",
    recommendations: "Recommendations",
    noData: "No data",
    name: "Name",
    count: "Count",
    liveStatus: "Live status",
    watcher: "Watcher",
    overlay: "Overlay",
    running: "Running",
    stopping: "Stopping",
    stopped: "Stopped",
    refresh: "Refresh",
    startWatcher: "Start watcher",
    stopWatcher: "Stop watcher",
    startOverlay: "Start overlay",
    stopOverlay: "Stop overlay",
    databaseState: "Database state",
    currentLiveRow: "Current live row",
    lastRuntimeError: "Last runtime error",
    lastWatcherStats: "Last watcher stats",
    noWatcherStats: "No watcher stats yet",
    liveControlFailed: "Live control failed",
    run: "Run",
    runningOperation: "Running...",
    operationComplete: "Complete",
    operationFailed: "Operation failed"
  },
  zh: {
    brandSubtitle: "本地 Web UI",
    languageLabel: "语言",
    themeLabel: "主题",
    themeSystem: "跟随系统",
    themeLight: "浅色",
    themeDark: "深色",
    skipToMain: "跳到主要内容",
    applicationNavigation: "应用导航",
    primaryNavigation: "主导航",
    nav_home: "首页",
    nav_timeline: "时间线",
    nav_catalog: "目录",
    nav_lists: "清单",
    nav_insights: "洞察",
    nav_operations: "数据操作",
    nav_settings: "设置",
    title_home: "首页",
    subtitle_home: "运行状态和最近活动",
    title_timeline: "时间线",
    subtitle_timeline: "按时间顺序查看播放记录",
    title_catalog: "目录",
    subtitle_catalog: "舞蹈条目和本地偏好",
    title_lists: "清单",
    subtitle_lists: "计划中的舞蹈清单",
    title_insights: "洞察",
    subtitle_insights: "基于已接受历史的汇总",
    title_operations: "数据操作",
    subtitle_operations: "受控的批量工作流",
    title_settings: "设置",
    subtitle_settings: "已保存的本地配置",
    reset: "重置",
    resetTitle: "重新载入已保存配置",
    save: "保存",
    saveTitle: "保存配置",
    browse: "浏览",
    browseTitle: "打开原生{kind}选择器",
    enabled: "已启用",
    disabled: "已禁用",
    loadingConfig: "正在加载配置...",
    saved: "已保存",
    unsaved: "未保存",
    saveFailed: "保存失败",
    savedNull: "保存为空值",
    automatic: "自动",
    customPath: "自定义",
    useAsManual: "设为手动路径",
    exists: "存在",
    missing: "缺失",
    inaccessible: "不可访问",
    detectedSources: "自动来源路径预览",
    defaultVrcxDb: "标准 VRCX 数据库",
    defaultVrcLogDir: "默认 VRChat 日志目录",
    unsupportedKeys: "不支持的配置键",
    preserved: "已保留",
    loading: "正在加载...",
    danceTracks: "舞蹈条目",
    playbackRecords: "播放记录",
    acceptedRecords: "已接受",
    attentionRecords: "需注意",
    runtimeState: "运行状态",
    dbFound: "数据库已找到",
    noDb: "无数据库",
    noLiveRow: "没有实时播放记录",
    recentAccepted: "最近已接受记录",
    local: "本地",
    noRecords: "没有记录",
    time: "时间",
    track: "条目",
    source: "来源",
    accepted: "已接受",
    live: "实时来源",
    load: "加载",
    timelineDate: "时间线日期",
    openDatePicker: "打开日期选择器",
    previousMonth: "上个月",
    previousDay: "前一天",
    nextDay: "后一天",
    nextMonth: "下个月",
    timelineSortChronological: "时间顺序",
    timelineSortReverse: "倒序",
    reverseTimelineOrder: "倒序显示时间线",
    copyDailyDancesTitle: "复制有效事件",
    copiedDailyDances: "已复制有效事件",
    noAcceptedTimelineRecords: "这一天没有有效跳舞事件",
    timelineLoadFailed: "时间线加载失败",
    copyDailyDancesFailed: "复制失败",
    sourceRandom: "随机",
    sourceOther: "他人",
    sourceSelf: "自己",
    sourceRecommend: "推荐",
    sourceQueuedSelf: "预定",
    sourceUnknown: "未知",
    noTimelineRecords: "没有时间线记录",
    record: "记录",
    reviewStatus: "状态",
    actions: "操作",
    accept: "接受",
    exclude: "排除",
    restoreDefault: "恢复默认",
    manual: "手动",
    defaultResult: "默认",
    reviewUpdateFailed: "更新审阅失败",
    status_accepted: "已接受",
    status_excluded: "已排除",
    status_needs_attention: "需注意",
    status_pending: "待定",
    searchCatalog: "搜索目录",
    search: "搜索",
    noTracks: "没有条目",
    title: "标题",
    artist: "艺人",
    preferences: "偏好",
    favorite: "收藏",
    wantToLearn: "想学",
    queuedSelfManifests: "自选队列清单",
    found: "已找到",
    noManifests: "没有清单",
    sourceDistribution: "来源分布",
    topTracks: "常跳条目",
    recommendations: "推荐",
    noData: "没有数据",
    name: "名称",
    count: "数量",
    liveStatus: "\u5b9e\u65f6\u72b6\u6001",
    watcher: "Watcher",
    overlay: "Overlay",
    running: "\u8fd0\u884c\u4e2d",
    stopping: "\u6b63\u5728\u505c\u6b62",
    stopped: "\u5df2\u505c\u6b62",
    refresh: "\u5237\u65b0",
    startWatcher: "\u542f\u52a8 watcher",
    stopWatcher: "\u505c\u6b62 watcher",
    startOverlay: "\u542f\u52a8 overlay",
    stopOverlay: "\u505c\u6b62 overlay",
    databaseState: "\u6570\u636e\u5e93\u72b6\u6001",
    currentLiveRow: "\u5f53\u524d\u5b9e\u65f6\u64ad\u653e\u8bb0\u5f55",
    lastRuntimeError: "\u6700\u8fd1\u8fd0\u884c\u9519\u8bef",
    lastWatcherStats: "\u6700\u8fd1 watcher \u7edf\u8ba1",
    noWatcherStats: "\u5c1a\u65e0 watcher \u7edf\u8ba1",
    liveControlFailed: "\u5b9e\u65f6\u63a7\u5236\u5931\u8d25",
    run: "执行",
    runningOperation: "执行中...",
    operationComplete: "已完成",
    operationFailed: "操作失败"
  }
};
const FIELD_TEXT = {
  config_version: { zh: { label: "配置版本", group: "系统", summary: "本地配置结构版本。" } },
  app_db: { zh: { label: "应用数据库", group: "应用内部路径", summary: "SQLite 运行状态。" } },
  queued_self_dir: { zh: { label: "自选队列目录", group: "应用内部路径", summary: "计划自选舞蹈的 Markdown 清单。" } },
  capture_dir: { zh: { label: "捕获目录", group: "应用内部路径", summary: "实时 watcher 捕获输出。" } },
  run_log_dir: { zh: { label: "运行日志目录", group: "应用内部路径", summary: "常规应用运行日志。" } },
  source_vrc_log_dir: { zh: { label: "VRChat 源日志归档", group: "应用内部路径", summary: "逐字节归档的源 output_log 文件。" } },
  recording_frames_dir: { zh: { label: "录像帧目录", group: "应用内部路径", summary: "用于分析的顶部裁剪帧样本。" } },
  self_user_id: { zh: { label: "本机 VRChat 用户 ID", group: "外部数据源", summary: "用于判断 VRCX 历史点歌人是否为自己。" } },
  vrcx_db_path: { zh: { label: "VRCX 数据库", group: "外部数据源", summary: "VRCX 播放历史 SQLite 文件。" } },
  vrc_log_dir: { zh: { label: "VRChat 日志目录", group: "外部数据源", summary: "包含 VRChat output_log 文件的目录。" } },
  wanna_cache_dir: { zh: { label: "WannaDance 缓存", group: "外部数据源", summary: "用于离线目录同步的本地 WannaDance 缓存。" } },
  recordings_dir: { zh: { label: "录像目录", group: "外部数据源", summary: "sample-frame 工具使用的录像文件。" } },
  dance_day_boundary_time: { zh: { label: "跳舞日分界", group: "运行默认值", summary: "本地时间到达该时刻时开始新的跳舞日。" } },
  auto_start_watcher: { zh: { label: "自动启动 watcher", group: "运行默认值", summary: "应用工作流启动实时捕获时使用的默认偏好。" } },
  auto_start_overlay: { zh: { label: "自动启动 overlay", group: "运行默认值", summary: "启用后会同步启用 watcher 自动启动。" } },
  overlay_port: { zh: { label: "独立 Overlay 端口", group: "高级设置", summary: "仅在 watcher 不通过 Web UI 提供 overlay 时使用的本机端口。" } }
};
const AUTOMATIC_SOURCE_PATH_KEYS = new Set(["vrcx_db_path", "vrc_log_dir"]);
const DANCE_SYSTEM_LABELS = {
  wannadance: "WannaDance",
  pypydance: "PyPyDance",
  pypy: "PyPyDance",
  dududance: "Dudu",
  dudu: "Dudu",
  vrdancing: "VRDancing"
};
const state = {
  active: viewFromPath(location.pathname),
  lang: initialLanguage(),
  theme: initialTheme(),
  configSnapshot: null,
  operationsSnapshot: null,
  draft: {},
  operationDrafts: {},
  operationResults: {},
  operationErrors: {},
  runningOperation: null,
  fieldErrors: {},
  pathPreviews: {},
  previewTimers: {},
  timelineDate: "",
  timelineSort: "asc"
};

const brandSubtitleNode = document.getElementById("brand-subtitle");
const navNode = document.getElementById("nav");
const languageNode = document.getElementById("language-switch");
const themeLabelNode = document.getElementById("theme-label");
const themeSelectNode = document.getElementById("theme-select");
const toolbarNode = document.getElementById("view-toolbar");
const titleNode = document.getElementById("view-title");
const subtitleNode = document.getElementById("view-subtitle");
const sidebarPathNode = document.getElementById("sidebar-path");
const skipLinkNode = document.querySelector(".skip-link");
const sidebarNode = document.querySelector(".sidebar");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[char]));
}

function initialLanguage() {
  const saved = localStorage.getItem(LANGUAGE_KEY);
  if (saved === "en" || saved === "zh") return saved;
  return navigator.language && navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
}

function ui(key) {
  return TEXT[state.lang]?.[key] ?? TEXT.en[key] ?? key;
}

function navLabel(key) {
  return ui(`nav_${key}`);
}

function initialTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  return ["system", "light", "dark"].includes(saved) ? saved : "system";
}

function viewFromPath(path) {
  return Object.entries(ROUTES).find(([, route]) => route === path)?.[0] || "home";
}

function applyLocationState(view) {
  if (view !== "timeline") return;
  const params = new URLSearchParams(location.search);
  const date = normalizeTimelineDateInput(params.get("date") || "");
  state.timelineDate = isValidLocalDate(date) ? date : "";
  state.timelineSort = params.get("sort") === "desc" ? "desc" : "asc";
}

function syncTimelineUrl() {
  if (state.active !== "timeline") return;
  const params = new URLSearchParams();
  if (isValidLocalDate(state.timelineDate)) params.set("date", state.timelineDate);
  if (state.timelineSort === "desc") params.set("sort", "desc");
  const query = params.toString();
  const target = `${ROUTES.timeline}${query ? `?${query}` : ""}`;
  if (`${location.pathname}${location.search}` !== target) {
    history.replaceState({}, "", target);
  }
}

function viewTitle(key) {
  return [ui(`title_${key}`), ui(`subtitle_${key}`)];
}

function fieldText(field, part) {
  return FIELD_TEXT[field.key]?.[state.lang]?.[part] || field[part] || "";
}

function operationText(operation, part) {
  return operation.text?.[state.lang]?.[part] || operation[part] || "";
}

function pickerKind(kind) {
  if (state.lang !== "zh") return kind;
  return kind === "directory" ? "文件夹" : "文件";
}

function pathStatusLabel(resolved) {
  if (resolved.error) return ui("inaccessible");
  return resolved.exists ? ui("exists") : ui("missing");
}

function reviewStatusLabel(value) {
  const key = `status_${String(value || "").replaceAll(" ", "_")}`;
  return ui(key);
}

function reviewStatusClass(value) {
  if (value === "accepted") return "green";
  if (value === "excluded") return "red";
  if (value === "pending") return "blue";
  return "orange";
}

function formatLocalDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function localDateParts(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(year, month - 1, day);
  if (
    parsed.getFullYear() !== year ||
    parsed.getMonth() !== month - 1 ||
    parsed.getDate() !== day
  ) {
    return null;
  }
  return { year, month, day, date: parsed };
}

function isValidLocalDate(value) {
  return localDateParts(value) !== null;
}

function parseLocalDate(value) {
  const parts = localDateParts(value);
  return parts ? parts.date : new Date();
}

function normalizeTimelineDateInput(value) {
  const text = String(value || "");
  const digits = text.replace(/\D/g, "").slice(0, 8);
  if (digits.length === 4 && /-$/.test(text)) return `${digits}-`;
  if (digits.length === 6 && /-$/.test(text)) return `${digits.slice(0, 4)}-${digits.slice(4)}-`;
  if (digits.length <= 4) return digits;
  if (digits.length <= 6) return `${digits.slice(0, 4)}-${digits.slice(4)}`;
  return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6)}`;
}

function addLocalDays(value, days) {
  const date = parseLocalDate(value);
  date.setDate(date.getDate() + days);
  return formatLocalDate(date);
}

function addLocalMonths(value, months) {
  const source = parseLocalDate(value);
  const day = source.getDate();
  const target = new Date(source.getFullYear(), source.getMonth() + months, 1);
  const lastDay = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
  target.setDate(Math.min(day, lastDay));
  return formatLocalDate(target);
}

function translatedError(message) {
  if (state.lang !== "zh") return message;
  if (message === "path is required") return "路径不能为空";
  if (message === "value must be true or false") return "值必须为 true 或 false";
  if (message === "value must be an integer") return "值必须是整数";
  const range = String(message || "").match(/^value must be between (\d+) and (\d+)$/);
  if (range) return `值必须在 ${range[1]} 到 ${range[2]} 之间`;
  return message;
}

function api(path, options = {}) {
  const init = { ...options };
  init.headers = { ...(options.headers || {}) };
  if (init.body && typeof init.body !== "string") {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(init.body);
  }
  if ((init.method || "GET").toUpperCase() !== "GET") {
    init.headers["X-Dancing-Log-CSRF"] = CSRF_TOKEN;
  }
  return fetch(path, init).then(async response => {
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.error || "request failed");
      error.data = data;
      throw error;
    }
    return data;
  });
}

function setView(next, { navigate = false, syncLocation = false, focusHeading = false } = {}) {
  if (!NAV.includes(next)) next = "home";
  if (navigate) {
    history.pushState({}, "", ROUTES[next]);
    syncLocation = true;
  }
  if (syncLocation) applyLocationState(next);
  state.active = next;
  for (const key of NAV) {
    document.getElementById(`view-${key}`).classList.toggle("active", key === next);
  }
  for (const link of navNode.querySelectorAll("a[data-view]")) {
    const active = link.dataset.view === next;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  const [title, subtitle] = viewTitle(next);
  titleNode.textContent = title;
  subtitleNode.textContent = subtitle;
  document.title = `${title} — dancing-log`;
  toolbarNode.innerHTML = "";
  renderActive();
  if (focusHeading) titleNode.focus({ preventScroll: true });
}

function renderNav() {
  navNode.innerHTML = NAV.map(key => `
    <a href="${ROUTES[key]}" data-view="${key}" class="${key === state.active ? "active" : ""}" ${key === state.active ? 'aria-current="page"' : ""}>${esc(navLabel(key))}</a>
  `).join("");
  for (const link of navNode.querySelectorAll("a[data-view]")) {
    link.onclick = event => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      setView(link.dataset.view, { navigate: true, focusHeading: true });
    };
  }
}

function renderLanguageSwitch() {
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  brandSubtitleNode.textContent = ui("brandSubtitle");
  skipLinkNode.textContent = ui("skipToMain");
  sidebarNode.setAttribute("aria-label", ui("applicationNavigation"));
  navNode.setAttribute("aria-label", ui("primaryNavigation"));
  languageNode.setAttribute("aria-label", ui("languageLabel"));
  languageNode.innerHTML = `
    <button type="button" data-lang="en" class="${state.lang === "en" ? "active" : ""}" aria-pressed="${state.lang === "en"}">EN</button>
    <button type="button" data-lang="zh" class="${state.lang === "zh" ? "active" : ""}" aria-pressed="${state.lang === "zh"}">中文</button>
  `;
  for (const button of languageNode.querySelectorAll("button[data-lang]")) {
    button.onclick = () => setLanguage(button.dataset.lang);
  }
}

function setLanguage(lang) {
  if (lang !== "en" && lang !== "zh") return;
  state.lang = lang;
  localStorage.setItem(LANGUAGE_KEY, lang);
  renderLanguageSwitch();
  renderThemePicker();
  renderNav();
  const [title, subtitle] = viewTitle(state.active);
  titleNode.textContent = title;
  subtitleNode.textContent = subtitle;
  document.title = `${title} — dancing-log`;
  renderActive();
  languageNode.querySelector(`[data-lang="${lang}"]`)?.focus();
}

function showMessage(id, message, kind = "") {
  const node = document.getElementById(id);
  if (!node) return;
  node.textContent = message || "";
  node.className = `message ${message ? "show" : ""} ${kind}`;
  node.setAttribute("role", kind === "error" ? "alert" : "status");
  node.setAttribute("aria-live", kind === "error" ? "assertive" : "polite");
  node.setAttribute("aria-atomic", "true");
}

function renderActive() {
  if (state.active === "settings") return renderSettings();
  if (state.active === "home") return renderHome();
  if (state.active === "timeline") return renderTimeline();
  if (state.active === "catalog") return renderCatalog();
  if (state.active === "lists") return renderLists();
  if (state.active === "insights") return renderInsights();
  if (state.active === "operations") return renderOperations();
}

async function loadConfig() {
  const snapshot = await api("/api/config");
  state.configSnapshot = snapshot;
  state.draft = { ...snapshot.config };
  state.fieldErrors = {};
  updatePathPreviewsFromSnapshot(snapshot);
  sidebarPathNode.textContent = snapshot.config_path;
}

function updatePathPreviewsFromSnapshot(snapshot) {
  state.pathPreviews = {};
  for (const field of snapshot.fields || []) {
    if (field.path) state.pathPreviews[field.key] = field.path;
  }
}

function groupedFields(fields) {
  const groups = [];
  for (const field of fields) {
    const groupName = fieldText(field, "group");
    let group = groups.find(item => item.name === groupName);
    if (!group) {
      group = { name: groupName, fields: [] };
      groups.push(group);
    }
    group.fields.push(field);
  }
  return groups;
}

function safeDomId(value) {
  return String(value).replace(/[^a-zA-Z0-9_-]/g, "_");
}

function fieldControlId(key) {
  return `field-control-${safeDomId(key)}`;
}

function fieldDescriptionId(key) {
  return `field-description-${safeDomId(key)}`;
}

function fieldErrorId(key) {
  return `field-error-${safeDomId(key)}`;
}

function renderSettings() {
  toolbarNode.innerHTML = `
    <button class="button" type="button" id="settings-reset" title="${esc(ui("resetTitle"))}">${esc(ui("reset"))}</button>
    <button class="button primary" type="button" id="settings-save" title="${esc(ui("saveTitle"))}">${esc(ui("save"))}</button>
  `;
  const node = document.getElementById("view-settings");
  if (!state.configSnapshot) {
    node.innerHTML = `<div class="panel"><div class="empty" role="status">${esc(ui("loadingConfig"))}</div></div>`;
    loadConfig().then(renderSettings).catch(error => {
      node.innerHTML = `<div class="message show error" role="alert">${esc(error.message)}</div>`;
    });
    return;
  }
  const snapshot = state.configSnapshot;
  const groups = groupedFields(snapshot.fields);
  node.innerHTML = `
    <div class="message" id="settings-message" role="status" aria-live="polite" aria-atomic="true"></div>
    <div class="settings-grid">
      ${groups.map(group => renderSettingsGroup(group)).join("")}
      ${renderDetectedSources(snapshot.detected_sources || [])}
      ${renderUnsupported(snapshot.unsupported || {})}
    </div>
  `;
  document.getElementById("settings-save").onclick = saveSettings;
  document.getElementById("settings-reset").onclick = async () => {
    const resetButton = document.getElementById("settings-reset");
    const saveButton = document.getElementById("settings-save");
    resetButton.disabled = true;
    saveButton.disabled = true;
    try {
      await loadConfig();
      renderSettings();
      document.getElementById("settings-reset")?.focus();
    } catch (error) {
      resetButton.disabled = false;
      saveButton.disabled = false;
      showMessage("settings-message", error.message, "error");
    }
  };
  bindFieldControls();
}

function renderSettingsGroup(group) {
  return `
    <section class="panel">
      <div class="panel-head"><h2>${esc(group.name)}</h2></div>
      <div class="panel-body">
        ${group.fields.map(renderField).join("")}
      </div>
    </section>
  `;
}

function renderField(field) {
  const key = field.key;
  const value = state.draft[key];
  const error = state.fieldErrors[key];
  const controlId = fieldControlId(key);
  const describedBy = [fieldDescriptionId(key)];
  if (field.path) describedBy.push(pathPreviewId(key));
  if (error) describedBy.push(fieldErrorId(key));
  return `
    <div class="field-row" data-field="${esc(key)}">
      <div class="field-label">
        <label class="field-name" for="${controlId}">${esc(fieldText(field, "label"))}</label>
        <code>${esc(key)}</code>
        <span class="field-summary" id="${fieldDescriptionId(key)}">${esc(fieldText(field, "summary"))}</span>
      </div>
      <div class="field-control">
        ${renderFieldControl(field, value, controlId, describedBy.join(" "), Boolean(error))}
        ${field.path ? renderPathPreview(field) : ""}
        ${error ? `<span class="resolved missing" id="${fieldErrorId(key)}" role="alert">${esc(translatedError(error))}</span>` : ""}
      </div>
    </div>
  `;
}

function renderFieldControl(field, value, controlId, describedBy, invalid) {
  const attrs = `id="${controlId}" aria-describedby="${esc(describedBy)}" ${invalid ? 'aria-invalid="true"' : ""}`;
  if (field.type === "readonly") {
    return `<input type="text" ${attrs} readonly value="${esc(value)}">`;
  }
  if (field.type === "boolean") {
    return `
      <div class="toggle-line">
        <input type="checkbox" ${attrs} data-key="${esc(field.key)}" ${value ? "checked" : ""}>
        <span data-toggle-state>${value ? esc(ui("enabled")) : esc(ui("disabled"))}</span>
      </div>
    `;
  }
  if (field.type === "integer") {
    return `
      <input type="number" ${attrs} data-key="${esc(field.key)}" min="${esc(field.min)}" max="${esc(field.max)}" value="${esc(value)}">
    `;
  }
  if (field.type === "time") {
    return `
      <input type="time" ${attrs} data-key="${esc(field.key)}" min="${esc(field.min)}" max="${esc(field.max)}" step="60" value="${esc(value)}">
    `;
  }
  if (field.type === "path") {
    if (isAutomaticSourcePath(field.key)) {
      return renderAutomaticSourcePathControl(field, value, attrs, controlId);
    }
    return `
      <div class="input-line">
        <input type="text" ${attrs} data-key="${esc(field.key)}" placeholder="${field.required ? "" : "null"}" value="${esc(value ?? "")}">
        <button class="button" type="button" data-pick="${esc(field.key)}" aria-label="${esc(`${ui("browse")}: ${fieldText(field, "label")}`)}" title="${esc(ui("browseTitle").replace("{kind}", pickerKind(field.picker)))}">${esc(ui("browse"))}</button>
      </div>
    `;
  }
  return `<input type="text" ${attrs} data-key="${esc(field.key)}" placeholder="${esc(field.placeholder || "")}" value="${esc(value ?? "")}">`;
}

function isAutomaticSourcePath(key) {
  return AUTOMATIC_SOURCE_PATH_KEYS.has(key);
}

function isCustomPathEnabled(key) {
  const value = state.draft[key];
  return value !== null && value !== "";
}

function renderAutomaticSourcePathControl(field, value, attrs, controlId) {
  const custom = isCustomPathEnabled(field.key);
  const automatic = automaticSourceForField(field.key);
  const displayValue = custom ? value : (automatic?.value || "");
  return `
    <div class="input-line path-mode-line">
      <label class="toggle-line">
        <input type="checkbox" data-path-custom="${esc(field.key)}" aria-controls="${controlId}" ${custom ? "checked" : ""}>
        <span>${esc(ui("customPath"))}</span>
      </label>
      <input type="text" ${attrs} data-key="${esc(field.key)}" placeholder="${custom ? "" : esc(ui("automatic"))}" value="${esc(displayValue ?? "")}" ${custom ? "" : "disabled"}>
      <button class="button" type="button" data-pick="${esc(field.key)}" aria-label="${esc(`${ui("browse")}: ${fieldText(field, "label")}`)}" title="${esc(ui("browseTitle").replace("{kind}", pickerKind(field.picker)))}" ${custom ? "" : "disabled"}>${esc(ui("browse"))}</button>
      ${renderFieldSaveStatus(field.key)}
    </div>
  `;
}

function normalizeDraftValue(value) {
  return value === "" ? null : value;
}

function fieldStatusId(key) {
  return `field-status-${safeDomId(key)}`;
}

function isFieldDirty(key) {
  return normalizeDraftValue(state.draft[key]) !== normalizeDraftValue(state.configSnapshot?.config?.[key]);
}

function renderFieldSaveStatus(key) {
  const dirty = isFieldDirty(key);
  return `<span id="${fieldStatusId(key)}" class="pill ${dirty ? "orange" : "green"}" role="status" aria-live="polite">${esc(ui(dirty ? "unsaved" : "saved"))}</span>`;
}

function updateFieldStatusNode(key) {
  const node = document.getElementById(fieldStatusId(key));
  if (!node) return;
  node.outerHTML = renderFieldSaveStatus(key);
}

function renderPathPreview(field) {
  const rawValue = state.draft[field.key];
  const preview = state.pathPreviews[field.key] || field.path || {};
  if (isAutomaticSourcePath(field.key) && !isCustomPathEnabled(field.key)) {
    const automatic = automaticSourceForField(field.key);
    if (automatic) {
      const cls = automatic.exists ? "ok" : "missing";
      const suffix = pathStatusLabel(automatic);
      return `<span id="${pathPreviewId(field.key)}" class="resolved ${cls}" aria-live="polite">${esc(ui("automatic"))}: ${esc(automatic.value)} (${esc(suffix)})</span>`;
    }
    return `<span id="${pathPreviewId(field.key)}" class="resolved missing" aria-live="polite">${esc(ui("automatic"))}: ${esc(ui("missing"))}</span>`;
  }
  if ((rawValue === null || rawValue === "") && !field.required) {
    return `<span id="${pathPreviewId(field.key)}" class="resolved" aria-live="polite">${esc(ui("savedNull"))}</span>`;
  }
  if (!preview.resolved) {
    return `<span id="${pathPreviewId(field.key)}" class="resolved" aria-live="polite">${esc(ui("savedNull"))}</span>`;
  }
  const cls = preview.exists ? "ok" : "missing";
  const suffix = pathStatusLabel(preview);
  return `<span id="${pathPreviewId(field.key)}" class="resolved ${cls}" aria-live="polite">${esc(preview.resolved)} (${esc(suffix)})</span>`;
}

function automaticSourceForField(key) {
  return (state.configSnapshot?.detected_sources || []).find(candidate => candidate.field === key) || null;
}

function pathPreviewId(key) {
  return `path-preview-${safeDomId(key)}`;
}

function updatePathPreviewNode(key) {
  const node = document.getElementById(pathPreviewId(key));
  const field = state.configSnapshot?.fields?.find(item => item.key === key);
  if (!node || !field) return;
  node.outerHTML = renderPathPreview(field);
}

function schedulePathPreview(key, value) {
  const field = state.configSnapshot?.fields?.find(item => item.key === key);
  if (!field || field.type !== "path") return;
  clearTimeout(state.previewTimers[key]);
  if ((value === null || value === "") && !field.required) {
    state.pathPreviews[key] = { resolved: null, exists: null };
    updatePathPreviewNode(key);
    return;
  }
  const requestedValue = value;
  state.previewTimers[key] = setTimeout(async () => {
    try {
      const result = await api("/api/resolve-path", {
        method: "POST",
        body: { field: key, current_value: requestedValue }
      });
      if (state.draft[key] !== requestedValue) return;
      state.pathPreviews[key] = result.path || {};
      updatePathPreviewNode(key);
    } catch (error) {
      if (state.draft[key] !== requestedValue) return;
      state.pathPreviews[key] = {
        resolved: String(requestedValue ?? ""),
        exists: false,
        kind: "inaccessible",
        error: error.message
      };
      updatePathPreviewNode(key);
    }
  }, 250);
}

function renderDetectedSources(candidates) {
  const externalCandidates = candidates.filter(candidate => !isAutomaticSourcePath(candidate.field));
  if (!externalCandidates.length) return "";
  return `
    <section class="panel">
      <div class="panel-head"><h2>${esc(ui("detectedSources"))}</h2></div>
      <div class="panel-body">
        <div class="pill-row">
          ${externalCandidates.map(renderDetectedSourceCandidate).join("")}
        </div>
      </div>
    </section>
  `;
}

function renderDetectedSourceCandidate(candidate) {
  const label = `${detectedSourceLabel(candidate)} ${candidate.exists ? "" : `(${ui(candidate.error ? "inaccessible" : "missing")})`}`;
  if (!candidate.exists) {
    return `<span class="pill orange" title="${esc(candidate.value)}">${esc(label)}</span>`;
  }
  return `
    <button class="button" type="button" data-use-detected="${esc(candidate.field)}" data-value="${esc(candidate.value)}" title="${esc(candidate.value)}">
      ${esc(ui("useAsManual"))}: ${esc(label)}
    </button>
  `;
}

function detectedSourceLabel(candidate) {
  if (candidate.field === "vrcx_db_path") return ui("defaultVrcxDb");
  if (candidate.field === "vrc_log_dir") return ui("defaultVrcLogDir");
  return candidate.label;
}

function renderUnsupported(unsupported) {
  const keys = Object.keys(unsupported);
  if (!keys.length) return "";
  return `
    <section class="panel">
      <div class="panel-head"><h2>${esc(ui("unsupportedKeys"))}</h2><span class="pill orange">${esc(ui("preserved"))}</span></div>
      <div class="panel-body">
        <pre class="readonly-json">${esc(JSON.stringify(unsupported, null, 2))}</pre>
      </div>
    </section>
  `;
}

function bindFieldControls() {
  for (const control of document.querySelectorAll("[data-key]")) {
    control.oninput = () => updateDraftFromControl(control);
    control.onchange = () => updateDraftFromControl(control);
  }
  for (const control of document.querySelectorAll("[data-path-custom]")) {
    control.onchange = () => updatePathCustomToggle(control);
  }
  for (const button of document.querySelectorAll("[data-pick]")) {
    button.onclick = () => pickPath(button.dataset.pick);
  }
  for (const button of document.querySelectorAll("[data-use-detected]")) {
    button.onclick = () => {
      state.draft[button.dataset.useDetected] = button.dataset.value;
      schedulePathPreview(button.dataset.useDetected, button.dataset.value);
      renderSettings();
      document.querySelector(`[data-key="${button.dataset.useDetected}"]`)?.focus();
    };
  }
}

function updatePathCustomToggle(control) {
  const key = control.dataset.pathCustom;
  if (!key) return;
  if (control.checked) {
    const automatic = automaticSourceForField(key);
    state.draft[key] = state.draft[key] || automatic?.value || "";
    schedulePathPreview(key, state.draft[key]);
  } else {
    state.draft[key] = null;
    state.pathPreviews[key] = { resolved: null, exists: null };
  }
  renderSettings();
  const focusTarget = control.checked
    ? document.querySelector(`[data-key="${key}"]`)
    : document.querySelector(`[data-path-custom="${key}"]`);
  focusTarget?.focus();
}

function updateDraftFromControl(control) {
  const key = control.dataset.key;
  const field = state.configSnapshot.fields.find(item => item.key === key);
  if (control.type === "checkbox") {
    state.draft[key] = control.checked;
    const stateNode = control.parentElement?.querySelector("[data-toggle-state]");
    if (stateNode) stateNode.textContent = ui(control.checked ? "enabled" : "disabled");
    if (key === "auto_start_overlay" && control.checked) {
      state.draft.auto_start_watcher = true;
      const watcherControl = document.querySelector('[data-key="auto_start_watcher"]');
      if (watcherControl) {
        watcherControl.checked = true;
        const watcherState = watcherControl.parentElement?.querySelector("[data-toggle-state]");
        if (watcherState) watcherState.textContent = ui("enabled");
      }
    }
  } else if (control.type === "number") {
    state.draft[key] = Number(control.value);
  } else {
    const text = control.value;
    state.draft[key] = field && !field.required && text.trim() === "" ? null : text;
  }
  if (field?.type === "path") schedulePathPreview(key, state.draft[key]);
  if (field?.type === "path" && isAutomaticSourcePath(key)) updateFieldStatusNode(key);
}

async function pickPath(key) {
  showMessage("settings-message", "");
  try {
    const result = await api("/api/pick-path", {
      method: "POST",
      body: { field: key, current_value: state.draft[key] }
    });
    if (result.cancelled) return;
    state.draft[key] = result.value;
    schedulePathPreview(key, result.value);
    renderSettings();
    document.querySelector(`[data-key="${key}"]`)?.focus();
  } catch (error) {
    showMessage("settings-message", error.message, "error");
  }
}

async function saveSettings() {
  showMessage("settings-message", "");
  state.fieldErrors = {};
  try {
    const result = await api("/api/config", {
      method: "POST",
      body: { config: state.draft }
    });
    state.configSnapshot = result.snapshot;
    state.draft = { ...result.snapshot.config };
    updatePathPreviewsFromSnapshot(result.snapshot);
    renderSettings();
    showMessage("settings-message", ui("saved"), "success");
    document.getElementById("settings-save")?.focus();
  } catch (error) {
    if (error.data && error.data.errors) state.fieldErrors = error.data.errors;
    if (error.data && error.data.snapshot) state.configSnapshot = error.data.snapshot;
    renderSettings();
    showMessage("settings-message", ui("saveFailed"), "error");
    document.querySelector('[aria-invalid="true"]')?.focus();
  }
}

async function renderHome() {
  const node = document.getElementById("view-home");
  node.innerHTML = `<div class="panel"><div class="empty" role="status">${esc(ui("loading"))}</div></div>`;
  const data = await api("/api/summary").catch(error => ({ error: error.message, counts: {}, recent: [] }));
  if (state.active !== "home") return;
  toolbarNode.innerHTML = renderHomeToolbar(data.session || {});
  node.innerHTML = `
    ${(data.startup_warnings || []).length ? `<div class="message show error" role="alert">${data.startup_warnings.map(esc).join("<br>")}</div>` : ""}
    <div class="message" id="home-message" role="status" aria-live="polite" aria-atomic="true"></div>
    <div class="grid summary-grid">
      ${metric(ui("danceTracks"), data.counts?.dance_tracks ?? 0, "blue")}
      ${metric(ui("playbackRecords"), data.counts?.playback_records ?? 0, "green")}
      ${metric(ui("acceptedRecords"), data.counts?.accepted_playback_records ?? 0, "blue")}
      ${metric(ui("attentionRecords"), data.counts?.needs_attention_playback_records ?? 0, "orange")}
    </div>
    <div class="grid two-col">
      ${renderLiveStatus(data.session || {})}
      <section class="panel">
        <div class="panel-head"><h2>${esc(ui("currentLiveRow"))}</h2></div>
        <div class="panel-body">
          ${data.current_live ? `<pre class="readonly-json">${esc(JSON.stringify(data.current_live, null, 2))}</pre>` : `<div class="empty">${esc(ui("noLiveRow"))}</div>`}
        </div>
      </section>
    </div>
    <div class="grid two-col">
      <section class="panel">
        <div class="panel-head"><h2>${esc(ui("databaseState"))}</h2>${data.database_exists ? `<span class="pill green">${esc(ui("dbFound"))}</span>` : `<span class="pill orange">${esc(ui("noDb"))}</span>`}</div>
        <div class="panel-body">
          <div class="resolved">${esc(data.database_path || "")}</div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>${esc(ui("recentAccepted"))}</h2></div>
        <div class="panel-body">${renderRecent(data.recent || [])}</div>
      </section>
    </div>
  `;
  bindHomeControls();
}

function renderHomeToolbar(session) {
  const watcherState = lifecycleState(session.watcher_state, session.watcher_running);
  const overlayState = lifecycleState(session.overlay_state, session.overlay_running);
  const watcherActive = watcherState !== "stopped";
  const overlayActive = overlayState !== "stopped";
  const overlayControlDisabled = watcherState === "stopping" || overlayState === "stopping";
  return `
    <button class="button" type="button" id="home-refresh">${esc(ui("refresh"))}</button>
    <button class="button ${watcherActive ? "danger" : "primary"}" type="button" data-live-control="watcher" data-live-action="${watcherActive ? "stop" : "start"}" ${watcherState === "stopping" ? "disabled" : ""}>
      ${esc(ui(watcherActive ? "stopWatcher" : "startWatcher"))}
    </button>
    <button class="button ${overlayActive ? "danger" : "primary"}" type="button" data-live-control="overlay" data-live-action="${overlayActive ? "stop" : "start"}" ${overlayControlDisabled ? "disabled" : ""}>
      ${esc(ui(overlayActive ? "stopOverlay" : "startOverlay"))}
    </button>
  `;
}

function renderHomeSession(session) {
  toolbarNode.innerHTML = renderHomeToolbar(session);
  bindHomeControls();
  const liveStatus = document.getElementById("home-live-status");
  if (liveStatus) liveStatus.outerHTML = renderLiveStatus(session);
}

function homeSessionIsStopping(session) {
  return lifecycleState(session.watcher_state, session.watcher_running) === "stopping"
    || lifecycleState(session.overlay_state, session.overlay_running) === "stopping";
}

async function pollHomeSessionToTerminalState(session) {
  let current = session;
  renderHomeSession(current);
  for (let attempt = 0; attempt < LIVE_STATE_POLL_LIMIT; attempt += 1) {
    if (!homeSessionIsStopping(current) || state.active !== "home") return;
    await new Promise(resolve => setTimeout(resolve, LIVE_STATE_POLL_INTERVAL_MS));
    try {
      const summary = await api("/api/summary");
      current = summary.session || {};
      renderHomeSession(current);
    } catch {
      return;
    }
  }
}

function renderThemePicker() {
  themeLabelNode.textContent = ui("themeLabel");
  themeSelectNode.setAttribute("aria-label", ui("themeLabel"));
  themeSelectNode.innerHTML = `
    <option value="system" ${state.theme === "system" ? "selected" : ""}>${esc(ui("themeSystem"))}</option>
    <option value="light" ${state.theme === "light" ? "selected" : ""}>${esc(ui("themeLight"))}</option>
    <option value="dark" ${state.theme === "dark" ? "selected" : ""}>${esc(ui("themeDark"))}</option>
  `;
  themeSelectNode.onchange = () => setTheme(themeSelectNode.value);
  applyTheme();
}

function applyTheme() {
  if (state.theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.dataset.theme = state.theme;
}

function setTheme(theme) {
  if (!["system", "light", "dark"].includes(theme)) return;
  state.theme = theme;
  localStorage.setItem(THEME_KEY, theme);
  applyTheme();
}

function bindHomeControls() {
  const refresh = document.getElementById("home-refresh");
  if (refresh) refresh.onclick = async () => {
    await renderHome();
    document.getElementById("home-refresh")?.focus();
  };
  for (const button of document.querySelectorAll("[data-live-control]")) {
    button.onclick = () => controlLive(button.dataset.liveControl, button.dataset.liveAction);
  }
}

async function controlLive(kind, action) {
  const controls = [...document.querySelectorAll("[data-live-control], #home-refresh")];
  for (const control of controls) control.disabled = true;
  showMessage("home-message", "");
  try {
    await api(`/api/live/${kind}`, {
      method: "POST",
      body: { action }
    });
    await renderHome();
  } catch (error) {
    showMessage("home-message", `${ui("liveControlFailed")}: ${error.message}`, "error");
    if (error.data?.session) {
      await pollHomeSessionToTerminalState(error.data.session);
    }
  } finally {
    for (const control of controls) control.disabled = false;
    document.querySelector(`[data-live-control="${kind}"]`)?.focus();
  }
}

function renderLiveStatus(session) {
  const stats = session.last_watcher_stats;
  const watcherState = lifecycleState(session.watcher_state, session.watcher_running);
  const overlayState = lifecycleState(session.overlay_state, session.overlay_running);
  return `
    <section class="panel" id="home-live-status" aria-live="polite">
      <div class="panel-head"><h2>${esc(ui("liveStatus"))}</h2></div>
      <div class="panel-body">
        <div class="status-grid">
          ${statusItem(ui("watcher"), watcherState)}
          ${statusItem(ui("overlay"), overlayState)}
        </div>
        ${session.last_error ? `<div class="message show error" role="alert"><strong>${esc(ui("lastRuntimeError"))}</strong><br>${esc(session.last_error)}</div>` : ""}
        ${stats ? `<div><div class="resolved">${esc(ui("lastWatcherStats"))}</div><pre class="readonly-json">${esc(JSON.stringify(stats, null, 2))}</pre></div>` : `<div class="empty">${esc(ui("noWatcherStats"))}</div>`}
      </div>
    </section>
  `;
}

function lifecycleState(value, running) {
  const state = String(value || "").toLowerCase();
  if (["running", "stopping", "stopped"].includes(state)) return state;
  return running ? "running" : "stopped";
}

function statusItem(label, state) {
  const color = state === "running" ? "green" : state === "stopping" ? "blue" : "orange";
  return `
    <div class="status-item">
      <span>${esc(label)}</span>
      <strong><span class="pill ${color}">${esc(ui(state))}</span></strong>
    </div>
  `;
}

function metric(label, value, color) {
  return `<section class="panel metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><div class="pill-row"><span class="pill ${color}">${esc(ui("local"))}</span></div></section>`;
}

function renderRecent(rows) {
  if (!rows.length) return `<div class="empty">${esc(ui("noRecords"))}</div>`;
  return `<table><caption class="sr-only">${esc(ui("recentAccepted"))}</caption><thead><tr><th scope="col">${esc(ui("time"))}</th><th scope="col">${esc(ui("track"))}</th><th scope="col">${esc(ui("source"))}</th></tr></thead><tbody>
    ${rows.map(row => `<tr><td>${esc(row.played_at)}</td><td>${esc(row.video_name || row.title || row.external_id || "")}</td><td>${esc(row.source || "")}</td></tr>`).join("")}
  </tbody></table>`;
}

async function renderTimeline() {
  state.timelineSort = state.timelineSort || "asc";
  const initialTimelineDate = state.timelineDate || "";
  toolbarNode.innerHTML = `
    <div class="timeline-date-nav">
      <button class="timeline-step" type="button" data-timeline-step="month" data-step="-1" title="${esc(ui("previousMonth"))}" aria-label="${esc(ui("previousMonth"))}">&lt;&lt;</button>
      <button class="timeline-step" type="button" data-timeline-step="day" data-step="-1" title="${esc(ui("previousDay"))}" aria-label="${esc(ui("previousDay"))}">&lt;</button>
      <div class="timeline-date-field">
        <input class="timeline-date-input" type="text" id="timeline-date" value="${esc(initialTimelineDate)}" inputmode="numeric" autocomplete="off" maxlength="10" placeholder="YYYY-MM-DD" aria-label="${esc(ui("timelineDate"))}">
        <input class="timeline-date-picker" type="date" id="timeline-date-picker" value="${esc(initialTimelineDate)}" aria-label="${esc(ui("openDatePicker"))}" title="${esc(ui("openDatePicker"))}">
      </div>
      <button class="timeline-step" type="button" data-timeline-step="day" data-step="1" title="${esc(ui("nextDay"))}" aria-label="${esc(ui("nextDay"))}">&gt;</button>
      <button class="timeline-step" type="button" data-timeline-step="month" data-step="1" title="${esc(ui("nextMonth"))}" aria-label="${esc(ui("nextMonth"))}">&gt;&gt;</button>
    </div>
    <button class="button timeline-icon-button timeline-sort-button" type="button" id="timeline-sort" title="${esc(timelineSortLabel())}" aria-label="${esc(ui("reverseTimelineOrder"))}" aria-pressed="${state.timelineSort === "desc"}" data-sort="${esc(state.timelineSort)}"><span class="timeline-sort-part timeline-sort-asc" aria-hidden="true">↑</span><span class="timeline-sort-part timeline-sort-desc" aria-hidden="true">↓</span></button>
    <button class="button timeline-icon-button timeline-copy-button" type="button" id="timeline-copy" title="${esc(ui("copyDailyDancesTitle"))}" aria-label="${esc(ui("copyDailyDancesTitle"))}">⧉</button>
  `;
  const node = document.getElementById("view-timeline");
  const dateInput = document.getElementById("timeline-date");
  const datePicker = document.getElementById("timeline-date-picker");
  const sortButton = document.getElementById("timeline-sort");
  const copyButton = document.getElementById("timeline-copy");
  let loadRequest = 0;
  let currentRecords = [];
  function renderRecords() {
    node.innerHTML = `
      <div class="message" id="timeline-message" role="status" aria-live="polite" aria-atomic="true"></div>
      <section class="panel"><div class="panel-body">${renderTimelineRows(sortedTimelineRows(currentRecords))}</div></section>
    `;
    bindTimelineActions(node, load);
  }
  async function load() {
    const normalizedDate = normalizeTimelineDateInput(dateInput.value);
    const hasSelectedDate = isValidLocalDate(normalizedDate);
    if (normalizedDate && dateInput.value !== normalizedDate) {
      dateInput.value = normalizedDate;
    }
    if (hasSelectedDate) {
      state.timelineDate = normalizedDate;
      datePicker.value = normalizedDate;
    }
    const requestId = ++loadRequest;
    const path = hasSelectedDate ? `/api/timeline?date=${encodeURIComponent(normalizedDate)}` : "/api/timeline";
    let data;
    try {
      data = await api(path);
    } catch (error) {
      if (requestId !== loadRequest) return;
      currentRecords = [];
      renderRecords();
      showMessage("timeline-message", `${ui("timelineLoadFailed")}: ${translatedError(error.message)}`, "error");
      return;
    }
    if (requestId !== loadRequest) return;
    const resolvedDate = normalizeTimelineDateInput(data.date || normalizedDate);
    if (isValidLocalDate(resolvedDate)) {
      state.timelineDate = resolvedDate;
      dateInput.value = resolvedDate;
      datePicker.value = resolvedDate;
    }
    syncTimelineUrl();
    currentRecords = data.records || [];
    renderRecords();
  }
  function moveTimelineDate(unit, amount) {
    const current = isValidLocalDate(dateInput.value)
      ? dateInput.value
      : (isValidLocalDate(state.timelineDate) ? state.timelineDate : formatLocalDate(new Date()));
    dateInput.value = unit === "month" ? addLocalMonths(current, amount) : addLocalDays(current, amount);
    state.timelineDate = dateInput.value;
    datePicker.value = dateInput.value;
    load();
  }
  dateInput.oninput = () => {
    const normalizedDate = normalizeTimelineDateInput(dateInput.value);
    if (dateInput.value !== normalizedDate) {
      dateInput.value = normalizedDate;
    }
    if (!isValidLocalDate(normalizedDate)) {
      loadRequest += 1;
      return;
    }
    state.timelineDate = normalizedDate;
    datePicker.value = normalizedDate;
    load();
  };
  dateInput.onblur = () => {
    const normalizedDate = normalizeTimelineDateInput(dateInput.value);
    if (isValidLocalDate(normalizedDate)) {
      dateInput.value = normalizedDate;
      datePicker.value = normalizedDate;
      if (normalizedDate !== state.timelineDate) {
        state.timelineDate = normalizedDate;
        load();
      }
      return;
    }
    dateInput.value = state.timelineDate || "";
  };
  dateInput.onkeydown = event => {
    if (event.key !== "Enter") return;
    const normalizedDate = normalizeTimelineDateInput(dateInput.value);
    if (!isValidLocalDate(normalizedDate)) return;
    event.preventDefault();
    dateInput.value = normalizedDate;
    state.timelineDate = normalizedDate;
    datePicker.value = normalizedDate;
    load();
  };
  datePicker.onchange = () => {
    const selectedDate = normalizeTimelineDateInput(datePicker.value);
    if (!isValidLocalDate(selectedDate)) return;
    dateInput.value = selectedDate;
    state.timelineDate = selectedDate;
    load();
  };
  datePicker.onclick = () => {
    if (typeof datePicker.showPicker !== "function") return;
    try {
      datePicker.showPicker();
    } catch {
    }
  };
  sortButton.onclick = () => {
    state.timelineSort = state.timelineSort === "desc" ? "asc" : "desc";
    sortButton.title = timelineSortLabel();
    sortButton.setAttribute("aria-pressed", state.timelineSort === "desc" ? "true" : "false");
    sortButton.dataset.sort = state.timelineSort;
    syncTimelineUrl();
    renderRecords();
  };
  copyButton.onclick = async () => {
    const text = dailyDanceClipboardText(currentRecords);
    if (!text) {
      showMessage("timeline-message", ui("noAcceptedTimelineRecords"), "error");
      return;
    }
    try {
      await copyTextToClipboard(text);
      showMessage("timeline-message", `${ui("copiedDailyDances")}: ${acceptedTimelineRows(currentRecords).length}`, "success");
    } catch (error) {
      showMessage("timeline-message", `${ui("copyDailyDancesFailed")}: ${error.message}`, "error");
    }
  };
  for (const button of toolbarNode.querySelectorAll("[data-timeline-step]")) {
    button.onclick = () => moveTimelineDate(button.dataset.timelineStep, Number(button.dataset.step));
  }
  await load();
}

function timelineSortLabel() {
  return state.timelineSort === "desc" ? ui("timelineSortReverse") : ui("timelineSortChronological");
}

function sortedTimelineRows(rows) {
  return state.timelineSort === "desc" ? [...rows].reverse() : rows;
}

function acceptedTimelineRows(rows) {
  return rows.filter(row => (row.review_status || row.effective_playback_status) === "accepted");
}

function dailyDanceClipboardText(rows) {
  return acceptedTimelineRows(rows)
    .map(row => row.line || `${row.time} ${row.display}`)
    .join("\n");
}

async function copyTextToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  try {
    if (!document.execCommand("copy")) throw new Error("clipboard unavailable");
  } finally {
    document.body.removeChild(textarea);
  }
}

function renderTimelineRows(rows) {
  if (!rows.length) return `<div class="empty">${esc(ui("noTimelineRecords"))}</div>`;
  return `<div class="table-scroll" role="region" aria-label="${esc(ui("playbackRecords"))}" tabindex="0"><table class="timeline-table"><caption class="sr-only">${esc(ui("playbackRecords"))}</caption><thead><tr><th scope="col" style="width:110px">${esc(ui("time"))}</th><th scope="col">${esc(ui("record"))}</th><th scope="col" style="width:170px">${esc(ui("reviewStatus"))}</th><th scope="col" style="width:240px">${esc(ui("actions"))}</th></tr></thead><tbody>
    ${rows.map(row => `<tr><td>${esc(row.time)}</td><td>${renderTimelineRecord(row)}</td><td>${renderTimelineStatus(row)}</td><td>${renderTimelineActions(row)}</td></tr>`).join("")}
  </tbody></table></div>`;
}

function renderTimelineRecord(row) {
  const systemLabel = danceSystemLabel(row);
  return `
    <div class="timeline-record">
      <div class="timeline-record-title">
        <span>${esc(row.display)}</span>
        ${systemLabel ? `<span class="pill violet timeline-system">${esc(systemLabel)}</span>` : ""}
      </div>
      ${renderTimelineSource(row)}
    </div>
  `;
}

function renderTimelineSource(row) {
  const source = timelineSource(row);
  const requester = source.showRequester ? String(row.requester_display_name || row.source_display_name || "").trim() : "";
  const requesterUserId = String(row.requester_user_id || "").trim();
  const requesterTitle = requester && requesterUserId ? ` title="${esc(requesterUserId)}"` : "";
  return `<div class="timeline-source"><span>${esc(source.label)}</span>${requester ? ` · <strong${requesterTitle}>${esc(requester)}</strong>` : ""}</div>`;
}

function timelineSource(row) {
  const value = String(row.source_type || "").trim().toLowerCase().replaceAll("-", "_");
  if (value === "random") return { label: ui("sourceRandom"), showRequester: false };
  if (value === "self") return { label: ui("sourceSelf"), showRequester: true };
  if (value === "recommend" || value === "recommended" || value === "recommendation") return { label: ui("sourceRecommend"), showRequester: true };
  if (value === "queued_self" || value === "queued" || value === "reserved" || value === "reservation") return { label: ui("sourceQueuedSelf"), showRequester: true };
  if (value === "other" || value === "player" || value === "requester" || value === "requester_marker") return { label: ui("sourceOther"), showRequester: true };
  return { label: ui("sourceUnknown"), showRequester: true };
}

function danceSystemLabel(row) {
  const key = String(row.dance_system_key || row.system_key || "").trim().toLowerCase();
  const name = String(row.dance_system_name || "").trim();
  if (name) return name;
  if (DANCE_SYSTEM_LABELS[key]) return DANCE_SYSTEM_LABELS[key];
  return key;
}

function renderTimelineStatus(row) {
  const status = row.review_status || row.effective_playback_status || "";
  const defaultStatus = row.default_playback_status || status;
  const manualStatus = row.manual_decision_status || "";
  const detail = `${ui("manual")} · ${ui("defaultResult")}: ${reviewStatusLabel(defaultStatus)}`;
  return `
    <div class="timeline-status">
      <span class="pill ${reviewStatusClass(status)}">${esc(reviewStatusLabel(status))}</span>
      ${manualStatus ? `<span class="status-detail">${esc(detail)}</span>` : ""}
    </div>
  `;
}

function renderTimelineActions(row) {
  const status = row.review_status || row.effective_playback_status || "";
  const hasManual = Boolean(row.manual_decision_status);
  return `
    <div class="row-actions">
      <button class="mini-button primary" type="button" data-playback-action="accept" data-playback-id="${esc(row.id)}" ${status === "accepted" ? "disabled" : ""}>${esc(ui("accept"))}</button>
      <button class="mini-button danger" type="button" data-playback-action="exclude" data-playback-id="${esc(row.id)}" ${status === "excluded" ? "disabled" : ""}>${esc(ui("exclude"))}</button>
      <button class="mini-button" type="button" data-playback-action="restore_default" data-playback-id="${esc(row.id)}" ${hasManual ? "" : "disabled"}>${esc(ui("restoreDefault"))}</button>
    </div>
  `;
}

function bindTimelineActions(container, reload) {
  for (const button of container.querySelectorAll("[data-playback-action]")) {
    button.onclick = async () => {
      const playbackRecordId = Number(button.dataset.playbackId);
      const playbackRecordKey = button.dataset.playbackId;
      const action = button.dataset.playbackAction;
      button.disabled = true;
      try {
        await api("/api/playback-review", {
          method: "POST",
          body: { playback_record_id: playbackRecordId, action }
        });
        await reload();
        const rowButtons = [...container.querySelectorAll("[data-playback-id]")]
          .filter(candidate => candidate.dataset.playbackId === playbackRecordKey);
        (rowButtons.find(candidate => !candidate.disabled) || document.getElementById("timeline-copy"))?.focus();
      } catch (error) {
        showMessage("timeline-message", `${ui("reviewUpdateFailed")}: ${translatedError(error.message)}`, "error");
        button.disabled = false;
      }
    };
  }
}

async function renderCatalog() {
  toolbarNode.innerHTML = `
    <input type="text" id="catalog-search" aria-label="${esc(ui("searchCatalog"))}" placeholder="${esc(ui("searchCatalog"))}">
    <button class="button" type="button" id="catalog-load">${esc(ui("search"))}</button>
  `;
  const node = document.getElementById("view-catalog");
  async function load() {
    const q = document.getElementById("catalog-search").value;
    const data = await api(`/api/catalog?q=${encodeURIComponent(q)}&limit=100`);
    node.innerHTML = `<section class="panel"><div class="panel-body">${renderCatalogRows(data.tracks || [])}</div></section>`;
  }
  document.getElementById("catalog-load").onclick = load;
  document.getElementById("catalog-search").onkeydown = event => {
    if (event.key === "Enter") load();
  };
  await load();
}

function renderCatalogRows(rows) {
  if (!rows.length) return `<div class="empty">${esc(ui("noTracks"))}</div>`;
  return `<table><caption class="sr-only">${esc(ui("danceTracks"))}</caption><thead><tr><th scope="col" style="width:130px">${esc(ui("track"))}</th><th scope="col">${esc(ui("title"))}</th><th scope="col">${esc(ui("artist"))}</th><th scope="col" style="width:150px">${esc(ui("preferences"))}</th></tr></thead><tbody>
    ${rows.map(row => `<tr>
      <td>${esc(row.system_key)}:${esc(row.external_id)}</td>
      <td>${esc(row.title || "")}</td>
      <td>${esc(row.artist || "")}</td>
      <td><div class="pill-row">${row.favorite ? `<span class="pill green">${esc(ui("favorite"))}</span>` : ''}${row.want_to_learn ? `<span class="pill violet">${esc(ui("wantToLearn"))}</span>` : ''}</div></td>
    </tr>`).join("")}
  </tbody></table>`;
}

async function renderLists() {
  const node = document.getElementById("view-lists");
  const data = await api("/api/lists");
  node.innerHTML = `
    <section class="panel">
      <div class="panel-head"><h2>${esc(ui("queuedSelfManifests"))}</h2>${data.exists ? `<span class="pill green">${esc(ui("found"))}</span>` : `<span class="pill orange">${esc(ui("missing"))}</span>`}</div>
      <div class="panel-body">
        <div class="resolved">${esc(data.queued_self_dir)}</div>
        ${renderManifests(data.manifests || [])}
      </div>
    </section>
  `;
}

function renderManifests(rows) {
  if (!rows.length) return `<div class="empty">${esc(ui("noManifests"))}</div>`;
  return `<div class="list-stack">${rows.map(row => `
    <div class="list-item">
      <strong>${esc(row.name)}</strong>
      <code>${esc(row.path)}</code>
      ${(row.preview || []).map(line => `<span>${esc(line)}</span>`).join("")}
    </div>
  `).join("")}</div>`;
}

async function renderInsights() {
  const node = document.getElementById("view-insights");
  const data = await api("/api/insights");
  node.innerHTML = `
    <div class="grid two-col">
      <section class="panel"><div class="panel-head"><h2>${esc(ui("sourceDistribution"))}</h2></div><div class="panel-body">${renderKeyCount(data.source_distribution || [], "source", ui("sourceDistribution"))}</div></section>
      <section class="panel"><div class="panel-head"><h2>${esc(ui("topTracks"))}</h2></div><div class="panel-body">${renderKeyCount(data.top_tracks || [], "title", ui("topTracks"))}</div></section>
    </div>
    <section class="panel"><div class="panel-head"><h2>${esc(ui("recommendations"))}</h2></div><div class="panel-body">${renderCatalogRows(data.recommendations || [])}</div></section>
  `;
}

function renderKeyCount(rows, key, caption) {
  if (!rows.length) return `<div class="empty">${esc(ui("noData"))}</div>`;
  return `<table><caption class="sr-only">${esc(caption)}</caption><thead><tr><th scope="col">${esc(ui("name"))}</th><th scope="col" style="width:90px">${esc(ui("count"))}</th></tr></thead><tbody>
    ${rows.map(row => `<tr><td>${esc(row[key] || row.external_id || "(none)")}</td><td>${esc(row.count || 0)}</td></tr>`).join("")}
  </tbody></table>`;
}

async function renderOperations() {
  const node = document.getElementById("view-operations");
  if (!state.operationsSnapshot) {
    node.innerHTML = `<div class="panel"><div class="empty" role="status">${esc(ui("loading"))}</div></div>`;
    api("/api/operations").then(data => {
      state.operationsSnapshot = data;
      renderOperations();
    }).catch(error => {
      node.innerHTML = `<div class="message show error" role="alert">${esc(error.message)}</div>`;
    });
    return;
  }
  const operations = state.operationsSnapshot.operations || [];
  node.innerHTML = `<div class="list-stack">${operations.map(renderOperationPanel).join("")}</div>`;
  bindOperationControls(operations);
}

function renderOperationPanel(operation) {
  ensureOperationDraft(operation);
  const result = state.operationResults[operation.key];
  const error = state.operationErrors[operation.key];
  const running = state.runningOperation === operation.key;
  return `
    <section class="panel">
      <div class="panel-head">
        <h2>${esc(operationText(operation, "title"))}</h2>
        <span class="pill orange">${esc(operationText(operation, "risk"))}</span>
      </div>
      <div class="panel-body">
        <p class="operation-summary" id="operation-summary-${safeDomId(operation.key)}">${esc(operationText(operation, "summary"))}</p>
        <code>${esc(operation.command)}</code>
        <div class="settings-grid">
          ${renderOperationParameters(operation)}
        </div>
        <div class="toolbar">
          <button class="button primary" type="button" data-run-operation="${esc(operation.key)}" aria-describedby="operation-summary-${safeDomId(operation.key)}" ${state.runningOperation ? "disabled" : ""}>${esc(running ? ui("runningOperation") : ui("run"))}</button>
        </div>
        ${error ? `<div class="message show error" role="alert"><strong>${esc(ui("operationFailed"))}</strong><br>${esc(error)}</div>` : ""}
        ${result ? renderOperationResult(result) : ""}
      </div>
    </section>
  `;
}

function renderOperationParameters(operation) {
  if (!operation.parameters || !operation.parameters.length) return "";
  return operation.parameters.map(parameter => renderOperationParameter(operation, parameter)).join("");
}

function renderOperationParameter(operation, parameter) {
  const controlId = operationControlId(operation.key, parameter.key);
  const descriptionId = operationDescriptionId(operation.key, parameter.key);
  return `
    <div class="field-row">
      <div class="field-label">
        <label class="field-name" for="${controlId}">${esc(parameter.label)}</label>
        <code>${esc(parameter.key)}</code>
        <span class="field-summary" id="${descriptionId}">${esc(parameter.summary)}</span>
      </div>
      <div class="field-control">
        ${renderOperationParameterControl(operation, parameter, controlId, descriptionId)}
      </div>
    </div>
  `;
}

function operationControlId(operationKey, parameterKey) {
  return `operation-${safeDomId(operationKey)}-${safeDomId(parameterKey)}`;
}

function operationDescriptionId(operationKey, parameterKey) {
  return `${operationControlId(operationKey, parameterKey)}-description`;
}

function renderOperationParameterControl(operation, parameter, controlId, descriptionId) {
  const value = state.operationDrafts[operation.key]?.[parameter.key];
  const dataAttrs = `id="${controlId}" aria-describedby="${descriptionId}" ${parameter.required ? 'aria-required="true"' : ""} data-operation-key="${esc(operation.key)}" data-param-key="${esc(parameter.key)}"`;
  if (parameter.type === "boolean") {
    return `
      <div class="toggle-line">
        <input type="checkbox" ${dataAttrs} ${value ? "checked" : ""}>
        <span data-toggle-state>${value ? esc(ui("enabled")) : esc(ui("disabled"))}</span>
      </div>
    `;
  }
  if (parameter.type === "integer") {
    return `<input type="number" ${dataAttrs} value="${esc(value ?? "")}">`;
  }
  if (parameter.type === "choice") {
    return `
      <select ${dataAttrs}>
        ${(parameter.choices || []).map(choice => `<option value="${esc(choice)}" ${choice === value ? "selected" : ""}>${esc(choice)}</option>`).join("")}
      </select>
    `;
  }
  return `<input type="text" ${dataAttrs} value="${esc(value ?? "")}">`;
}

function renderOperationResult(result) {
  return `
    <div class="message show success" role="status"><strong>${esc(ui("operationComplete"))}</strong><br>${esc(result.summary || "")}</div>
    <pre class="readonly-json">${esc((result.lines || []).join("\n"))}</pre>
  `;
}

function ensureOperationDraft(operation) {
  if (state.operationDrafts[operation.key]) return;
  const draft = {};
  for (const parameter of operation.parameters || []) {
    if (parameter.type === "boolean") {
      draft[parameter.key] = Boolean(parameter.default);
    } else if (parameter.default !== null && parameter.default !== undefined) {
      draft[parameter.key] = parameter.default;
    } else {
      draft[parameter.key] = "";
    }
  }
  state.operationDrafts[operation.key] = draft;
}

function bindOperationControls(operations) {
  for (const control of document.querySelectorAll("[data-operation-key][data-param-key]")) {
    control.oninput = () => updateOperationDraft(control);
    control.onchange = () => updateOperationDraft(control);
  }
  for (const button of document.querySelectorAll("[data-run-operation]")) {
    button.onclick = () => runOperation(button.dataset.runOperation, operations);
  }
}

function updateOperationDraft(control) {
  const operationKey = control.dataset.operationKey;
  const paramKey = control.dataset.paramKey;
  const operation = (state.operationsSnapshot?.operations || []).find(item => item.key === operationKey);
  const parameter = operation?.parameters?.find(item => item.key === paramKey);
  if (!operation || !parameter) return;
  ensureOperationDraft(operation);
  if (parameter.type === "boolean") {
    state.operationDrafts[operationKey][paramKey] = control.checked;
    const stateNode = control.parentElement?.querySelector("[data-toggle-state]");
    if (stateNode) stateNode.textContent = ui(control.checked ? "enabled" : "disabled");
  } else {
    state.operationDrafts[operationKey][paramKey] = control.value;
  }
}

function operationPayload(operation) {
  ensureOperationDraft(operation);
  const draft = state.operationDrafts[operation.key] || {};
  const parameters = {};
  for (const parameter of operation.parameters || []) {
    const value = draft[parameter.key];
    if (parameter.type === "boolean") {
      parameters[parameter.key] = Boolean(value);
    } else if (value !== "" && value !== null && value !== undefined) {
      parameters[parameter.key] = value;
    }
  }
  return { operation: operation.key, parameters };
}

async function runOperation(key, operations) {
  const operation = operations.find(item => item.key === key);
  if (!operation || state.runningOperation) return;
  state.runningOperation = key;
  state.operationErrors[key] = "";
  state.operationResults[key] = null;
  for (const button of document.querySelectorAll("[data-run-operation]")) button.disabled = true;
  const activeButton = document.querySelector(`[data-run-operation="${key}"]`);
  if (activeButton) {
    activeButton.textContent = ui("runningOperation");
    activeButton.setAttribute("aria-busy", "true");
  }
  try {
    const response = await api("/api/operations/run", {
      method: "POST",
      body: operationPayload(operation)
    });
    state.operationResults[key] = response.result;
  } catch (error) {
    state.operationErrors[key] = error.message;
  } finally {
    state.runningOperation = null;
    renderOperations();
    document.querySelector(`[data-run-operation="${key}"]`)?.focus();
  }
}

renderLanguageSwitch();
renderThemePicker();
renderNav();
addEventListener("popstate", () => setView(viewFromPath(location.pathname), { syncLocation: true, focusHeading: true }));
setView(viewFromPath(location.pathname), { syncLocation: true });
</script>
</body>
</html>
"""

def render_webui_html(csrf_token: str) -> str:
    """Render the single-page UI with the server-generated CSRF token."""
    routes_json = json.dumps(WEBUI_ROUTE_BY_VIEW, ensure_ascii=True, separators=(",", ":"))
    return WEBUI_HTML.replace(CSRF_TOKEN_PLACEHOLDER, csrf_token).replace(
        ROUTES_PLACEHOLDER,
        routes_json,
    )
