import {
  Field,
  FluentProvider,
  Link,
  Select,
  Text,
  ToggleButton,
  mergeClasses,
  webDarkTheme,
  webLightTheme,
} from "@fluentui/react-components";
import { useEffect, useMemo, useRef, useState } from "react";
import { bootstrap, type ViewKey, viewFromPath } from "./api";
import {
  LANGUAGE_KEY,
  THEME_KEY,
  initialLanguage,
  initialTheme,
  translator,
  viewTitle,
  type Language,
  type ThemeChoice,
} from "./i18n";
import { HomePage } from "./pages/HomePage";
import { TimelinePage } from "./pages/TimelinePage";
import { CatalogPage, InsightsPage, ListsPage } from "./pages/ReadPages";
import { OperationsPage } from "./pages/OperationsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { useAppStyles, useGlobalStyles } from "./styles";

const views: ViewKey[] = [
  "home",
  "timeline",
  "catalog",
  "lists",
  "insights",
  "operations",
  "settings",
];

function useSystemDark(): boolean {
  const [dark, setDark] = useState(() => matchMedia("(prefers-color-scheme: dark)").matches);

  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const update = () => setDark(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return dark;
}

export function App() {
  useGlobalStyles();
  const styles = useAppStyles();
  const [active, setActive] = useState<ViewKey>(() => viewFromPath(location.pathname));
  const [language, setLanguageState] = useState<Language>(initialLanguage);
  const [themeChoice, setThemeChoiceState] = useState<ThemeChoice>(initialTheme);
  const [configPath, setConfigPath] = useState("");
  const [focusHeading, setFocusHeading] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const systemDark = useSystemDark();
  const t = useMemo(() => translator(language), [language]);
  const [title, subtitle] = viewTitle(active, t);
  const resolvedDark = themeChoice === "dark" || (themeChoice === "system" && systemDark);

  useEffect(() => {
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
    document.title = `${title} — dancing-log`;
  }, [language, title]);

  useEffect(() => {
    if (themeChoice === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.dataset.theme = themeChoice;
  }, [themeChoice]);

  useEffect(() => {
    const onPopState = () => {
      setActive(viewFromPath(location.pathname));
      setFocusHeading(true);
    };
    addEventListener("popstate", onPopState);
    return () => removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    if (!focusHeading) return;
    headingRef.current?.focus();
    setFocusHeading(false);
  }, [active, focusHeading]);

  const navigate = (view: ViewKey) => {
    if (view === active) return;
    history.pushState({}, "", bootstrap.routes[view]);
    setActive(view);
    setFocusHeading(true);
  };

  const setLanguage = (next: Language) => {
    localStorage.setItem(LANGUAGE_KEY, next);
    setLanguageState(next);
  };

  const setThemeChoice = (next: ThemeChoice) => {
    localStorage.setItem(THEME_KEY, next);
    setThemeChoiceState(next);
  };

  const pageProps = { language, t };
  const page = (() => {
    if (active === "home") return <HomePage {...pageProps} />;
    if (active === "timeline") return <TimelinePage {...pageProps} />;
    if (active === "catalog") return <CatalogPage {...pageProps} />;
    if (active === "lists") return <ListsPage {...pageProps} />;
    if (active === "insights") return <InsightsPage {...pageProps} />;
    if (active === "operations") return <OperationsPage {...pageProps} />;
    return <SettingsPage {...pageProps} onConfigPath={setConfigPath} />;
  })();

  return (
    <FluentProvider
      className={styles.provider}
      theme={resolvedDark ? webDarkTheme : webLightTheme}
    >
      <Link className={styles.skipLink} href="#main-content">
        {t("skipToMain")}
      </Link>
      <div className={styles.shell}>
        <aside className={styles.sidebar} aria-label={t("applicationNavigation")}>
          <div className={styles.brand}>
            <Text size={500} weight="semibold">dancing-log</Text>
            <Text size={200} className={styles.muted}>{t("brandSubtitle")}</Text>
          </div>
          <nav className={styles.nav} aria-label={t("primaryNavigation")}>
            {views.map((view) => (
              <Link
                key={view}
                className={mergeClasses(styles.navLink, active === view && styles.navLinkActive)}
                href={bootstrap.routes[view]}
                aria-current={active === view ? "page" : undefined}
                onClick={(event) => {
                  if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                  event.preventDefault();
                  navigate(view);
                }}
              >
                {t(`nav_${view}`)}
              </Link>
            ))}
          </nav>
          {configPath && <Text size={100} className={styles.sidebarFoot}>{configPath}</Text>}
        </aside>

        <main id="main-content" className={styles.main} tabIndex={-1}>
          <header className={styles.topbar}>
            <div className={styles.titleBlock}>
              <h1 className={styles.heading} ref={headingRef} tabIndex={-1}>{title}</h1>
              <Text className={styles.subtitle}>{subtitle}</Text>
            </div>
            <div className={styles.topActions}>
              <Field label={t("themeLabel")} size="small">
                <Select
                  aria-label={t("themeLabel")}
                  value={themeChoice}
                  onChange={(_, data) => setThemeChoice(data.value as ThemeChoice)}
                >
                  <option value="system">{t("themeSystem")}</option>
                  <option value="light">{t("themeLight")}</option>
                  <option value="dark">{t("themeDark")}</option>
                </Select>
              </Field>
              <div className={styles.languageGroup} role="group" aria-label={t("languageLabel")}>
                <ToggleButton
                  size="small"
                  checked={language === "en"}
                  onClick={() => setLanguage("en")}
                >
                  EN
                </ToggleButton>
                <ToggleButton
                  size="small"
                  checked={language === "zh"}
                  onClick={() => setLanguage("zh")}
                >
                  中文
                </ToggleButton>
              </div>
            </div>
          </header>
          {page}
        </main>
      </div>
    </FluentProvider>
  );
}
