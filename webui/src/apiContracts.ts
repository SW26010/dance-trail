import { z } from "zod";

export const jsonObjectSchema = z.record(z.string(), z.unknown());

export const apiErrorResponseSchema = z.union([
  z.object({ error: z.string() }).passthrough(),
  z.object({ errors: z.record(z.string(), z.string()) }).passthrough(),
]);

export const sessionSchema = z.object({
  session_state: z.string(),
  watcher_running: z.boolean(),
  overlay_running: z.boolean(),
  watcher_state: z.string(),
  overlay_state: z.string(),
  last_error: z.string().nullable(),
  last_watcher_stats: z.unknown(),
}).passthrough();

export type Session = z.infer<typeof sessionSchema>;

export const summarySchema = z.object({
  database_path: z.string(),
  database_exists: z.boolean(),
  counts: z.record(z.string(), z.number()),
  recent: z.array(jsonObjectSchema),
  current_live: z.unknown(),
  config_warnings: z.array(z.string()),
  startup_warnings: z.array(z.string()),
  session: sessionSchema,
  database_error: z.string().optional(),
}).passthrough();

export type Summary = z.infer<typeof summarySchema>;

export const liveControlResponseSchema = z.object({
  session: sessionSchema,
}).passthrough();

export const exitResponseSchema = z.object({ status: z.literal("exiting") });

export const timelineRecordSchema = z.object({
  id: z.number().int(),
  time: z.string(),
  played_at: z.string(),
  display: z.string(),
  line: z.string(),
  review_status: z.string(),
  default_playback_status: z.string(),
  manual_decision_status: z.string().nullable(),
  effective_playback_status: z.string(),
  has_manual_decision: z.boolean(),
  dance_system_key: z.string().nullable(),
  dance_system_name: z.string().nullable(),
  source_type: z.string().nullable(),
  source_display_name: z.string().nullable(),
  requester_display_name: z.string().nullable(),
  requester_user_id: z.string().nullable(),
}).passthrough();

export type TimelineRecord = z.infer<typeof timelineRecordSchema>;

export const timelineSnapshotSchema = z.object({
  date: z.string(),
  source: z.string(),
  records: z.array(timelineRecordSchema),
  database_exists: z.boolean(),
  error: z.string().optional(),
}).passthrough();

export const catalogSnapshotSchema = z.object({
  tracks: z.array(jsonObjectSchema),
  database_exists: z.boolean(),
  query: z.string(),
  error: z.string().optional(),
}).passthrough();

export const listsSnapshotSchema = z.object({
  queued_self_dir: z.string(),
  exists: z.boolean(),
  manifests: z.array(jsonObjectSchema),
}).passthrough();

export type ListsSnapshot = z.infer<typeof listsSnapshotSchema>;

export const insightsSnapshotSchema = z.object({
  database_exists: z.boolean(),
  source_distribution: z.array(jsonObjectSchema),
  top_tracks: z.array(jsonObjectSchema),
  attention_counts: z.record(z.string(), z.number()),
  recommendations: z.array(jsonObjectSchema),
  error: z.string().optional(),
}).passthrough();

export type InsightsSnapshot = z.infer<typeof insightsSnapshotSchema>;

export const operationParameterSchema = z.object({
  key: z.string(),
  label: z.string(),
  summary: z.string(),
  type: z.enum(["boolean", "integer", "choice", "text", "path"]),
  required: z.boolean(),
  default: z.unknown(),
  choices: z.array(z.string()).optional(),
}).passthrough();

const operationTextSchema = z.object({
  title: z.string(),
  summary: z.string(),
  risk: z.string(),
}).passthrough();

export const operationSchema = z.object({
  key: z.string(),
  title: z.string(),
  summary: z.string(),
  risk: z.string(),
  command: z.string(),
  text: z.record(z.string(), operationTextSchema),
  parameters: z.array(operationParameterSchema),
}).passthrough();

export type Operation = z.infer<typeof operationSchema>;
export type OperationParameter = z.infer<typeof operationParameterSchema>;

export const operationsSnapshotSchema = z.object({
  operations: z.array(operationSchema),
}).passthrough();

export const operationResultSchema = z.object({
  operation_key: z.string(),
  title: z.string(),
  status: z.string(),
  summary: z.string(),
  lines: z.array(z.string()),
  metrics: jsonObjectSchema,
}).passthrough();

export type OperationResult = z.infer<typeof operationResultSchema>;

export const runOperationResponseSchema = z.object({
  result: operationResultSchema,
}).passthrough();

export const pathPreviewSchema = z.object({
  resolved: z.string().nullable(),
  exists: z.boolean().nullable(),
  kind: z.string().optional(),
  error: z.string().optional(),
}).passthrough();

export type PathPreview = z.infer<typeof pathPreviewSchema>;

export const detectedSourceSchema = z.object({
  field: z.string(),
  label: z.string(),
  value: z.string(),
  exists: z.boolean(),
  kind: z.string(),
  error: z.string().nullable().optional(),
}).passthrough();

export type DetectedSource = z.infer<typeof detectedSourceSchema>;

export const configFieldSchema = z.object({
  key: z.string(),
  label: z.string(),
  group: z.string(),
  summary: z.string(),
  type: z.enum(["readonly", "boolean", "integer", "time", "path", "text"]),
  required: z.boolean(),
  min: z.union([z.number(), z.string()]).optional(),
  max: z.union([z.number(), z.string()]).optional(),
  placeholder: z.string().optional(),
  picker: z.enum(["file", "directory"]).optional(),
  path: pathPreviewSchema.optional(),
  value: z.unknown(),
}).passthrough();

export type ConfigField = z.infer<typeof configFieldSchema>;

export const configSnapshotSchema = z.object({
  app_root: z.string(),
  config_path: z.string(),
  config: jsonObjectSchema,
  fields: z.array(configFieldSchema),
  unsupported: jsonObjectSchema,
  detected_sources: z.array(detectedSourceSchema),
  warnings: z.array(z.string()),
}).passthrough();

export type ConfigSnapshot = z.infer<typeof configSnapshotSchema>;

export const resolvePathResponseSchema = z.object({
  field: z.string(),
  path: pathPreviewSchema,
}).passthrough();

export const pickPathResponseSchema = z.union([
  z.object({ cancelled: z.literal(true) }).passthrough(),
  z.object({ field: z.string(), value: z.string() }).passthrough(),
]);

export const saveConfigResponseSchema = z.object({
  saved: z.literal(true),
  snapshot: configSnapshotSchema,
}).passthrough();

export const playbackReviewResponseSchema = z.object({
  review: jsonObjectSchema,
}).passthrough();
