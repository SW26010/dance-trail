import {
  Badge,
  Button,
  Card,
  CardHeader,
  Field,
  Input,
  SpinButton,
  Spinner,
  Switch,
  Text,
} from "@fluentui/react-components";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, postJson } from "../api";
import {
  configSnapshotSchema,
  pickPathResponseSchema,
  resolvePathResponseSchema,
  saveConfigResponseSchema,
  type ConfigField,
  type ConfigSnapshot,
  type DetectedSource,
  type PathPreview,
} from "../apiContracts";
import { FeedbackRegion } from "../components/FeedbackRegion";
import { useAppStyles } from "../styles";
import type { Language } from "../i18n";
import type { JsonObject, PageProps } from "./types";
import { errorMessage } from "./types";

const automaticFields = new Set(["vrcx_db_path", "vrc_log_dir"]);

const chineseFields: Record<string, { label: string; group: string; summary: string }> = {
  config_version: { label: "配置版本", group: "系统", summary: "本地配置结构版本。" },
  app_db: { label: "应用数据库", group: "应用内部路径", summary: "SQLite 运行状态。" },
  queued_self_dir: { label: "自选队列目录", group: "应用内部路径", summary: "计划自选舞蹈的 Markdown 清单。" },
  capture_dir: { label: "捕获目录", group: "应用内部路径", summary: "实时 watcher 捕获输出。" },
  run_log_dir: { label: "运行日志目录", group: "应用内部路径", summary: "常规应用运行日志。" },
  source_vrc_log_dir: { label: "VRChat 源日志归档", group: "应用内部路径", summary: "逐字节归档的源 output_log 文件。" },
  recording_frames_dir: { label: "录像帧目录", group: "应用内部路径", summary: "用于分析的顶部裁剪帧样本。" },
  self_user_id: { label: "本机 VRChat 用户 ID", group: "外部数据源", summary: "用于判断 VRCX 历史点歌人是否为自己。" },
  vrcx_db_path: { label: "VRCX 数据库", group: "外部数据源", summary: "VRCX 播放历史 SQLite 文件。" },
  vrc_log_dir: { label: "VRChat 日志目录", group: "外部数据源", summary: "包含 VRChat output_log 文件的目录。" },
  wanna_cache_dir: { label: "WannaDance 缓存", group: "外部数据源", summary: "用于离线目录同步的本地 WannaDance 缓存。" },
  recordings_dir: { label: "录像目录", group: "外部数据源", summary: "sample-frame 工具使用的录像文件。" },
  dance_day_boundary_time: { label: "跳舞日分界", group: "运行默认值", summary: "本地时间到达该时刻时开始新的跳舞日。" },
  auto_start_watcher: { label: "自动启动 watcher", group: "运行默认值", summary: "应用工作流启动实时捕获时使用的默认偏好。" },
  auto_start_overlay: { label: "自动启动 overlay", group: "运行默认值", summary: "启用后会同步启用 watcher 自动启动。" },
  overlay_port: { label: "独立 Overlay 端口", group: "高级设置", summary: "仅在 watcher 不通过 Web UI 提供 overlay 时使用的本机端口。" },
};

function fieldText(field: ConfigField, language: Language, part: "label" | "group" | "summary") {
  return language === "zh" ? (chineseFields[field.key]?.[part] ?? field[part] ?? "") : (field[part] ?? "");
}

function normalized(value: unknown) {
  return value === "" ? null : value;
}

export function SettingsPage({ language, t, onConfigPath }: PageProps & { onConfigPath: (path: string) => void }) {
  const styles = useAppStyles();
  const [snapshot, setSnapshot] = useState<ConfigSnapshot | null>(null);
  const [draft, setDraft] = useState<JsonObject>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [previews, setPreviews] = useState<Record<string, PathPreview>>({});
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const previewTimers = useRef<Record<string, number>>({});
  const previewSequence = useRef<Record<string, number>>({});
  const resetRef = useRef<HTMLButtonElement>(null);

  const applySnapshot = useCallback((next: ConfigSnapshot) => {
    setSnapshot(next);
    setDraft({ ...next.config });
    setFieldErrors({});
    setPreviews(Object.fromEntries(next.fields.flatMap((field) => (
      field.path ? [[field.key, field.path] as const] : []
    ))));
    onConfigPath(next.config_path);
  }, [onConfigPath]);

  const load = useCallback(async () => {
    const next = await api("/api/config", configSnapshotSchema);
    applySnapshot(next);
  }, [applySnapshot]);

  useEffect(() => {
    const timers = previewTimers.current;
    void load().catch((loadError) => setMessage({ text: errorMessage(loadError), error: true }));
    return () => Object.values(timers).forEach(clearTimeout);
  }, [load]);

  const detected = (key: string) => snapshot?.detected_sources?.find((candidate) => candidate.field === key);

  const schedulePreview = (field: ConfigField, value: unknown) => {
    if (field.type !== "path") return;
    clearTimeout(previewTimers.current[field.key]);
    const sequence = (previewSequence.current[field.key] ?? 0) + 1;
    previewSequence.current[field.key] = sequence;
    if ((value === null || value === "") && !field.required) {
      setPreviews((current) => ({ ...current, [field.key]: { resolved: null, exists: null } }));
      return;
    }
    previewTimers.current[field.key] = window.setTimeout(async () => {
      try {
        const result = await postJson("/api/resolve-path", resolvePathResponseSchema, { field: field.key, current_value: value });
        if (previewSequence.current[field.key] !== sequence) return;
        setPreviews((current) => ({ ...current, [field.key]: result.path }));
      } catch (previewError) {
        if (previewSequence.current[field.key] !== sequence) return;
        setPreviews((current) => ({
          ...current,
          [field.key]: { resolved: String(value ?? ""), exists: false, kind: "inaccessible", error: errorMessage(previewError) },
        }));
      }
    }, 250);
  };

  const updateDraft = (field: ConfigField, value: unknown) => {
    setDraft((current) => {
      const next = { ...current, [field.key]: value };
      if (field.key === "auto_start_overlay" && value) next.auto_start_watcher = true;
      return next;
    });
    if (field.type === "path") schedulePreview(field, value);
  };

  const pickPath = async (field: ConfigField) => {
    setMessage(null);
    try {
      const result = await postJson("/api/pick-path", pickPathResponseSchema, { field: field.key, current_value: draft[field.key] });
      if (!("cancelled" in result)) updateDraft(field, result.value);
    } catch (pickError) {
      setMessage({ text: errorMessage(pickError), error: true });
    }
  };

  const save = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await postJson("/api/config", saveConfigResponseSchema, { config: draft });
      applySnapshot(result.snapshot);
      setMessage({ text: t("saved") });
    } catch (saveError) {
      const errors = saveError instanceof ApiError && saveError.data.errors && typeof saveError.data.errors === "object"
        ? saveError.data.errors as Record<string, string>
        : {};
      setFieldErrors(errors);
      setMessage({ text: errorMessage(saveError), error: true });
      const first = Object.keys(errors)[0];
      requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-field="${first}"] input`)?.focus());
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    setBusy(true);
    setMessage(null);
    try {
      await load();
    } catch (loadError) {
      setMessage({ text: errorMessage(loadError), error: true });
    } finally {
      setBusy(false);
      requestAnimationFrame(() => resetRef.current?.focus());
    }
  };

  const groups = useMemo(() => {
    const grouped = new Map<string, ConfigField[]>();
    for (const field of snapshot?.fields ?? []) {
      const group = fieldText(field, language, "group");
      grouped.set(group, [...(grouped.get(group) ?? []), field]);
    }
    return [...grouped.entries()];
  }, [language, snapshot]);

  return (
    <div id="view-settings" className={styles.page}>
      <FeedbackRegion
        message={message?.text}
        title={message?.error ? t("saveFailed") : undefined}
        intent={message?.error ? "error" : "success"}
      />
      {!snapshot && !message && <Spinner label={t("loadingConfig")} />}
      {snapshot && (
        <>
          <div className={styles.pageToolbar}>
            <Button ref={resetRef} disabled={busy} onClick={() => void reset()}>{t("reset")}</Button>
            <Button appearance="primary" disabled={busy} onClick={() => void save()}>{t("save")}</Button>
          </div>
          <div className={styles.stack}>
            {groups.map(([group, fields]) => (
          <Card className="panel" key={group}>
            <CardHeader header={<Text weight="semibold" size={400}>{group}</Text>} />
            <div className={styles.cardBody}>
              {fields.map((field) => (
                <ConfigFieldEditor
                  key={field.key}
                  field={field}
                  language={language}
                  value={draft[field.key]}
                  savedValue={snapshot.config[field.key]}
                  error={fieldErrors[field.key]}
                  preview={previews[field.key]}
                  automatic={detected(field.key)}
                  update={updateDraft}
                  pick={pickPath}
                  t={t}
                />
              ))}
            </div>
          </Card>
            ))}
            {Object.keys(snapshot.unsupported ?? {}).length > 0 && (
              <Card className="panel">
                <CardHeader header={<Text weight="semibold" size={400}>{t("unsupportedKeys")}</Text>} action={<Badge appearance="tint" color="warning">{t("preserved")}</Badge>} />
                <pre className={styles.codeBlock}>{JSON.stringify(snapshot.unsupported, null, 2)}</pre>
              </Card>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function ConfigFieldEditor({ field, language, value, savedValue, error, preview, automatic, update, pick, t }: {
  field: ConfigField;
  language: Language;
  value: unknown;
  savedValue: unknown;
  error?: string;
  preview?: PathPreview;
  automatic?: DetectedSource;
  update: (field: ConfigField, value: unknown) => void;
  pick: (field: ConfigField) => Promise<void>;
  t: PageProps["t"];
}) {
  const styles = useAppStyles();
  const custom = !automaticFields.has(field.key) || (value !== null && value !== "");
  const displayValue = custom ? value : (automatic?.value ?? "");
  const dirty = normalized(value) !== normalized(savedValue);
  const descriptionId = `field-description-${field.key}`;
  const errorId = `field-error-${field.key}`;
  const previewId = `path-preview-${field.key}`;
  const describedBy = [descriptionId, field.type === "path" ? previewId : "", error ? errorId : ""].filter(Boolean).join(" ");
  const shared = {
    "aria-label": fieldText(field, language, "label"),
    "aria-describedby": describedBy,
    "aria-invalid": Boolean(error) || undefined,
  };

  const control = (() => {
    if (field.type === "readonly") return <Input {...shared} readOnly value={String(value ?? "")} />;
    if (field.type === "boolean") {
      return <Switch {...shared} checked={Boolean(value)} label={t(value ? "enabled" : "disabled")} onChange={(_, data) => update(field, data.checked)} />;
    }
    if (field.type === "integer") {
      return <SpinButton {...shared} value={Number(value ?? 0)} min={Number(field.min)} max={Number(field.max)} onChange={(_, data) => update(field, data.value ?? 0)} />;
    }
    if (field.type === "time") {
      return <Input {...shared} type="time" value={String(value ?? "")} min={String(field.min ?? "")} max={String(field.max ?? "")} step={60} onChange={(_, data) => update(field, data.value)} />;
    }
    if (field.type === "path") {
      return (
        <div className={styles.inputLine}>
          {automaticFields.has(field.key) && (
            <Switch
              checked={custom}
              label={t("customPath")}
              onChange={(_, data) => update(field, data.checked ? (automatic?.value ?? "") : null)}
            />
          )}
          <Input
            {...shared}
            className={styles.grow}
            disabled={!custom}
            value={String(displayValue ?? "")}
            placeholder={custom ? (field.required ? "" : "null") : t("automatic")}
            onChange={(_, data) => update(field, field.required || data.value.trim() ? data.value : null)}
          />
          <Button disabled={!custom} onClick={() => void pick(field)} aria-label={`${t("browse")}: ${fieldText(field, language, "label")}`}>{t("browse")}</Button>
          {automaticFields.has(field.key) && <Badge appearance="tint" color={dirty ? "warning" : "success"}>{t(dirty ? "unsaved" : "saved")}</Badge>}
        </div>
      );
    }
    return <Input {...shared} value={String(value ?? "")} placeholder={field.placeholder ?? ""} onChange={(_, data) => update(field, field.required || data.value.trim() ? data.value : null)} />;
  })();

  return (
    <div className={styles.fieldGrid} data-field={field.key}>
      <div className={styles.fieldIdentity}>
        <Text weight="semibold">{fieldText(field, language, "label")}</Text>
        <code className={styles.code}>{field.key}</code>
        <Text size={200} className={styles.muted} id={descriptionId}>{fieldText(field, language, "summary")}</Text>
      </div>
      <div className={styles.fieldControl}>
        <Field required={field.required} validationState={error ? "error" : "none"}>
          {control}
        </Field>
        {field.type === "path" && <PathStatus field={field} value={value} preview={preview} automatic={automatic} custom={custom} t={t} />}
        {error && <Text id={errorId} role="alert">{error}</Text>}
      </div>
    </div>
  );
}

function PathStatus({ field, value, preview, automatic, custom, t }: {
  field: ConfigField;
  value: unknown;
  preview?: PathPreview;
  automatic?: DetectedSource;
  custom: boolean;
  t: PageProps["t"];
}) {
  const styles = useAppStyles();
  const id = `path-preview-${field.key}`;
  if (!custom) {
    const status = automatic?.error ? t("inaccessible") : automatic?.exists ? t("exists") : t("missing");
    return <Text id={id} className={styles.resolved} aria-live="polite">{t("automatic")}: {automatic?.value ?? t("missing")} ({status})</Text>;
  }
  if ((value === null || value === "") && !field.required) return <Text id={id} className={styles.resolved} aria-live="polite">{t("savedNull")}</Text>;
  if (!preview?.resolved) return <Text id={id} className={styles.resolved} aria-live="polite">{t("savedNull")}</Text>;
  const status = preview.error ? t("inaccessible") : preview.exists ? t("exists") : t("missing");
  return <Text id={id} className={styles.resolved} aria-live="polite">{preview.resolved} ({status})</Text>;
}
