import {
  Badge,
  Button,
  Card,
  CardHeader,
  SearchBox,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
} from "@fluentui/react-components";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import {
  catalogSnapshotSchema,
  insightsSnapshotSchema,
  listsSnapshotSchema,
  type InsightsSnapshot,
  type ListsSnapshot,
} from "../apiContracts";
import { useAppStyles } from "../styles";
import type { JsonObject, PageProps } from "./types";
import { errorMessage } from "./types";

export function CatalogPage({ t }: PageProps) {
  const styles = useAppStyles();
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<JsonObject[] | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async (requestedQuery: string) => {
    setError("");
    try {
      const data = await api(`/api/catalog?q=${encodeURIComponent(requestedQuery)}&limit=100`, catalogSnapshotSchema);
      setRows(data.tracks);
    } catch (loadError) {
      setError(errorMessage(loadError));
      setRows([]);
    }
  }, []);

  useEffect(() => { void load(""); }, [load]);

  return (
    <div id="view-catalog" className={styles.page}>
      <div className={styles.pageToolbar}>
        <SearchBox
          aria-label={t("searchCatalog")}
          placeholder={t("searchCatalog")}
          value={query}
          onChange={(_, data) => setQuery(data.value)}
          onKeyDown={(event) => { if (event.key === "Enter") void load(query); }}
        />
        <Button onClick={() => void load(query)}>{t("search")}</Button>
      </div>
      <Card className="panel">
        {error ? <Text>{error}</Text> : rows === null ? <Spinner label={t("loading")} /> : <CatalogTable rows={rows} t={t} />}
      </Card>
    </div>
  );
}

export function ListsPage({ t }: PageProps) {
  const styles = useAppStyles();
  const [data, setData] = useState<ListsSnapshot | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/api/lists", listsSnapshotSchema).then(setData).catch((loadError) => setError(errorMessage(loadError)));
  }, []);

  return (
    <div id="view-lists" className={styles.page}>
      <Card className="panel">
        <CardHeader
          header={<Text weight="semibold" size={400}>{t("queuedSelfManifests")}</Text>}
          action={data && <Badge appearance="tint" color={data.exists ? "success" : "warning"}>{t(data.exists ? "found" : "missing")}</Badge>}
        />
        <div className={styles.cardBody}>
          {error ? <Text>{error}</Text> : !data ? <Spinner label={t("loading")} /> : (
            <>
              <Text className={styles.resolved}>{data.queued_self_dir ?? ""}</Text>
              {(data.manifests ?? []).length ? (
                <div className={styles.stack}>{(data.manifests ?? []).map((row, index) => (
                  <div className={styles.listItem} key={String(row.path ?? index)}>
                    <Text weight="semibold">{String(row.name ?? "")}</Text>
                    <code className={styles.code}>{String(row.path ?? "")}</code>
                    {(Array.isArray(row.preview) ? row.preview : []).map((line, lineIndex) => <Text key={lineIndex}>{String(line)}</Text>)}
                  </div>
                ))}</div>
              ) : <div className={styles.empty}>{t("noManifests")}</div>}
            </>
          )}
        </div>
      </Card>
    </div>
  );
}

export function InsightsPage({ t }: PageProps) {
  const styles = useAppStyles();
  const [data, setData] = useState<InsightsSnapshot | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/api/insights", insightsSnapshotSchema).then(setData).catch((loadError) => setError(errorMessage(loadError)));
  }, []);

  if (error) return <Text>{error}</Text>;
  if (!data) return <Spinner label={t("loading")} />;
  return (
    <div id="view-insights" className={styles.page}>
      <div className={styles.grid}>
        <Card className="panel">
          <CardHeader header={<Text weight="semibold" size={400}>{t("sourceDistribution")}</Text>} />
          <KeyCountTable rows={data.source_distribution ?? []} valueKey="source" label={t("sourceDistribution")} t={t} />
        </Card>
        <Card className="panel">
          <CardHeader header={<Text weight="semibold" size={400}>{t("topTracks")}</Text>} />
          <KeyCountTable rows={data.top_tracks ?? []} valueKey="title" label={t("topTracks")} t={t} />
        </Card>
      </div>
      <Card className="panel">
        <CardHeader header={<Text weight="semibold" size={400}>{t("recommendations")}</Text>} />
        <CatalogTable rows={data.recommendations ?? []} t={t} />
      </Card>
    </div>
  );
}

function CatalogTable({ rows, t }: { rows: JsonObject[]; t: PageProps["t"] }) {
  const styles = useAppStyles();
  if (!rows.length) return <div className={styles.empty}>{t("noTracks")}</div>;
  return (
    <div className={styles.tableRegion} role="region" aria-label={t("danceTracks")} tabIndex={0}>
      <Table aria-label={t("danceTracks")} className={styles.table}>
        <TableHeader><TableRow>
          <TableHeaderCell>{t("track")}</TableHeaderCell>
          <TableHeaderCell>{t("title")}</TableHeaderCell>
          <TableHeaderCell>{t("artist")}</TableHeaderCell>
          <TableHeaderCell>{t("preferences")}</TableHeaderCell>
        </TableRow></TableHeader>
        <TableBody>{rows.map((row, index) => (
          <TableRow key={String(row.id ?? `${row.system_key}:${row.external_id}:${index}`)}>
            <TableCell>{String(row.system_key ?? "")}:{String(row.external_id ?? "")}</TableCell>
            <TableCell>{String(row.title ?? "")}</TableCell>
            <TableCell>{String(row.artist ?? "")}</TableCell>
            <TableCell><div className={styles.inline}>
              {Boolean(row.favorite) && <Badge appearance="tint" color="success">{t("favorite")}</Badge>}
              {Boolean(row.want_to_learn) && <Badge appearance="tint" color="informative">{t("wantToLearn")}</Badge>}
            </div></TableCell>
          </TableRow>
        ))}</TableBody>
      </Table>
    </div>
  );
}

function KeyCountTable({ rows, valueKey, label, t }: { rows: JsonObject[]; valueKey: string; label: string; t: PageProps["t"] }) {
  const styles = useAppStyles();
  if (!rows.length) return <div className={styles.empty}>{t("noData")}</div>;
  return (
    <Table aria-label={label} size="small">
      <TableHeader><TableRow><TableHeaderCell>{t("name")}</TableHeaderCell><TableHeaderCell>{t("count")}</TableHeaderCell></TableRow></TableHeader>
      <TableBody>{rows.map((row, index) => (
        <TableRow key={String(row[valueKey] ?? row.external_id ?? index)}>
          <TableCell>{String(row[valueKey] ?? row.external_id ?? "(none)")}</TableCell>
          <TableCell>{String(row.count ?? 0)}</TableCell>
        </TableRow>
      ))}</TableBody>
    </Table>
  );
}
