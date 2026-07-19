import {
  Badge,
  Button,
  Card,
  Input,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  ToggleButton,
} from "@fluentui/react-components";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, postJson } from "../api";
import {
  playbackReviewResponseSchema,
  timelineSnapshotSchema,
  type TimelineRecord,
} from "../apiContracts";
import { FeedbackRegion } from "../components/FeedbackRegion";
import { useAppStyles } from "../styles";
import type { PageProps } from "./types";
import { errorMessage } from "./types";

type SortOrder = "asc" | "desc";

const systemLabels: Record<string, string> = {
  wannadance: "WannaDance",
  pypydance: "PyPyDance",
  pypy: "PyPyDance",
  dududance: "Dudu",
  dudu: "Dudu",
  vrdancing: "VRDancing",
};

function localDateParts(value: string) {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(year, month - 1, day);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return null;
  return { year, month, day, date };
}

function formatLocalDate(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function normalizeDateInput(value: string) {
  const digits = value.replace(/\D/g, "").slice(0, 8);
  if (digits.length === 4 && /-$/.test(value)) return `${digits}-`;
  if (digits.length === 6 && /-$/.test(value)) return `${digits.slice(0, 4)}-${digits.slice(4)}-`;
  if (digits.length <= 4) return digits;
  if (digits.length <= 6) return `${digits.slice(0, 4)}-${digits.slice(4)}`;
  return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6)}`;
}

function moveDate(value: string, unit: "day" | "month", amount: number) {
  const source = localDateParts(value)?.date ?? new Date();
  if (unit === "day") {
    source.setDate(source.getDate() + amount);
  } else {
    const day = source.getDate();
    const target = new Date(source.getFullYear(), source.getMonth() + amount, 1);
    const lastDay = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
    target.setDate(Math.min(day, lastDay));
    return formatLocalDate(target);
  }
  return formatLocalDate(source);
}

async function copyText(text: string) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.readOnly = true;
  textarea.style.position = "fixed";
  textarea.style.transform = "translateX(-100%)";
  document.body.appendChild(textarea);
  textarea.select();
  try {
    if (!document.execCommand("copy")) throw new Error("clipboard unavailable");
  } finally {
    textarea.remove();
  }
}

export function TimelinePage({ t }: PageProps) {
  const styles = useAppStyles();
  const query = useMemo(() => new URLSearchParams(location.search), []);
  const [date, setDate] = useState(() => normalizeDateInput(query.get("date") ?? ""));
  const [resolvedDate, setResolvedDate] = useState("");
  const [sort, setSort] = useState<SortOrder>(query.get("sort") === "desc" ? "desc" : "asc");
  const [records, setRecords] = useState<TimelineRecord[]>([]);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const loadRequest = useRef(0);

  const syncUrl = useCallback((nextDate: string, nextSort: SortOrder) => {
    const search = new URLSearchParams();
    if (localDateParts(nextDate)) search.set("date", nextDate);
    if (nextSort === "desc") search.set("sort", "desc");
    history.replaceState({}, "", `${location.pathname}${search.size ? `?${search}` : ""}`);
  }, []);

  const load = useCallback(async (requested = date) => {
    const normalized = normalizeDateInput(requested);
    const valid = Boolean(localDateParts(normalized));
    const requestId = ++loadRequest.current;
    setLoading(true);
    setMessage(null);
    try {
      const snapshot = await api(
        valid ? `/api/timeline?date=${encodeURIComponent(normalized)}` : "/api/timeline",
        timelineSnapshotSchema,
      );
      if (requestId !== loadRequest.current) return;
      const nextDate = normalizeDateInput(snapshot.date ?? normalized);
      if (localDateParts(nextDate)) {
        setDate(nextDate);
        setResolvedDate(nextDate);
        syncUrl(nextDate, sort);
      }
      setRecords(snapshot.records ?? []);
    } catch (loadError) {
      if (requestId !== loadRequest.current) return;
      setRecords([]);
      setMessage({ text: `${t("timelineLoadFailed")}: ${errorMessage(loadError)}`, error: true });
    } finally {
      if (requestId === loadRequest.current) setLoading(false);
    }
  }, [date, sort, syncUrl, t]);

  // oxlint-disable-next-line react/exhaustive-deps -- Initial URL state is intentionally loaded once.
  useEffect(() => { void load(date); }, []);

  const visibleRecords = sort === "desc" ? [...records].reverse() : records;
  const accepted = records.filter((row) => (row.review_status ?? row.effective_playback_status) === "accepted");

  const changeDate = (next: string) => {
    const normalized = normalizeDateInput(next);
    setDate(normalized);
    if (localDateParts(normalized)) void load(normalized);
    else {
      loadRequest.current += 1;
      setLoading(false);
    }
  };

  const stepDate = (unit: "day" | "month", amount: number) => {
    const next = moveDate(localDateParts(date) ? date : resolvedDate, unit, amount);
    setDate(next);
    void load(next);
  };

  const toggleSort = () => {
    const next = sort === "desc" ? "asc" : "desc";
    setSort(next);
    syncUrl(resolvedDate || date, next);
  };

  const copyAccepted = async () => {
    if (!accepted.length) {
      setMessage({ text: t("noAcceptedTimelineRecords"), error: true });
      return;
    }
    try {
      await copyText(accepted.map((row) => String(row.line ?? `${row.time ?? ""} ${row.display ?? ""}`)).join("\n"));
      setMessage({ text: `${t("copiedDailyDances")}: ${accepted.length}` });
    } catch (copyError) {
      setMessage({ text: `${t("copyDailyDancesFailed")}: ${errorMessage(copyError)}`, error: true });
    }
  };

  const updateReview = async (row: TimelineRecord, action: string) => {
    setUpdatingId(row.id);
    setMessage(null);
    try {
      await postJson("/api/playback-review", playbackReviewResponseSchema, { playback_record_id: row.id, action });
      await load(resolvedDate || date);
      requestAnimationFrame(() => {
        const buttons = [...document.querySelectorAll<HTMLButtonElement>(`[data-playback-id="${row.id}"]`)];
        (buttons.find((button) => !button.disabled) ?? document.getElementById("timeline-copy"))?.focus();
      });
    } catch (reviewError) {
      setMessage({ text: `${t("reviewUpdateFailed")}: ${errorMessage(reviewError)}`, error: true });
    } finally {
      setUpdatingId(null);
    }
  };

  return (
    <div id="view-timeline" className={styles.page}>
      <div className={styles.pageToolbar}>
        <Button aria-label={t("previousMonth")} title={t("previousMonth")} onClick={() => stepDate("month", -1)}>&lt;&lt;</Button>
        <Button aria-label={t("previousDay")} title={t("previousDay")} onClick={() => stepDate("day", -1)}>&lt;</Button>
        <Input
          aria-label={t("timelineDate")}
          value={date}
          placeholder="YYYY-MM-DD"
          maxLength={10}
          inputMode="numeric"
          onChange={(_, data) => changeDate(data.value)}
          onBlur={() => { if (!localDateParts(date)) setDate(resolvedDate); }}
        />
        <Input
          aria-label={t("openDatePicker")}
          title={t("openDatePicker")}
          type="date"
          value={localDateParts(date) ? date : ""}
          onChange={(_, data) => changeDate(data.value)}
        />
        <Button aria-label={t("nextDay")} title={t("nextDay")} onClick={() => stepDate("day", 1)}>&gt;</Button>
        <Button aria-label={t("nextMonth")} title={t("nextMonth")} onClick={() => stepDate("month", 1)}>&gt;&gt;</Button>
        <ToggleButton
          checked={sort === "desc"}
          aria-label={t("reverseTimelineOrder")}
          title={sort === "desc" ? t("timelineSortReverse") : t("timelineSortChronological")}
          onClick={toggleSort}
        >
          {sort === "desc" ? "↓" : "↑"}
        </ToggleButton>
        <Button id="timeline-copy" aria-label={t("copyDailyDancesTitle")} title={t("copyDailyDancesTitle")} onClick={() => void copyAccepted()}>⧉</Button>
      </div>

      <FeedbackRegion
        message={message?.text}
        intent={message?.error ? "error" : "success"}
      />

      <Card className="panel">
        {loading && !records.length ? <div className={styles.empty}>{t("loading")}</div> : (
          <TimelineTable rows={visibleRecords} updatingId={updatingId} updateReview={updateReview} t={t} />
        )}
      </Card>
    </div>
  );
}

function sourcePresentation(row: TimelineRecord, t: PageProps["t"]) {
  const value = String(row.source_type ?? "").trim().toLowerCase().replaceAll("-", "_");
  if (value === "random") return { label: t("sourceRandom"), requester: false };
  if (value === "self") return { label: t("sourceSelf"), requester: true };
  if (["recommend", "recommended", "recommendation"].includes(value)) return { label: t("sourceRecommend"), requester: true };
  if (["queued_self", "queued", "reserved", "reservation"].includes(value)) return { label: t("sourceQueuedSelf"), requester: true };
  if (["other", "player", "requester", "requester_marker"].includes(value)) return { label: t("sourceOther"), requester: true };
  return { label: t("sourceUnknown"), requester: true };
}

function statusLabel(status: string, t: PageProps["t"]) {
  if (status === "accepted") return t("status_accepted");
  if (status === "excluded") return t("status_excluded");
  if (status === "pending") return t("status_pending");
  return t("status_needs_attention");
}

function statusColor(status: string): "success" | "danger" | "informative" | "warning" {
  if (status === "accepted") return "success";
  if (status === "excluded") return "danger";
  if (status === "pending") return "informative";
  return "warning";
}

function TimelineTable({ rows, updatingId, updateReview, t }: {
  rows: TimelineRecord[];
  updatingId: number | null;
  updateReview: (row: TimelineRecord, action: string) => Promise<void>;
  t: PageProps["t"];
}) {
  const styles = useAppStyles();
  if (!rows.length) return <div className={styles.empty}>{t("noTimelineRecords")}</div>;
  return (
    <div className={styles.tableRegion} role="region" aria-label={t("playbackRecords")} tabIndex={0}>
      <Table aria-label={t("playbackRecords")} className={`timeline-table ${styles.table}`}>
        <TableHeader><TableRow>
          <TableHeaderCell>{t("time")}</TableHeaderCell>
          <TableHeaderCell>{t("record")}</TableHeaderCell>
          <TableHeaderCell>{t("reviewStatus")}</TableHeaderCell>
          <TableHeaderCell>{t("actions")}</TableHeaderCell>
        </TableRow></TableHeader>
        <TableBody>{rows.map((row) => {
          const status = String(row.review_status ?? row.effective_playback_status ?? "");
          const source = sourcePresentation(row, t);
          const requester = source.requester ? String(row.requester_display_name ?? row.source_display_name ?? "").trim() : "";
          const systemKey = String(row.dance_system_key ?? row.system_key ?? "").trim().toLowerCase();
          const system = String(row.dance_system_name ?? "").trim() || systemLabels[systemKey] || systemKey;
          const hasManual = Boolean(row.manual_decision_status);
          return (
            <TableRow key={row.id}>
              <TableCell>{String(row.time ?? "")}</TableCell>
              <TableCell>
                <div className={styles.timelineRecord}>
                  <div className={styles.inline}>
                    <Text>{String(row.display ?? "")}</Text>
                    {system && <Badge appearance="tint" color="informative">{system}</Badge>}
                  </div>
                  <Text size={200} className={styles.muted}>
                    {source.label}{requester ? <> · <strong title={String(row.requester_user_id ?? "")}>{requester}</strong></> : null}
                  </Text>
                </div>
              </TableCell>
              <TableCell>
                <div className={styles.stack}>
                  <Badge appearance="tint" color={statusColor(status)}>{statusLabel(status, t)}</Badge>
                  {hasManual && <Text size={200} className={styles.muted}>{t("manual")} · {t("defaultResult")}: {statusLabel(String(row.default_playback_status ?? status), t)}</Text>}
                </div>
              </TableCell>
              <TableCell>
                <div className={styles.inline}>
                  <Button appearance="primary" size="small" data-playback-id={row.id} disabled={status === "accepted" || updatingId === row.id} onClick={() => void updateReview(row, "accept")}>{t("accept")}</Button>
                  <Button size="small" data-playback-id={row.id} disabled={status === "excluded" || updatingId === row.id} onClick={() => void updateReview(row, "exclude")}>{t("exclude")}</Button>
                  <Button size="small" data-playback-id={row.id} disabled={!hasManual || updatingId === row.id} onClick={() => void updateReview(row, "restore_default")}>{t("restoreDefault")}</Button>
                </div>
              </TableCell>
            </TableRow>
          );
        })}</TableBody>
      </Table>
    </div>
  );
}
