import {
  Badge,
  Button,
  Card,
  CardHeader,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  DialogTrigger,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
} from "@fluentui/react-components";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, postJson } from "../api";
import {
  liveControlResponseSchema,
  exitResponseSchema,
  sessionSchema,
  summarySchema,
  type Session,
  type Summary,
} from "../apiContracts";
import { FeedbackRegion } from "../components/FeedbackRegion";
import { useAppStyles } from "../styles";
import type { PageProps, JsonObject } from "./types";
import { errorMessage } from "./types";

function lifecycleState(value: string | undefined, running: boolean | undefined): "running" | "stopping" | "stopped" {
  const state = String(value ?? "").toLowerCase();
  if (state === "running" || state === "stopping" || state === "stopped") return state;
  return running ? "running" : "stopped";
}

const pause = (milliseconds: number) => new Promise((resolve) => setTimeout(resolve, milliseconds));

export function HomePage({ t }: PageProps) {
  const styles = useAppStyles();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState("");
  const [busyControl, setBusyControl] = useState("");
  const [exitDialogOpen, setExitDialogOpen] = useState(false);
  const [exitAccepted, setExitAccepted] = useState(false);
  const [exitError, setExitError] = useState("");
  const mounted = useRef(false);
  const loadRequest = useRef(0);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      loadRequest.current += 1;
    };
  }, []);

  const load = useCallback(async () => {
    const request = ++loadRequest.current;
    try {
      const next = await api("/api/summary", summarySchema);
      if (mounted.current && request === loadRequest.current) {
        setSummary(next);
        setError("");
      }
    } catch (loadError) {
      if (mounted.current && request === loadRequest.current) {
        setError(errorMessage(loadError));
      }
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const pollStoppingSession = async (session: Session) => {
    let current = session;
    for (let attempt = 0; attempt < 20 && mounted.current; attempt += 1) {
      const watcher = lifecycleState(current.watcher_state, current.watcher_running);
      const overlay = lifecycleState(current.overlay_state, current.overlay_running);
      setSummary((value) => value ? { ...value, session: current } : value);
      if (watcher !== "stopping" && overlay !== "stopping") return;
      await pause(250);
      try {
        const next = await api("/api/summary", summarySchema);
        current = next.session;
      } catch {
        return;
      }
    }
    if (mounted.current) {
      setSummary((value) => value ? { ...value, session: current } : value);
    }
  };

  const control = async (kind: "watcher" | "overlay", action: "start" | "stop") => {
    setBusyControl(kind);
    setError("");
    try {
      await postJson(`/api/live/${kind}`, liveControlResponseSchema, { action });
      await load();
    } catch (controlError) {
      setError(errorMessage(controlError));
      const conflictSession = controlError instanceof ApiError
        ? sessionSchema.safeParse(controlError.data.session)
        : null;
      if (conflictSession?.success) {
        await pollStoppingSession(conflictSession.data);
      }
    } finally {
      setBusyControl("");
      requestAnimationFrame(() => {
        document.querySelector<HTMLButtonElement>(`[data-live-control="${kind}"]`)?.focus();
      });
    }
  };

  const data: Partial<Summary> = summary ?? {};
  const session: Partial<Session> = data.session ?? {};
  const watcherState = lifecycleState(session.watcher_state, session.watcher_running);
  const overlayState = lifecycleState(session.overlay_state, session.overlay_running);
  const watcherActive = watcherState !== "stopped";
  const overlayActive = overlayState !== "stopped";
  const controlsBusy = Boolean(busyControl) || exitAccepted;
  const counts = data.counts ?? {};

  const exitApp = async () => {
    setBusyControl("exit");
    setExitError("");
    loadRequest.current += 1;
    try {
      await postJson("/api/app/exit", exitResponseSchema, {});
      setExitAccepted(true);
      setError("");
      setExitDialogOpen(false);
    } catch (exitFailure) {
      setExitError(errorMessage(exitFailure));
    } finally {
      setBusyControl("");
    }
  };

  return (
    <div className={styles.page}>
      <FeedbackRegion
        message={error || null}
        title={error ? t("liveControlFailed") : undefined}
        intent="error"
      />
      <div className={styles.pageToolbar}>
        <Button disabled={controlsBusy} onClick={() => void load()}>{t("refresh")}</Button>
        {summary && (
          <>
            <Button
              appearance="primary"
              data-live-control="watcher"
              disabled={controlsBusy || watcherState === "stopping"}
              onClick={() => void control("watcher", watcherActive ? "stop" : "start")}
            >
              {t(watcherActive ? "stopWatcher" : "startWatcher")}
            </Button>
            <Button
              appearance="primary"
              data-live-control="overlay"
              disabled={controlsBusy || watcherState === "stopping" || overlayState === "stopping"}
              onClick={() => void control("overlay", overlayActive ? "stop" : "start")}
            >
              {t(overlayActive ? "stopOverlay" : "startOverlay")}
            </Button>
          </>
        )}
        <Dialog open={exitDialogOpen} onOpenChange={(_, next) => {
          if (busyControl !== "exit") setExitDialogOpen(next.open);
        }}>
          <DialogTrigger disableButtonEnhancement>
            <Button disabled={controlsBusy} onClick={() => setExitError("")}>{t("exitApp")}</Button>
          </DialogTrigger>
          <DialogSurface>
            <DialogBody>
              <DialogTitle>{t("exitApp")}</DialogTitle>
              <DialogContent>
                {t("exitAppConfirm")}
                <FeedbackRegion message={exitError || null} title={t("exitAppFailed")} intent="error" />
              </DialogContent>
              <DialogActions>
                <DialogTrigger disableButtonEnhancement>
                  <Button disabled={busyControl === "exit"}>{t("exitAppCancel")}</Button>
                </DialogTrigger>
                <Button appearance="primary" disabled={busyControl === "exit"} onClick={() => void exitApp()}>
                  {t(busyControl === "exit" ? "exitingApp" : "exitApp")}
                </Button>
              </DialogActions>
            </DialogBody>
          </DialogSurface>
        </Dialog>
      </div>
      <FeedbackRegion message={exitAccepted ? t("exitAppAccepted") : null} />
      {!summary && !error && <Spinner label={t("loading")} />}
      {summary && (
        <>
      {(data.startup_warnings ?? []).map((warning) => (
        <MessageBar key={warning} intent="error">
          <MessageBarBody>{warning}</MessageBarBody>
        </MessageBar>
      ))}
      <div className={styles.metricGrid}>
        {[
          [t("danceTracks"), counts.dance_tracks ?? 0],
          [t("playbackRecords"), counts.playback_records ?? 0],
          [t("acceptedRecords"), counts.accepted_playback_records ?? 0],
          [t("attentionRecords"), counts.needs_attention_playback_records ?? 0],
        ].map(([label, value]) => (
          <Card key={String(label)} className={styles.metric}>
            <Text>{label}</Text>
            <Text className={styles.metricValue}>{value}</Text>
            <Badge appearance="tint" color="brand">{t("local")}</Badge>
          </Card>
        ))}
      </div>

      <div className={styles.grid}>
        <Card id="home-live-status" className={styles.card}>
          <CardHeader header={<Text weight="semibold" size={400}>{t("liveStatus")}</Text>} />
          <div className={styles.cardBody}>
            <div className={styles.metricGrid}>
              <StatusItem label={t("watcher")} state={watcherState} t={t} />
              <StatusItem label={t("overlay")} state={overlayState} t={t} />
            </div>
            {session.last_error && (
              <MessageBar intent="error">
                <MessageBarBody><MessageBarTitle>{t("lastRuntimeError")}</MessageBarTitle>{session.last_error}</MessageBarBody>
              </MessageBar>
            )}
            {session.last_watcher_stats ? (
              <div className={styles.stack}>
                <Text className={styles.muted}>{t("lastWatcherStats")}</Text>
                <pre className={styles.codeBlock}>{JSON.stringify(session.last_watcher_stats, null, 2)}</pre>
              </div>
            ) : <div className={styles.empty}>{t("noWatcherStats")}</div>}
          </div>
        </Card>

        <Card className={styles.card}>
          <CardHeader header={<Text weight="semibold" size={400}>{t("currentLiveRow")}</Text>} />
          <div className={styles.cardBody}>
            {data.current_live
              ? <pre className={styles.codeBlock}>{JSON.stringify(data.current_live, null, 2)}</pre>
              : <div className={styles.empty}>{t("noLiveRow")}</div>}
          </div>
        </Card>
      </div>

      <div className={styles.grid}>
        <Card className={styles.card}>
          <CardHeader
            header={<Text weight="semibold" size={400}>{t("databaseState")}</Text>}
            action={<Badge appearance="tint" color={data.database_exists ? "success" : "warning"}>{t(data.database_exists ? "dbFound" : "noDb")}</Badge>}
          />
          <div className={styles.cardBody}><Text className={styles.resolved}>{data.database_path ?? ""}</Text></div>
        </Card>
        <Card className={styles.card}>
          <CardHeader header={<Text weight="semibold" size={400}>{t("recentAccepted")}</Text>} />
          <div className={styles.cardBody}><RecentTable rows={data.recent ?? []} t={t} /></div>
        </Card>
      </div>
        </>
      )}
    </div>
  );
}

function StatusItem({ label, state, t }: { label: string; state: "running" | "stopping" | "stopped"; t: PageProps["t"] }) {
  const styles = useAppStyles();
  return (
    <div className={styles.metric}>
      <Text>{label}</Text>
      <Badge appearance="tint" color={state === "running" ? "success" : state === "stopping" ? "informative" : "warning"}>
        {t(state)}
      </Badge>
    </div>
  );
}

function RecentTable({ rows, t }: { rows: JsonObject[]; t: PageProps["t"] }) {
  const styles = useAppStyles();
  if (!rows.length) return <div className={styles.empty}>{t("noRecords")}</div>;
  return (
    <div className={styles.tableRegion} role="region" aria-label={t("recentAccepted")} tabIndex={0}>
      <Table aria-label={t("recentAccepted")} size="small" className={styles.compactTable}>
        <TableHeader><TableRow>
          <TableHeaderCell>{t("time")}</TableHeaderCell>
          <TableHeaderCell>{t("track")}</TableHeaderCell>
          <TableHeaderCell>{t("source")}</TableHeaderCell>
        </TableRow></TableHeader>
        <TableBody>{rows.map((row, index) => (
          <TableRow key={String(row.id ?? index)}>
            <TableCell>{String(row.played_at ?? "")}</TableCell>
            <TableCell>{String(row.video_name ?? row.title ?? row.external_id ?? "")}</TableCell>
            <TableCell>{String(row.source ?? "")}</TableCell>
          </TableRow>
        ))}</TableBody>
      </Table>
    </div>
  );
}
